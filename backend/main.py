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
    Request,
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
from backend.db.database import init_db, SessionLocal
from backend.db import crud as db_crud
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return 500 with error detail so the frontend can show a useful message."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Internal server error"},
    )


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Database tables created / verified")


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
        # Persist session row in Postgres
        try:
            db = SessionLocal()
            db_crud.upsert_session(db, session_id, "idle")
            db.close()
        except Exception as exc:
            logger.warning("DB upsert_session failed: %s", exc)
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
    try:
        sid = uuid.uuid4().hex
        _get_or_create_session(sid)
        logger.info("Conversation session created: %s", sid)
        return ConversationStartResponse(session_id=sid)
    except Exception as exc:
        logger.exception("start_conversation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


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
        # Try loading from disk so a page-refresh doesn't lose the session
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state
    return JSONResponse({
        "session_id": session_id,
        "status": state.status.value,
        "steps": [s.model_dump() for s in state.steps],
        "errors": state.errors,
        "final_video_path": state.final_video_path,
        "has_video": bool(state.final_video_path),
        "video_failed_keys": state.failed_video_keys,
    })


# ---------------------------------------------------------------------------
# GET /api/story/{session_id}/state
# ---------------------------------------------------------------------------

@app.get("/api/story/{session_id}/state")
async def get_state(session_id: str) -> JSONResponse:
    """Return the full StoryState JSON."""
    if session_id not in _sessions:
        # Try loading from disk so a page-refresh doesn't lose the session
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state
    data = state.to_dict()

    # Inject a derived title and premise for the frontend carousel/story screen.
    # StoryBreakdown has no explicit title field — derive one from the characters
    # and the first scene text so the UI always has something meaningful to show.
    if state.breakdown and "breakdown" in data and data["breakdown"]:
        bd = data["breakdown"]
        # Build a short title from character names (e.g. "Laptop & TV")
        chars = state.breakdown.characters_prompts
        if chars:
            names = [c.name for c in chars[:2]]
            bd["title"] = " & ".join(names) if len(names) > 1 else names[0]
        else:
            bd["title"] = "Your Masterpiece"
        # Use the first scene paragraph as the premise/description
        if state.breakdown.story:
            bd["premise"] = state.breakdown.story[0][:160].rstrip() + ("…" if len(state.breakdown.story[0]) > 160 else "")

    return JSONResponse(data)


# ---------------------------------------------------------------------------
# GET /api/story/{session_id}/video
# ---------------------------------------------------------------------------

@app.get("/api/story/{session_id}/video", response_model=None)
async def get_video(session_id: str):
    """
    Return a JSON response with the video URL and version number.

    If the video file exists on disk, the URL points to the local streaming
    endpoint (/api/story/{session_id}/video/stream).  Otherwise a MinIO
    presigned URL is returned.
    """
    if session_id not in _sessions:
        # Try loading from disk so a page-refresh doesn't lose the session
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state
    if not state.final_video_path:
        raise HTTPException(status_code=404, detail="Final video not yet available")

    video_path = Path(state.final_video_path)
    video_version = len(state.edit_history) + 1

    # If the file is on disk, point to the local streaming endpoint
    if video_path.exists():
        return JSONResponse({
            "video_url": f"/api/story/{session_id}/video/stream",
            "version": video_version,
        })

    # Fall back to MinIO presigned URL
    from backend.utils.minio_client import presigned_url, session_object_key, object_exists_sync
    minio_key = session_object_key(session_id, "final/story.mp4")
    if object_exists_sync(minio_key):
        url = await presigned_url(minio_key)
        return JSONResponse({"video_url": url, "version": video_version})

    raise HTTPException(status_code=404, detail="Video file not found")


@app.get("/api/story/{session_id}/video/stream", response_model=None)
async def stream_video(session_id: str):
    """Serve the compiled MP4 directly as a binary stream."""
    if session_id not in _sessions:
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
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
        filename=video_path.name,
    )


