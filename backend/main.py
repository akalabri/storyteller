"""
FastAPI server for the Storyteller backend.

Endpoints
─────────
POST /api/story/generate
    Start a new story generation pipeline.
    Body: { "session_id": str (optional), "conversation_transcript": str }
    Returns: { "session_id": str }

GET /api/story/{session_id}/status
    Poll the current pipeline status and step progress.

WS /ws/{session_id}
    WebSocket — streams ProgressEvent JSON objects in real time.

GET /api/story/{session_id}/state
    Return the full StoryState JSON.

GET /api/story/{session_id}/video
    Stream the final compiled video (MP4).

POST /api/story/{session_id}/edit
    Submit a conversational edit request.
    Body: { "message": str }
    Returns: { "session_id": str, "dirty_keys": [...], "reasoning": str }

DELETE /api/story/{session_id}
    Remove a session and all its artifacts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.agents.conversation_agent import run_live_conversation
from backend.agents.edit_conversation_agent import run_edit_conversation
from backend.agents.edit_agent import plan_edit
from backend.config import DEV_MODE, DEV_SESSION_ID, DEV_STEPS, session_dir
from backend.pipeline.orchestrator import ProgressEvent, StoryOrchestrator
from backend.pipeline.state import PipelineStatus, StoryState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(title="Storyteller API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory session registry
# Sessions are keyed by session_id and hold:
#   - orchestrator:  StoryOrchestrator
#   - progress_queue: asyncio.Queue[ProgressEvent]
#   - task: asyncio.Task (the running pipeline)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}


def _get_or_create_session(session_id: str) -> dict[str, Any]:
    if session_id not in _sessions:
        q: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        orch = StoryOrchestrator(session_id=session_id, progress_queue=q)
        _sessions[session_id] = {
            "orchestrator": orch,
            "progress_queue": q,
            "task": None,
        }
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ConversationStartResponse(BaseModel):
    session_id: str


class GenerateRequest(BaseModel):
    session_id: str | None = None
    # Optional: if the session already has a saved transcript (from live voice
    # conversation), this field can be omitted.
    conversation_transcript: str | None = None


class GenerateResponse(BaseModel):
    session_id: str


class EditRequest(BaseModel):
    message: str


class EditResponse(BaseModel):
    session_id: str
    dirty_keys: list[str]
    reasoning: str


class EditConversationStartResponse(BaseModel):
    session_id: str


class EditFromTranscriptRequest(BaseModel):
    # Optional override — if omitted, the saved edit_conversation_transcript is used
    transcript: str | None = None


class EditFromTranscriptResponse(BaseModel):
    session_id: str
    dirty_keys: list[str]
    reasoning: str


# ---------------------------------------------------------------------------
# POST /api/story/generate
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# POST /api/conversation/start
# ---------------------------------------------------------------------------

@app.post("/api/conversation/start", response_model=ConversationStartResponse)
async def start_conversation() -> ConversationStartResponse:
    """
    Create a new session for a live voice conversation.
    Returns the session_id that the frontend uses for the conversation WebSocket
    and, later, for the generation pipeline.
    """
    sid = uuid.uuid4().hex
    _get_or_create_session(sid)
    logger.info("Conversation session created: %s", sid)
    return ConversationStartResponse(session_id=sid)


# ---------------------------------------------------------------------------
# WS /ws/conversation/{session_id}
# ---------------------------------------------------------------------------

@app.websocket("/ws/conversation/{session_id}")
async def conversation_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Real-time voice conversation bridge.

    Binary frames (browser → backend): PCM audio, 16 kHz, Int16, mono.
    Binary frames (backend → browser): PCM audio, 24 kHz, Int16, mono (AI voice).
    Text frames   (backend → browser): JSON control events.

    See backend/agents/conversation_agent.py for the full protocol.
    """
    await websocket.accept()
    logger.info("Conversation WS connected: %s", session_id)
    try:
        await run_live_conversation(session_id, websocket)
    except Exception as exc:
        logger.exception("Conversation WS error for %s: %s", session_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("Conversation WS closed: %s", session_id)


# ---------------------------------------------------------------------------
# POST /api/story/generate
# ---------------------------------------------------------------------------

@app.post("/api/story/generate", response_model=GenerateResponse)
async def generate_story(request: GenerateRequest) -> GenerateResponse:
    """
    Start a new story generation pipeline in the background.

    The conversation_transcript can be omitted when the session already has
    a saved transcript from a prior live voice conversation.
    """
    sid = request.session_id or uuid.uuid4().hex
    session = _get_or_create_session(sid)
    orch: StoryOrchestrator = session["orchestrator"]

    # Resolve transcript: body takes priority, then fall back to saved state
    transcript = request.conversation_transcript
    if not transcript and orch.state.conversation_transcript:
        transcript = orch.state.conversation_transcript
    if not transcript:
        # Last resort: load from disk (session may have been created by conv WS)
        state_path = session_dir(sid) / "story_state.json"
        if state_path.exists():
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            transcript = saved.conversation_transcript
            # Sync the orchestrator state
            orch.state = saved

    if not transcript and DEV_MODE:
        # In dev mode, load the transcript from the dev session automatically.
        from backend.config import SESSIONS_DIR
        dev_state_path = SESSIONS_DIR / DEV_SESSION_ID / "story_state.json"
        if dev_state_path.exists():
            from backend.pipeline.state import StoryState as _SS2
            dev_saved = _SS2.load(dev_state_path)
            transcript = dev_saved.conversation_transcript
            logger.info("DEV_MODE: loaded transcript from dev session '%s'", DEV_SESSION_ID)

    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="No conversation transcript available. "
                   "Either provide conversation_transcript in the body or complete a voice conversation first.",
        )

    # Cancel any previous task
    if session["task"] and not session["task"].done():
        session["task"].cancel()

    async def _run():
        await orch.run_full_pipeline(transcript)

    session["task"] = asyncio.create_task(_run())
    logger.info("Pipeline started for session %s", sid)
    return GenerateResponse(session_id=sid)


