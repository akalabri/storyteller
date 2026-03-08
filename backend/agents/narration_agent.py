"""
Narration agent — generates MP3 narration + word-level timestamps for a
single story scene using the ElevenLabs /with-timestamps endpoint.

Designed to be called sequentially (one scene at a time) to respect the
ElevenLabs rate limit.  Each call is async-friendly (blocking HTTP is
dispatched to the thread-pool executor).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path

import httpx

from backend.config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
    ELEVENLABS_VOICE_ID,
)

logger = logging.getLogger(__name__)

ELEVENLABS_URL = (
    f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/with-timestamps"
)


# ---------------------------------------------------------------------------
# Timestamp helpers (verbatim logic from 3-2_generate_narration.py)
# ---------------------------------------------------------------------------

def _chars_to_words(alignment: dict) -> list[dict]:
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    words: list[dict] = []
    current_word: list[str] = []
    word_start: float | None = None
    word_end: float | None = None

    for ch, t_start, t_end in zip(chars, starts, ends):
        if ch in (" ", "\n", "\t"):
            if current_word:
                words.append(
                    {"word": "".join(current_word), "start": word_start, "end": word_end}
                )
                current_word = []
                word_start = None
                word_end = None
        else:
            if not current_word:
                word_start = t_start
            current_word.append(ch)
            word_end = t_end

    if current_word:
        words.append(
            {"word": "".join(current_word), "start": word_start, "end": word_end}
        )

    return words


# ---------------------------------------------------------------------------
# Core async function
# ---------------------------------------------------------------------------

async def generate_narration(
    scene_text: str,
    audio_path: Path,
    timestamps_path: Path,
) -> dict:
    """
    Call ElevenLabs /with-timestamps for one scene, save the MP3 and a
    companion timestamps JSON, and return the timestamps dict.

    Uses httpx for async HTTP so the event loop stays free.
    """
    if not ELEVENLABS_API_KEY:
        raise RuntimeError(
            "Missing ElevenLabs API key. Set ELEVENLABS_API_KEY or XI_API_KEY in .env"
        )

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    timestamps_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "text": scene_text.strip(),
        "model_id": ELEVENLABS_MODEL_ID,
        "output_format": ELEVENLABS_OUTPUT_FORMAT,
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }

    logger.info("Generating narration for scene (%.60s…)", scene_text[:60])

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(ELEVENLABS_URL, headers=headers, json=payload)
        response.raise_for_status()

    result = response.json()

    # Save audio
    audio_bytes = base64.b64decode(result["audio_base64"])
    audio_path.write_bytes(audio_bytes)

    # Build and save timestamps
    alignment = result.get("alignment", {})
    normalized = result.get("normalized_alignment", {})
    timestamps = {
        "character_alignment": alignment,
        "normalized_alignment": normalized,
        "words": _chars_to_words(alignment),
    }
    timestamps_path.write_text(
        json.dumps(timestamps, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    word_count = len(timestamps["words"])
    duration = timestamps["words"][-1]["end"] if timestamps["words"] else 0.0
    logger.info(
        "Narration saved: %s  |  words=%d  duration=%.1fs",
        audio_path.name,
        word_count,
        duration,
    )

    return timestamps
