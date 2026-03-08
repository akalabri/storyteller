"""
8_compile_video.py — Assembles sub-scene MP4s into a final story video.

Reads:
  - story_convo_example_breakdown.json  → scene narration texts (for subtitles)
  - story_visual_plan.json              → scene/sub-scene structure
  - output_narration/scene_N.mp3        → narration audio per scene
  - output_videos/scene_N_sub_M.mp4     → 8-second video clips per sub-scene

Produces:
  - output_final/story.mp4              → final compiled video
"""

import json
import logging
import textwrap
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Pillow ≥ 9.1.0 dropped ANTIALIAS; moviepy still references it
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    VideoFileClip,
    concatenate_videoclips,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# PATHS — change these to match your output structure
# =============================================================================
SCRIPTS_DIR = Path(__file__).parent

BREAKDOWN_JSON = SCRIPTS_DIR / "story_convo_example_breakdown.json"
VISUAL_PLAN_JSON = SCRIPTS_DIR / "story_visual_plan.json"
NARRATION_DIR = SCRIPTS_DIR / "output_narration"
VIDEOS_DIR = SCRIPTS_DIR / "output_videos"
OUTPUT_DIR = SCRIPTS_DIR / "output_final"

BACKGROUND_MUSIC = SCRIPTS_DIR.parent / "video_compiling" / "assets" / "imgs" / "story_music.mp3"

# =============================================================================
# VIDEO / AUDIO SETTINGS — adjust to taste
# =============================================================================
NARRATION_VOLUME = 2.0          # multiply narration gain
MUSIC_VOLUME = 0.1              # multiply background music gain
FPS = 24

# =============================================================================
# SUBTITLE SETTINGS
# =============================================================================
# Full path to a .ttf file, or None to use the system default font.
# On Windows the Amiri font from the video_compiling assets works well for a
# consistent look; for English text Arial or any other Latin .ttf is fine.
SUBTITLE_FONT_PATH: Path | None = None   # e.g. SCRIPTS_DIR.parent / "video_compiling/assets/fonts/Amiri-Regular.ttf"
SUBTITLE_FONTSIZE = 28
SUBTITLE_COLOR = (0, 0, 0)       # RGB tuple — black
SUBTITLE_BG_COLOR = (255, 255, 255)  # RGB — white strip background
SUBTITLE_AREA_HEIGHT = 150       # extra pixels added below each frame for subtitles
SUBTITLE_PADDING_X = 16          # horizontal padding inside the subtitle strip


# =============================================================================
# Helpers
# =============================================================================

def split_into_three(text: str) -> tuple[str, str, str]:
    """Split text into three roughly equal parts by word count."""
    words = text.split()
    n = len(words)
    cut1 = n // 3
    cut2 = 2 * n // 3
    part1 = " ".join(words[:cut1])
    part2 = " ".join(words[cut1:cut2])
    part3 = " ".join(words[cut2:])
    return part1, part2, part3


def load_breakdown(path: Path) -> list[str]:
    """Return the list of scene text strings from the breakdown JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["story"]


def load_visual_plan(path: Path) -> list[dict]:
    """Return the list of scene dicts from the visual plan JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["scenes"]


