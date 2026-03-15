"""
Scene video agent — generates an 8-second MP4 for a single sub-scene.

Primary path:  Google Veo via Vertex AI
Fallback path: FAL Veo 3.1 reference-to-video
               triggered automatically when Veo raises VeoSafetyBlockedError.

All blocking I/O (GCS upload/download, FAL HTTP, Veo polling) runs in the
thread-pool executor so the async orchestrator can run multiple video jobs
concurrently.

Error handling
──────────────
Veo (primary)
  - Rate limits (HTTP 429):    retried with VIDEO_RATE_LIMIT_DELAYS back-off.
  - Transient errors (5xx):    retried with VIDEO_TRANSIENT_DELAYS back-off.
  - Internal error (code 13):  retried with VEO_INTERNAL_ERROR_DELAYS back-off.
  - Safety block:              raises VeoSafetyBlockedError → triggers FAL fallback.
  - Any other error:           raised immediately (no retry).

FAL (fallback — only reached after VeoSafetyBlockedError)
  - Rate limits (HTTP 429):    retried with VIDEO_RATE_LIMIT_DELAYS back-off.
  - Transient errors (5xx):    retried with VIDEO_TRANSIENT_DELAYS back-off.
  - Job failure / timeout:     raised immediately.
  - Any other error:           raised immediately.

If both Veo and FAL fail, VideoGenerationError is raised.
The orchestrator treats any raised exception as a hard failure for that
sub-scene and will NOT proceed to video compilation for it.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import random
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from google import genai
from google.genai import types
from google.cloud import storage

from backend.config import (
    FAL_API_KEY,
    FAL_ASPECT_RATIO,
    FAL_DURATION,
    FAL_GENERATE_AUDIO,
    FAL_MAX_IMAGE_BYTES,
    FAL_MODEL_ID,
    FAL_POLL_INTERVAL_S,
    FAL_QUEUE_BASE,
    FAL_RATE_LIMIT_DELAYS,
    FAL_RESOLUTION,
    FAL_SAFETY_TOLERANCE,
    FAL_TIMEOUT_S,
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
    VEO_ASPECT_RATIO,
    VEO_BUCKET,
    VEO_DURATION_SECONDS,
    VEO_GENERATE_AUDIO,
    VEO_INTERNAL_ERROR_DELAYS,
    VEO_INTERNAL_ERROR_RETRIES,
    VEO_MODEL,
    VEO_POLL_INTERVAL_S,
    VEO_RESOLUTION,
    VEO_TIMEOUT_S,
    RETRY_JITTER_MAX_S,
    VIDEO_RATE_LIMIT_DELAYS,
    VIDEO_TRANSIENT_DELAYS,
)
from backend.utils.retry import VeoSafetyBlockedError, is_veo_safety_error

logger = logging.getLogger(__name__)

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------

class VideoGenerationError(RuntimeError):
    """
    Raised when video generation fails for a sub-scene after all retries and
    fallback paths have been exhausted.
    """


# ---------------------------------------------------------------------------
# Error classifiers
# ---------------------------------------------------------------------------

def _is_rate_limit(exc: Exception) -> bool:
    return "429" in str(exc)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc)
    return any(code in msg for code in ("500", "502", "503", "504")) or isinstance(
        exc, (ConnectionError, TimeoutError, OSError)
    )


def _is_veo_internal_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "code 13" in msg or '"code": 13' in msg


def _jittered_sleep(base_delay: int) -> None:
    """Sleep for *base_delay* plus random jitter to stagger concurrent retries."""
    jitter = random.uniform(0, RETRY_JITTER_MAX_S)
    time.sleep(base_delay + jitter)


# ===========================================================================
# PRIMARY: Veo via Google Vertex AI
# ===========================================================================

def _upload_gcs_sync(local_path: str, bucket_name: str, blob_name: str) -> str:
    gcs = storage.Client(project=GOOGLE_CLOUD_PROJECT)
    blob = gcs.bucket(bucket_name).blob(blob_name)
    ext = Path(local_path).suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    blob.upload_from_filename(local_path, content_type=mime)
    return f"gs://{bucket_name}/{blob_name}"


def _download_gcs_sync(gs_uri: str, local_path: str) -> None:
    parsed = urlparse(gs_uri)
    bucket_name = parsed.netloc
    blob_name = parsed.path.lstrip("/")
    gcs = storage.Client(project=GOOGLE_CLOUD_PROJECT)
    gcs.bucket(bucket_name).blob(blob_name).download_to_filename(local_path)


def _wait_for_veo_operation(client: genai.Client, op, poll_s: int, timeout_s: int):
    start = time.time()
    while not op.done:
        if time.time() - start > timeout_s:
            raise TimeoutError(f"Veo operation timed out after {timeout_s}s")
        time.sleep(poll_s)
        op = client.operations.get(op)
    return op


def _submit_veo_with_retry(
    client: genai.Client,
    video_prompt: str,
    reference_images: list,
    output_gcs_prefix: str,
    filename: str,
) -> object:
    """
    Submit the Veo generation request, retrying on rate limits and transient
    errors.  Returns the operation object on success.
    """
    rate_limit_attempt = 0
    transient_attempt = 0
    rate_limit_delays = list(VIDEO_RATE_LIMIT_DELAYS)
    transient_delays = list(VIDEO_TRANSIENT_DELAYS)

    while True:
        try:
            return client.models.generate_videos(
                model=VEO_MODEL,
                prompt=video_prompt,
                config=types.GenerateVideosConfig(
                    reference_images=reference_images,
                    aspect_ratio=VEO_ASPECT_RATIO,
                    duration_seconds=VEO_DURATION_SECONDS,
                    resolution=VEO_RESOLUTION,
                    generate_audio=VEO_GENERATE_AUDIO,
                    output_gcs_uri=output_gcs_prefix,
                ),
            )

        except Exception as exc:
            if _is_rate_limit(exc):
                if rate_limit_attempt < len(rate_limit_delays):
                    delay = rate_limit_delays[rate_limit_attempt]
                    rate_limit_attempt += 1
                    logger.warning(
                        "[Veo][%s] Rate limited — attempt %d/%d. Retrying in ~%ds.",
                        filename, rate_limit_attempt, len(rate_limit_delays), delay,
                    )
                    _jittered_sleep(delay)
                else:
                    logger.error("[Veo][%s] Rate limit retries exhausted.", filename)
                    raise
            elif _is_transient(exc):
                if transient_attempt < len(transient_delays):
                    delay = transient_delays[transient_attempt]
                    transient_attempt += 1
                    logger.warning(
                        "[Veo][%s] Transient error (attempt %d/%d) — retrying in ~%ds. Error: %s",
                        filename, transient_attempt, len(transient_delays), delay, exc,
                    )
                    _jittered_sleep(delay)
                else:
                    logger.error("[Veo][%s] Transient error retries exhausted.", filename)
                    raise
            else:
                logger.error("[Veo][%s] Non-retryable submission error: %s", filename, exc)
                raise


def _generate_veo_sync(
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    run_id: str,
    output_dir: Path,
    filename: str,
) -> str:
    """
    Run Veo generation synchronously.  Returns local mp4 path.

    Retry strategy
    ──────────────
    - 429 rate limit on submit:   retried via _submit_veo_with_retry.
    - 5xx / network on submit:    retried via _submit_veo_with_retry.
    - Veo internal error (13):    retried up to VEO_INTERNAL_ERROR_RETRIES times.
    - Safety block:               raises VeoSafetyBlockedError (triggers FAL fallback).
    - No response after polling:  raises RuntimeError.
    """
    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
    )

    # Upload all images to GCS
    reference_images = []
    blob_name = f"veo_inputs/{run_id}/subscene.png"
    gcs_uri = _upload_gcs_sync(subscene_image_path, VEO_BUCKET, blob_name)
    reference_images.append(
        types.VideoGenerationReferenceImage(
            image=types.Image(gcs_uri=gcs_uri, mime_type="image/png"),
            reference_type="asset",
        )
    )
    for i, char_path in enumerate(character_image_paths):
        ext = Path(char_path).suffix.lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
        blob_name = f"veo_inputs/{run_id}/character_{i}{ext}"
        gcs_uri = _upload_gcs_sync(char_path, VEO_BUCKET, blob_name)
        reference_images.append(
            types.VideoGenerationReferenceImage(
                image=types.Image(gcs_uri=gcs_uri, mime_type=mime),
                reference_type="asset",
            )
        )

    output_gcs_prefix = f"gs://{VEO_BUCKET}/veo_outputs/{run_id}/"

    for internal_attempt in range(VEO_INTERNAL_ERROR_RETRIES + 1):
        operation = _submit_veo_with_retry(
            client, video_prompt, reference_images, output_gcs_prefix, filename
        )

        operation = _wait_for_veo_operation(
            client, operation, VEO_POLL_INTERVAL_S, VEO_TIMEOUT_S
        )

        if operation.response:
            break

        err = getattr(operation, "error", None)
        err_code = err.get("code") if isinstance(err, dict) else getattr(err, "code", None)
        err_msg = str(err) if err else str(operation)

        if err_code == 3 or is_veo_safety_error(Exception(err_msg)):
            raise VeoSafetyBlockedError(
                "Veo blocked generation (safety or third-party content policy)"
            )

        if err_code == 13 and internal_attempt < VEO_INTERNAL_ERROR_RETRIES:
            delay = VEO_INTERNAL_ERROR_DELAYS[internal_attempt]
            logger.warning(
                "[Veo][%s] Internal error (code 13) — attempt %d/%d. Retrying in ~%ds.",
                filename, internal_attempt + 1, VEO_INTERNAL_ERROR_RETRIES, delay,
            )
            _jittered_sleep(delay)
            continue

        raise RuntimeError(f"Veo returned no response for '{filename}': {operation}")

    video_gcs_uri = operation.result.generated_videos[0].video.uri
    local_mp4 = str(output_dir / f"{run_id}.mp4")
    _download_gcs_sync(video_gcs_uri, local_mp4)
    return local_mp4


# ===========================================================================
# FALLBACK: FAL Veo 3.1 reference-to-video
# ===========================================================================

def _image_to_data_uri(path: str) -> str:
    p = Path(path)
    raw = p.read_bytes()
    if len(raw) > FAL_MAX_IMAGE_BYTES and _PIL_AVAILABLE:
        img = _PILImage.open(io.BytesIO(raw)).convert("RGB")
        scale = (FAL_MAX_IMAGE_BYTES / len(raw)) ** 0.5
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, _PILImage.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        raw = buf.getvalue()
        mime = "image/jpeg"
    else:
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _fal_request(method: str, url: str, data: dict | None = None) -> dict:
    if not FAL_API_KEY:
        raise RuntimeError("Set FAL_API_KEY or FAL_KEY in .env")
    headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        err_body = exc.read().decode() if exc.fp else ""
        try:
            err_json = json.loads(err_body)
            detail = err_json.get("detail") or err_json.get("message") or err_body
        except Exception:
            detail = err_body or str(exc)
        raise RuntimeError(f"FAL API {exc.code}: {detail}") from exc


def _fal_request_with_retry(
    method: str,
    url: str,
    data: dict | None,
    filename: str,
) -> dict:
    """
    Wrapper around _fal_request that retries on rate limits and transient errors.
    """
    rate_limit_attempt = 0
    transient_attempt = 0
    rate_limit_delays = list(FAL_RATE_LIMIT_DELAYS)
    transient_delays = list(VIDEO_TRANSIENT_DELAYS)

    while True:
        try:
            return _fal_request(method, url, data)

        except RuntimeError as exc:
            msg = str(exc)
            if "429" in msg:
                if rate_limit_attempt < len(rate_limit_delays):
                    delay = rate_limit_delays[rate_limit_attempt]
                    rate_limit_attempt += 1
                    logger.warning(
                        "[FAL][%s] Rate limited — attempt %d/%d. Retrying in ~%ds.",
                        filename, rate_limit_attempt, len(rate_limit_delays), delay,
                    )
                    _jittered_sleep(delay)
                else:
                    logger.error("[FAL][%s] Rate limit retries exhausted.", filename)
                    raise
            elif any(code in msg for code in ("500", "502", "503", "504")):
                if transient_attempt < len(transient_delays):
                    delay = transient_delays[transient_attempt]
                    transient_attempt += 1
                    logger.warning(
                        "[FAL][%s] Transient error (attempt %d/%d) — retrying in ~%ds. Error: %s",
                        filename, transient_attempt, len(transient_delays), delay, exc,
                    )
                    _jittered_sleep(delay)
                else:
                    logger.error("[FAL][%s] Transient error retries exhausted.", filename)
                    raise
            else:
                raise

        except (ConnectionError, TimeoutError, OSError) as exc:
            if transient_attempt < len(transient_delays):
                delay = transient_delays[transient_attempt]
                transient_attempt += 1
                logger.warning(
                    "[FAL][%s] Network error (attempt %d/%d) — retrying in ~%ds. Error: %s",
                    filename, transient_attempt, len(transient_delays), delay, exc,
                )
                _jittered_sleep(delay)
            else:
                logger.error("[FAL][%s] Network error retries exhausted.", filename)
                raise


def _download_url_sync(url: str, path: Path) -> None:
    req = Request(url, headers={"User-Agent": "Python"})
    with urlopen(req, timeout=300) as resp:
        path.write_bytes(resp.read())


def _generate_fal_sync(
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    output_path: Path,
    filename: str,
) -> None:
    """
    Run FAL Veo 3.1 generation synchronously.

    Retry strategy
    ──────────────
    - 429 / 5xx on submit or poll:  retried via _fal_request_with_retry.
    - Job failure status:           raised immediately as RuntimeError.
    - Poll timeout:                 raised as TimeoutError.
    - Missing video in result:      raised as RuntimeError.
    """
    endpoint = f"{FAL_QUEUE_BASE}/{FAL_MODEL_ID}"
    image_urls = [_image_to_data_uri(subscene_image_path)]
    image_urls.extend(_image_to_data_uri(p) for p in character_image_paths)

    payload = {
        "prompt": video_prompt,
        "image_urls": image_urls,
        "resolution": FAL_RESOLUTION,
        "duration": FAL_DURATION,
        "aspect_ratio": FAL_ASPECT_RATIO,
        "generate_audio": FAL_GENERATE_AUDIO,
        "safety_tolerance": FAL_SAFETY_TOLERANCE,
    }

    # Submit
    out = _fal_request_with_retry("POST", endpoint, payload, filename)
    status_url = out.get("status_url")
    response_url = out.get("response_url")
    request_id = out.get("request_id") or out.get("requestId")
    if not status_url:
        status_url = f"{FAL_QUEUE_BASE}/{FAL_MODEL_ID}/requests/{request_id}/status"
    if not response_url:
        response_url = f"{FAL_QUEUE_BASE}/{FAL_MODEL_ID}/requests/{request_id}"

    # Poll
    poll_url = f"{status_url}?logs=1" if "?" not in status_url else f"{status_url}&logs=1"
    deadline = time.time() + FAL_TIMEOUT_S
    while time.time() < deadline:
        status_resp = _fal_request_with_retry("GET", poll_url, None, filename)
        st = (status_resp.get("status") or "").upper()
        if st == "COMPLETED":
            response_url = status_resp.get("response_url") or response_url
            break
        if st == "FAILED":
            raise RuntimeError(f"FAL job failed for '{filename}': {status_resp}")
        time.sleep(FAL_POLL_INTERVAL_S)
    else:
        raise TimeoutError(f"FAL job did not complete within {FAL_TIMEOUT_S}s for '{filename}'")

    # Fetch result
    result = _fal_request_with_retry("GET", response_url, None, filename)
    video_info = result.get("video") or result.get("data", {}).get("video")
    if not video_info:
        raise RuntimeError(f"FAL result missing video for '{filename}': {result}")
    video_url = video_info.get("url")
    if not video_url:
        raise RuntimeError(f"FAL video object missing url for '{filename}': {video_info}")

    _download_url_sync(video_url, output_path)


# ===========================================================================
# Helpers
# ===========================================================================

class _null_context:
    """No-op async context manager used when no FAL semaphore is provided."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass


