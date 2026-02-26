import subprocess
import sys
import os
import glob
import re


def merge_videos(input_files, output_file):
    """Merge a list of video files into one."""
    if not input_files:
        print("Error: No input files provided.")
        sys.exit(1)

    # Write a temporary file list for ffmpeg concat
    list_file = "_merge_list.txt"
    with open(list_file, "w") as f:
        for path in input_files:
            # ffmpeg requires escaped paths
            safe = path.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    print(f"Merging {len(input_files)} segments into: {output_file}")
    for i, f in enumerate(input_files):
        print(f"  [{i+1}] {f}")
    print()

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",   # no re-encoding
            output_file
        ],
        capture_output=True, text=True
    )

    os.remove(list_file)

    if result.returncode == 0:
        print(f"Done! Merged video saved as: {output_file}")
    else:
        print("Error during merging:")
        print(result.stderr)
        sys.exit(1)


def auto_find_segments(base_file):
    """Find all _1, _2, _3 ... segments for a given base filename."""
    base, ext = os.path.splitext(base_file)
    pattern = f"{base}_*{ext}"
    files = glob.glob(pattern)

    # Sort by the number at the end
    def extract_num(f):
        match = re.search(r"_(\d+)" + re.escape(ext) + "$", f)
        return int(match.group(1)) if match else 0

    files.sort(key=extract_num)
    return files


def main():
    inputs = ["../videos/story_1.mp4", "../videos/story_2.mp4", "../videos/story_3.mp4"]
    output = "../videos/story_merged.mp4"
    merge_videos(inputs, output)

if __name__ == "__main__":
    main()
