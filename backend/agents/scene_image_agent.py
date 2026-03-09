"""
Scene image agent — generates a single scene PNG from an image prompt using
Gemini image generation, with character reference images as context.

Designed to be called concurrently (asyncio.gather) for all sub-scenes.
Each blocking genai call runs in the thread-pool executor.

Error handling
──────────────
- Rate limits (HTTP 429): retried with exponential back-off up to
  IMAGE_RATE_LIMIT_DELAYS attempts.
- Transient server errors (HTTP 5xx, network issues): retried with
  IMAGE_TRANSIENT_DELAYS back-off.
- Content policy violations: raised immediately as
  ContentViolationError (non-retryable).
- No image in response: raised as ImageGenerationError (non-retryable).
- All retries exhausted: raises the last captured exception.

The orchestrator treats any raised exception from this module as a hard
failure for that sub-scene and will NOT proceed to video generation for it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image

from backend.config import (
    GEMINI_IMAGE_LOCATION,
    GEMINI_IMAGE_MODEL,
    GOOGLE_CLOUD_PROJECT,
    IMAGE_RATE_LIMIT_DELAYS,
    IMAGE_TRANSIENT_DELAYS,
    SCENE_ASPECT_RATIO,
    SCENE_RESOLUTION,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception types
# ---------------------------------------------------------------------------

class ImageGenerationError(RuntimeError):
    """Raised when the model returns a response with no image part."""


class ContentViolationError(ImageGenerationError):
    """
    Raised when the model refuses to generate an image due to a content
    policy violation.  This is non-retryable.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keywords that indicate a content policy refusal in the model's text response.
_CONTENT_VIOLATION_SIGNALS = (
    "safety",
    "policy",
    "cannot generate",
    "can't generate",
    "unable to generate",
    "not able to generate",
    "violat",
    "inappropriate",
    "harmful",
    "explicit",
    "refused",
)


def _is_content_violation(text: str) -> bool:
    lowered = text.lower()
    return any(signal in lowered for signal in _CONTENT_VIOLATION_SIGNALS)


def _is_rate_limit(exc: Exception) -> bool:
    return "429" in str(exc)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc)
    return any(code in msg for code in ("500", "502", "503", "504")) or isinstance(
        exc, (ConnectionError, TimeoutError, OSError)
    )


def _load_reference_images(character_paths: list[str]) -> list[Image.Image]:
    images = []
    for path in sorted(character_paths):
        p = Path(path)
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and p.exists():
            images.append(Image.open(p).convert("RGBA"))
    return images


# ---------------------------------------------------------------------------
# Sync generation (runs inside executor)
# ---------------------------------------------------------------------------

