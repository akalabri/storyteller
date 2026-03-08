"""
Conversation agent — bridges a browser WebSocket to a Gemini Live session.

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

When the conversation ends (END_KEYWORDS detected or browser sends end_session),
the full transcript is saved to StoryState.conversation_transcript so that
POST /api/story/generate can start the pipeline immediately without a body transcript.
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

END_KEYWORDS = [
    "goodbye", "good bye", "bye bye", "that's all", "thats all",
    "we're done", "were done", "i'm done", "im done",
    "we are done", "that's enough", "thats enough",
    "end session", "let's create it", "let's make it",
    "go ahead and create", "you can create", "create the story",
    "thank you that's all", "thanks that's all",
    "yes please", "yes go ahead", "sounds good let's go",
]

SYSTEM_PROMPT = """You are a warm, imaginative story consultant. Your sole purpose in this conversation is to gather everything needed to create a wonderful personalized story — you will NOT tell or narrate the story yourself. A separate system will generate the actual story after this conversation ends.

Begin by greeting the user warmly and with genuine curiosity. You are not conducting an interview; you are having a real, flowing conversation. Through that conversation, naturally uncover:

- The kind of story they'd enjoy — genre and mood (e.g. funny, mysterious, educational, romantic, adventurous, heartwarming, fantasy, etc.)
- The world or setting of the story
- Characters they have in mind — names, personalities, relationships, appearances
- Specific details they care about — clothing, objects, special traits, cultural or language elements
- Any themes, messages, or lessons they want the story to carry
- The intended audience (e.g. young children, teenagers, adults) and any special context

Do NOT ask about these as a checklist. Let the conversation breathe. Follow their lead. React with genuine enthusiasm. Ask natural follow-up questions the way a curious friend would.

Once you feel you have a rich enough picture — you do not need every detail — summarize back what you've gathered in a warm, conversational way (e.g. "So we have a funny story set in an anime-style Arabic village, with Salem the clever cat and Hadi the honest goat, teaching kids about honesty — does that sound right?"). Invite them to add, change, or confirm anything.

When they confirm everything is good and they are ready, say something like "Perfect, I have everything I need to create your story! I'll get started on it now." — then end your response. The session will close automatically.

If the user signals they are done or happy with what's been collected (says things like "yes", "sounds good", "let's go", "go ahead", etc. after your summary), give a brief warm sign-off and end your response.

