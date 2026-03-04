import os
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from google import genai
from google.genai import types
from google.cloud import storage
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ID      = os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini")
LOCATION        = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
VEO_BUCKET      = os.environ.get("VEO_BUCKET", "challengegemini-storyteller")

MODEL            = "veo-3.1-fast-generate-001"
ASPECT_RATIO     = "9:16"
DURATION_SECONDS = 8
RESOLUTION       = "720p"
# Veo supports video-only: set False for silent output (narration is added separately).
GENERATE_AUDIO   = False

RETRY_DELAYS = [15, 30, 60, 120]   # seconds, on 429
INTERNAL_ERROR_RETRIES = 3         # retries when Veo returns code 13 (internal error)
INTERNAL_ERROR_DELAYS = [30, 60, 120]  # seconds between retries


class VeoSafetyBlockedError(Exception):
    """Raised when Veo blocks generation due to person/face safety settings."""
    pass


# ---------------------------------------------------------------------------
# GCS helpers
# ---------------------------------------------------------------------------

def upload_to_gcs(local_path: str, bucket_name: str, blob_name: str) -> str:
    gcs = storage.Client(project=PROJECT_ID)
    blob = gcs.bucket(bucket_name).blob(blob_name)
    mime = "image/png" if local_path.lower().endswith(".png") else "image/jpeg"
    blob.upload_from_filename(local_path, content_type=mime)
    return f"gs://{bucket_name}/{blob_name}"


def download_from_gcs(gs_uri: str, local_path: str) -> None:
    u = urlparse(gs_uri)
    bucket_name = u.netloc
    blob_name   = u.path.lstrip("/")
    gcs = storage.Client(project=PROJECT_ID)
    gcs.bucket(bucket_name).blob(blob_name).download_to_filename(local_path)


# ---------------------------------------------------------------------------
# Video generation
# ---------------------------------------------------------------------------

def wait_for_operation(client: genai.Client, op,
                        poll_s: int = 15, timeout_s: int = 1800):
    start = time.time()
    while not op.done:
        if time.time() - start > timeout_s:
            raise TimeoutError(f"Timed out after {timeout_s}s")
        time.sleep(poll_s)
        op = client.operations.get(op)
    return op