def _generate_sync(
    image_prompt: str,
    character_paths: list[str],
    out_path: str,
) -> None:
    """
    Call the Gemini image generation API and save the result to ``out_path``.

    Retry strategy
    ──────────────
    - 429 rate limit  → back-off using IMAGE_RATE_LIMIT_DELAYS, then give up.
    - 5xx / network   → back-off using IMAGE_TRANSIENT_DELAYS, then give up.
    - Content refusal → raise ContentViolationError immediately (no retry).
    - Any other error → raise immediately (no retry).
    """
    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GEMINI_IMAGE_LOCATION,
    )

    ref_images = _load_reference_images(character_paths)
    contents: list = [image_prompt, *ref_images]

    rate_limit_delays = list(IMAGE_RATE_LIMIT_DELAYS)
    transient_delays = list(IMAGE_TRANSIENT_DELAYS)

    rate_limit_attempt = 0
    transient_attempt = 0

    while True:
        try:
            response = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=SCENE_ASPECT_RATIO,
                        image_size=SCENE_RESOLUTION,
                    ),
                ),
            )

            # Extract image from response parts
            for part in response.parts:
                img = part.as_image()
                if img is not None:
                    img.save(out_path)
                    return

            # No image found — check if it's a content policy refusal
            text_parts = [
                p.text for p in response.parts if hasattr(p, "text") and p.text
            ]
            combined_text = " ".join(text_parts)

            if _is_content_violation(combined_text):
                raise ContentViolationError(
                    f"Content policy violation for '{out_path}'. "
                    f"Model said: {combined_text}"
                )

            raise ImageGenerationError(
                f"No image in response for '{out_path}'. "
                f"Model said: {combined_text or '(no text)'}"
            )

        except (ContentViolationError, ImageGenerationError):
            # Non-retryable — propagate immediately
            raise

        except genai_errors.ClientError as exc:
            if _is_rate_limit(exc):
                if rate_limit_attempt < len(rate_limit_delays):
                    delay = rate_limit_delays[rate_limit_attempt]
                    rate_limit_attempt += 1
                    logger.warning(
                        "[scene_image] Rate limited — attempt %d/%d. "
                        "Retrying in %ds. File: %s",
                        rate_limit_attempt,
                        len(rate_limit_delays),
                        delay,
                        Path(out_path).name,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "[scene_image] Rate limit retries exhausted for '%s'.",
                        Path(out_path).name,
                    )
                    raise
            elif _is_transient(exc):
                if transient_attempt < len(transient_delays):
                    delay = transient_delays[transient_attempt]
                    transient_attempt += 1
                    logger.warning(
                        "[scene_image] Transient API error (attempt %d/%d) — "
                        "retrying in %ds. File: %s. Error: %s",
                        transient_attempt,
                        len(transient_delays),
                        delay,
                        Path(out_path).name,
                        exc,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "[scene_image] Transient error retries exhausted for '%s'.",
                        Path(out_path).name,
                    )
                    raise
            else:
                # Unknown client error — do not retry
                logger.error(
                    "[scene_image] Non-retryable API error for '%s': %s",
                    Path(out_path).name,
                    exc,
                )
                raise

        except (ConnectionError, TimeoutError, OSError) as exc:
            if transient_attempt < len(transient_delays):
                delay = transient_delays[transient_attempt]
                transient_attempt += 1
                logger.warning(
                    "[scene_image] Network error (attempt %d/%d) — "
                    "retrying in %ds. File: %s. Error: %s",
                    transient_attempt,
                    len(transient_delays),
                    delay,
                    Path(out_path).name,
                    exc,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "[scene_image] Network error retries exhausted for '%s'.",
                    Path(out_path).name,
                )
                raise

        except Exception as exc:
            # Unexpected error — log and propagate without retry
            logger.error(
                "[scene_image] Unexpected error for '%s': %s",
                Path(out_path).name,
                exc,
            )
            raise


# ---------------------------------------------------------------------------
# Public async function
# ---------------------------------------------------------------------------

async def generate_scene_image(
    scene_idx: int,
    sub_idx: int,
    image_prompt: str,
    character_image_paths: list[str],
    output_dir: Path,
) -> tuple[str, str]:
    """
    Generate a sub-scene image and save it to ``output_dir``.

    Returns ``(subscene_key, saved_path)`` where subscene_key is
    ``"scene_{scene_idx}_sub_{sub_idx}"``.

    Raises
    ------
    ContentViolationError
        The model refused due to a content policy violation.
    ImageGenerationError
        The model returned a response with no image.
    google.genai.errors.ClientError
        API error after all retries are exhausted.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"scene_{scene_idx}_sub_{sub_idx}.png"
    out_path = str(output_dir / filename)

    if Path(out_path).exists():
        logger.info("[scene_image] Already exists, skipping: %s", filename)
        return f"scene_{scene_idx}_sub_{sub_idx}", out_path

    logger.info("[scene_image] Generating: %s", filename)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, _generate_sync, image_prompt, character_image_paths, out_path
    )
    logger.info("[scene_image] Saved: %s", filename)
    return f"scene_{scene_idx}_sub_{sub_idx}", out_path