# ---------------------------------------------------------------------------
# GET /api/story/{session_id}/thumbnail
# ---------------------------------------------------------------------------

@app.get("/api/story/{session_id}/thumbnail", response_model=None)
async def get_thumbnail(session_id: str):
    """
    Return a thumbnail image URL for the session.

    Tries scene_1_sub_1.png first, then falls back to the first available
    scene image.  Serves from local disk when available, otherwise returns
    a MinIO presigned URL.
    """
    if session_id not in _sessions:
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    state: StoryState = _sessions[session_id]["orchestrator"].state

    # Pick the best available scene image: prefer scene_1_sub_1, then any
    preferred_keys = ["scene_1_sub_1", "scene_1_sub_2", "scene_1_sub_3"]
    image_path_str: str | None = None
    for key in preferred_keys:
        if key in state.scene_image_paths:
            image_path_str = state.scene_image_paths[key]
            break
    if not image_path_str and state.scene_image_paths:
        image_path_str = next(iter(state.scene_image_paths.values()))

    if not image_path_str:
        raise HTTPException(status_code=404, detail="No scene images available yet")

    # Serve from local disk if available
    img_path = Path(image_path_str)
    if img_path.exists():
        return FileResponse(path=str(img_path), media_type="image/png")

    # Fall back to MinIO
    from backend.utils.minio_client import presigned_url, session_object_key, object_exists_sync
    minio_key = session_object_key(session_id, f"scenes/{img_path.name}")
    if object_exists_sync(minio_key):
        url = await presigned_url(minio_key)
        return JSONResponse({"thumbnail_url": url})

    raise HTTPException(status_code=404, detail="Thumbnail image not found")


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

    # Record edit in Postgres
    try:
        db = SessionLocal()
        db_crud.record_edit(db, session_id, request.message, reasoning, sorted(dirty_keys))
        db.close()
    except Exception as exc:
        logger.warning("DB record_edit failed: %s", exc)

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
# POST /api/story/{session_id}/retry
# ---------------------------------------------------------------------------

@app.post("/api/story/{session_id}/retry", response_model=GenerateResponse)
async def retry_failed_scenes(session_id: str) -> GenerateResponse:
    """
    Re-run only the failed or skipped steps from the last pipeline run.

    Already-completed steps (scene images, videos, narration, etc.) are
    not regenerated — the orchestrator's skip-if-exists guard ensures that
    any file already on disk is reused.  Only steps whose status is
    'failed' or 'skipped' are retried, plus the final compile if the video
    is missing.
    """
    if session_id not in _sessions:
        # Try loading from disk so a page-refresh doesn't lose the session
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    session = _sessions[session_id]
    orch: StoryOrchestrator = session["orchestrator"]

    if orch.state.status == PipelineStatus.RUNNING:
        raise HTTPException(
            status_code=409, detail="Pipeline is still running. Wait for it to finish."
        )

    # Derive dirty_keys from steps that failed or were skipped
    dirty_keys: set[str] = {
        s.step for s in orch.state.steps
        if s.status in ("failed", "skipped")
    }

    # Always include compile if the final video is missing
    if not orch.state.final_video_path:
        dirty_keys.add("final_video")

    if not dirty_keys:
        raise HTTPException(status_code=400, detail="No failed or skipped steps to retry.")

    # Clear previous errors and failed keys so the UI shows a clean state
    orch.state.errors = []
    orch.state.failed_video_keys = []

    # Cancel any previous background task
    if session["task"] and not session["task"].done():
        session["task"].cancel()

    async def _run_retry():
        await orch.run_selective(dirty_keys)

    session["task"] = asyncio.create_task(_run_retry())
    logger.info(
        "Retry started for session %s. Retrying %d key(s): %s",
        session_id,
        len(dirty_keys),
        sorted(dirty_keys),
    )
    return GenerateResponse(session_id=session_id)


# ---------------------------------------------------------------------------
# POST /api/story/{session_id}/recompile
# ---------------------------------------------------------------------------

