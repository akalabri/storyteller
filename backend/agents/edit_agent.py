"""
Edit agent — interprets a natural-language edit request, applies the minimal
change to the StoryState, and computes the set of pipeline nodes that must be
regenerated as a result.

Flow
----
1. Receive: user edit message + full current StoryState
2. Call Gemini 2.5 Pro (structured output) → EditPlan
   - updated_breakdown  (optional, only changed if user touched story/characters)
   - updated_visual_plan (optional, only changed if user touched prompts)
   - dirty_nodes         (explicit list of what to regenerate)
   - reasoning           (explanation for the user)
3. Merge updates back into StoryState
4. Return the updated state + the set of dirty node keys so the orchestrator
   knows exactly which pipeline steps to re-run

Dependency graph (used by propagate_dirty_nodes)
-------------------------------------------------
breakdown.story[i]           → narration[i], visual_plan, scene_images[i_*], scene_videos[i_*]
breakdown.characters_prompts → character_images[*], scene_images[*], scene_videos[*]
breakdown.special_instructions → visual_plan, scene_images[*], scene_videos[*]
visual_plan                  → scene_images[*], scene_videos[*]
visual_plan.scenes[i].subscenes[j].image_prompt → scene_images[i_j], scene_videos[i_j]
visual_plan.scenes[i].subscenes[j].video_prompt → scene_videos[i_j]
character_images[name]       → scene_images[*], scene_videos[*]
scene_images[i_j]            → scene_videos[i_j]
ANY of the above             → final_video
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from backend.config import (
    GEMINI_TEXT_MODEL,
    GEMINI_TEXT_LOCATION,
    GOOGLE_CLOUD_PROJECT,
)
from backend.pipeline.state import (
    StoryBreakdown,
    StoryVisualPlan,
    StoryState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EditPlan schema
# ---------------------------------------------------------------------------

class DirtyNode(BaseModel):
    """A single pipeline node that needs to be regenerated."""
    node_type: str = Field(
        description=(
            "One of: 'narration', 'character_image', 'visual_plan', "
            "'scene_image', 'scene_video', 'final_video'. "
            "Use 'all_scene_images', 'all_scene_videos' to mark all at once."
        )
    )
    key: str = Field(
        description=(
            "Identifier for the specific artifact. "
            "For narration: scene index as string e.g. '1'. "
            "For character_image: character slug e.g. 'Ember'. "
            "For scene_image / scene_video: subscene key e.g. 'scene_2_sub_1'. "
            "For visual_plan / final_video: use 'all'."
        )
    )


class EditPlan(BaseModel):
    reasoning: str = Field(
        description="Clear explanation of what changed and why these nodes need regeneration."
    )
    updated_breakdown: StoryBreakdown | None = Field(
        default=None,
        description=(
            "Full updated StoryBreakdown if any story text, character description, "
            "or special instructions changed. Null if breakdown is unchanged."
        ),
    )
    updated_visual_plan: StoryVisualPlan | None = Field(
        default=None,
        description=(
            "Full updated StoryVisualPlan if any image_prompt or video_prompt changed directly. "
            "Null if visual plan is unchanged."
        ),
    )
    dirty_nodes: list[DirtyNode] = Field(
        description=(
            "The minimal set of pipeline nodes that must be regenerated. "
            "The orchestrator will propagate dependencies automatically, "
            "so list only the root-level nodes that were directly edited."
        )
    )


# ---------------------------------------------------------------------------
# Dependency propagation
# ---------------------------------------------------------------------------

def propagate_dirty_nodes(
    direct_dirty: list[DirtyNode],
    state: StoryState,
) -> set[str]:
    """
    Given the directly-changed nodes, walk the dependency graph forward and
    return the full set of artifact keys that must be regenerated.

    Returned key format mirrors StoryState dict keys:
        narration          → "narration:{scene_idx}"
        character_image    → "character:{char_name}"
        visual_plan        → "visual_plan"
        scene_image        → "scene_image:{scene_i_sub_j}"
        scene_video        → "scene_video:{scene_i_sub_j}"
        final_video        → "final_video"
    """
    dirty: set[str] = set()

    def _all_subscene_keys() -> list[str]:
        if not state.visual_plan:
            return []
        return [
            f"scene_{s.scene_index}_sub_{sub.index}"
            for s in state.visual_plan.scenes
            for sub in s.subscenes
        ]

    def _subscene_keys_for_scene(scene_idx: int) -> list[str]:
        if not state.visual_plan:
            return []
        for s in state.visual_plan.scenes:
            if s.scene_index == scene_idx:
                return [f"scene_{s.scene_index}_sub_{sub.index}" for sub in s.subscenes]
        return []

    def _mark_all_scene_images_and_videos() -> None:
        for key in _all_subscene_keys():
            dirty.add(f"scene_image:{key}")
            dirty.add(f"scene_video:{key}")

    def _mark_scene_images_and_videos_for_scene(scene_idx: int) -> None:
        for key in _subscene_keys_for_scene(scene_idx):
            dirty.add(f"scene_image:{key}")
            dirty.add(f"scene_video:{key}")

    for node in direct_dirty:
        ntype = node.node_type
        key = node.key

        if ntype == "narration":
            dirty.add(f"narration:{key}")
            dirty.add("final_video")

        elif ntype == "character_image":
            dirty.add(f"character:{key}")
            # Character images feed scene images → scene videos
            _mark_all_scene_images_and_videos()
            dirty.add("final_video")

        elif ntype == "visual_plan":
            dirty.add("visual_plan")
            _mark_all_scene_images_and_videos()
            dirty.add("final_video")

        elif ntype == "scene_image":
            if key == "all":
                for sk in _all_subscene_keys():
                    dirty.add(f"scene_image:{sk}")
                    dirty.add(f"scene_video:{sk}")
            else:
                dirty.add(f"scene_image:{key}")
                dirty.add(f"scene_video:{key}")
            dirty.add("final_video")

        elif ntype == "scene_video":
            if key == "all":
                for sk in _all_subscene_keys():
                    dirty.add(f"scene_video:{sk}")
            else:
                dirty.add(f"scene_video:{key}")
            dirty.add("final_video")

        elif ntype == "all_scene_images":
            for sk in _all_subscene_keys():
                dirty.add(f"scene_image:{sk}")
                dirty.add(f"scene_video:{sk}")
            dirty.add("final_video")

        elif ntype == "all_scene_videos":
            for sk in _all_subscene_keys():
                dirty.add(f"scene_video:{sk}")
            dirty.add("final_video")

        elif ntype == "final_video":
            dirty.add("final_video")

    # Also handle breakdown-level changes
    # (LLM may change breakdown; propagate downstream manually)
    return dirty


def dirty_nodes_from_breakdown_diff(
    old: StoryBreakdown | None,
    new: StoryBreakdown,
    state: StoryState,
) -> list[DirtyNode]:
    """
    Compare old and new breakdowns and return the minimal DirtyNode list.
    Called by plan_edit after the LLM has produced an updated_breakdown.
    """
    nodes: list[DirtyNode] = []

    if old is None:
        # Everything is new
        return [DirtyNode(node_type="visual_plan", key="all")]

    # Check story scenes
    for i, (old_scene, new_scene) in enumerate(
        zip(old.story, new.story), start=1
    ):
        if old_scene != new_scene:
            nodes.append(DirtyNode(node_type="narration", key=str(i)))
            nodes.append(DirtyNode(node_type="visual_plan", key="all"))
            nodes.append(DirtyNode(node_type="all_scene_images", key="all"))
            break  # one change triggers full downstream; no need to iterate further

    # If story scene count changed, also dirty everything
    if len(old.story) != len(new.story):
        nodes.append(DirtyNode(node_type="visual_plan", key="all"))
        nodes.append(DirtyNode(node_type="all_scene_images", key="all"))
        for i in range(1, max(len(old.story), len(new.story)) + 1):
            nodes.append(DirtyNode(node_type="narration", key=str(i)))

    # Check characters
    old_chars = {c.name: c.description for c in old.characters_prompts}
    new_chars = {c.name: c.description for c in new.characters_prompts}
    for name, desc in new_chars.items():
        if old_chars.get(name) != desc:
            from backend.utils.file_io import safe_filename
            nodes.append(DirtyNode(node_type="character_image", key=safe_filename(name)))

    # Check special_instructions
    if old.special_instructions != new.special_instructions:
        nodes.append(DirtyNode(node_type="visual_plan", key="all"))

    # Deduplicate
    seen: set[str] = set()
    unique: list[DirtyNode] = []
    for n in nodes:
        k = f"{n.node_type}:{n.key}"
        if k not in seen:
            seen.add(k)
            unique.append(n)
    return unique


# ---------------------------------------------------------------------------
# System prompt for the edit LLM
# ---------------------------------------------------------------------------

EDIT_SYSTEM_PROMPT = """You are a story editing assistant for an AI-driven story video generator.