Important: Never narrate or tell the story itself. Your only job is to listen, explore, and collect."""


# ---------------------------------------------------------------------------
# Transcript formatting
# ---------------------------------------------------------------------------

def _format_transcript(log: list[tuple[str, str]]) -> str:
    lines = [
        f"Story Conversation — {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
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

async def run_live_conversation(session_id: str, websocket: WebSocket) -> None:
    """
    Open a Gemini Live session and bridge it to the browser WebSocket.

    Binary frames from the browser (PCM 16kHz Int16) are forwarded to Gemini.
    Gemini audio (PCM 24kHz Int16) is forwarded back as binary frames.
    Transcript and state events are sent as text JSON frames.

    When the session ends (farewell keyword or browser end_session message),
    the full transcript is saved to ``sessions/{session_id}/story_state.json``
    and a ``session_end`` event is sent to the browser.
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
    farewell_timeout_task: list[asyncio.Task | None] = [None]  # mutable cell

    async def _farewell_timeout() -> None:
        """Force-close the session if farewell takes too long (8 s)."""
        await asyncio.sleep(8)
        if not stop_event.is_set():
            logger.warning("Farewell timeout — forcing session end")
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
        """Send a JSON control frame to the browser (best-effort)."""
        try:
            await websocket.send_text(json.dumps(data))
        except Exception:
            pass

    async def _send_bytes(data: bytes) -> None:
        """Send a binary audio frame to the browser (best-effort)."""
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    try:
        async with client.aio.live.connect(model=MODEL_ID, config=config) as gemini:

            async def browser_to_gemini() -> None:
                """Read PCM audio + control frames from browser WS → forward to Gemini."""
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
                                # Ask Gemini to say goodbye, then we'll shut down
                                # after it finishes speaking (handled in receiver).
                                farewell_requested.set()
                                _start_farewell_timeout()
                                try:
                                    await gemini.send_client_content(
                                        turns=types.Content(
                                            role="user",
                                            parts=[types.Part.from_text(
                                                text="Please give a warm, brief sign-off and end the session."
                                            )],
                                        ),
                                        turn_complete=True,
                                    )
                                except Exception as exc:
                                    logger.warning("Could not send farewell to Gemini: %s", exc)
                        except json.JSONDecodeError:
                            pass

            async def gemini_to_browser() -> None:
                """Receive from Gemini → forward audio + control events to browser.

                Gemini Live streams a response as a sequence of messages, each
                carrying a chunk of audio / transcription, terminated by a single
                turn_complete message.  session.receive() is an async generator
                that exhausts after that turn_complete — the outer while loop
                re-calls it so we keep receiving across all conversation turns.

                We track whether the AI actually produced output in a turn so we
                don't flash "Listening" between intermediate turn_complete events
                that carry no model content (Gemini sometimes emits these).

                When telling a long story Gemini splits its response across
                multiple consecutive turns.  We delay the "listening" state
                signal by a short window (LISTENING_DELAY_S) so that if a new
                speaking turn starts immediately we never falsely tell the
                browser to switch to listening mode mid-story.
                """
                LISTENING_DELAY_S = 1.5  # seconds to wait before declaring "listening"

                user_buf: list[str] = []
                model_buf: list[str] = []
                ai_spoke_this_turn = False  # did the AI produce audio/text this turn?
                # Task that fires the deferred "listening" signal; cancelled if AI
                # starts speaking again before the delay expires.
                _listening_task: asyncio.Task | None = None

                async def _deferred_listening() -> None:
                    """Send 'listening' after a short pause (cancellable)."""
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

                            # ── Accumulate transcripts ────────────────────
                            if sc.input_transcription and sc.input_transcription.text:
                                user_buf.append(sc.input_transcription.text)

                            if sc.output_transcription and sc.output_transcription.text:
                                model_buf.append(sc.output_transcription.text)

                            # ── Forward AI audio + mark that AI is speaking ─
                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        if not ai_spoke_this_turn:
                                            # Cancel any pending "listening" signal —
                                            # the AI is speaking again immediately.
                                            if _listening_task and not _listening_task.done():
                                                _listening_task.cancel()
                                        ai_spoke_this_turn = True
                                        await _send_json({"type": "state", "value": "speaking"})
                                        await _send_bytes(part.inline_data.data)

                            # ── Turn boundary ─────────────────────────────
                            if sc.turn_complete:
                                # Flush user transcript
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

                                # Flush AI transcript
                                if model_buf:
                                    model_text = " ".join(model_buf).strip()
                                    if model_text:
                                        transcript_log.append(("Storyteller", model_text))
                                        await _send_json({
                                            "type": "transcript",
                                            "speaker": "ai",
                                            "text": model_text,
                                        })
                                    model_buf.clear()

                                # Farewell: shut down after AI finishes speaking
                                if farewell_requested.is_set() and ai_spoke_this_turn:
                                    if _listening_task and not _listening_task.done():
                                        _listening_task.cancel()
                                    _cancel_farewell_timeout()
                                    stop_event.set()
                                    await _send_json({"type": "state", "value": "processing"})
                                    return

                                # Only schedule "listening" when the AI actually
                                # finished a real speaking turn.  Gemini can emit
                                # bare turn_complete with no audio (e.g. after user
                                # speech detection) — skip those.
                                # The deferred task is cancelled if the AI starts
                                # another turn immediately (multi-turn story telling).
                                if ai_spoke_this_turn:
                                    if _listening_task and not _listening_task.done():
                                        _listening_task.cancel()
                                    _listening_task = asyncio.create_task(_deferred_listening())

                                ai_spoke_this_turn = False
                                # Break inner loop → outer while re-calls receive()
                                break

                except Exception as exc:
                    logger.error("gemini_to_browser error: %s", exc)
                    stop_event.set()

            await asyncio.gather(browser_to_gemini(), gemini_to_browser())

    except Exception as exc:
        logger.exception("Live conversation error for session %s: %s", session_id, exc)
        await _send_json({"type": "error", "message": str(exc)})
        return

    # ---------------------------------------------------------------------------
    # Save transcript to session state
    # ---------------------------------------------------------------------------
    if transcript_log:
        full_transcript = _format_transcript(transcript_log)
        state_path = session_dir(session_id) / "story_state.json"

        if state_path.exists():
            state = StoryState.load(state_path)
        else:
            state = StoryState(session_id=session_id)

        state.conversation_transcript = full_transcript
        state.save(state_path)
        logger.info(
            "Conversation transcript saved for session %s (%d turns)",
            session_id,
            len(transcript_log),
        )

    await _send_json({"type": "session_end"})