@app.post("/api/story/{session_id}/recompile", response_model=GenerateResponse)
async def recompile_video(session_id: str) -> GenerateResponse:
    """Re-run only the compile step (ffmpeg assembly) without regenerating any assets."""
    if session_id not in _sessions:
        state_path = session_dir(session_id) / "story_state.json"
        if state_path.exists():
            _get_or_create_session(session_id)
            from backend.pipeline.state import StoryState as _SS
            saved = _SS.load(state_path)
            _sessions[session_id]["orchestrator"].state = saved
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    session = _sessions[session_id]
    orch: StoryOrchestrator = session["orchestrator"]

    if orch.state.status == PipelineStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Pipeline is still running.")

    if session["task"] and not session["task"].done():
        session["task"].cancel()

    async def _run_recompile():
        await orch.run_selective({"final_video"})

    session["task"] = asyncio.create_task(_run_recompile())
    logger.info("Recompile started for session %s", session_id)
    return GenerateResponse(session_id=session_id)


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
    selective regeneration on a **cloned** session so the original is preserved.

    Returns the new clone's session_id so the frontend navigates to it.
    """
    import shutil

    # Ensure original session is loaded
    state_path = session_dir(session_id) / "story_state.json"
    if session_id not in _sessions:
        if state_path.exists():
            _get_or_create_session(session_id)
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    # Reload from disk to pick up edit_conversation_transcript
    if state_path.exists():
        from backend.pipeline.state import StoryState as _SS
        saved = _SS.load(state_path)
        _sessions[session_id]["orchestrator"].state = saved

    orig_state = _sessions[session_id]["orchestrator"].state

    if orig_state.status == PipelineStatus.RUNNING:
        raise HTTPException(
            status_code=409, detail="Pipeline is still running. Wait for it to finish."
        )

    if orig_state.breakdown is None:
        raise HTTPException(
            status_code=400, detail="Story has not been generated yet."
        )

    # Resolve transcript
    transcript = request.transcript or orig_state.edit_conversation_transcript
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="No edit transcript available. Complete an edit conversation first.",
        )

    # --- Clone the session directory so the original is preserved ---
    version = len(orig_state.edit_history) + 2  # v2 for first edit, v3 for second, etc.
    clone_id = f"{session_id}_v{version}"
    orig_dir = session_dir(session_id)
    clone_dir = orig_dir.parent / clone_id

    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    shutil.copytree(str(orig_dir), str(clone_dir))
    logger.info("Cloned session %s → %s", session_id, clone_id)

    # Create orchestrator for the clone and update its session_id + file paths
    clone_session = _get_or_create_session(clone_id)
    clone_orch: StoryOrchestrator = clone_session["orchestrator"]
    clone_state_path = session_dir(clone_id) / "story_state.json"
    if clone_state_path.exists():
        from backend.pipeline.state import StoryState as _SS
        clone_state = _SS.load(clone_state_path)
        clone_state.session_id = clone_id

        # Rewrite absolute paths so they point to the clone directory
        orig_id_segment = f"/{session_id}/"
        clone_id_segment = f"/{clone_id}/"
        def _rewrite(p: str) -> str:
            return p.replace(orig_id_segment, clone_id_segment) if p else p
        clone_state.narration_paths = {k: _rewrite(v) for k, v in clone_state.narration_paths.items()}
        clone_state.character_image_paths = {k: _rewrite(v) for k, v in clone_state.character_image_paths.items()}
        clone_state.scene_image_paths = {k: _rewrite(v) for k, v in clone_state.scene_image_paths.items()}
        clone_state.scene_video_paths = {k: _rewrite(v) for k, v in clone_state.scene_video_paths.items()}
        if clone_state.final_video_path:
            clone_state.final_video_path = _rewrite(clone_state.final_video_path)

        clone_orch.state = clone_state

    # Plan the edit on the clone
    updated_state, dirty_keys = await plan_edit(transcript, clone_orch.state)

    clone_orch.state = updated_state
    clone_orch.state.session_id = clone_id
    clone_orch._save()

    reasoning = ""
    if updated_state.edit_history:
        reasoning = updated_state.edit_history[-1].get("reasoning", "")

    # Record edit in Postgres
    try:
        db = SessionLocal()
        db_crud.record_edit(db, clone_id, transcript[:500], reasoning, sorted(dirty_keys))
        db.close()
    except Exception as exc:
        logger.warning("DB record_edit failed: %s", exc)

    if clone_session["task"] and not clone_session["task"].done():
        clone_session["task"].cancel()

    async def _run_edit():
        await clone_orch.run_selective(dirty_keys)

    clone_session["task"] = asyncio.create_task(_run_edit())
    logger.info(
        "Edit-from-transcript started for clone %s (from %s). Dirty keys (%d): %s",
        clone_id,
        session_id,
        len(dirty_keys),
        sorted(dirty_keys),
    )

    return EditFromTranscriptResponse(
        session_id=clone_id,
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
# Page tracking
# ---------------------------------------------------------------------------

class TrackPageRequest(BaseModel):
    page: str                    # LANDING | CONVERSATION | PROCESSING | RESULT
    session_id: str | None = None


@app.post("/api/track")
async def track_page(request: TrackPageRequest) -> JSONResponse:
    """Record that a user navigated to a page."""
    db = SessionLocal()
    try:
        row = db_crud.track_page_view(db, request.session_id, request.page)
        logger.info("Page view: %s → %s", request.session_id or "anonymous", request.page)
        return JSONResponse({
            "id": row.id,
            "session_id": row.session_id,
            "page": row.page,
        })
    finally:
        db.close()


@app.get("/api/track")
async def get_tracking(session_id: str | None = None) -> JSONResponse:
    """Get page view history (optionally filtered by session_id)."""
    db = SessionLocal()
    try:
        rows = db_crud.get_page_views(db, session_id)
        return JSONResponse([
            {"id": r.id, "session_id": r.session_id, "page": r.page, "created_at": str(r.created_at)}
            for r in rows
        ])
    finally:
        db.close()


@app.get("/api/track/{session_id}/current")
async def get_current(session_id: str) -> JSONResponse:
    """Get the current page for a session."""
    db = SessionLocal()
    try:
        page = db_crud.get_current_page(db, session_id)
        return JSONResponse({"session_id": session_id, "current_page": page})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/stories  — list all sessions that have a final video
# ---------------------------------------------------------------------------

@app.get("/api/stories")
async def list_stories() -> JSONResponse:
    """
    Return metadata for every session that has a completed final video,
    ordered newest first.  Used by the landing-page carousel so it can
    populate itself from real data instead of relying on localStorage.

    Each item:
      { id, title, desc, version, thumbnail_url, video_url }
    """
    from backend.config import SESSIONS_DIR
    from backend.pipeline.state import StoryState as _SS

    results = []

    for state_path in sorted(SESSIONS_DIR.glob("*/story_state.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        session_id = state_path.parent.name
        try:
            state = _SS.load(state_path)
        except Exception:
            continue

        if not state.final_video_path:
            continue

        if not Path(state.final_video_path).exists():
            continue

        video_version = len(state.edit_history) + 1

        # Derive title + desc the same way get_state() does
        title = "Your Masterpiece"
        desc = ""
        if state.breakdown:
            chars = state.breakdown.characters_prompts
            if chars:
                names = [c.name for c in chars[:2]]
                title = " & ".join(names) if len(names) > 1 else names[0]
            if state.breakdown.story:
                first = state.breakdown.story[0]
                desc = first[:160].rstrip() + ("…" if len(first) > 160 else "")

        results.append({
            "id": session_id,
            "title": title,
            "desc": desc,
            "version": video_version,
            "thumbnail_url": f"/api/story/{session_id}/thumbnail",
            "video_url": f"/api/story/{session_id}/video",
        })

    return JSONResponse(results)


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
