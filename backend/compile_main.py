import os
import glob
import re

from src.merge_subtitle import burn_subtitles_per_scene
from src.merge_videos import merge_videos
from src.audio_to_video import merge as merge_audio


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    videos_dir = os.path.join(base_dir, "output_videos", "output_videos")
    narration_dir = os.path.join(base_dir, "output_videos", "output_narration")
    subtitled_dir = os.path.join(base_dir, "output_videos", "output_subtitled")
    merged_dir = os.path.join(base_dir, "output_videos", "output_scenes_merged")
    final_dir = os.path.join(base_dir, "output_videos", "output_scenes_final")

    # --- Step 1: burn karaoke subtitles into each sub-video ---
    print(f"\n{'='*50}")
    print("Step 1: Burning karaoke subtitles")
    print(f"{'='*50}")
    burn_subtitles_per_scene(videos_dir, narration_dir, subtitled_dir)

    # discover scene numbers from subtitled sub-videos
    sub_files = glob.glob(os.path.join(subtitled_dir, "scene_*_sub_*.mp4"))
    scene_nums = sorted({int(re.search(r"scene_(\d+)", f).group(1)) for f in sub_files})

    if not scene_nums:
        print("No subtitled sub-videos found.")
        return

    os.makedirs(merged_dir, exist_ok=True)
    os.makedirs(final_dir, exist_ok=True)

    for scene_num in scene_nums:
        print(f"\n{'='*50}")
        print(f"Scene {scene_num}")
        print(f"{'='*50}")

        # --- Step 2: merge sub-videos into one scene video ---
        pattern = os.path.join(subtitled_dir, f"scene_{scene_num}_sub_*.mp4")
        subs = sorted(
            glob.glob(pattern),
            key=lambda f: int(re.search(r"sub_(\d+)", f).group(1)),
        )
        merged_video = os.path.join(merged_dir, f"scene_{scene_num}.mp4")
        merge_videos(subs, merged_video)

        # --- Step 3: add narration audio to the merged scene ---
        audio_file = os.path.join(narration_dir, f"scene_{scene_num}.mp3")
        final_video = os.path.join(final_dir, f"scene_{scene_num}.mp4")

        if not os.path.isfile(audio_file):
            print(f"Warning: {audio_file} not found, skipping audio merge")
            continue

        merge_audio(merged_video, audio_file, final_video, "mix")

    # --- Step 4: merge all final scenes into one video ---
    print(f"\n{'='*50}")
    print("Step 4: Merging all scenes into final video")
    print(f"{'='*50}")

    all_scenes = sorted(
        glob.glob(os.path.join(final_dir, "scene_*.mp4")),
        key=lambda f: int(re.search(r"scene_(\d+)", f).group(1)),
    )
    final_video = os.path.join(final_dir, "story.mp4")
    merge_videos(all_scenes, final_video)

    print(f"\nAll done! Final video: {final_video}")


if __name__ == "__main__":
    main()
