"""
Generate sub-scene videos using FAL Veo 3.1 reference-to-video.
Same loop as 7-1 (Kling) but calls fal-ai/veo3.1/reference-to-video with
multiple reference images (subscene + characters). Uses FAL_API_KEY from .env.
Queue: submit → poll status → fetch result → download mp4.
"""

import base64
import io
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv

try:
    from PIL import Image
except ImportError:
    Image = None

# FAL limit per image; stay under to leave room for base64 overhead
MAX_IMAGE_BYTES = 7 * 1024 * 1024

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

QUEUE_BASE = "https://queue.fal.run"
MODEL_ID   = "fal-ai/veo3.1/reference-to-video"
ENDPOINT   = f"{QUEUE_BASE}/{MODEL_ID}"

RESOLUTION       = "1080p"
DURATION         = "8s"
ASPECT_RATIO     = "16:9"
GENERATE_AUDIO   = True
SAFETY_TOLERANCE = "6"   # 1 strict … 6 least strict

POLL_INTERVAL = 15
TIMEOUT       = 1800

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_fal_key() -> str:
    key = os.environ.get("FAL_API_KEY") or os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("Set FAL_API_KEY or FAL_KEY in .env")
    return key


def image_to_data_uri(path: str) -> str:
    p = Path(path)
    raw = p.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES and Image is not None:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        scale = (MAX_IMAGE_BYTES / len(raw)) ** 0.5
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        raw = buf.getvalue()
        mime = "image/jpeg"
    else:
        ext = p.suffix.lower()
        mime = "image/png" if ext == ".png" else "image/jpeg"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def fal_request(method: str, url: str, key: str, data: dict | None = None) -> dict:
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        try:
            err_json = json.loads(err_body)
            detail = err_json.get("detail") or err_json.get("message") or err_body
        except Exception:
            detail = err_body or str(e)
        raise RuntimeError(f"FAL API {e.code}: {detail}") from e


def download_url_to_path(url: str, path: Path) -> None:
    req = Request(url, headers={"User-Agent": "Python"})
    with urlopen(req, timeout=300) as resp:
        path.write_bytes(resp.read())


def generate_video_veo31(
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    output_path: Path,
) -> None:
    key = get_fal_key()

    # Reference images: subscene first, then character refs (all as data URIs)
    image_urls = [image_to_data_uri(subscene_image_path)]
    image_urls.extend(image_to_data_uri(p) for p in character_image_paths)

    payload = {
        "prompt": video_prompt,
        "image_urls": image_urls,
        "resolution": RESOLUTION,
        "duration": DURATION,
        "aspect_ratio": ASPECT_RATIO,
        "generate_audio": GENERATE_AUDIO,
        "safety_tolerance": SAFETY_TOLERANCE,
    }

    # 1) Submit
    out = fal_request("POST", ENDPOINT, key, payload)
    status_url = out.get("status_url")
    response_url = out.get("response_url")
    request_id = out.get("request_id") or out.get("requestId")

    if not status_url:
        status_url = f"{QUEUE_BASE}/{MODEL_ID}/requests/{request_id}/status"
    if not response_url:
        response_url = f"{QUEUE_BASE}/{MODEL_ID}/requests/{request_id}"

    # 2) Poll status
    poll_url = f"{status_url}?logs=1" if "?" not in status_url else f"{status_url}&logs=1"
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        status_resp = fal_request("GET", poll_url, key)
        st = (status_resp.get("status") or "").upper()
        if st == "COMPLETED":
            response_url = status_resp.get("response_url") or response_url
            break
        if st == "FAILED":
            raise RuntimeError(f"Veo 3.1 job failed: {status_resp}")
        time.sleep(POLL_INTERVAL)
    else:
        raise TimeoutError(f"Veo 3.1 job did not complete within {TIMEOUT}s")

    # 3) Fetch result
    result = fal_request("GET", response_url, key)
    video_info = result.get("video") or result.get("data", {}).get("video")
    if not video_info:
        raise RuntimeError(f"Result missing video: {result}")
    video_url = video_info.get("url")
    if not video_url:
        raise RuntimeError(f"Video object missing url: {video_info}")

    # 4) Download
    download_url_to_path(video_url, output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    scripts_dir = Path(__file__).parent

    visual_plan_path = scripts_dir / "story_visual_plan.json"
    characters_dir   = scripts_dir / "output_characters"
    scenes_dir       = scripts_dir / "output_scenes"
    output_dir       = scripts_dir / "output_videos"
    output_dir.mkdir(exist_ok=True)

    with open(visual_plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    supported = {".png", ".jpg", ".jpeg", ".webp"}
    character_paths = sorted(
        str(p) for p in characters_dir.iterdir()
        if p.suffix.lower() in supported
    )
    print(f"Character reference images: {[Path(p).name for p in character_paths]}\n")

    total_scenes    = len(plan["scenes"])
    total_subscenes = sum(len(s["subscenes"]) for s in plan["scenes"])
    generated       = 0

    print(f"Generating videos (Veo 3.1 ref-to-video) for {total_scenes} scene(s) / {total_subscenes} sub-scene(s)...\n")

    for scene in plan["scenes"]:
        scene_idx = scene["scene_index"]
        print(f"  Scene {scene_idx}: {scene['scene_summary']}")

        for sub in scene["subscenes"]:
            sub_idx      = sub["index"]
            out_filename = f"scene_{scene_idx}_sub_{sub_idx}.mp4"
            out_path     = output_dir / out_filename
            scene_img    = scenes_dir / f"scene_{scene_idx}_sub_{sub_idx}.png"

            if out_path.exists():
                print(f"    [Scene {scene_idx} / Sub {sub_idx}] Already exists, skipping.")
                generated += 1
                continue

            if not scene_img.exists():
                print(f"    [Scene {scene_idx} / Sub {sub_idx}] Missing scene image ({scene_img.name}), skipping.")
                continue

            print(f"    [Scene {scene_idx} / Sub {sub_idx}] Generating...", end=" ", flush=True)
            try:
                generate_video_veo31(
                    video_prompt=sub["video_prompt"],
                    subscene_image_path=str(scene_img),
                    character_image_paths=character_paths,
                    output_path=out_path,
                )
                generated += 1
                print(f"Saved -> output_videos/{out_filename}")
            except (HTTPError, URLError, RuntimeError, TimeoutError) as e:
                print(f"Error: {e}")
                continue

        print()

    print(f"Done. {generated}/{total_subscenes} videos saved to: {output_dir}")


if __name__ == "__main__":
    main()
