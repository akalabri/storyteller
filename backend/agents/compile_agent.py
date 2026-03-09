"""
Compile agent — assembles sub-scene MP4s, narration MP3s, and optional
background music into the final story video using ffmpeg (via the src utilities).

Pipeline per scene
──────────────────
  1. burn_subtitles_per_scene  — karaoke ASS captions burned into each sub-video
  2. merge_videos              — concatenate subtitled sub-videos → merged scene
  3. speed-up audio            — if narration > total video length (N × 8 s), use
                                 atempo to compress it so it fits
  4. merge_audio               — mix narration onto merged scene video

Final steps
───────────
  5. merge_videos              — concatenate all final scene videos → combined
  6. background music          — boost narration volume and optionally blend BG
                                 music via ffmpeg amix + volume filters

The compilation is CPU/IO-bound; it runs in the thread-pool executor so the
async orchestrator remains responsive.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from backend.config import (
    BACKGROUND_MUSIC_PATH,
    MUSIC_VOLUME,
    NARRATION_VOLUME,
)
from backend.pipeline.state import StoryBreakdown, StoryVisualPlan
from backend.src.audio_to_video import merge as merge_audio
from backend.src.merge_subtitle import burn_subtitles_per_scene, get_media_duration
from backend.src.merge_videos import merge_videos

logger = logging.getLogger(__name__)

# Duration of each sub-video clip (seconds) — matches VEO_DURATION_SECONDS
SUB_VIDEO_DURATION_S: float = 8.0


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _speed_up_audio_if_needed(
    audio_path: str,
    video_duration: float,
    output_path: str,
) -> str:
    """
    If the audio is longer than *video_duration*, speed it up with ffmpeg
    ``atempo`` so it fits.  Returns the path to the (possibly adjusted) audio.

    ``atempo`` only accepts values in [0.5, 2.0], so for speed factors above
    2× the filter is chained (e.g. 3× → atempo=2.0,atempo=1.5).
    """
    audio_duration = get_media_duration(audio_path)
    if audio_duration <= video_duration:
        return audio_path

    speed_factor = audio_duration / video_duration
    logger.info(
        "Audio (%.2fs) longer than video (%.2fs); speeding up ×%.3f → %s",
        audio_duration, video_duration, speed_factor, output_path,
    )

    filters: list[str] = []
    remaining = speed_factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    filters.append(f"atempo={remaining:.6f}")

    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
        "-filter:a", ",".join(filters),
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "Audio speed-up failed (%s) — using original audio.", result.stderr[:200]
        )
        return audio_path
    return output_path


# ---------------------------------------------------------------------------
# Background music / volume helpers
# ---------------------------------------------------------------------------

def _apply_volume_and_bg_music(
    video_path: str,
    output_path: str,
    narration_volume: float,
    bg_music_path: str | None,
    music_volume: float,
) -> None:
    """
    Apply narration volume boost and optionally blend looping background music.

    Uses ``-stream_loop -1`` so a short music file repeats for the full
    duration of the video.  ``amix duration=first`` then trims the mix to
    the video length.
    """
    if bg_music_path and os.path.isfile(bg_music_path):
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1",
            "-i", bg_music_path,
            "-filter_complex",
            (
                f"[0:a]volume={narration_volume}[a_narr];"
                f"[1:a]volume={music_volume}[a_music];"
                f"[a_narr][a_music]amix=inputs=2:duration=first:normalize=0[aout]"
            ),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            output_path,
        ]
    else:
        # No BG music — just boost the narration volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-filter:a", f"volume={narration_volume}",
            "-c:v", "copy",
            "-c:a", "aac",
            output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "Volume/music mixing failed (%s) — copying pre-mix video to output.",
            result.stderr[:200],
        )
        shutil.copy2(video_path, output_path)


# ---------------------------------------------------------------------------
# Main compilation function (sync — runs inside thread-pool executor)
# ---------------------------------------------------------------------------

def _compile_sync(
    breakdown: StoryBreakdown,
    visual_plan: StoryVisualPlan,
    narration_dir: Path,
    videos_dir: Path,
    output_path: Path,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Intermediate directories live next to the final output
    tmp_root = output_path.parent / "compile_tmp"
    subtitled_dir = tmp_root / "subtitled"
    merged_dir = tmp_root / "merged"
    final_scenes_dir = tmp_root / "final_scenes"

    for d in (subtitled_dir, merged_dir, final_scenes_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── Step 1: burn karaoke subtitles into each sub-video ──────────────────
    logger.info("Compile step 1: burning karaoke subtitles…")
    burn_subtitles_per_scene(
        str(videos_dir),
        str(narration_dir),
        str(subtitled_dir),
    )

    # Discover which scene numbers were processed
    sub_files = glob.glob(str(subtitled_dir / "scene_*_sub_*.mp4"))
    scene_nums = sorted({
        int(re.search(r"scene_(\d+)", f).group(1))
        for f in sub_files
    })

    if not scene_nums:
        raise RuntimeError(
            "No subtitled sub-videos found after subtitle step. "
            "Ensure videos and narration are fully populated."
        )

    final_scene_paths: list[str] = []

    for scene_num in scene_nums:
        logger.info("Compile scene %d…", scene_num)

        # ── Step 2: merge this scene's subtitled sub-videos ─────────────────
        subs = sorted(
            glob.glob(str(subtitled_dir / f"scene_{scene_num}_sub_*.mp4")),
            key=lambda f: int(re.search(r"sub_(\d+)", f).group(1)),
        )
        if not subs:
            logger.warning("Scene %d: no subtitled sub-videos — skipping.", scene_num)
            continue

        merged_video = str(merged_dir / f"scene_{scene_num}.mp4")
        merge_videos(subs, merged_video)

        # ── Step 3: speed-up narration audio if it overflows ────────────────
        audio_file = str(narration_dir / f"scene_{scene_num}.mp3")
        if not os.path.isfile(audio_file):
            logger.warning(
                "Scene %d: narration audio not found (%s) — skipping.", scene_num, audio_file
            )
            continue

        # Total video length = number of sub-clips × fixed sub-clip duration
        video_duration = len(subs) * SUB_VIDEO_DURATION_S
        sped_audio_path = str(tmp_root / f"scene_{scene_num}_narration.mp3")
        actual_audio = _speed_up_audio_if_needed(audio_file, video_duration, sped_audio_path)

        # ── Step 4: mix narration audio into merged scene video ──────────────
        final_scene_video = str(final_scenes_dir / f"scene_{scene_num}.mp4")
        merge_audio(merged_video, actual_audio, final_scene_video, "mix")
        final_scene_paths.append(final_scene_video)

    if not final_scene_paths:
        raise RuntimeError(
            "No final scene videos were produced. "
            "Ensure all scenes have both videos and narration audio."
        )

    # ── Step 5: merge all final scene videos into one combined video ─────────
    logger.info("Compile step 5: merging %d scene(s) into combined video…", len(final_scene_paths))
    pre_music_path = str(output_path.parent / "story_pre_music.mp4")
    merge_videos(final_scene_paths, pre_music_path)

    # ── Step 6: apply narration volume boost + optional background music ─────
    bg_path = str(BACKGROUND_MUSIC_PATH) if BACKGROUND_MUSIC_PATH.exists() else None
    if bg_path:
        logger.info("Compile step 6: adding background music (%s)…", bg_path)
    else:
        logger.info("Compile step 6: no background music found — boosting narration volume only.")

    _apply_volume_and_bg_music(
        pre_music_path,
        str(output_path),
        narration_volume=NARRATION_VOLUME,
        bg_music_path=bg_path,
        music_volume=MUSIC_VOLUME,
    )

    # Clean up the temporary pre-music file
    if os.path.isfile(pre_music_path):
        os.remove(pre_music_path)

    logger.info("Final video written to %s", output_path)
    return str(output_path)


# ---------------------------------------------------------------------------
# Public async entry point
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

    Runs the blocking ffmpeg pipeline in the thread-pool executor.
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
