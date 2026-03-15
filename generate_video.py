"""
Standalone video generation script using Google Veo via Vertex AI.

Edit the variables in the CONFIG section below, then run:
    python generate_video.py
"""

import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.cloud import storage

# ===========================================================================
# CONFIG — edit these
# ===========================================================================

PROMPT = "A baker kneading dough in a warm sunlit kitchen, cinematic slow motion"

_ROOT = Path(__file__).parent
_SESSION = _ROOT / "sessions" / "dev_session"

SCENE_IMAGE = str(_SESSION / "scenes" / "scene_1_sub_1.png")

CHARACTER_IMAGES = [
    str(_SESSION / "characters" / "Baker.png"),
]

OUTPUT_PATH = "output_video.mp4"

# Veo model options:
#   "veo-3.1-fast-generate-001"  — faster, lower quality
#   "veo-3.1-generate-001"       — slower, higher quality
#   "veo-3.0-generate-001"       — previous generation
MODEL = "veo-3.1-generate-001"

# ===========================================================================
# Setup
# ===========================================================================

load_dotenv(_ROOT / ".env")

GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
VEO_BUCKET = os.environ.get("VEO_BUCKET", "challengegemini-storyteller")

_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if _creds:
    _creds_path = Path(_creds)
    if not _creds_path.is_absolute():
        _creds_path = _ROOT / _creds_path
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_creds_path.resolve())

# ===========================================================================
# Helpers
# ===========================================================================

def upload_to_gcs(local_path: str, run_id: str, label: str) -> str:
    ext = Path(local_path).suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    blob_name = f"veo_inputs/{run_id}/{label}{ext}"
    gcs = storage.Client(project=GOOGLE_CLOUD_PROJECT)
    gcs.bucket(VEO_BUCKET).blob(blob_name).upload_from_filename(local_path, content_type=mime)
    gcs_uri = f"gs://{VEO_BUCKET}/{blob_name}"
    print(f"  Uploaded {Path(local_path).name} → {gcs_uri}")
    return gcs_uri


def download_from_gcs(gs_uri: str, local_path: str) -> None:
    parsed = urlparse(gs_uri)
    bucket_name = parsed.netloc
    blob_name = parsed.path.lstrip("/")
    gcs = storage.Client(project=GOOGLE_CLOUD_PROJECT)
    gcs.bucket(bucket_name).blob(blob_name).download_to_filename(local_path)


# ===========================================================================
# Main
# ===========================================================================

run_id = uuid.uuid4().hex[:8]
output = Path(OUTPUT_PATH)
output.parent.mkdir(parents=True, exist_ok=True)

print(f"\nPrompt : {PROMPT}")
print(f"Run ID : {run_id}")
print(f"Output : {output.resolve()}\n")

# Upload reference images
print("Uploading reference images to GCS...")
reference_images = []

scene_gcs = upload_to_gcs(SCENE_IMAGE, run_id, "scene")
reference_images.append(
    types.VideoGenerationReferenceImage(
        image=types.Image(gcs_uri=scene_gcs, mime_type="image/png"),
        reference_type="asset",
    )
)

for i, char_path in enumerate(CHARACTER_IMAGES):
    char_gcs = upload_to_gcs(char_path, run_id, f"character_{i}")
    ext = Path(char_path).suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    reference_images.append(
        types.VideoGenerationReferenceImage(
            image=types.Image(gcs_uri=char_gcs, mime_type=mime),
            reference_type="asset",
        )
    )

# Submit to Veo
print("\nSubmitting to Veo...")
client = genai.Client(
    vertexai=True,
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION,
)

operation = client.models.generate_videos(
    model=MODEL,
    prompt=PROMPT,
    config=types.GenerateVideosConfig(
        reference_images=reference_images,
        aspect_ratio="9:16",
        duration_seconds=8,
        resolution="720p",
        generate_audio=False,
        output_gcs_uri=f"gs://{VEO_BUCKET}/veo_outputs/{run_id}/",
    ),
)
print("Job submitted. Polling every 15s (may take a few minutes)...")

# Poll until done
start = time.time()
while not operation.done:
    elapsed = int(time.time() - start)
    print(f"  Waiting... ({elapsed}s elapsed)")
    time.sleep(15)
    operation = client.operations.get(operation)

if not operation.response:
    raise RuntimeError(f"Veo returned no response: {getattr(operation, 'error', operation)}")

# Download result
video_gcs_uri = operation.result.generated_videos[0].video.uri
print(f"\nDone! Downloading from {video_gcs_uri} ...")
download_from_gcs(video_gcs_uri, str(output))
print(f"\nVideo saved to: {output.resolve()}")
