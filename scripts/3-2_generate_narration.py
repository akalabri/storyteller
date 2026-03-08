import os
import json
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY") or os.getenv("XI_API_KEY")

VOICE_ID = "zNsotODqUhvbJ5wMG7Ei"
MODEL_ID = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"

ELEVENLABS_URL = (
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps"
)

HEADERS = {
    "xi-api-key": ELEVENLABS_API_KEY or "",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def chars_to_words(alignment: dict) -> list[dict]:
    """
    Convert character-level alignment into word-level timestamp entries.

    Each entry: {"word": str, "start": float, "end": float}
    """
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
                    {
                        "word": "".join(current_word),
                        "start": word_start,
                        "end": word_end,
                    }
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
# TTS with timestamps
# ---------------------------------------------------------------------------


def synthesise_scene_with_timestamps(
    text: str, audio_path: str, timestamps_path: str
) -> dict:
    """
    Call ElevenLabs /with-timestamps, save audio and a companion JSON
    containing both character- and word-level timestamps.

    Returns the parsed timestamps dict saved to disk.
    """
    payload = {
        "text": text.strip(),
        "model_id": MODEL_ID,
        "output_format": OUTPUT_FORMAT,
    }

    response = requests.post(ELEVENLABS_URL, headers=HEADERS, json=payload)
    response.raise_for_status()

    result = response.json()

    # Decode and save audio
    audio_bytes = base64.b64decode(result["audio_base64"])
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)

    # Build timestamps payload
    alignment = result.get("alignment", {})
    normalized = result.get("normalized_alignment", {})

    timestamps = {
        "character_alignment": alignment,
        "normalized_alignment": normalized,
        "words": chars_to_words(alignment),
    }

    with open(timestamps_path, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, indent=2, ensure_ascii=False)

    return timestamps


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    scripts_dir = os.path.dirname(__file__)
    breakdown_path = os.path.join(scripts_dir, "story_convo_example_breakdown.json")
    output_dir = os.path.join(scripts_dir, "output_narration")
    os.makedirs(output_dir, exist_ok=True)

    with open(breakdown_path, "r", encoding="utf-8") as f:
        breakdown = json.load(f)

    scenes = breakdown["story"]
    special = breakdown.get("special_instructions", "")

    if special:
        print(
            f"Special instructions noted: {special[:120]}{'...' if len(special) > 120 else ''}\n"
        )

    if not ELEVENLABS_API_KEY or not ELEVENLABS_API_KEY.strip():
        raise SystemExit(
            "Missing ElevenLabs API key. Set ELEVENLABS_API_KEY or XI_API_KEY in your .env file."
        )

    # Patch header now that we know the key is valid
    HEADERS["xi-api-key"] = ELEVENLABS_API_KEY

    print(f"Generating narration + timestamps for {len(scenes)} scene(s) (ElevenLabs)...\n")

    for i, scene_text in enumerate(scenes, start=1):
        audio_path = os.path.join(output_dir, f"scene_{i}.mp3")
        timestamps_path = os.path.join(output_dir, f"scene_{i}_timestamps.json")

        timestamps = synthesise_scene_with_timestamps(
            scene_text, audio_path, timestamps_path
        )

        word_count = len(timestamps["words"])
        duration = (
            timestamps["words"][-1]["end"] if timestamps["words"] else 0.0
        )
        preview = scene_text[:80].replace("\n", " ")

        print(f"  [Scene {i}] Audio    -> {audio_path}")
        print(f"             Timestamps-> {timestamps_path}")
        print(f"             Words: {word_count}  |  Duration: {duration:.2f}s")
        print(f"             \"{preview}{'...' if len(scene_text) > 80 else ''}\"")
        print()

    print(f"All narration files saved to: {output_dir}")


if __name__ == "__main__":
    main()