def _load_pil_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a PIL font, falling back gracefully if the file is not found."""
    if SUBTITLE_FONT_PATH and SUBTITLE_FONT_PATH.exists():
        return ImageFont.truetype(str(SUBTITLE_FONT_PATH), size)
    # Try common Windows system fonts
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    # Last resort: PIL built-in bitmap font (small, no sizing)
    logger.warning("No TrueType font found — falling back to PIL default font (very small).")
    return ImageFont.load_default()


def _render_subtitle_strip(text: str, width: int) -> np.ndarray:
    """
    Render subtitle text onto a white strip using PIL.

    Returns a numpy array of shape (SUBTITLE_AREA_HEIGHT, width, 3) dtype uint8.
    """
    font = _load_pil_font(SUBTITLE_FONTSIZE)

    # Word-wrap: use textwrap as a rough guide, then verify with PIL metrics
    avg_char_width = SUBTITLE_FONTSIZE * 0.55
    chars_per_line = max(1, int((width - SUBTITLE_PADDING_X * 2) / avg_char_width))
    wrapped_lines = textwrap.wrap(text, width=chars_per_line) or [""]

    img = Image.new("RGB", (width, SUBTITLE_AREA_HEIGHT), color=SUBTITLE_BG_COLOR)
    draw = ImageDraw.Draw(img)

    line_height = SUBTITLE_FONTSIZE + 8
    total_text_h = len(wrapped_lines) * line_height
    y = (SUBTITLE_AREA_HEIGHT - total_text_h) // 2

    for line in wrapped_lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2
        draw.text((x, y), line, fill=SUBTITLE_COLOR, font=font)
        y += line_height

    return np.array(img)


def add_subtitle_to_clip(video_clip: VideoFileClip, subtitle_text: str) -> VideoClip:
    """
    Return a new VideoClip with a white subtitle strip appended below each frame.

    Uses PIL for text rendering — no ImageMagick required.
    """
    orig_w, orig_h = video_clip.size
    subtitle_strip = _render_subtitle_strip(subtitle_text.strip(), orig_w)  # (H, W, 3)

    def make_frame(t: float) -> np.ndarray:
        frame = video_clip.get_frame(t)          # (orig_h, orig_w, 3)
        return np.vstack([frame, subtitle_strip])  # (orig_h + SUBTITLE_AREA_HEIGHT, orig_w, 3)

    new_clip = VideoClip(make_frame, duration=video_clip.duration)
    new_clip.fps = getattr(video_clip, "fps", None) or FPS
    return new_clip


def build_scene_clip(
    scene_index: int,
    subscenes: list[dict],
    scene_text: str,
    narration_path: Path,
    videos_dir: Path,
) -> tuple[VideoFileClip | None, AudioFileClip]:
    """
    Build a single concatenated clip for one scene.

    The 3 sub-scene videos are joined silently with subtitle overlays, then
    the full narration audio is placed on the combined clip so it plays
    uninterrupted across all sub-scene transitions.

    Returns (scene_clip, narration_clip). The caller must close narration_clip
    only AFTER write_videofile completes, because the clip's audio track holds
    a live reference to the narration reader.
    """
    subtitle_parts = split_into_three(scene_text)
    narration = AudioFileClip(str(narration_path))

    sub_clips = []
    for sub in subscenes:
        sub_idx = sub["index"]
        video_path = videos_dir / f"scene_{scene_index}_sub_{sub_idx}.mp4"

        if not video_path.exists():
            logger.warning("Missing video: %s — skipping sub-scene", video_path)
            continue

        # Load sub-scene video without audio, add subtitle strip
        raw_clip = VideoFileClip(str(video_path)).without_audio()
        sub_clips.append(add_subtitle_to_clip(raw_clip, subtitle_parts[sub_idx - 1]))

    if not sub_clips:
        return None, narration

    # Concatenate all sub-scenes for this scene into one continuous clip,
    # then attach the full narration so speech never gets cut at a sub-scene boundary.
    scene_video = concatenate_videoclips(sub_clips, method="compose")
    scene_video = scene_video.set_audio(narration)

    return scene_video, narration


# =============================================================================
# Main
# =============================================================================

def compile_video() -> Path:
    start = time.time()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "story.mp4"

    scene_texts = load_breakdown(BREAKDOWN_JSON)
    scenes = load_visual_plan(VISUAL_PLAN_JSON)

    if len(scene_texts) < len(scenes):
        logger.warning(
            "Breakdown has %d scenes but visual plan has %d — extra scenes will have no subtitle text.",
            len(scene_texts),
            len(scenes),
        )

    scene_clips = []
    all_narration_clips = []  # kept alive until after write_videofile

    for scene in scenes:
        scene_idx = scene["scene_index"]
        narration_path = NARRATION_DIR / f"scene_{scene_idx}.mp3"

        if not narration_path.exists():
            logger.warning("Missing narration: %s — skipping scene %d", narration_path, scene_idx)
            continue

        # Use matching breakdown text; fall back to empty string if index is out of range
        text = scene_texts[scene_idx - 1] if scene_idx - 1 < len(scene_texts) else ""

        logger.info("Processing scene %d …", scene_idx)
        scene_clip, narration_clip = build_scene_clip(
            scene_idx,
            scene["subscenes"],
            text,
            narration_path,
            VIDEOS_DIR,
        )
        all_narration_clips.append(narration_clip)
        if scene_clip is not None:
            scene_clips.append(scene_clip)

    if not scene_clips:
        raise RuntimeError("No clips were produced. Check that output_videos/ and output_narration/ are populated.")

    logger.info("Concatenating %d scene clips …", len(scene_clips))
    final_video = concatenate_videoclips(scene_clips, method="compose")

    # --- Background music ---
    if BACKGROUND_MUSIC.exists():
        bg_music = AudioFileClip(str(BACKGROUND_MUSIC)).volumex(MUSIC_VOLUME)
        if bg_music.duration < final_video.duration:
            bg_music = bg_music.loop(duration=final_video.duration)
        else:
            bg_music = bg_music.subclip(0, final_video.duration)

        narration_combined = final_video.audio.volumex(NARRATION_VOLUME)
        mixed_audio = CompositeAudioClip([narration_combined, bg_music])
        final_video = final_video.set_audio(mixed_audio)
    else:
        logger.warning("Background music not found at %s — skipping.", BACKGROUND_MUSIC)
        final_video = final_video.set_audio(final_video.audio.volumex(NARRATION_VOLUME))

    logger.info("Writing final video to %s …", output_path)
    final_video.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        remove_temp=True,
        logger=None,
    )

    # Clean up — narration clips must stay open until after write_videofile
    final_video.close()
    for c in scene_clips:
        c.close()
    for n in all_narration_clips:
        n.close()

    elapsed = time.time() - start
    logger.info("Done. Final video saved to %s (%.1fs)", output_path, elapsed)
    return output_path


if __name__ == "__main__":
    compile_video()