# ===========================================================================
# Public async function
# ===========================================================================

async def generate_scene_video(
    scene_idx: int,
    sub_idx: int,
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    output_dir: Path,
    fal_sem: asyncio.Semaphore | None = None,
) -> tuple[str, str]:
    """
    Generate a sub-scene video and save it to ``output_dir``.

    Tries Veo first; falls back to FAL on VeoSafetyBlockedError.
    Returns ``(subscene_key, saved_path)``.

    Parameters
    ----------
    fal_sem:
        Optional semaphore that gates concurrent FAL requests.  Pass one
        shared semaphore from the orchestrator to cap the number of
        simultaneous FAL submissions and avoid FAL rate limits.

    Raises
    ------
    VideoGenerationError
        Both Veo and FAL failed after all retries.
    VeoSafetyBlockedError
        Veo blocked and FAL also failed (wrapped in VideoGenerationError).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"scene_{scene_idx}_sub_{sub_idx}.mp4"
    out_path = output_dir / filename
    key = f"scene_{scene_idx}_sub_{sub_idx}"

    if out_path.exists():
        logger.info("[scene_video] Already exists, skipping: %s", filename)
        return key, str(out_path)

    run_id = f"s{scene_idx}_{sub_idx}_{uuid.uuid4().hex[:6]}"
    loop = asyncio.get_running_loop()

    # ---- Primary: Veo ----
    veo_error: Exception | None = None
    try:
        logger.info("[scene_video] Generating via Veo: %s", filename)
        local_mp4 = await loop.run_in_executor(
            None,
            _generate_veo_sync,
            video_prompt,
            subscene_image_path,
            list(character_image_paths),
            run_id,
            output_dir,
            filename,
        )
        Path(local_mp4).rename(out_path)
        logger.info("[scene_video] Saved (Veo): %s", filename)
        return key, str(out_path)

    except VeoSafetyBlockedError as exc:
        veo_error = exc
        logger.warning(
            "[scene_video][%s] Veo safety block — falling back to FAL Veo 3.1.", filename
        )

    except Exception as exc:
        logger.error("[scene_video][%s] Veo failed: %s", filename, exc)
        raise VideoGenerationError(
            f"Veo failed for '{filename}': {exc}"
        ) from exc

    # ---- Fallback: FAL (only reached on VeoSafetyBlockedError) ----
    # Acquire the shared semaphore before submitting to FAL so we never
    # exceed FAL's per-minute concurrency quota.
    async with (fal_sem if fal_sem is not None else _null_context()):
        try:
            logger.info("[scene_video] Generating via FAL fallback: %s", filename)
            await loop.run_in_executor(
                None,
                _generate_fal_sync,
                video_prompt,
                subscene_image_path,
                list(character_image_paths),
                out_path,
                filename,
            )
            logger.info("[scene_video] Saved (FAL): %s", filename)
            return key, str(out_path)

        except Exception as exc:
            logger.error("[scene_video][%s] FAL fallback also failed: %s", filename, exc)
            raise VideoGenerationError(
                f"Both Veo (safety block) and FAL failed for '{filename}': {exc}"
            ) from exc