You will receive:
1. The user's edit request (natural language)
2. The current story state as JSON:
   - breakdown: { story: [...], characters_prompts: [...], special_instructions: "..." }
   - visual_plan: { scenes: [{ scene_index, scene_summary, subscenes: [{ index, image_prompt, video_prompt }] }] }

Your job is to:
1. Understand exactly what the user wants to change
2. Return an updated_breakdown (only if story text, character descriptions, or special_instructions changed)
3. Return an updated_visual_plan (only if image_prompt or video_prompt values changed directly)
4. List the minimal set of dirty_nodes — only the ROOT changes, not downstream consequences
   (the system handles dependency propagation automatically)
5. Write a clear reasoning explanation

IMPORTANT RULES:
- Only include updated_breakdown if you actually changed something in it. Set to null otherwise.
- Only include updated_visual_plan if you changed prompts directly. Set to null otherwise.
- Never invent changes the user didn't ask for
- dirty_nodes should reflect only what was directly edited, not downstream effects
- Be conservative: prefer changing the minimum required to satisfy the user's request

Respond only with the structured JSON — no extra commentary."""


# ---------------------------------------------------------------------------
# Core sync function
# ---------------------------------------------------------------------------

def _plan_edit_sync(
    edit_message: str,
    state: StoryState,
) -> EditPlan:
    state_summary = {
        "breakdown": state.breakdown.model_dump() if state.breakdown else None,
        "visual_plan": state.visual_plan.model_dump() if state.visual_plan else None,
    }
    user_input = (
        f"USER EDIT REQUEST:\n{edit_message}\n\n"
        f"CURRENT STATE:\n{json.dumps(state_summary, indent=2, ensure_ascii=False)}"
    )

    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GEMINI_TEXT_LOCATION,
    )

    response = client.models.generate_content(
        model=GEMINI_TEXT_MODEL,
        contents=user_input,
        config=types.GenerateContentConfig(
            system_instruction=EDIT_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=EditPlan,
            temperature=0.3,
        ),
    )
    return response.parsed


# ---------------------------------------------------------------------------
# Public async function
# ---------------------------------------------------------------------------

async def plan_edit(
    edit_message: str,
    state: StoryState,
) -> tuple[StoryState, set[str]]:
    """
    Interpret the user's edit request, update the StoryState, and return
    the full set of dirty artifact keys that must be regenerated.

    Returns ``(updated_state, dirty_keys)``
    """
    logger.info("Planning edit: '%.80s'…", edit_message)

    loop = asyncio.get_running_loop()
    edit_plan: EditPlan = await loop.run_in_executor(
        None, _plan_edit_sync, edit_message, state
    )

    logger.info("Edit plan reasoning: %s", edit_plan.reasoning)

    # Apply breakdown changes
    old_breakdown = state.breakdown
    if edit_plan.updated_breakdown is not None:
        state.breakdown = edit_plan.updated_breakdown
        # Augment dirty_nodes from diff
        extra = dirty_nodes_from_breakdown_diff(old_breakdown, state.breakdown, state)
        edit_plan.dirty_nodes = list(edit_plan.dirty_nodes) + extra

    # Apply visual plan changes
    if edit_plan.updated_visual_plan is not None:
        state.visual_plan = edit_plan.updated_visual_plan

    # Propagate and collect full dirty set
    dirty_keys = propagate_dirty_nodes(edit_plan.dirty_nodes, state)
    logger.info("Dirty nodes after propagation (%d): %s", len(dirty_keys), sorted(dirty_keys))

    # Record edit in history
    state.edit_history.append({
        "message": edit_message,
        "reasoning": edit_plan.reasoning,
        "dirty_nodes": [n.model_dump() for n in edit_plan.dirty_nodes],
        "dirty_keys": sorted(dirty_keys),
    })

    return state, dirty_keys
