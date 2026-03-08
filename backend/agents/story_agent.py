"""
Story agent — converts a raw conversation transcript into a structured
StoryBreakdown (scenes, character prompts, special instructions).

Uses Gemini (default: 2.5 Flash for speed) via Vertex AI with JSON schema
enforcement. Runs the blocking call in a thread-pool executor with a
configurable timeout so the async orchestrator does not hang.
"""

from __future__ import annotations

import asyncio
import logging
import time

from google import genai
from google.genai import types

from backend.config import (
    GEMINI_STORY_MODEL,
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
    STORY_BREAKDOWN_TIMEOUT_S,
)
from backend.pipeline.state import StoryBreakdown

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a story production assistant. You will receive a raw conversation \
between a user and an AI storyteller. Your job is to analyse that conversation and produce a \
structured output with three components.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. story
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Split the story into 4–5 short scenes (use 3 only if the story is genuinely minimal).

SCENE RULES — follow every rule for every scene:
• ONE narrative beat per scene — a single moment, action, or turn of events. Do not cram \
  multiple plot points into one scene.
• Length: 60–90 words per scene. Never exceed 100 words. Be punchy and precise.
• Write genuine narrative prose (the story itself, not a summary or description of it).
• Use vivid, concrete sensory details — what characters see, hear, smell, feel.
• End each scene on a small hook or tension that pulls the reader into the next.
• Preserve the characters, setting, theme, and key plot beats established in the conversation.
• Adapt the tone to the target audience (e.g. warm and gentle for young children, suspenseful \
  for older readers).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. characters_prompts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Identify every main character. For each one, craft a detailed visual prompt suitable for \
generating a reference character-sheet image used for consistent rendering across all scenes.

The prompt MUST include:
• Facial features (eye colour, shape, expression), hair (colour, length, texture, style)
• Skin tone (use specific descriptive terms, not just "light" or "dark")
• Body type and approximate age/size
• Clothing: colours, style, cultural details, any patterns or textures
• Footwear and any accessories, tools, or recurring props
• Lighting or mood cues if relevant to the story's visual style

Be specific — avoid vague adjectives like "nice", "normal", or "beautiful". \
Do NOT include the character's name anywhere in the description — the name is stored separately.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. special_instructions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Extract any instructions relevant to visual production: graphic or art style (e.g. watercolour, \
3-D render, flat illustration), story tone, cultural or language requirements, target audience \
notes, or anything the user explicitly requested. If nothing was mentioned, return an empty string.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Respond ONLY with the structured JSON — no extra commentary."""


# ---------------------------------------------------------------------------
# Core async function
# ---------------------------------------------------------------------------

def _generate_sync(conversation_text: str) -> StoryBreakdown:
    """Synchronous call — runs in a thread-pool executor."""
    logger.info("Story breakdown: calling %s (transcript %d chars)…", GEMINI_STORY_MODEL, len(conversation_text))
    start = time.monotonic()
    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
    )

    response = client.models.generate_content(
        model=GEMINI_STORY_MODEL,
        contents=conversation_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=StoryBreakdown,
            temperature=0.4,
        ),
    )
    elapsed = time.monotonic() - start
    logger.info("Story breakdown: %s returned in %.1fs", GEMINI_STORY_MODEL, elapsed)
    return response.parsed


async def generate_story_breakdown(conversation_transcript: str) -> StoryBreakdown:
    """
    Convert a raw conversation transcript into a StoryBreakdown.

    Runs the blocking Gemini call in the default thread-pool executor so
    the event loop stays free. Uses a timeout to avoid hanging indefinitely.
    """
    logger.info(
        "Generating story breakdown from conversation transcript (model=%s, timeout=%ds)…",
        GEMINI_STORY_MODEL,
        STORY_BREAKDOWN_TIMEOUT_S,
    )
    loop = asyncio.get_running_loop()
    try:
        breakdown: StoryBreakdown = await asyncio.wait_for(
            loop.run_in_executor(None, _generate_sync, conversation_transcript),
            timeout=STORY_BREAKDOWN_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Story breakdown timed out after %d seconds. Try increasing STORY_BREAKDOWN_TIMEOUT_S or check Vertex AI latency.",
            STORY_BREAKDOWN_TIMEOUT_S,
        )
        raise RuntimeError(
            f"Story breakdown timed out after {STORY_BREAKDOWN_TIMEOUT_S} seconds. "
            "Set STORY_BREAKDOWN_TIMEOUT_S in .env to increase, or check your network/Vertex AI."
        ) from None
    logger.info(
        "Story breakdown ready: %d scenes, %d characters.",
        len(breakdown.story),
        len(breakdown.characters_prompts),
    )
    return breakdown
