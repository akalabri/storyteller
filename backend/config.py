"""
Central configuration for the storyteller backend.

All environment variables and pipeline constants are defined here so
every agent/utility imports from one place.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from backend/)
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")


def _resolve_google_credentials() -> None:
    """Resolve GOOGLE_APPLICATION_CREDENTIALS to an absolute path and validate it exists."""
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds:
        return
    path = Path(creds)
    if not path.is_absolute():
        path = _root / path
    if path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path.resolve())
        return
    raise FileNotFoundError(
        f"Google credentials file not found: {path}\n"
        "Vertex AI needs a service account key. Either:\n"
        "  1. Create a key in GCP Console → IAM → Service Accounts → Keys,\n"
        "     save it as key.json in the project root, and set in .env:\n"
        "     GOOGLE_APPLICATION_CREDENTIALS=key.json\n"
        "  2. Or use Application Default Credentials: run\n"
        "     gcloud auth application-default login\n"
        "     and leave GOOGLE_APPLICATION_CREDENTIALS unset in .env."
    )


_resolve_google_credentials()

# ---------------------------------------------------------------------------
# Google Cloud / Vertex AI
# ---------------------------------------------------------------------------
GOOGLE_CLOUD_PROJECT: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini")
GOOGLE_CLOUD_LOCATION: str = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
VEO_BUCKET: str = os.environ.get("VEO_BUCKET", "challengegemini-storyteller")

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
ELEVENLABS_API_KEY: str = (
    os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("XI_API_KEY") or ""
)
FAL_API_KEY: str = (
    os.environ.get("FAL_API_KEY") or os.environ.get("FAL_KEY") or ""
)

# ---------------------------------------------------------------------------
# Gemini models
# ---------------------------------------------------------------------------
# Gemini 3.1 Pro (preview) — requires location="global" on Vertex AI.
GEMINI_TEXT_MODEL: str = os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.1-pro-preview")
GEMINI_TEXT_LOCATION: str = os.environ.get("GEMINI_TEXT_LOCATION", "global")
# Model used for story breakdown (transcript → scenes + character prompts).
GEMINI_STORY_MODEL: str = os.environ.get("GEMINI_STORY_MODEL", "gemini-3.1-pro-preview")
# Timeout in seconds for the story breakdown API call (avoids hanging forever).
STORY_BREAKDOWN_TIMEOUT_S: int = int(os.environ.get("STORY_BREAKDOWN_TIMEOUT_S", "120"))
# Temporary: use 2.5 flash for image gen (character + scene images)
GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image-preview"
GEMINI_IMAGE_LOCATION: str = "global"   # image models require global endpoint

# ---------------------------------------------------------------------------
# ElevenLabs
# ---------------------------------------------------------------------------
ELEVENLABS_VOICE_ID: str = "zNsotODqUhvbJ5wMG7Ei"
ELEVENLABS_MODEL_ID: str = "eleven_multilingual_v2"
ELEVENLABS_OUTPUT_FORMAT: str = "mp3_44100_128"

# ---------------------------------------------------------------------------
# Character image generation
# ---------------------------------------------------------------------------
CHARACTER_ASPECT_RATIO: str = "9:16"
CHARACTER_RESOLUTION: str = "2K"
CHARACTER_SHEET_PREFIX: str = (
    "Character reference sheet for a 2d story illustration. "
    "Show the character from three angles on a clean white background: "
    "front view (center), side profile (left), and back view (right). "
    "Include a small close-up of the face and head in the top corner. "
    "Consistent lighting, flat style suitable for animation. "
    "Character details: "
)

# ---------------------------------------------------------------------------
# Scene image generation
# ---------------------------------------------------------------------------
SCENE_ASPECT_RATIO: str = "9:16"
SCENE_RESOLUTION: str = "2K"

# ---------------------------------------------------------------------------
# Veo (primary video generator via Google)
# ---------------------------------------------------------------------------
VEO_MODEL: str = "veo-3.1-fast-generate-001"
VEO_ASPECT_RATIO: str = "9:16"
VEO_DURATION_SECONDS: int = 8
VEO_RESOLUTION: str = "720p"
VEO_GENERATE_AUDIO: bool = False
VEO_POLL_INTERVAL_S: int = 15
VEO_TIMEOUT_S: int = 1800

# ---------------------------------------------------------------------------
# FAL (fallback video generator — Veo 3.1 ref-to-video via FAL)
# ---------------------------------------------------------------------------
FAL_MODEL_ID: str = "fal-ai/veo3.1/reference-to-video"
FAL_QUEUE_BASE: str = "https://queue.fal.run"
FAL_RESOLUTION: str = "1080p"
FAL_DURATION: str = "8s"
FAL_ASPECT_RATIO: str = "9:16"
FAL_GENERATE_AUDIO: bool = False
FAL_SAFETY_TOLERANCE: str = "6"
FAL_POLL_INTERVAL_S: int = 15
FAL_TIMEOUT_S: int = 1800
FAL_MAX_IMAGE_BYTES: int = 7 * 1024 * 1024

# ---------------------------------------------------------------------------
# Concurrency control
# ---------------------------------------------------------------------------
# When set to "1" in .env, all image / video / audio generation runs
# sequentially (one at a time) instead of concurrently.  Useful to avoid
# hitting API rate limits.
SEQUENTIAL_GENERATION: bool = os.environ.get("SEQUENTIAL_GENERATION", "0") == "1"

# ---------------------------------------------------------------------------
# Dev mode
# ---------------------------------------------------------------------------
# When DEV_MODE=1, the pipeline runs only the steps listed in DEV_STEPS and
# bootstraps all other steps from the cached session at
# sessions/DEV_SESSION_ID/.  If a skipped step's artifacts are missing from
# the dev session, the pipeline raises an error immediately rather than
# silently running the expensive step.
#
# DEV_STEPS is a comma-separated list of step names to actually execute.
# Valid step names:
#   story_breakdown   — generate story + character descriptions from transcript
#   narration         — generate TTS narration audio per scene
#   character_images  — generate character reference sheet images
#   scene_prompts     — generate visual plan / scene image+video prompts
#   scene_images      — generate scene images
#   scene_videos      — generate scene videos
#   compile           — compile final video
#
# Example .env entries:
#   DEV_MODE=1
#   DEV_SESSION_ID=dev_session
#   DEV_STEPS=story_breakdown,character_images
#
# When DEV_MODE=0 (default) the pipeline runs all steps normally.
DEV_MODE: bool = os.environ.get("DEV_MODE", "0") == "1"
DEV_SESSION_ID: str = os.environ.get("DEV_SESSION_ID", "dev_session")

_raw_dev_steps = os.environ.get("DEV_STEPS", "")
DEV_STEPS: set[str] = (
    {s.strip() for s in _raw_dev_steps.split(",") if s.strip()}
    if DEV_MODE
    else set()
)

# Keep legacy DEV_SKIP as an alias so old .env files still work.
# If DEV_SKIP=1 and DEV_MODE is not explicitly set, treat it as DEV_MODE=1
# with an empty DEV_STEPS (run nothing, load everything from dev session).
_legacy_dev_skip = os.environ.get("DEV_SKIP", "0") == "1"
if _legacy_dev_skip and not DEV_MODE:
    DEV_MODE = True

# ---------------------------------------------------------------------------
# Retry settings
# ---------------------------------------------------------------------------
RATE_LIMIT_DELAYS: list[int] = [15, 30, 60, 120]     # seconds on 429
VEO_INTERNAL_ERROR_RETRIES: int = 3
VEO_INTERNAL_ERROR_DELAYS: list[int] = [30, 60, 120]

# Scene image generation retries
# Rate-limit back-off delays (seconds) — applied on HTTP 429 responses.
IMAGE_RATE_LIMIT_DELAYS: list[int] = [15, 30, 60, 120]
# Transient-error back-off delays (seconds) — applied on 5xx / network errors.
IMAGE_TRANSIENT_DELAYS: list[int] = [5, 15, 30]

# Scene video generation retries (Veo + FAL)
# Rate-limit back-off delays (seconds) — applied on HTTP 429 responses.
VIDEO_RATE_LIMIT_DELAYS: list[int] = [15, 30, 60, 120]
# Transient-error back-off delays (seconds) — applied on 5xx / network / timeout errors.
VIDEO_TRANSIENT_DELAYS: list[int] = [10, 30, 60]

# ---------------------------------------------------------------------------
# Video compilation
# ---------------------------------------------------------------------------
VIDEO_FPS: int = 24
NARRATION_VOLUME: float = 2.0
MUSIC_VOLUME: float = 0.1
SUBTITLE_FONTSIZE: int = 28
SUBTITLE_AREA_HEIGHT: int = 150
SUBTITLE_PADDING_X: int = 16
SUBTITLE_COLOR: tuple[int, int, int] = (0, 0, 0)
SUBTITLE_BG_COLOR: tuple[int, int, int] = (255, 255, 255)
SUBTITLE_FONT_PATH: Path | None = None   # set to a .ttf path to override default

# Optional background music relative to project root
BACKGROUND_MUSIC_PATH: Path = _root / "backend" / "assets" / "story_background.mp3"

# ---------------------------------------------------------------------------
# MinIO
# ---------------------------------------------------------------------------
MINIO_ENDPOINT: str = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY: str = os.environ.get("MINIO_ACCESS_KEY", "minio")
MINIO_SECRET_KEY: str = os.environ.get("MINIO_SECRET_KEY", "minio1234")
MINIO_BUCKET: str = os.environ.get("MINIO_BUCKET", "storyteller")
MINIO_SECURE: bool = os.environ.get("MINIO_SECURE", "0") == "1"

# ---------------------------------------------------------------------------
# Sessions directory
# ---------------------------------------------------------------------------
SESSIONS_DIR: Path = _root / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def session_dir(session_id: str) -> Path:
    """Return (and create) the output directory for a given session."""
    p = SESSIONS_DIR / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p
