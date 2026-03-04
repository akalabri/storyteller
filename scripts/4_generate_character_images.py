import os
import json
import re
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ID   = os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini")
# Gemini image models require global endpoint; us-central1 returns "model not found".
LOCATION     = "global"
# Nano Banana 2. If 404, try gemini-3.1-flash-image (no -preview) or gemini-2.5-flash-image-preview.
MODEL = "gemini-3.1-flash-image-preview"
# MODEL = "gemini-3.1-flash-image"
# MODEL = "gemini-2.5-flash-image-preview"
ASPECT_RATIO = "9:16"  # vertical / portrait (phone-style)
RESOLUTION   = "2K"

CHARACTER_SHEET_PREFIX = (
    "Character reference sheet for a 2d story illustration. "
    "Show the character from three angles on a clean white background: "
    "front view (center), side profile (left), and back view (right). "
    "Include a small close-up of the face and head in the top corner. "
    "Consistent lighting, flat style suitable for animation. "
    "Character details: "
)

# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    """Convert a character name (including Arabic) to a safe ASCII filename."""
    slug = re.sub(r'[^\w\- ]', '', name, flags=re.ASCII).strip()
    slug = re.sub(r'\s+', '_', slug)
    return slug if slug else f"character_{hash(name) & 0xFFFF}"


def generate_character_sheet(client: genai.Client,
                              character: dict,
                              out_path: str) -> str:
    prompt = CHARACTER_SHEET_PREFIX + character["description"]

    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=ASPECT_RATIO,
                image_size=RESOLUTION,
            ),
        ),
    )

    saved = False
    for part in response.parts:
        img = part.as_image()
        if img is not None:
            img.save(out_path)
            saved = True
            break

    if not saved:
        # Surface any text the model returned instead of an image
        text_parts = [p.text for p in response.parts if hasattr(p, "text") and p.text]
        raise RuntimeError(
            f"No image returned for '{character['name']}'. "
            f"Model response: {' '.join(text_parts)}"
        )

    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    scripts_dir = os.path.dirname(__file__)
    breakdown_path = os.path.join(scripts_dir, "story_convo_example_breakdown.json")
    output_dir = os.path.join(scripts_dir, "output_characters")
    os.makedirs(output_dir, exist_ok=True)

    with open(breakdown_path, "r", encoding="utf-8") as f:
        breakdown = json.load(f)

    characters = breakdown["characters_prompts"]

    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,  # forced global for image models (see LOCATION above)
    )

    print(f"Generating reference sheets for {len(characters)} character(s)...\n")

    for character in characters:
        name = character["name"]
        filename = safe_filename(name) + ".png"
        out_path = os.path.join(output_dir, filename)

        print(f"  [{name}] Generating...")
        generate_character_sheet(client, character, out_path)
        print(f"  [{name}] Saved -> {out_path}\n")

    print(f"All character sheets saved to: {output_dir}")


if __name__ == "__main__":
    main()
