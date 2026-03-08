"""
Compile agent — assembles sub-scene MP4s, narration MP3s, and optional
background music into the final story video using MoviePy + PIL.

The compilation is CPU-bound and blocking; it runs in the thread-pool
executor so the async orchestrator remains responsive.
"""

from __future__ import annotations

import asyncio
import logging
import textwrap
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS  # type: ignore[attr-defined]

from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    VideoClip,
    VideoFileClip,
    concatenate_videoclips,
)

from backend.config import (
    BACKGROUND_MUSIC_PATH,
    MUSIC_VOLUME,
    NARRATION_VOLUME,
    SUBTITLE_AREA_HEIGHT,
    SUBTITLE_BG_COLOR,
    SUBTITLE_COLOR,
    SUBTITLE_FONT_PATH,
    SUBTITLE_FONTSIZE,
    SUBTITLE_PADDING_X,
    VIDEO_FPS,
)
from backend.pipeline.state import StoryBreakdown, StoryVisualPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subtitle helpers (ported from 8_compile_video.py)
# ---------------------------------------------------------------------------

def _split_into_three(text: str) -> tuple[str, str, str]:
    words = text.split()
    n = len(words)
    cut1, cut2 = n // 3, 2 * n // 3
    return (
        " ".join(words[:cut1]),
        " ".join(words[cut1:cut2]),
        " ".join(words[cut2:]),
    )


def _load_pil_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if SUBTITLE_FONT_PATH and Path(SUBTITLE_FONT_PATH).exists():
        return ImageFont.truetype(str(SUBTITLE_FONT_PATH), size)
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    logger.warning("No TrueType font found — falling back to PIL default font.")
    return ImageFont.load_default()


def _render_subtitle_strip(text: str, width: int) -> np.ndarray:
    font = _load_pil_font(SUBTITLE_FONTSIZE)
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


def _add_subtitle_to_clip(video_clip: VideoFileClip, subtitle_text: str) -> VideoClip:
    orig_w, _ = video_clip.size
    strip = _render_subtitle_strip(subtitle_text.strip(), orig_w)

    def make_frame(t: float) -> np.ndarray:
        return np.vstack([video_clip.get_frame(t), strip])

    new_clip = VideoClip(make_frame, duration=video_clip.duration)
    new_clip.fps = getattr(video_clip, "fps", None) or VIDEO_FPS
    return new_clip


# ---------------------------------------------------------------------------
# Scene clip builder
# ---------------------------------------------------------------------------

def _build_scene_clip(
    scene_idx: int,
    subscenes: list[dict],
    scene_text: str,
    narration_path: Path,
    videos_dir: Path,
) -> tuple[Optional[VideoClip], AudioFileClip]:
    subtitle_parts = _split_into_three(scene_text)
    narration = AudioFileClip(str(narration_path))

    sub_clips = []
    for sub in subscenes:
        sub_idx = sub["index"]
        video_path = videos_dir / f"scene_{scene_idx}_sub_{sub_idx}.mp4"
        if not video_path.exists():
            logger.warning("Missing video: %s — skipping sub-scene.", video_path)
            continue
        raw_clip = VideoFileClip(str(video_path)).without_audio()
        sub_clips.append(_add_subtitle_to_clip(raw_clip, subtitle_parts[sub_idx - 1]))

    if not sub_clips:
        return None, narration

    scene_video = concatenate_videoclips(sub_clips, method="compose")
    scene_video = scene_video.set_audio(narration)
    return scene_video, narration


# ---------------------------------------------------------------------------
# Main compilation function (sync — runs inside executor)
# ---------------------------------------------------------------------------

def _compile_sync(
    breakdown: StoryBreakdown,
    visual_plan: StoryVisualPlan,
    narration_dir: Path,
    videos_dir: Path,
    output_path: Path,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    scene_texts = breakdown.story
    scenes_data = visual_plan.scenes

    scene_clips: list[VideoClip] = []
    all_narration_clips: list[AudioFileClip] = []

    for scene in scenes_data:
        scene_idx = scene.scene_index
        narration_path = narration_dir / f"scene_{scene_idx}.mp3"

        if not narration_path.exists():
            logger.warning("Missing narration for scene %d — skipping.", scene_idx)
            continue

        text = scene_texts[scene_idx - 1] if scene_idx - 1 < len(scene_texts) else ""
        subscenes_data = [s.model_dump() for s in scene.subscenes]

        logger.info("Compiling scene %d…", scene_idx)
        clip, narration_clip = _build_scene_clip(
            scene_idx, subscenes_data, text, narration_path, videos_dir
        )
        all_narration_clips.append(narration_clip)
        if clip is not None:
            scene_clips.append(clip)

    if not scene_clips:
        raise RuntimeError(
            "No clips produced. Ensure output_videos/ and output_narration/ are populated."
        )

    logger.info("Concatenating %d scene clip(s)…", len(scene_clips))
    final_video = concatenate_videoclips(scene_clips, method="compose")

    # Optional background music
    if BACKGROUND_MUSIC_PATH.exists():
        bg_music = AudioFileClip(str(BACKGROUND_MUSIC_PATH)).volumex(MUSIC_VOLUME)
        if bg_music.duration < final_video.duration:
            bg_music = bg_music.loop(duration=final_video.duration)
        else:
            bg_music = bg_music.subclip(0, final_video.duration)
        narration_combined = final_video.audio.volumex(NARRATION_VOLUME)
        final_video = final_video.set_audio(CompositeAudioClip([narration_combined, bg_music]))
    else:
        final_video = final_video.set_audio(final_video.audio.volumex(NARRATION_VOLUME))

    logger.info("Writing final video to %s…", output_path)
    final_video.write_videofile(
        str(output_path),
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        remove_temp=True,
        logger=None,
    )

    final_video.close()
    for c in scene_clips:
        c.close()
    for n in all_narration_clips:
        n.close()

    return str(output_path)


# ---------------------------------------------------------------------------
# Public async function
# ---------------------------------------------------------------------------

async def compile_video(
    breakdown: StoryBreakdown,
    visual_plan: StoryVisualPlan,
    narration_dir: Path,
    videos_dir: Path,
    output_path: Path,
) -> str:
    """
    Compile the final story video.

    Runs the blocking MoviePy pipeline in the thread-pool executor.
    Returns the path to the output MP4.
    """
    logger.info("Starting video compilation…")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        _compile_sync,
        breakdown,
        visual_plan,
        narration_dir,
        videos_dir,
        output_path,
    )
    logger.info("Video compilation complete: %s", result)
    return result
