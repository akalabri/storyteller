"""
Quick test: call Gemini with a structured JSON response (same pattern as
scene_prompt_agent.py) and check which models are actually available.

Usage:
    python test_gemini_model.py
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from backend.config import GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION


# ---------------------------------------------------------------------------
# Tiny dummy schema — mirrors the SubScene / ScenePrompts pattern
# ---------------------------------------------------------------------------

class DummySubscene(BaseModel):
    index: int = Field(description="1-based sub-scene index")
    description: str = Field(description="One sentence describing what happens visually")


class DummyScenePlan(BaseModel):
    scene_summary: str = Field(description="One-sentence summary of the scene")
    subscenes: list[DummySubscene] = Field(description="Exactly 3 sub-scenes")


# ---------------------------------------------------------------------------
# Dummy scene text (same example from the task description)
# ---------------------------------------------------------------------------

DUMMY_SCENE = (
    "Jasper the cat, clever and quick, pounced behind the bakery. "
    "His emerald eyes spotted it first: a golden bell, gleaming in a sunbeam. "
    "It had fallen from the baker's prize cow! He snatched it up, its little clapper "
    "silenced in his paw. Just then, Daisy the goat trotted around the corner, her fluffy "
    "white coat like a friendly cloud. \"What have you got there, Jasper?\" she asked, "
    "her big brown eyes full of simple curiosity."
)

SYSTEM_PROMPT = (
    "You are a visual story director. "
    "Split the scene text into three sequential chunks and describe one visual image for each chunk. "
    "Output only structured JSON."
)

# ---------------------------------------------------------------------------
# Models to test: (model_id, location)
# Gemini 3.x Preview models require location="global"; 2.5 uses regional.
# ---------------------------------------------------------------------------

MODELS_TO_TEST = [
    ("gemini-2.5-pro", None),                    # None = use GOOGLE_CLOUD_LOCATION (us-central1)
    ("gemini-2.5-flash", None),
    ("gemini-3.1-pro-preview", "global"),
    ("gemini-3-flash-preview", "global"),
]


def test_model(model_id: str, location: str | None) -> None:
    loc = location or GOOGLE_CLOUD_LOCATION
    print(f"\n{'='*60}")
    print(f"Testing model: {model_id}  (location={loc})")
    print('='*60)

    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=loc,
    )

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=f"SCENE:\n{DUMMY_SCENE}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=DummyScenePlan,
                temperature=0.5,
            ),
        )
        plan: DummyScenePlan = response.parsed
        print(f"  Summary : {plan.scene_summary}")
        for sub in plan.subscenes:
            print(f"  Sub {sub.index}   : {sub.description}")
        print(f"  STATUS  : OK")
    except Exception as e:
        print(f"  STATUS  : FAILED — {type(e).__name__}: {e}")


if __name__ == "__main__":
    for model_id, location in MODELS_TO_TEST:
        test_model(model_id, location)

    print("\nDone.")