def generate_video(client: genai.Client,
                   video_prompt: str,
                   subscene_image_path: str,
                   character_image_paths: list[str],
                   run_id: str,
                   output_dir: Path) -> str:
    """
    Upload the subscene image + character images to GCS, call Veo,
    poll until done, download the mp4, and return the local path.
    """
    # Upload all reference images to GCS
    reference_images = []

    # Subscene image goes first (primary visual reference)
    blob_name = f"veo_inputs/{run_id}/subscene.png"
    gcs_uri   = upload_to_gcs(subscene_image_path, VEO_BUCKET, blob_name)
    reference_images.append(
        types.VideoGenerationReferenceImage(
            image=types.Image(gcs_uri=gcs_uri, mime_type="image/png"),
            reference_type="asset",
        )
    )

    # Character reference images follow
    for i, char_path in enumerate(character_image_paths):
        ext      = Path(char_path).suffix.lower()
        mime     = "image/png" if ext == ".png" else "image/jpeg"
        blob_name = f"veo_inputs/{run_id}/character_{i}{ext}"
        gcs_uri   = upload_to_gcs(char_path, VEO_BUCKET, blob_name)
        reference_images.append(
            types.VideoGenerationReferenceImage(
                image=types.Image(gcs_uri=gcs_uri, mime_type=mime),
                reference_type="asset",
            )
        )

    output_gcs_prefix = f"gs://{VEO_BUCKET}/veo_outputs/{run_id}/"

    for internal_attempt in range(INTERNAL_ERROR_RETRIES + 1):
        # Call Veo with retry on 429
        for attempt, delay in enumerate(RETRY_DELAYS + [None], start=1):
            try:
                operation = client.models.generate_videos(
                    model=MODEL,
                    prompt=video_prompt,
                    config=types.GenerateVideosConfig(
                        reference_images=reference_images,
                        aspect_ratio=ASPECT_RATIO,
                        duration_seconds=DURATION_SECONDS,
                        resolution=RESOLUTION,
                        generate_audio=GENERATE_AUDIO,
                        output_gcs_uri=output_gcs_prefix,
                    ),
                )
                break
            except Exception as e:
                if "429" in str(e) and delay is not None:
                    print(f"\n      Rate limited (attempt {attempt}). Waiting {delay}s...",
                          end=" ", flush=True)
                    time.sleep(delay)
                    print("retrying...", end=" ", flush=True)
                else:
                    raise

        print("waiting for Veo...", end=" ", flush=True)
        operation = wait_for_operation(client, operation)

        if operation.response:
            break

        err = getattr(operation, "error", None)
        err_code = err.get("code") if isinstance(err, dict) else getattr(err, "code", None)
        err_msg = str(err) if err else str(operation)
        if "person/face generation" in err_msg or "safety" in err_msg.lower() or "blocked" in err_msg.lower():
            raise VeoSafetyBlockedError("Safety settings blocked generation (person/face)")
        if err_code == 13 and internal_attempt < INTERNAL_ERROR_RETRIES:
            delay = INTERNAL_ERROR_DELAYS[internal_attempt]
            print(f"\n      Veo internal error (code 13). Retrying in {delay}s...", flush=True)
            time.sleep(delay)
            continue
        raise RuntimeError(f"Veo returned no response. Op: {operation}")

    video_gcs_uri = operation.result.generated_videos[0].video.uri

    local_mp4 = str(output_dir / f"{run_id}.mp4")
    download_from_gcs(video_gcs_uri, local_mp4)
    return local_mp4


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    scripts_dir = Path(__file__).parent

    visual_plan_path  = scripts_dir / "story_visual_plan.json"
    characters_dir    = scripts_dir / "output_characters"
    scenes_dir        = scripts_dir / "output_scenes"
    output_dir        = scripts_dir / "output_videos"
    output_dir.mkdir(exist_ok=True)

    with open(visual_plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
    )

    # Collect character reference image paths
    supported = {".png", ".jpg", ".jpeg", ".webp"}
    character_paths = sorted(
        str(p) for p in characters_dir.iterdir()
        if p.suffix.lower() in supported
    )
    print(f"Character reference images: {[Path(p).name for p in character_paths]}\n")

    total_scenes    = len(plan["scenes"])
    total_subscenes = sum(len(s["subscenes"]) for s in plan["scenes"])
    generated       = 0

    print(f"Generating videos for {total_scenes} scene(s) / {total_subscenes} sub-scene(s)...\n")

    for scene in plan["scenes"]:
        scene_idx = scene["scene_index"]
        print(f"  Scene {scene_idx}: {scene['scene_summary']}")

        for sub in scene["subscenes"]:
            sub_idx       = sub["index"]
            out_filename  = f"scene_{scene_idx}_sub_{sub_idx}.mp4"
            out_path      = output_dir / out_filename
            scene_img     = scenes_dir / f"scene_{scene_idx}_sub_{sub_idx}.png"

            if out_path.exists():
                print(f"    [Scene {scene_idx} / Sub {sub_idx}] Already exists, skipping.")
                generated += 1
                continue

            if not scene_img.exists():
                print(f"    [Scene {scene_idx} / Sub {sub_idx}] "
                      f"Missing scene image ({scene_img.name}), skipping.")
                continue

            run_id = f"s{scene_idx}_{sub_idx}_{uuid.uuid4().hex[:6]}"
            print(f"    [Scene {scene_idx} / Sub {sub_idx}] Generating...", end=" ", flush=True)

            try:
                local_mp4 = generate_video(
                    client=client,
                    video_prompt=sub["video_prompt"],
                    subscene_image_path=str(scene_img),
                    character_image_paths=character_paths,
                    run_id=run_id,
                    output_dir=output_dir,
                )
            except VeoSafetyBlockedError:
                print("Skipped (safety / person-face block).")
                continue

            # Rename to the stable output filename
            Path(local_mp4).rename(out_path)
            generated += 1
            print(f"Saved -> output_videos/{out_filename}")

        print()

    print(f"Done. {generated}/{total_subscenes} videos saved to: {output_dir}")


if __name__ == "__main__":
    main()
