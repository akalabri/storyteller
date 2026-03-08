import os
import json
from google.cloud import texttospeech
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-US"
SPEAKING_RATE = 1.0   # Slightly slower for a children's story
PITCH         = 0.0


# ---------------------------------------------------------------------------
# TTS helpers
# ---------------------------------------------------------------------------

def build_ssml(text: str) -> str:
    """
    Wrap plain story text in SSML for a gentle, narrative delivery.
    Splits on sentence-ending punctuation and inserts natural pauses.
    """
    import re

    # Split into sentences; keep the delimiter attached to the preceding token
    sentences = re.split(r'(?<=[.!?…])\s+', text.strip())

    parts = []
    for sentence in sentences:
        sentence = sentence.strip()
        if sentence:
            parts.append(f'<s>{sentence}</s>')

    inner = '\n<break time="400ms"/>\n'.join(parts)

    return (
        f'<speak>'
        f'<prosody rate="{SPEAKING_RATE}" pitch="{PITCH:+.1f}st">'
        f'{inner}'
        f'</prosody>'
        f'</speak>'
    )


def synthesise_scene(client: texttospeech.TextToSpeechClient,
                     text: str,
                     out_path: str) -> str:
    ssml = build_ssml(text)

    synthesis_input = texttospeech.SynthesisInput(ssml=ssml)

    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE_CODE,
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=SPEAKING_RATE,
        pitch=PITCH,
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    with open(out_path, "wb") as f:
        f.write(response.audio_content)

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

    # Check whether special instructions mention a specific narrative style
    if special:
        print(f"Special instructions noted: {special[:120]}{'...' if len(special) > 120 else ''}\n")

    client = texttospeech.TextToSpeechClient()

    print(f"Generating narration for {len(scenes)} scene(s)...\n")

    for i, scene_text in enumerate(scenes, start=1):
        out_path = os.path.join(output_dir, f"scene_{i}.mp3")
        synthesise_scene(client, scene_text, out_path)
        preview = scene_text[:80].replace("\n", " ")
        print(f"  [Scene {i}] Saved -> {out_path}")
        print(f"            \"{preview}{'...' if len(scene_text) > 80 else ''}\"")

    print(f"\nAll narration files saved to: {output_dir}")


if __name__ == "__main__":
    main()
