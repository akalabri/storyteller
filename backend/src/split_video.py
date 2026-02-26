import subprocess
<<<<<<< HEAD
=======
import sys
>>>>>>> da3daa2bda9703d7c15bd87f92c3b10e62f0f97c
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
<<<<<<< HEAD
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def split_video(filepath, segment_duration) -> list[str]:
    """Split video into segments of given duration (in seconds).

    Returns list of output file paths.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

=======
    return float(result.stdout.strip())


def split_video(filepath, segment_duration):
    """Split video into segments of given duration (in seconds)."""
    if not os.path.isfile(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    # Get file info
>>>>>>> da3daa2bda9703d7c15bd87f92c3b10e62f0f97c
    base, ext = os.path.splitext(filepath)
    duration = get_video_duration(filepath)
    num_segments = math.ceil(duration / segment_duration)

<<<<<<< HEAD
    outputs = []
=======
    print(f"Video duration : {duration:.2f}s")
    print(f"Segment length : {segment_duration}s")
    print(f"Total segments : {num_segments}")
    print()

>>>>>>> da3daa2bda9703d7c15bd87f92c3b10e62f0f97c
    for i in range(num_segments):
        start = i * segment_duration
        output = f"{base}_{i + 1}{ext}"

<<<<<<< HEAD
=======
        print(f"Creating segment {i + 1}/{num_segments}: {output}")

>>>>>>> da3daa2bda9703d7c15bd87f92c3b10e62f0f97c
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", filepath,
                "-t", str(segment_duration),
<<<<<<< HEAD
                "-c", "copy",
=======
                "-c", "copy",          # no re-encoding = fast & lossless
>>>>>>> da3daa2bda9703d7c15bd87f92c3b10e62f0f97c
                output
            ],
            capture_output=True
        )
<<<<<<< HEAD
        outputs.append(output)

    return outputs
=======

    print("\nDone! All segments saved.")


if __name__ == "__main__":


    video_path = "../videos/story.mp4"
    seg_dur = 15
    split_video(video_path, seg_dur)
>>>>>>> da3daa2bda9703d7c15bd87f92c3b10e62f0f97c
