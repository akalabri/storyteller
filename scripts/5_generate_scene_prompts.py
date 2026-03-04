import os
import json
from pydantic import BaseModel, Field
from typing import List
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class SubScene(BaseModel):
    index: int = Field(description="Sub-scene index within its parent scene, 1-based (1, 2, or 3)")
    image_prompt: str = Field(
        description=(
            "A cinematic production prompt for a single illustrated frame. "
            "Character reference images are already supplied — do NOT describe how characters look. "
            "Instead, direct them: what are they doing, how are they physically engaging with the world around them "
            "(touching, reacting to, moving through, gazing at something), and what emotion are they performing. "
            "Then build the world around them: the specific background composition, depth layers, "
            "atmospheric effects (mist, falling snow, dappled light, glowing embers, breath in cold air), "
            "and any environmental details that anchor the story moment. "
            "Choose a deliberate camera angle that serves the narrative — low angle to show wonder, "
            "tight over-the-shoulder to build intimacy, wide establishing shot to convey isolation, "
            "Dutch tilt for unease, bird's-eye for scale, etc. "
            "Specify the lighting setup: direction, quality, color temperature, and any practical light sources "
            "(moonlight through branches, a lantern's warm pool, firelight catching fur). "
            "End with the art style and mood so the tone is locked. "
            "Write this as a film director briefing a cinematographer — specific, evocative, purposeful."
        )
    )
    video_prompt: str = Field(
        description=(
            "A prompt for animating the still image into a short clip. "
            "Describe only what moves or changes — camera drift or push, character micro-actions "
            "(a breath, a paw lifting, ears perking), and environmental animation "
            "(snow drifting down, fire flickering, tree branches swaying gently). "
            "Do NOT re-describe the static scene; the image is already the reference. "
            "Characters must NOT speak, mouth words, or make any talking gestures — no dialogue or lip movement of any kind. "
            "Keep motion subtle and purposeful, consistent with a gentle children's animated story."
        )
    )


class ScenePrompts(BaseModel):
    scene_index: int = Field(description="The 1-based index of the main story scene this belongs to")
    scene_summary: str = Field(
        description="A brief one-sentence summary of what happens in this scene (for reference)"
    )
    subscenes: List[SubScene] = Field(
        description="Exactly 3 sub-scenes that together cover the full arc of this story scene"
    )


class StoryVisualPlan(BaseModel):
    scenes: List[ScenePrompts] = Field(
        description="One entry per main story scene, each containing exactly 3 sub-scenes"
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior production director crafting the visual shooting plan for an animated children's story.

You will receive:
- The story broken into scenes (narrative prose) — read each one carefully; the specific details in the prose are your visual source material
- Character descriptions — these are provided only so you know which characters appear in each scene; reference images will be passed directly to the image model, so never describe character appearance in prompts
- Special instructions (art style, tone, target audience)

Your task is to produce a detailed shot-by-shot visual plan. For each story scene, create exactly 3 consecutive 
sub-scenes that form a clear beginning → middle → end arc for that scene.

For each sub-scene produce two prompts:

1. image_prompt — Write this as a film director briefing a cinematographer on a single frame.
   The character reference images are already provided to the image model — do NOT describe how characters look.
   Focus entirely on:
   - What the character(s) are DOING and how they are physically engaging with their environment
     (a paw brushing snow off a buried key, a fox pressing her nose to cold bark, two foxes sitting close by a fire)
   - The emotional performance: what feeling is on their face and body right now in this exact moment
   - Background composition: foreground elements, mid-ground action, distant backdrop — use depth
   - Atmospheric effects grounded in the story prose: falling snow, breath misting in cold air, 
     warm firelight catching fur, glowing symbols on wood, patches of green breaking through white
   - A deliberate camera angle chosen to serve the story moment:
     low-angle looking up to convey wonder or discovery; tight over-the-shoulder for intimacy; 
     wide shot to show isolation in a vast snowy forest; extreme close-up on a detail (the key, 
     the carved words, an eye); shallow depth-of-field to pull focus to an emotional beat
   - Lighting: direction, quality, color temperature, and specific practical sources 
     (cold blue moonlight through pine canopy, the amber glow of a key catching light, 
     warm orange firelight from a cottage hearth)
   - Art style and overall mood, consistent with the special instructions
   Pull specific imagery, actions, and sensory details directly from the story prose for that scene.

2. video_prompt — Describe only what moves or changes to animate the still into a short clip.
   Cover: gentle camera movement (slow push in, subtle drift), character micro-actions 
   (ear twitch, a slow exhale, a tentative step), and environmental motion 
   (snowflakes drifting, embers floating up, firelight flickering, a scarf shifting in a breeze).
   Do NOT re-describe the static scene. Characters must never speak or mouth words — no talking, no lip movement, no dialogue gestures. Keep motion gentle and wonder-filled.

Apply the special instructions (art style, tone, audience) consistently across all prompts.
Output only the structured JSON — no additional commentary."""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def generate_scene_prompts(breakdown: dict) -> StoryVisualPlan:
    scenes = breakdown["story"]
    characters = breakdown["characters_prompts"]
    instructions = breakdown.get("special_instructions", "")

    characters_block = "\n".join(
        f"- {c['name']}: {c['description']}" for c in characters
    )

    user_input = f"""STORY SCENES:
{chr(10).join(f"Scene {i+1}: {text}" for i, text in enumerate(scenes))}

CHARACTER DESCRIPTIONS:
{characters_block}

SPECIAL INSTRUCTIONS:
{instructions if instructions else "(none)"}"""

    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=user_input,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=StoryVisualPlan,
            temperature=0.6,
        ),
    )

    return response.parsed


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_visual_plan(plan: StoryVisualPlan) -> None:
    wide = "═" * 70
    thin = "─" * 70

    for scene in plan.scenes:
        print(f"\n{wide}")
        print(f"  SCENE {scene.scene_index}")
        print(f"  {scene.scene_summary}")
        print(f"{wide}")

        for sub in scene.subscenes:
            print(f"\n  Sub-scene {sub.index}")
            print(f"  {thin}")

            print("\n  IMAGE PROMPT")
            for line in sub.image_prompt.strip().splitlines():
                print(f"    {line}")

            print("\n  VIDEO PROMPT")
            for line in sub.video_prompt.strip().splitlines():
                print(f"    {line}")

    print(f"\n{wide}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scripts_dir = os.path.dirname(__file__)
    breakdown_path = os.path.join(scripts_dir, "story_convo_example_breakdown.json")

    with open(breakdown_path, "r", encoding="utf-8") as f:
        breakdown = json.load(f)

    print(f"Generating visual plan for {len(breakdown['story'])} scene(s)...\n")
    plan = generate_scene_prompts(breakdown)
    print_visual_plan(plan)

    output_path = os.path.join(scripts_dir, "story_visual_plan.json")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(plan.model_dump_json(indent=2))
    print(f"Visual plan saved to: {output_path}")
