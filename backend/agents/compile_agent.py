"""
Compile agent — assembles sub-scene MP4s, narration MP3s, and optional
background music into the final story video using ffmpeg (via the src utilities).

Pipeline per scene
──────────────────
  0. pre-pass  — for every scene, check if narration audio exceeds MAX_SCENE_AUDIO_S
                 (23 s).  If so, speed it up with atempo and record the speed factor.
  1. burn_subtitles_per_scene  — karaoke ASS captions burned into each sub-video,
                                 with word timestamps scaled by the speed factor so
                                 subtitles stay in sync with the faster audio.
  2. merge_videos              — concatenate subtitled sub-videos → merged scene
  3. (audio already processed) — sped-up (or original) audio from the pre-pass
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

# Hard cap for narration audio per scene (seconds).
# If the narration is longer than this, it is sped up to fit.
# Set slightly below the theoretical maximum (N × 8 s) so there is a small
# buffer and the audio never overruns the last frame.
MAX_SCENE_AUDIO_S: float = 23.0


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _speed_up_audio_if_needed(
    audio_path: str,
    max_duration: float,
    output_path: str,
) -> tuple[str, float]:
    """
    If the audio is longer than *max_duration*, speed it up with ffmpeg
    ``atempo`` so it fits within that limit.

    Returns a ``(path, speed_factor)`` tuple where *path* is the (possibly
    new) audio file and *speed_factor* is the ratio ``original / target``
    (1.0 when no speed-up was needed).

    ``atempo`` only accepts values in [0.5, 2.0], so for speed factors above
    2× the filter is chained (e.g. 3× → atempo=2.0,atempo=1.5).
    """
    audio_duration = get_media_duration(audio_path)
    if audio_duration <= max_duration:
        return audio_path, 1.0

    speed_factor = audio_duration / max_duration
    logger.info(
        "Audio (%.2fs) exceeds cap (%.2fs); speeding up ×%.4f → %s",
        audio_duration, max_duration, speed_factor, output_path,
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
        return audio_path, 1.0
    return output_path, speed_factor


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

    # ── Step 1 (pre-pass): discover scenes and compute audio speed factors ───
    # We must know the speed factor before burning subtitles so that word
    # timestamps can be compressed to match the (possibly faster) audio.
    raw_sub_files = glob.glob(str(videos_dir / "scene_*_sub_*.mp4"))
    scene_nums = sorted({
        int(re.search(r"scene_(\d+)", f).group(1))
        for f in raw_sub_files
    })

    if not scene_nums:
        raise RuntimeError(
            "No sub-videos found in videos directory. "
            "Ensure scene videos are fully generated."
        )

    # Map scene_num → speed_factor (1.0 means no change)
    scene_speed_factors: dict[int, float] = {}
    # Map scene_num → path of (possibly sped-up) audio
    scene_audio_paths: dict[int, str] = {}
    # Map scene_num → sorted list of raw sub-video paths
    scene_sub_videos: dict[int, list[str]] = {}

    for scene_num in scene_nums:
        subs = sorted(
            glob.glob(str(videos_dir / f"scene_{scene_num}_sub_*.mp4")),
            key=lambda f: int(re.search(r"sub_(\d+)", f).group(1)),
        )
        scene_sub_videos[scene_num] = subs

        audio_file = str(narration_dir / f"scene_{scene_num}.mp3")
        if not os.path.isfile(audio_file):
            logger.warning(
                "Scene %d: narration audio not found (%s) — will skip.", scene_num, audio_file
            )
            scene_speed_factors[scene_num] = 1.0
            scene_audio_paths[scene_num] = audio_file
            continue

        sped_audio_path = str(tmp_root / f"scene_{scene_num}_narration.mp3")
        actual_audio, speed_factor = _speed_up_audio_if_needed(
            audio_file, MAX_SCENE_AUDIO_S, sped_audio_path
        )
        scene_speed_factors[scene_num] = speed_factor
        scene_audio_paths[scene_num] = actual_audio

    # ── Step 1: burn karaoke subtitles into each sub-video ──────────────────
    # Pass speed factors so timestamps are scaled to match sped-up audio.
    logger.info("Compile step 1: burning karaoke subtitles…")
    burn_subtitles_per_scene(
        str(videos_dir),
        str(narration_dir),
        str(subtitled_dir),
        speed_factors=scene_speed_factors,
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

        # ── Step 3: audio was already processed in the pre-pass ─────────────
        actual_audio = scene_audio_paths.get(scene_num, "")
        if not os.path.isfile(actual_audio):
            logger.warning(
                "Scene %d: narration audio not found (%s) — skipping.", scene_num, actual_audio
            )
            continue

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
