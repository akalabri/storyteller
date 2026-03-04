import os
import json
import time
from pathlib import Path
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

RETRY_DELAYS = [15, 30, 60, 120]  # seconds between attempts on 429

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ID   = os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini")
# Gemini image models require global endpoint; us-central1 returns "model not found".
LOCATION     = "global"
# Nano Banana 2 for scene images. If 404, try gemini-3.1-flash-image (no -preview) or gemini-2.5-flash-image-preview.
MODEL        = "gemini-3.1-flash-image-preview"
# MODEL        = "gemini-3.1-flash-image"
# MODEL        = "gemini-2.5-flash-image-preview"
ASPECT_RATIO = "9:16"  # vertical / portrait (phone-style), to match character sheets
RESOLUTION   = "2K"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_reference_images(characters_dir: str) -> list:
    """Load all character PNG/JPG files from the output_characters folder."""
    supported = {".png", ".jpg", ".jpeg", ".webp"}
    images = []
    for path in sorted(Path(characters_dir).iterdir()):
        if path.suffix.lower() in supported:
            images.append(Image.open(path).convert("RGBA"))
            print(f"  [ref] Loaded character image: {path.name}")
    return images


def generate_subscene_image(client: genai.Client,
                             image_prompt: str,
                             reference_images: list,
                             out_path: str) -> None:
    contents = [image_prompt, *reference_images]

    for attempt, delay in enumerate(RETRY_DELAYS + [None], start=1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=ASPECT_RATIO,
                        image_size=RESOLUTION,
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
                f"No image in response for {out_path}. "
                f"Model said: {' '.join(text_parts)}"
            )

        except genai_errors.ClientError as e:
            if "429" in str(e) and delay is not None:
                print(f"\n      Rate limited (attempt {attempt}). Waiting {delay}s...",
                      end=" ", flush=True)
                time.sleep(delay)
                print("retrying...", end=" ", flush=True)
            else:
                raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    scripts_dir = Path(__file__).parent

    visual_plan_path = scripts_dir / "story_visual_plan.json"
    characters_dir   = scripts_dir / "output_characters"
    output_dir       = scripts_dir / "output_scenes"
    output_dir.mkdir(exist_ok=True)

    with open(visual_plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,  # forced global for image models (see LOCATION above)
    )

    print("Loading character reference images...")
    ref_images = load_reference_images(str(characters_dir))
    if not ref_images:
        print("  Warning: no character reference images found in output_characters/")
    print()

    total_scenes    = len(plan["scenes"])
    total_subscenes = sum(len(s["subscenes"]) for s in plan["scenes"])
    generated       = 0

    print(f"Generating images for {total_scenes} scene(s) / {total_subscenes} sub-scene(s)...\n")

    for scene in plan["scenes"]:
        scene_idx = scene["scene_index"]
        print(f"  Scene {scene_idx}: {scene['scene_summary']}")

        for sub in scene["subscenes"]:
            sub_idx   = sub["index"]
            filename  = f"scene_{scene_idx}_sub_{sub_idx}.png"
            out_path  = str(output_dir / filename)

            if Path(out_path).exists():
                print(f"    [Scene {scene_idx} / Sub {sub_idx}] Already exists, skipping.")
                generated += 1
                continue

            print(f"    [Scene {scene_idx} / Sub {sub_idx}] Generating...", end=" ", flush=True)
            generate_subscene_image(client, sub["image_prompt"], ref_images, out_path)
            generated += 1
            print(f"Saved -> output_scenes/{filename}")

        print()

    print(f"Done. {generated}/{total_subscenes} images saved to: {output_dir}")


if __name__ == "__main__":
    main()
