import subprocess
import os




def _has_audio_stream(filepath):
    """Check if a media file contains an audio stream."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", filepath],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def merge(VIDEO_FILE, AUDIO_FILE, OUTPUT_FILE, MODE):
    if not os.path.isfile(VIDEO_FILE):
        print(f"Error: Video file not found: {VIDEO_FILE}")
        return
    if not os.path.isfile(AUDIO_FILE):
        print(f"Error: Audio file not found: {AUDIO_FILE}")
        return

    # mix requires video to have audio — fall back to replace if it doesn't
    if MODE == "mix" and not _has_audio_stream(VIDEO_FILE):
        print(f"Video has no audio stream, falling back to replace mode")
        MODE = "replace"

    print(f"Video : {VIDEO_FILE}")
    print(f"Audio : {AUDIO_FILE}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Mode  : {MODE}\n")

    if MODE == "replace":
        cmd = [
            "ffmpeg", "-y",
            "-i", VIDEO_FILE,
            "-i", AUDIO_FILE,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            OUTPUT_FILE
        ]
    elif MODE == "mix":
        cmd = [
            "ffmpeg", "-y",
            "-i", VIDEO_FILE,
            "-i", AUDIO_FILE,
            "-filter_complex", "amix=inputs=2:duration=first:normalize=0",
            "-c:v", "copy",
            "-c:a", "aac",
            OUTPUT_FILE
        ]
    else:
        print(f"Unknown mode: {MODE}. Use 'replace' or 'mix'.")
        return

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"Done! Saved as: {OUTPUT_FILE}")
    else:
        print("Error during processing:")
        print(result.stderr)

def main():

    VIDEO_FILE  = "../videos/story.mp4"
    AUDIO_FILE  = "../audios/audio.m4a"
    OUTPUT_FILE = "../videos/story_with_audio.mp4"

    # Mode: "replace" → swap video audio with new audio
    #       "mix"     → blend new audio with existing video audio
    MODE = "mix"
    merge(VIDEO_FILE, AUDIO_FILE, OUTPUT_FILE, MODE)

if __name__ == "__main__":
    main()