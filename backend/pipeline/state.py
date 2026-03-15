"""
Unified artifact state for the storyteller pipeline.

All generated artifacts (prompts, file paths, structured data) live in one
StoryState instance that is persisted to story_state.json in the session
directory.  The edit agent reads this file, applies minimal changes, then the
orchestrator uses it to determine which nodes are dirty and must be regenerated.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Nested schemas (mirror the scripts' Pydantic models so we can embed them)
# ---------------------------------------------------------------------------

class CharacterPrompt(BaseModel):
    name: str = Field(description="Character name as it appears in the story")
    description: str = Field(
        description=(
            "Rich visual prompt for generating a reference character-sheet image. "
            "Must NOT mention the character's name. "
            "Describes: age, ethnicity, face, hair, skin tone, build, clothing, "
            "footwear, accessories, and distinctive features."
        )
    )


class PropDescription(BaseModel):
    name: str = Field(
        description="Short canonical label for the prop, object, or location (e.g. 'golden bell', 'village square', 'baker's cottage')"
    )
    description: str = Field(
        description=(
            "Precise visual description for use verbatim in image prompts. "
            "Covers shape, size, colour, material, texture, and all distinctive features "
            "so the object looks identical every time it is rendered."
        )
    )


class StoryBreakdown(BaseModel):
    story: list[str] = Field(
        description="The story split into 3–5 scenes as narrative prose."
    )
    characters_prompts: list[CharacterPrompt] = Field(
        description="One entry per main character with a detailed visual prompt."
    )
    prop_descriptions: list[PropDescription] = Field(
        default_factory=list,
        description=(
            "One entry per significant recurring prop, object, named location, or "
            "non-character entity (animals, crowds) that appears in more than one scene. "
            "Used to keep visual descriptions consistent across all scene images."
        ),
    )
    special_instructions: str = Field(
        default="",
        description=(
            "Instructions for downstream agents: graphic style, visual tone, "
            "cultural details, language preferences, target audience. "
            "Empty string if nothing notable was mentioned."
        ),
    )


class SubScene(BaseModel):
    index: int = Field(description="1-based sub-scene index within its parent scene")
    image_prompt: str = Field(description="Cinematic director brief for a still frame")
    video_prompt: str = Field(description="Motion description for animating the still")


class ScenePrompts(BaseModel):
    scene_index: int = Field(description="1-based index of the main story scene")
    scene_summary: str = Field(description="One-sentence summary of this scene")
    subscenes: list[SubScene] = Field(description="Exactly 3 sub-scenes")


class StoryVisualPlan(BaseModel):
    scenes: list[ScenePrompts] = Field(
        description="One entry per story scene, each with exactly 3 sub-scenes"
    )


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------

class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    EDITING = "editing"
    PARTIAL_FAILURE = "partial_failure"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

class StepProgress(BaseModel):
    step: str
    status: StepStatus = StepStatus.PENDING
    message: str = ""


# ---------------------------------------------------------------------------
# Main unified state
# ---------------------------------------------------------------------------

class StoryState(BaseModel):
    session_id: str

    # --- Source material ---
    conversation_transcript: str | None = None
    # Transcript from the edit voice conversation (gathered by edit_conversation_agent)
    edit_conversation_transcript: str | None = None

    # --- LLM-generated structured data ---
    breakdown: StoryBreakdown | None = None
    visual_plan: StoryVisualPlan | None = None

    # --- Generated file paths (relative to session output dir) ---
    # key: scene index (int as str e.g. "1")
    narration_paths: dict[str, str] = Field(default_factory=dict)

    # key: character slug e.g. "Ember"
    character_image_paths: dict[str, str] = Field(default_factory=dict)

    # key: "scene_i_sub_j" e.g. "scene_1_sub_2"
    scene_image_paths: dict[str, str] = Field(default_factory=dict)
    scene_video_paths: dict[str, str] = Field(default_factory=dict)

    final_video_path: str | None = None

    # Sub-scene keys whose video generation failed (populated on partial_failure)
    failed_video_keys: list[str] = Field(default_factory=list)

    # --- Pipeline bookkeeping ---
    status: PipelineStatus = PipelineStatus.IDLE
    steps: list[StepProgress] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    # --- Edit history ---
    edit_history: list[dict[str, Any]] = Field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def subscene_key(self, scene_idx: int, sub_idx: int) -> str:
        return f"scene_{scene_idx}_sub_{sub_idx}"

    def scene_key(self, scene_idx: int) -> str:
        return str(scene_idx)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def update_step(self, step: str, status: StepStatus, message: str = "") -> None:
        for s in self.steps:
            if s.step == step:
                s.status = status
                s.message = message
                return
        self.steps.append(StepProgress(step=step, status=status, message=message))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "StoryState":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())