# ---------------------------------------------------------------------------
# GET /api/story/{session_id}/status
# ---------------------------------------------------------------------------

@app.get("/api/story/{session_id}/status")
async def get_status(session_id: str) -> JSONResponse:
    """Return the current pipeline status and step progress."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state
    return JSONResponse({
        "session_id": session_id,
        "status": state.status.value,
        "steps": [s.model_dump() for s in state.steps],
        "errors": state.errors,
        "final_video_path": state.final_video_path,
    })


# ---------------------------------------------------------------------------
# GET /api/story/{session_id}/state
# ---------------------------------------------------------------------------

@app.get("/api/story/{session_id}/state")
async def get_state(session_id: str) -> JSONResponse:
    """Return the full StoryState JSON."""
    if session_id not in _sessions:
        # Try loading from disk
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            session = _get_or_create_session(session_id)
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state
    return JSONResponse(state.to_dict())


# ---------------------------------------------------------------------------
# GET /api/story/{session_id}/video
# ---------------------------------------------------------------------------

@app.get("/api/story/{session_id}/video")
async def get_video(session_id: str) -> FileResponse:
    """Stream the final compiled MP4 video."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state
    if not state.final_video_path:
        raise HTTPException(status_code=404, detail="Final video not yet available")

    video_path = Path(state.final_video_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename="story.mp4",
    )


# ---------------------------------------------------------------------------
# POST /api/story/{session_id}/edit
# ---------------------------------------------------------------------------

