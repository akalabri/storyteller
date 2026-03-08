# Scripts overview

This folder runs a **story-to-video pipeline**: you have a conversation with an AI storyteller, then a series of scripts turn that into a structured story, narration, character art, scene images, and finally short video clips.

---

## What each script does

| Script | Purpose |
|--------|--------|
| **1_story_conversation.py** | Live voice chat with an AI storyteller (Gemini Live). You talk; it builds a 5-scene story from the conversation. On exit it saves the transcript. |
| **2_story_from_conversation.py** | Reads a conversation `.txt` and uses Gemini to produce a **structured breakdown**: story (3–5 scenes as prose), character visual prompts, and special instructions. |
| **3_generate_narration.py** | Google Cloud Text-to-Speech: turns each scene text into an MP3. |
| **3-1_generate_narration.py** | Same as 3 but uses **ElevenLabs** for narration (set `ELEVENLABS_API_KEY` or `XI_API_KEY`). |
| **4_generate_character_images.py** | Gemini image model: generates **character reference sheets** (one PNG per character) for consistent look. |
| **5_generate_scene_prompts.py** | Gemini: from the breakdown + characters, produces a **visual plan** — for each story scene, 3 sub-scenes with an `image_prompt` and `video_prompt` each. |
| **6_generate_scene_images.py** | Gemini image: generates **scene images** (one per sub-scene) using the visual plan and character refs. |
| **7_generate_scene_videos.py** | **Google Veo**: image-to-video from each scene image + character refs (uses GCS; outputs silent MP4s). |
| **7-1_generate_scene_videos.py** | **FAL Kling 3**: same idea as 7 but via FAL image-to-video (uses `FAL_API_KEY`). |
| **7-2_generate_scene_videos.py** | **FAL Veo 3.1**: same loop but FAL’s reference-to-video API. |

**Typical order:** 1 → 2 → (3 or 3-1) → 4 → 5 → 6 → (7 or 7-1 or 7-2). Downstream steps read from the paths below.

---

## Output structure (where everything lives)

All paths below are relative to the **`scripts/`** directory unless noted.

### Inputs you provide or create

| What | Where |
|------|--------|
| Conversation transcript | Anywhere you pass to script 2; example used in scripts: **`story_convo_example.txt`** |
| Story breakdown (from script 2) | **`story_convo_example_breakdown.json`** (same base name as the `.txt`, with `_breakdown.json`) |

### Generated outputs (all under `scripts/`)

| What | Path | Produced by |
|------|------|-------------|
| Conversation log (when you run script 1) | **`story_conversation_YYYYMMDD_HHMMSS.txt`** (in **current working directory** when you run the script, often project root or `scripts/`) | 1_story_conversation.py |
| Story breakdown JSON | **`<convo_basename>_breakdown.json`** (e.g. `story_convo_example_breakdown.json`) | 2_story_from_conversation.py |
| Visual plan (image + video prompts per sub-scene) | **`story_visual_plan.json`** | 5_generate_scene_prompts.py |
| Narration audio (one per story scene) | **`output_narration/scene_1.mp3`**, `scene_2.mp3`, … | 3 or 3-1 |
| Character reference images | **`output_characters/<name>.png`** (e.g. `Rihal.png`, `character_12345.png` for names that slug to empty) | 4_generate_character_images.py |
| Scene images (one per sub-scene) | **`output_scenes/scene_<i>_sub_<j>.png`** (e.g. `scene_1_sub_1.png`) | 6_generate_scene_images.py |
| Scene videos (one per sub-scene) | **`output_videos/scene_<i>_sub_<j>.mp4`** (e.g. `scene_1_sub_1.mp4`) | 7, 7-1, or 7-2 |

### Directory tree (after a full run)

```text
scripts/
├── story_convo_example.txt              # input conversation (example)
├── story_convo_example_breakdown.json   # story + characters + special_instructions
├── story_visual_plan.json               # image_prompt + video_prompt per sub-scene
├── output_narration/
│   └── scene_1.mp3, scene_2.mp3, ...
├── output_characters/
│   └── <CharacterName>.png, ...
├── output_scenes/
│   └── scene_1_sub_1.png, scene_1_sub_2.png, ...
└── output_videos/
    └── scene_1_sub_1.mp4, scene_1_sub_2.mp4, ...
```

So: **breakdown** and **visual plan** are in `scripts/`; **narration** in `output_narration/`; **character art** in `output_characters/`; **scene images** in `output_scenes/`; **scene videos** in `output_videos/`.
