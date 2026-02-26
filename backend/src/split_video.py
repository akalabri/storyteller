import subprocess
import os
import math


def get_video_duration(filepath):
    """Get video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            filepath
        ],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def split_video(filepath, segment_duration) -> list[str]:
    """Split video into segments of given duration (in seconds).

    Returns list of output file paths.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    base, ext = os.path.splitext(filepath)
    duration = get_video_duration(filepath)
    num_segments = math.ceil(duration / segment_duration)

    outputs = []
    for i in range(num_segments):
        start = i * segment_duration
        output = f"{base}_{i + 1}{ext}"

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", filepath,
                "-t", str(segment_duration),
                "-c", "copy",
                output
            ],
            capture_output=True
        )
        outputs.append(output)

    return outputs