@app.post("/api/story/{session_id}/edit", response_model=EditResponse)
async def edit_story(session_id: str, request: EditRequest) -> EditResponse:
    """
    Submit a conversational edit request.

    This call is synchronous (waits for the edit plan to be computed) but
    the selective regeneration pipeline runs in the background.
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = _sessions[session_id]
    orch: StoryOrchestrator = session["orchestrator"]
    state = orch.state

    if state.status == PipelineStatus.RUNNING:
        raise HTTPException(
            status_code=409, detail="Pipeline is still running. Wait for it to finish."
        )

    if state.breakdown is None:
        raise HTTPException(
            status_code=400, detail="Story has not been generated yet."
        )

    # Plan the edit (LLM call, awaited synchronously so we return reasoning)
    updated_state, dirty_keys = await plan_edit(request.message, state)

    # Update orchestrator state in place
    orch.state = updated_state
    orch._save()

    # Extract reasoning from last edit history entry
    reasoning = ""
    if updated_state.edit_history:
        reasoning = updated_state.edit_history[-1].get("reasoning", "")

    # Cancel any previous background task
    if session["task"] and not session["task"].done():
        session["task"].cancel()

    # Run selective regeneration in the background
    async def _run_edit():
        await orch.run_selective(dirty_keys)

    session["task"] = asyncio.create_task(_run_edit())
    logger.info(
        "Edit started for session %s. Dirty keys (%d): %s",
        session_id,
        len(dirty_keys),
        sorted(dirty_keys),
    )

    return EditResponse(
        session_id=session_id,
        dirty_keys=sorted(dirty_keys),
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# POST /api/edit-conversation/start
# ---------------------------------------------------------------------------

@app.post("/api/edit-conversation/start", response_model=EditConversationStartResponse)
async def start_edit_conversation(session_id: str | None = None) -> EditConversationStartResponse:
    """
    Prepare a session for an edit voice conversation.
    If session_id is provided (e.g. the dev session), that session is used as-is
    so the edit agent has access to the existing StoryState.
    Otherwise a new session id is created.
    """
    sid = session_id or uuid.uuid4().hex
    _get_or_create_session(sid)

    # If the session has a saved state on disk, load it into the orchestrator
    # so the edit agent can access breakdown / visual_plan context.
    state_path = session_dir(sid) / "story_state.json"
    if state_path.exists() and sid in _sessions:
        from backend.pipeline.state import StoryState as _SS
        saved = _SS.load(state_path)
        _sessions[sid]["orchestrator"].state = saved

    logger.info("Edit conversation session ready: %s", sid)
    return EditConversationStartResponse(session_id=sid)


# ---------------------------------------------------------------------------
# WS /ws/edit-conversation/{session_id}
# ---------------------------------------------------------------------------

@app.websocket("/ws/edit-conversation/{session_id}")
async def edit_conversation_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    Real-time edit consultation voice conversation bridge.

    Same audio/control protocol as /ws/conversation/{session_id} but uses the
    edit-focused system prompt. When the session ends, the transcript is saved
    to the session's StoryState.edit_conversation_transcript.
    """
    await websocket.accept()
    logger.info("Edit conversation WS connected: %s", session_id)
    try:
        await run_edit_conversation(session_id, websocket)
    except Exception as exc:
        logger.exception("Edit conversation WS error for %s: %s", session_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("Edit conversation WS closed: %s", session_id)


# ---------------------------------------------------------------------------
# POST /api/story/{session_id}/edit-from-transcript
# ---------------------------------------------------------------------------

@app.post("/api/story/{session_id}/edit-from-transcript", response_model=EditFromTranscriptResponse)
async def edit_from_transcript(
    session_id: str,
    request: EditFromTranscriptRequest,
) -> EditFromTranscriptResponse:
    """
    Process an edit conversation transcript through plan_edit and kick off
    selective regeneration.

    The transcript can be supplied in the request body, or omitted to use the
    saved edit_conversation_transcript from the session's StoryState.
    """
    # Ensure session is loaded
    state_path = session_dir(session_id) / "story_state.json"
    if session_id not in _sessions:
        if state_path.exists():
            _get_or_create_session(session_id)
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    # Always reload from disk so we pick up the edit_conversation_transcript
    # that was written by the edit conversation agent after the WS session ended.
    if state_path.exists():
        from backend.pipeline.state import StoryState as _SS
        saved = _SS.load(state_path)
        _sessions[session_id]["orchestrator"].state = saved

    session = _sessions[session_id]
    orch: StoryOrchestrator = session["orchestrator"]
    state = orch.state

    if state.status == PipelineStatus.RUNNING:
        raise HTTPException(
            status_code=409, detail="Pipeline is still running. Wait for it to finish."
        )

    if state.breakdown is None:
        raise HTTPException(
            status_code=400, detail="Story has not been generated yet."
        )

    # Resolve transcript
    transcript = request.transcript or state.edit_conversation_transcript
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="No edit transcript available. Complete an edit conversation first.",
        )

    # Plan the edit using the full conversation transcript as the edit message
    updated_state, dirty_keys = await plan_edit(transcript, state)

    orch.state = updated_state
    orch._save()

    reasoning = ""
    if updated_state.edit_history:
        reasoning = updated_state.edit_history[-1].get("reasoning", "")

    if session["task"] and not session["task"].done():
        session["task"].cancel()

    async def _run_edit():
        await orch.run_selective(dirty_keys)

    session["task"] = asyncio.create_task(_run_edit())
    logger.info(
        "Edit-from-transcript started for session %s. Dirty keys (%d): %s",
        session_id,
        len(dirty_keys),
        sorted(dirty_keys),
    )

    return EditFromTranscriptResponse(
        session_id=session_id,
        dirty_keys=sorted(dirty_keys),
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# DELETE /api/story/{session_id}
# ---------------------------------------------------------------------------

@app.delete("/api/story/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    """Cancel any running task and remove the session from memory."""
    session = _sessions.pop(session_id, None)
    if session:
        if session["task"] and not session["task"].done():
            session["task"].cancel()
    return JSONResponse({"deleted": session_id})


# ---------------------------------------------------------------------------
# WebSocket /ws/{session_id}
# ---------------------------------------------------------------------------

@app.websocket("/ws/{session_id}")
async def websocket_progress(websocket: WebSocket, session_id: str):
    """
    Real-time progress stream.

    The client receives JSON objects with the shape::

        {
            "step": "narration:1",
            "status": "done" | "running" | "failed" | "skipped",
            "message": "...",
            "data": {...}
        }

    The connection stays open until the pipeline finishes (status "done" or
    "error" on step "pipeline"), the client disconnects, or the server closes.
    """
    await websocket.accept()
    session = _get_or_create_session(session_id)
    q: asyncio.Queue[ProgressEvent] = session["progress_queue"]

    try:
        while True:
            # Drain the queue; timeout allows periodic keep-alive checks
            try:
                event: ProgressEvent = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Keep-alive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue

            payload = json.dumps(event.to_dict())
            await websocket.send_text(payload)

            # Close gracefully when pipeline finishes
            if (
                event.step == "pipeline"
                and event.status in ("done", "error")
            ):
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception as exc:
        logger.exception("WebSocket error for session %s: %s", session_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GET /api/dev-mode
# ---------------------------------------------------------------------------

@app.get("/api/dev-mode")
async def get_dev_mode() -> JSONResponse:
    """
    Return the current dev mode configuration so the frontend can adapt its
    UI (e.g. skip the conversation step when DEV_MODE is enabled).
    """
    return JSONResponse({
        "dev_mode": DEV_MODE,
        "dev_session_id": DEV_SESSION_ID if DEV_MODE else None,
        "dev_steps": sorted(DEV_STEPS) if DEV_MODE else [],
    })


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        # Only watch backend source files — never sessions/, frontend/, etc.
        # Without this, saving story_state.json restarts the server mid-pipeline.
        reload_dirs=["backend"],
    )
