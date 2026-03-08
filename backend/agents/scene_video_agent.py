"""
Scene video agent — generates an 8-second MP4 for a single sub-scene.

Primary path:  Google Veo via Vertex AI (7_generate_scene_videos.py logic)
Fallback path: FAL Veo 3.1 reference-to-video   (7-2 logic)
               triggered automatically when Veo raises VeoSafetyBlockedError.

All blocking I/O (GCS upload/download, FAL HTTP, Veo polling) runs in the
thread-pool executor so the async orchestrator can run multiple video jobs
concurrently.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

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
    FAL_RESOLUTION,
    FAL_SAFETY_TOLERANCE,
    FAL_TIMEOUT_S,
    GOOGLE_CLOUD_PROJECT,
    GOOGLE_CLOUD_LOCATION,
    RATE_LIMIT_DELAYS,
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
)
from backend.utils.retry import VeoSafetyBlockedError, is_veo_safety_error

logger = logging.getLogger(__name__)

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


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


def _generate_veo_sync(
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    run_id: str,
    output_dir: Path,
) -> str:
    """Run Veo generation synchronously. Returns local mp4 path."""
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
        # Submit with 429 retry
        delays = list(RATE_LIMIT_DELAYS)
        for attempt, delay in enumerate(delays + [None], start=1):  # type: ignore[operator]
            try:
                operation = client.models.generate_videos(
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
                break
            except Exception as exc:
                if "429" in str(exc) and delay is not None:
                    logger.warning(
                        "[Veo] Rate limited (attempt %d). Waiting %ss…", attempt, delay
                    )
                    time.sleep(delay)
                else:
                    raise

        # Poll
        operation = _wait_for_veo_operation(
            client, operation, VEO_POLL_INTERVAL_S, VEO_TIMEOUT_S
        )

        if operation.response:
            break

        err = getattr(operation, "error", None)
        err_code = err.get("code") if isinstance(err, dict) else getattr(err, "code", None)
        err_msg = str(err) if err else str(operation)

        if is_veo_safety_error(Exception(err_msg)):
            raise VeoSafetyBlockedError(
                "Veo blocked generation due to person/face safety settings"
            )

        if err_code == 13 and internal_attempt < VEO_INTERNAL_ERROR_RETRIES:
            delay = VEO_INTERNAL_ERROR_DELAYS[internal_attempt]
            logger.warning("[Veo] Internal error code 13. Retrying in %ss…", delay)
            time.sleep(delay)
            continue

        raise RuntimeError(f"Veo returned no response: {operation}")

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


def _download_url_sync(url: str, path: Path) -> None:
    req = Request(url, headers={"User-Agent": "Python"})
    with urlopen(req, timeout=300) as resp:
        path.write_bytes(resp.read())


def _generate_fal_sync(
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    output_path: Path,
) -> None:
    """Run FAL Veo 3.1 generation synchronously."""
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
    out = _fal_request("POST", endpoint, payload)
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
        status_resp = _fal_request("GET", poll_url)
        st = (status_resp.get("status") or "").upper()
        if st == "COMPLETED":
            response_url = status_resp.get("response_url") or response_url
            break
        if st == "FAILED":
            raise RuntimeError(f"FAL job failed: {status_resp}")
        time.sleep(FAL_POLL_INTERVAL_S)
    else:
        raise TimeoutError(f"FAL job did not complete within {FAL_TIMEOUT_S}s")

    # Fetch result
    result = _fal_request("GET", response_url)
    video_info = result.get("video") or result.get("data", {}).get("video")
    if not video_info:
        raise RuntimeError(f"FAL result missing video: {result}")
    video_url = video_info.get("url")
    if not video_url:
        raise RuntimeError(f"FAL video object missing url: {video_info}")

    _download_url_sync(video_url, output_path)


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
) -> tuple[str, str]:
    """
    Generate a sub-scene video.

    Tries Veo first; falls back to FAL on VeoSafetyBlockedError.
    Returns ``(subscene_key, saved_path)``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"scene_{scene_idx}_sub_{sub_idx}.mp4"
    out_path = output_dir / filename
    key = f"scene_{scene_idx}_sub_{sub_idx}"

    if out_path.exists():
        logger.info("Video already exists, skipping: %s", filename)
        return key, str(out_path)

    run_id = f"s{scene_idx}_{sub_idx}_{uuid.uuid4().hex[:6]}"
    loop = asyncio.get_running_loop()

    # ---- Primary: Veo ----
    try:
        logger.info("Generating video via Veo: %s", filename)
        local_mp4 = await loop.run_in_executor(
            None,
            _generate_veo_sync,
            video_prompt,
            subscene_image_path,
            list(character_image_paths),
            run_id,
            output_dir,
        )
        # Rename temp file to stable name
        Path(local_mp4).rename(out_path)
        logger.info("Video saved (Veo): %s", filename)
        return key, str(out_path)

    except VeoSafetyBlockedError:
        logger.warning(
            "[%s] Veo safety block — falling back to FAL Veo 3.1.", filename
        )

    except Exception as exc:
        logger.error("[%s] Veo failed with unexpected error: %s", filename, exc)
        raise

    # ---- Fallback: FAL ----
    try:
        logger.info("Generating video via FAL fallback: %s", filename)
        await loop.run_in_executor(
            None,
            _generate_fal_sync,
            video_prompt,
            subscene_image_path,
            list(character_image_paths),
            out_path,
        )
        logger.info("Video saved (FAL): %s", filename)
        return key, str(out_path)

    except (HTTPError, URLError, RuntimeError, TimeoutError) as exc:
        logger.error("[%s] FAL fallback also failed: %s", filename, exc)
        raise RuntimeError(f"Both Veo and FAL failed for {filename}: {exc}") from exc
