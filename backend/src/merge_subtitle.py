import json
import subprocess
import os
import tempfile
import glob
import re


def get_media_duration(path: str) -> float:
    """Get duration of a media file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format 'H:MM:SS.cc' (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def words_to_segments(words: list, max_words: int = 5, max_duration: float = 2.5) -> list:
    """Group word-level timestamps into subtitle segments, preserving per-word timing."""
    segments = []
    current_words = []
    current_start = None

    for w in words:
        word = w["word"]
        start = w["start"]
        end = w["end"]

        if current_start is None:
            current_start = start

        current_words.append({"word": word, "start": start, "end": end})

        is_sentence_end = word.rstrip().endswith((".", "!", "?", ";"))
        duration = end - current_start
        at_limit = len(current_words) >= max_words or duration >= max_duration

        if is_sentence_end or (at_limit and len(current_words) > 1):
            segments.append({
                "start": current_start,
                "end": end,
                "text": " ".join(cw["word"] for cw in current_words),
                "words": list(current_words),
            })
            current_words = []
            current_start = None

    # flush remaining — merge into last segment if too short
    if current_words:
        if segments and len(current_words) <= 2:
            segments[-1]["end"] = current_words[-1]["end"]
            segments[-1]["text"] += " " + " ".join(cw["word"] for cw in current_words)
            segments[-1]["words"].extend(current_words)
        else:
            segments.append({
                "start": current_start,
                "end": current_words[-1]["end"],
                "text": " ".join(cw["word"] for cw in current_words),
                "words": list(current_words),
            })

    return segments


def build_karaoke_text(word_list: list, seg_start: float) -> str:
    """Build ASS karaoke-tagged text from word-level timing."""
    parts = []
    prev_end = seg_start

    for w in word_list:
        duration_cs = max(1, round((w["end"] - prev_end) * 100))
        parts.append(f"{{\\k{duration_cs}}}{w['word']}")
        prev_end = w["end"]

    return " ".join(parts)


def segments_to_ass(segments: list) -> str:
    """Convert segments to ASS subtitle content with karaoke highlighting."""
    header = """[Script Info]
Title: Story Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Box,Arial Black,40,&H00000000,&H00000000,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,8,0,2,120,120,50,1
Style: Karaoke,Arial Black,40,&H0000BFFF,&H50FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,120,120,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for seg in segments:
        start = format_ass_time(seg["start"])
        end = format_ass_time(seg["end"])
        plain_text = seg["text"].replace("\n", "\\N")
        karaoke_text = build_karaoke_text(seg["words"], seg["start"])
        lines.append(f"Dialogue: 0,{start},{end},Box,,0,0,0,,{plain_text}")
        lines.append(f"Dialogue: 1,{start},{end},Karaoke,,0,0,0,,{karaoke_text}")

    return header + "\n".join(lines) + "\n"


def filter_words_for_range(words: list, t_start: float, t_end: float, offset: float) -> list:
    """Filter words that fall within [t_start, t_end) and shift timestamps by -offset."""
    filtered = []
    for w in words:
        # include word if it overlaps with the range
        if w["end"] > t_start and w["start"] < t_end:
            filtered.append({
                "word": w["word"],
                "start": max(0.0, w["start"] - offset),
                "end": min(t_end - offset, w["end"] - offset),
            })
    return filtered


def burn_ass_into_video(video_file: str, ass_content: str, output_file: str):
    """Burn ASS subtitle content into a video file."""
    ass_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ass", delete=False,
        dir=os.path.dirname(output_file) or ".",
    )
    ass_file.write(ass_content)
    ass_file.close()

    try:
        escaped_ass = ass_file.name.replace("\\", "\\\\").replace(":", "\\:")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file,
            "-vf", f"ass={escaped_ass}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "copy",
            output_file,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✓ {os.path.basename(output_file)}")
        else:
            print(f"  ✗ {os.path.basename(output_file)}: {result.stderr[:200]}")
    finally:
        os.unlink(ass_file.name)


def burn_subtitles_per_scene(videos_dir: str, narration_dir: str, output_dir: str):
    """Burn karaoke subtitles into each sub-scene video."""
    os.makedirs(output_dir, exist_ok=True)

    # find all timestamp files
    ts_pattern = os.path.join(narration_dir, "scene_*_timestamps.json")
    ts_files = sorted(
        glob.glob(ts_pattern),
        key=lambda f: int(re.search(r"scene_(\d+)", f).group(1)),
    )

    if not ts_files:
        print(f"Error: No timestamp files found in {narration_dir}")
        return

    for ts_file in ts_files:
        scene_num = int(re.search(r"scene_(\d+)", ts_file).group(1))

        with open(ts_file, "r") as f:
            data = json.load(f)

        words = data.get("words", [])
        if not words:
            print(f"Scene {scene_num}: no words, skipping")
            continue

        # find sub-videos for this scene, sorted by sub index
        sub_pattern = os.path.join(videos_dir, f"scene_{scene_num}_sub_*.mp4")
        sub_videos = sorted(
            glob.glob(sub_pattern),
            key=lambda f: int(re.search(r"sub_(\d+)", f).group(1)),
        )

        if not sub_videos:
            print(f"Scene {scene_num}: no sub-videos found, skipping")
            continue

        print(f"\nScene {scene_num}: {len(words)} words, {len(sub_videos)} sub-videos")

        cumulative_time = 0.0

        for sub_video in sub_videos:
            sub_num = int(re.search(r"sub_(\d+)", sub_video).group(1))
            sub_duration = get_media_duration(sub_video)
            t_start = cumulative_time
            t_end = cumulative_time + sub_duration

            # filter words for this sub-video's time range
            sub_words = filter_words_for_range(words, t_start, t_end, offset=t_start)

            if sub_words:
                segments = words_to_segments(sub_words)
                ass_content = segments_to_ass(segments)
            else:
                # no words in this range — just copy the video
                ass_content = None

            output_file = os.path.join(output_dir, os.path.basename(sub_video))

            if ass_content:
                print(f"  scene_{scene_num}_sub_{sub_num}: {t_start:.1f}s-{t_end:.1f}s, {len(segments)} subtitle lines")
                burn_ass_into_video(sub_video, ass_content, output_file)
            else:
                print(f"  scene_{scene_num}_sub_{sub_num}: {t_start:.1f}s-{t_end:.1f}s, no words — copying")
                subprocess.run(["cp", sub_video, output_file])

            cumulative_time = t_end


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    videos_dir = os.path.join(base_dir, "output_videos", "output_videos")
    narration_dir = os.path.join(base_dir, "output_videos", "output_narration")
    output_dir = os.path.join(base_dir, "output_videos", "output_subtitled")

    burn_subtitles_per_scene(videos_dir, narration_dir, output_dir)


if __name__ == "__main__":
    main()
