"""
Edit conversation agent — bridges a browser WebSocket to a Gemini Live session
for the purpose of gathering edit requests from the user.

The AI acts as an "edit consultant": it asks the user what they'd like to change
in their story video (scenes, characters, wording, graphics, etc.), confirms the
changes, and ends the session when the user has nothing more to edit.

The full conversation transcript is saved to the session's StoryState so that
POST /api/story/{session_id}/edit-from-transcript can pass it to plan_edit.

Audio protocol (binary frames):
  Browser → Backend  : raw PCM, Int16, 16 kHz, mono
  Backend → Browser  : raw PCM, Int16, 24 kHz, mono  (AI voice)

Control protocol (text JSON frames):
  Backend → Browser:
    { "type": "transcript", "speaker": "user"|"ai", "text": "..." }
    { "type": "state",      "value": "listening"|"speaking"|"processing" }
    { "type": "session_end" }
    { "type": "error",      "message": "..." }

  Browser → Backend:
    { "type": "end_session" }   optional: user presses End button
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import WebSocket
from google import genai
from google.genai import types

from backend.config import (
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
    session_dir,
)
from backend.pipeline.state import StoryState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_ID = "gemini-live-2.5-flash-native-audio"

# Keywords that signal the user is done editing
END_KEYWORDS = [
    "that's all", "thats all", "nothing else", "no more changes",
    "i'm done", "im done", "we're done", "were done",
    "no more edits", "looks good", "all good", "perfect",
    "that's everything", "thats everything", "nothing more",
    "go ahead", "yes please", "yes go ahead", "sounds good",
    "apply the changes", "make the changes", "regenerate",
    "create it", "make it", "let's go", "lets go",
    "goodbye", "bye", "thank you that's all", "thanks that's all",
]

SYSTEM_PROMPT = """You are a friendly and attentive story video editor assistant. The user has already created a story video and you are here to help them refine it.

Your job is to have a natural conversation to find out exactly what they want to change in their story video. They might want to edit:
- Scene descriptions or story text (what happens in a scene, the wording of narration)
- Character appearances (how a character looks, their colors, clothing, style)
- Visual style or graphics (art style, color palette, mood of scenes)
- Specific scenes (what a particular scene shows, the action or setting)
- Any other aspect of the story or visuals

Start by warmly greeting them and asking what they'd like to change. Listen carefully to each request. Ask clarifying follow-up questions if needed — for example, if they say "make the character look different", ask what specifically they'd like to change. Be conversational and helpful.

As you gather edits, briefly confirm back what you've understood. For example: "So you'd like Ember's fur to be deep crimson instead of orange, and the forest scene to feel darker and more mysterious — is that right?"

When the user confirms they have no more changes (says things like "that's all", "nothing else", "looks good", "go ahead", etc.), give a brief warm sign-off like "Great! I'll apply all those changes now." — then end your response. The session will close automatically and the changes will be processed.

Important rules:
- Never make up changes the user didn't ask for
- If they ask for something vague, ask a specific follow-up question
- Keep the conversation focused on edits — don't go off-topic
- Be concise and efficient — respect the user's time"""


# ---------------------------------------------------------------------------
# Transcript formatting
# ---------------------------------------------------------------------------

def _format_transcript(log: list[tuple[str, str]]) -> str:
    lines = [
        f"Edit Conversation — {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
        "=" * 60,
        "",
    ]
    for speaker, text in log:
        lines.append(f"{speaker}:")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main session runner
# ---------------------------------------------------------------------------

