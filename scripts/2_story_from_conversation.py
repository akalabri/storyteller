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

class CharacterPrompt(BaseModel):
    name: str = Field(description="Character's name as it appears in the story")
    description: str = Field(
        description=(
            "A rich visual prompt for generating a reference character-sheet image. "
            "Do NOT mention the character's name anywhere in this prompt. "
            "Describe only their visual appearance: age, ethnicity, face, hair, skin tone, build, "
            "clothing, footwear, accessories, and any distinctive features. "
            "The prompt should be detailed enough for a model to produce a consistent, "
            "multi-angle character sheet with no prior context."
        )
    )

class StoryBreakdown(BaseModel):
    story: List[str] = Field(
        description=(
            "The story split into 3–5 scenes. Each item is the narrative text for one scene — "
            "written as actual story prose, not a scene description or summary. "
            "The number of scenes should match what the story genuinely needs."
        )
    )
    characters_prompts: List[CharacterPrompt] = Field(
        description="One entry per main character with a detailed visual prompt for reference-image generation."
    )
    special_instructions: str = Field(
        description=(
            "Any important instructions for downstream agents creating scenes or animations. "
            "This may include graphic style, visual tone, cultural details, language preferences, "
            "target audience, or explicit requests the user made during the conversation. "
            "Leave as an empty string if nothing notable was mentioned."
        )
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a story production assistant. You will receive a raw conversation 
between a user and an AI storyteller. Your job is to analyse that conversation and produce a 
structured output with three components.

1. story — Split the final story into 3–5 scenes. Write each scene as genuine narrative prose 
   (the story itself, not a description of it). Use similar story content from the conversation and make it adhere to your instructions
   some stories are complete in 3 scenes, others need 5. see which one is best for the story. 

2. characters_prompts — Identify every main character that appears in the story. For each one, 
   craft a detailed visual prompt suitable for generating a reference character-sheet image. 
   The image will be used for consistent character rendering across all scenes, so the prompt 
   must describe the character from multiple angles and include: facial features, hair, skin 
   tone, body type, clothing (colours, style, cultural details), footwear, and any notable 
   accessories or props. Be specific — avoid vague adjectives like "nice" or "normal". 
   Do NOT include the character's name anywhere inside the description — the name is stored 
   separately in the name field.

3. special_instructions — Extract any instructions relevant to visual production: graphic or 
   art style (e.g. watercolour, 3-D render, flat illustration), story tone, cultural or language 
   requirements, target audience notes, or anything the user explicitly asked for. If nothing 
   was mentioned, return an empty string.

Respond only with the structured JSON — no extra commentary."""


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def process_conversation(conversation_path: str) -> StoryBreakdown:
    with open(conversation_path, "r", encoding="utf-8") as f:
        conversation_text = f.read()

    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT", "challengegemini"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=conversation_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=StoryBreakdown,
            temperature=0.4,
        ),
    )

    return response.parsed


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_breakdown(breakdown: StoryBreakdown) -> None:
    divider = "─" * 60

    # Story scenes
    print(f"\n{'═' * 60}")
    print("  STORY SCENES")
    print(f"{'═' * 60}")
    for i, scene in enumerate(breakdown.story, start=1):
        print(f"\n  Scene {i}")
        print(f"  {divider}")
        # Indent each line of the scene text
        for line in scene.strip().splitlines():
            print(f"  {line}")

    # Character prompts
    print(f"\n\n{'═' * 60}")
    print("  CHARACTER PROMPTS")
    print(f"{'═' * 60}")
    for char in breakdown.characters_prompts:
        print(f"\n  {char.name}")
        print(f"  {divider}")
        for line in char.description.strip().splitlines():
            print(f"  {line}")

    # Special instructions
    print(f"\n\n{'═' * 60}")
    print("  SPECIAL INSTRUCTIONS")
    print(f"{'═' * 60}")
    instructions = breakdown.special_instructions.strip()
    if instructions:
        for line in instructions.splitlines():
            print(f"  {line}")
    else:
        print("  (none)")

    print(f"\n{'═' * 60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    convo_path = os.path.join(os.path.dirname(__file__), "story_convo_example.txt")

    print(f"Processing conversation: {convo_path}")
    breakdown = process_conversation(convo_path)
    print_breakdown(breakdown)

    # Optionally save as JSON next to the input file
    output_path = convo_path.replace(".txt", "_breakdown.json")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(breakdown.model_dump_json(indent=2))
    print(f"Breakdown saved to: {output_path}")
