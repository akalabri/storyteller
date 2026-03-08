"""
Scene image agent — generates a single scene PNG from an image prompt using
Gemini image generation, with character reference images as context.

Designed to be called concurrently (asyncio.gather) for all sub-scenes.
Each blocking genai call runs in the thread-pool executor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from PIL import Image

from backend.config import (
    GEMINI_IMAGE_LOCATION,
    GEMINI_IMAGE_MODEL,
    GOOGLE_CLOUD_PROJECT,
    RATE_LIMIT_DELAYS,
    SCENE_ASPECT_RATIO,
    SCENE_RESOLUTION,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync generation (runs inside executor)
# ---------------------------------------------------------------------------

def _load_reference_images(character_paths: list[str]) -> list[Image.Image]:
    images = []
    for path in sorted(character_paths):
        p = Path(path)
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and p.exists():
            images.append(Image.open(p).convert("RGBA"))
    return images


def _generate_sync(
    image_prompt: str,
    character_paths: list[str],
    out_path: str,
) -> None:
    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GEMINI_IMAGE_LOCATION,
    )

    ref_images = _load_reference_images(character_paths)
    contents: list = [image_prompt, *ref_images]

    delays = list(RATE_LIMIT_DELAYS)
    last_exc: Exception | None = None

    for attempt, delay in enumerate(delays + [None], start=1):  # type: ignore[operator]
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

            for part in response.parts:
                img = part.as_image()
                if img is not None:
                    img.save(out_path)
                    return

            text_parts = [p.text for p in response.parts if hasattr(p, "text") and p.text]
            raise RuntimeError(
                f"No image in response for {out_path}. Model said: {' '.join(text_parts)}"
            )

        except genai_errors.ClientError as exc:
            if "429" in str(exc) and delay is not None:
                logger.warning(
                    "[scene_image] Rate limited (attempt %d). Waiting %ss…", attempt, delay
                )
                time.sleep(delay)
                last_exc = exc
            else:
                raise

    raise last_exc or RuntimeError("All retry attempts exhausted")


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
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"scene_{scene_idx}_sub_{sub_idx}.png"
    out_path = str(output_dir / filename)

    if Path(out_path).exists():
        logger.info("Scene image already exists, skipping: %s", filename)
        return f"scene_{scene_idx}_sub_{sub_idx}", out_path

    logger.info("Generating scene image: %s", filename)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, _generate_sync, image_prompt, character_image_paths, out_path
    )
    logger.info("Scene image saved: %s", filename)
    return f"scene_{scene_idx}_sub_{sub_idx}", out_path