async def run_edit_conversation(session_id: str, websocket: WebSocket) -> None:
    """
    Open a Gemini Live session for edit consultation and bridge it to the
    browser WebSocket.

    Binary frames from the browser (PCM 16kHz Int16) are forwarded to Gemini.
    Gemini audio (PCM 24kHz Int16) is forwarded back as binary frames.
    Transcript and state events are sent as text JSON frames.

    When the session ends (done keywords or browser end_session message),
    the full edit transcript is saved to the session's StoryState under
    ``edit_conversation_transcript`` so that the edit-from-transcript endpoint
    can process it.
    """
    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
    )

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=SYSTEM_PROMPT)]
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    stop_event = asyncio.Event()
    farewell_requested = asyncio.Event()
    transcript_log: list[tuple[str, str]] = []
    farewell_timeout_task: list[asyncio.Task | None] = [None]

    async def _farewell_timeout() -> None:
        await asyncio.sleep(8)
        if not stop_event.is_set():
            logger.warning("Edit farewell timeout — forcing session end")
            stop_event.set()

    def _start_farewell_timeout() -> None:
        t = farewell_timeout_task[0]
        if not t or t.done():
            farewell_timeout_task[0] = asyncio.create_task(_farewell_timeout())

    def _cancel_farewell_timeout() -> None:
        t = farewell_timeout_task[0]
        if t and not t.done():
            t.cancel()

    async def _send_json(data: dict) -> None:
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            pass

    async def _send_bytes(data: bytes) -> None:
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    try:
        async with client.aio.live.connect(model=MODEL_ID, config=config) as gemini:

            async def browser_to_gemini() -> None:
                while not stop_event.is_set():
                    try:
                        msg = await asyncio.wait_for(websocket.receive(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        stop_event.set()
                        return

                    if msg.get("type") == "websocket.disconnect":
                        stop_event.set()
                        return

                    audio_bytes = msg.get("bytes")
                    if audio_bytes:
                        try:
                            await gemini.send_realtime_input(
                                media=types.Blob(
                                    data=audio_bytes,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        except Exception as exc:
                            logger.warning("Gemini send error: %s", exc)

                    text_msg = msg.get("text")
                    if text_msg:
                        try:
                            ctrl = json.loads(text_msg)
                            if ctrl.get("type") == "end_session":
                                farewell_requested.set()
                                _start_farewell_timeout()
                                try:
                                    await gemini.send_client_content(
                                        turns=types.Content(
                                            role="user",
                                            parts=[types.Part.from_text(
                                                text="Please give a brief warm sign-off and end the session."
                                            )],
                                        ),
                                        turn_complete=True,
                                    )
                                except Exception as exc:
                                    logger.warning("Could not send farewell to Gemini: %s", exc)
                        except json.JSONDecodeError:
                            pass

            async def gemini_to_browser() -> None:
                LISTENING_DELAY_S = 1.5

                user_buf: list[str] = []
                model_buf: list[str] = []
                ai_spoke_this_turn = False
                _listening_task: asyncio.Task | None = None

                async def _deferred_listening() -> None:
                    await asyncio.sleep(LISTENING_DELAY_S)
                    if not stop_event.is_set():
                        await _send_json({"type": "state", "value": "listening"})

                try:
                    while not stop_event.is_set():
                        async for message in gemini.receive():
                            if stop_event.is_set():
                                return

                            sc = message.server_content
                            if not sc:
                                continue

                            if sc.input_transcription and sc.input_transcription.text:
                                user_buf.append(sc.input_transcription.text)

                            if sc.output_transcription and sc.output_transcription.text:
                                model_buf.append(sc.output_transcription.text)

                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        if not ai_spoke_this_turn:
                                            if _listening_task and not _listening_task.done():
                                                _listening_task.cancel()
                                        ai_spoke_this_turn = True
                                        await _send_json({"type": "state", "value": "speaking"})
                                        await _send_bytes(part.inline_data.data)

                            if sc.turn_complete:
                                if user_buf:
                                    user_text = " ".join(user_buf).strip()
                                    if user_text:
                                        transcript_log.append(("You", user_text))
                                        await _send_json({
                                            "type": "transcript",
                                            "speaker": "user",
                                            "text": user_text,
                                        })
                                        if any(kw in user_text.lower() for kw in END_KEYWORDS):
                                            farewell_requested.set()
                                            _start_farewell_timeout()
                                    user_buf.clear()

                                if model_buf:
                                    model_text = " ".join(model_buf).strip()
                                    if model_text:
                                        transcript_log.append(("Editor", model_text))
                                        await _send_json({
                                            "type": "transcript",
                                            "speaker": "ai",
                                            "text": model_text,
                                        })
                                    model_buf.clear()

                                if farewell_requested.is_set() and ai_spoke_this_turn:
                                    if _listening_task and not _listening_task.done():
                                        _listening_task.cancel()
                                    _cancel_farewell_timeout()
                                    stop_event.set()
                                    await _send_json({"type": "state", "value": "processing"})
                                    return

                                if ai_spoke_this_turn:
                                    if _listening_task and not _listening_task.done():
                                        _listening_task.cancel()
                                    _listening_task = asyncio.create_task(_deferred_listening())

                                ai_spoke_this_turn = False
                                break

                except Exception as exc:
                    logger.error("gemini_to_browser error: %s", exc)
                    stop_event.set()

            await asyncio.gather(browser_to_gemini(), gemini_to_browser())

    except Exception as exc:
        logger.exception("Edit conversation error for session %s: %s", session_id, exc)
        await _send_json({"type": "error", "message": str(exc)})
        return

    # ---------------------------------------------------------------------------
    # Save edit transcript to session state
    # ---------------------------------------------------------------------------
    if transcript_log:
        full_transcript = _format_transcript(transcript_log)
        state_path = session_dir(session_id) / "story_state.json"

        if state_path.exists():
            state = StoryState.load(state_path)
        else:
            state = StoryState(session_id=session_id)

        state.edit_conversation_transcript = full_transcript
        state.save(state_path)
        logger.info(
            "Edit conversation transcript saved for session %s (%d turns)",
            session_id,
            len(transcript_log),
        )

    await _send_json({"type": "session_end"})
