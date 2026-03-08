"""
Generate sub-scene videos using FAL Kling 3 (image-to-video).
Uses FAL_API_KEY from .env. Same loop as 7_generate_scene_videos.py but calls
fal-ai/kling-video/v3/standard/image-to-video (queue submit → poll status → fetch result).
"""

import base64
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FAL_BASE = "https://queue.fal.run/fal-ai/kling-video"
ENDPOINT = f"{FAL_BASE}/v3/standard/image-to-video"
DURATION = "5"
ASPECT_RATIO = "16:9"
GENERATE_AUDIO = True
NEGATIVE_PROMPT = "blur, distort, and low quality"
CFG_SCALE = 0.5

POLL_INTERVAL = 15
TIMEOUT = 1800
REQUEST_TIMEOUT = 300   # seconds for submit/status/result API calls
DOWNLOAD_TIMEOUT = 600  # seconds for video file download
MAX_RETRIES = 3
RETRY_DELAY = 30        # seconds between retries

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_fal_key() -> str:
    key = os.environ.get("FAL_API_KEY") or os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("Set FAL_API_KEY or FAL_KEY in .env")
    return key


def image_to_data_uri(path: str) -> str:
    path = Path(path)
    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    ext = path.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def fal_request(method: str, url: str, key: str, data: dict | None = None, timeout: int = REQUEST_TIMEOUT) -> dict:
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data else None
    req = Request(url, data=body, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def generate_video_kling(
    video_prompt: str,
    subscene_image_path: str,
    character_image_paths: list[str],
    output_path: Path,
) -> None:
    key = get_fal_key()

    start_data_uri = image_to_data_uri(subscene_image_path)

    elements = []
    if character_image_paths:
        frontal = image_to_data_uri(character_image_paths[0])
        refs = [image_to_data_uri(p) for p in character_image_paths[1:]] if len(character_image_paths) > 1 else []
        elements.append({
            "frontal_image_url": frontal,
            "reference_image_urls": refs,
        })

    payload = {
        "prompt": video_prompt,
        "start_image_url": start_data_uri,
        "duration": DURATION,
        "generate_audio": GENERATE_AUDIO,
        "aspect_ratio": ASPECT_RATIO,
        "negative_prompt": NEGATIVE_PROMPT,
        "cfg_scale": CFG_SCALE,
    }
    if elements:
        payload["elements"] = elements

    # 1) Submit
    out = fal_request("POST", ENDPOINT, key, payload)
    request_id = out.get("request_id") or out.get("requestId")
    status_url = out.get("status_url")
    result_url = out.get("response_url")

    if status_url and result_url:
        pass
    elif request_id:
        status_url = f"{FAL_BASE}/requests/{request_id}/status"
        result_url = f"{FAL_BASE}/requests/{request_id}"
    else:
        raise RuntimeError(f"Submit response missing request_id or status_url: {out}")

    # 2) Poll status
    poll_url = f"{status_url}?logs=1" if "?" not in status_url else f"{status_url}&logs=1"
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        status_resp = fal_request("GET", poll_url, key)
        st = status_resp.get("status", "").upper()
        if st == "COMPLETED":
            break
        if st == "FAILED":
            raise RuntimeError(f"Kling job failed: {status_resp}")
        time.sleep(POLL_INTERVAL)

    else:
        raise TimeoutError(f"Kling job did not complete within {TIMEOUT}s")

    # 3) Fetch result and get video URL
    result = fal_request("GET", result_url, key)
    video_info = result.get("video") or result.get("data", {}).get("video")
    if not video_info:
        raise RuntimeError(f"Result missing video: {result}")
    video_url = video_info.get("url")
    if not video_url:
        raise RuntimeError(f"Video object missing url: {video_info}")

    # 4) Download mp4
    req = Request(video_url, headers={"User-Agent": "Python"})
    with urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        output_path.write_bytes(resp.read())


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

    print(f"Generating videos (Kling 3) for {total_scenes} scene(s) / {total_subscenes} sub-scene(s)...\n")

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
            last_error = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    generate_video_kling(
                        video_prompt=sub["video_prompt"],
                        subscene_image_path=str(scene_img),
                        character_image_paths=character_paths,
                        output_path=out_path,
                    )
                    generated += 1
                    if attempt > 1:
                        print(f"(retry {attempt}) ", end="", flush=True)
                    print(f"Saved -> output_videos/{out_filename}")
                    break
                except (HTTPError, URLError, RuntimeError, TimeoutError) as e:
                    last_error = e
                    if attempt < MAX_RETRIES:
                        print(f"Error: {e} — retrying in {RETRY_DELAY}s...", flush=True)
                        time.sleep(RETRY_DELAY)
                    else:
                        print(f"Error: {e}")
            if last_error and not out_path.exists():
                continue

        print()

    print(f"Done. {generated}/{total_subscenes} videos saved to: {output_dir}")


if __name__ == "__main__":
    main()
