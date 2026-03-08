"""
Character image agent — generates a reference character-sheet PNG for one
character using Gemini image generation (Vertex AI, global endpoint).

Blocking genai calls are dispatched to the thread-pool executor so multiple
characters can be generated concurrently via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from backend.config import (
    CHARACTER_ASPECT_RATIO,
    CHARACTER_RESOLUTION,
    CHARACTER_SHEET_PREFIX,
    GEMINI_IMAGE_LOCATION,
    GEMINI_IMAGE_MODEL,
    GOOGLE_CLOUD_PROJECT,
    RATE_LIMIT_DELAYS,
)
from backend.pipeline.state import CharacterPrompt
from backend.utils.file_io import safe_filename
from backend.utils.retry import async_retry, RateLimitError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync generation (runs inside executor)
# ---------------------------------------------------------------------------

def _generate_sync(character: CharacterPrompt, out_path: str) -> str:
    """Generate and save a character sheet PNG. Returns the saved path."""
    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GEMINI_IMAGE_LOCATION,
    )

    prompt = CHARACTER_SHEET_PREFIX + character.description

    delays = list(RATE_LIMIT_DELAYS)
    last_exc: Exception | None = None

    for attempt, delay in enumerate(delays + [None], start=1):  # type: ignore[operator]
        try:
            response = client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=CHARACTER_ASPECT_RATIO,
                        image_size=CHARACTER_RESOLUTION,
                    ),
                ),
            )

            for part in response.parts:
                img = part.as_image()
                if img is not None:
                    img.save(out_path)
                    return out_path

            text_parts = [p.text for p in response.parts if hasattr(p, "text") and p.text]
            raise RuntimeError(
                f"No image returned for '{character.name}'. "
                f"Model said: {' '.join(text_parts)}"
            )

        except genai_errors.ClientError as exc:
            if "429" in str(exc) and delay is not None:
                import time
                logger.warning(
                    "[%s] Rate limited (attempt %d). Waiting %ss…",
                    character.name, attempt, delay,
                )
                time.sleep(delay)
                last_exc = exc
            else:
                raise

    raise last_exc or RuntimeError("All retry attempts failed")


# ---------------------------------------------------------------------------
# Public async function
# ---------------------------------------------------------------------------

async def generate_character_image(
    character: CharacterPrompt,
    output_dir: Path,
) -> tuple[str, str]:
    """
    Generate a reference character-sheet image for ``character``.

    Returns ``(character_name, saved_path)``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(character.name) + ".png"
    out_path = str(output_dir / filename)

    logger.info("Generating character sheet for '%s'…", character.name)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _generate_sync, character, out_path)
    logger.info("Character sheet saved: %s", filename)
    return character.name, out_path
