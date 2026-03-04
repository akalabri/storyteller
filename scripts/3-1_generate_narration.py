import os
import json
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ElevenLabs API key (env: ELEVENLABS_API_KEY or XI_API_KEY)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY") or os.getenv("XI_API_KEY")

VOICE_ID = "zNsotODqUhvbJ5wMG7Ei"
MODEL_ID = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"

# ---------------------------------------------------------------------------
# TTS helpers
# ---------------------------------------------------------------------------


def synthesise_scene(client: ElevenLabs, text: str, out_path: str) -> str:
    """Convert scene text to speech with ElevenLabs and save to file."""
    audio = client.text_to_speech.convert(
        text=text.strip(),
        voice_id=VOICE_ID,
        model_id=MODEL_ID,
        output_format=OUTPUT_FORMAT,
    )

    with open(out_path, "wb") as f:
        if isinstance(audio, bytes):
            f.write(audio)
        else:
            for chunk in audio:
                if chunk:
                    f.write(chunk)

    return out_path


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
        print(f"Special instructions noted: {special[:120]}{'...' if len(special) > 120 else ''}\n")

    if not ELEVENLABS_API_KEY or not ELEVENLABS_API_KEY.strip():
        raise SystemExit(
            "Missing ElevenLabs API key. Set ELEVENLABS_API_KEY or XI_API_KEY in your .env file."
        )
    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    print(f"Generating narration for {len(scenes)} scene(s) (ElevenLabs)...\n")

    for i, scene_text in enumerate(scenes, start=1):
        out_path = os.path.join(output_dir, f"scene_{i}.mp3")
        synthesise_scene(client, scene_text, out_path)
        preview = scene_text[:80].replace("\n", " ")
        print(f"  [Scene {i}] Saved -> {out_path}")
        print(f"            \"{preview}{'...' if len(scene_text) > 80 else ''}\"")

    print(f"\nAll narration files saved to: {output_dir}")


if __name__ == "__main__":
    main()
