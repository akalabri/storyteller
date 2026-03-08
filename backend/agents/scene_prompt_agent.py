"""
Scene prompt agent — generates the full StoryVisualPlan (image + video prompts
for every sub-scene) from the story breakdown.

Uses Gemini 2.5 Pro with JSON schema enforcement, dispatched to thread-pool.
"""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from backend.config import (
    GEMINI_TEXT_MODEL,
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
)
from backend.pipeline.state import StoryBreakdown, StoryVisualPlan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt (verbatim from 5_generate_scene_prompts.py)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior production director crafting the visual shooting plan for an animated children's story.

You will receive:
- The story broken into scenes (narrative prose) — read each one carefully and deeply; every specific detail in the prose is your visual source material
- Character descriptions — provided only so you know which characters appear; reference images will be passed directly to the image model, so NEVER describe how characters look
- Special instructions (art style, tone, target audience)

Your task is to produce a detailed shot-by-shot visual plan. For each story scene, create exactly 3 consecutive 
sub-scenes that form a clear beginning → middle → end arc for that scene.

NARRATION FIDELITY — this is critical:
Each sub-scene must be visually grounded in the specific narrative beat from the story prose.
- Sub-scene 1 (beginning): the setup or arrival — where are we, what is the character about to do or discover?
- Sub-scene 2 (middle): the action or turning point — the key moment of doing, reacting, or feeling
- Sub-scene 3 (end): the resolution or emotional landing — the consequence, the realisation, the quiet after

Pull concrete nouns, verbs, and sensory details directly from the prose (a buried key, cold bark, glowing symbols, 
patches of green through white). Do not invent details that contradict the story text.

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
# Core sync function (runs inside executor)
# ---------------------------------------------------------------------------

def _generate_sync(breakdown: StoryBreakdown) -> StoryVisualPlan:
    characters_block = "\n".join(
        f"- {c.name}: {c.description}" for c in breakdown.characters_prompts
    )
    user_input = (
        "STORY SCENES:\n"
        + "\n".join(f"Scene {i+1}: {text}" for i, text in enumerate(breakdown.story))
        + "\n\nCHARACTER DESCRIPTIONS:\n"
        + characters_block
        + "\n\nSPECIAL INSTRUCTIONS:\n"
        + (breakdown.special_instructions if breakdown.special_instructions else "(none)")
    )

    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
    )

    response = client.models.generate_content(
        model=GEMINI_TEXT_MODEL,
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
# Public async function
# ---------------------------------------------------------------------------

async def generate_scene_prompts(breakdown: StoryBreakdown) -> StoryVisualPlan:
    """
    Generate the full StoryVisualPlan from the story breakdown.

    Runs blocking Gemini call in thread-pool executor.
    """
    logger.info(
        "Generating scene prompts for %d scenes…", len(breakdown.story)
    )
    loop = asyncio.get_running_loop()
    plan: StoryVisualPlan = await loop.run_in_executor(None, _generate_sync, breakdown)
    total_subs = sum(len(s.subscenes) for s in plan.scenes)
    logger.info(
        "Visual plan ready: %d scenes, %d total sub-scenes.", len(plan.scenes), total_subs
    )
    return plan
