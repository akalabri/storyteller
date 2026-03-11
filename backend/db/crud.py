"""
Simple CRUD helpers for the storyteller database.

Every function takes an explicit db session — no global state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from backend.db import models

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def upsert_session(db: DBSession, session_id: str, status: str = "idle") -> models.Session:
    row = db.query(models.Session).filter_by(id=session_id).first()
    if row:
        row.status = status
        row.updated_at = _now()
    else:
        row = models.Session(id=session_id, status=status)
        db.add(row)
    db.commit()
    return row


def update_session_status(db: DBSession, session_id: str, status: str) -> None:
    row = db.query(models.Session).filter_by(id=session_id).first()
    if row:
        row.status = status
        row.updated_at = _now()
        db.commit()


# ---------------------------------------------------------------------------
# conversations
# ---------------------------------------------------------------------------

def save_conversation(db: DBSession, session_id: str, transcript: str) -> models.Conversation:
    row = db.query(models.Conversation).filter_by(session_id=session_id).first()
    if row:
        row.transcript = transcript
    else:
        row = models.Conversation(session_id=session_id, transcript=transcript)
        db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# stories / scenes / characters / props / subscenes
# ---------------------------------------------------------------------------

def save_story_breakdown(
    db: DBSession,
    session_id: str,
    breakdown,  # StoryBreakdown from state.py
) -> None:
    """Persist the full story breakdown (story, characters, props) to Postgres."""

    # -- story --
    story = db.query(models.Story).filter_by(session_id=session_id).first()
    if not story:
        story = models.Story(
            session_id=session_id,
            special_instructions=breakdown.special_instructions,
        )
        db.add(story)
    else:
        story.special_instructions = breakdown.special_instructions

    # -- scenes (delete + recreate for simplicity) --
    db.query(models.SubScene).filter(
        models.SubScene.scene_id.in_(
            db.query(models.Scene.id).filter_by(session_id=session_id)
        )
    ).delete(synchronize_session="fetch")
    db.query(models.Scene).filter_by(session_id=session_id).delete()

    for i, text in enumerate(breakdown.story, start=1):
        scene = models.Scene(session_id=session_id, scene_index=i, text=text)
        db.add(scene)

    # -- characters --
    db.query(models.Character).filter_by(session_id=session_id).delete()
    for cp in breakdown.characters_prompts:
        db.add(models.Character(
            session_id=session_id,
            name=cp.name,
            description=cp.description,
        ))

    # -- props --
    db.query(models.Prop).filter_by(session_id=session_id).delete()
    for p in breakdown.prop_descriptions:
        db.add(models.Prop(
            session_id=session_id,
            name=p.name,
            description=p.description,
        ))

    db.commit()


def save_visual_plan(db: DBSession, session_id: str, visual_plan) -> None:
    """Persist subscenes from the visual plan."""
    scenes = db.query(models.Scene).filter_by(session_id=session_id).order_by(models.Scene.scene_index).all()
    scene_map = {s.scene_index: s for s in scenes}

    for sp in visual_plan.scenes:
        scene = scene_map.get(sp.scene_index)
        if not scene:
            continue
        scene.summary = sp.scene_summary

        # Delete old subscenes for this scene
        db.query(models.SubScene).filter_by(scene_id=scene.id).delete()

        for sub in sp.subscenes:
            db.add(models.SubScene(
                scene_id=scene.id,
                sub_index=sub.index,
                image_prompt=sub.image_prompt,
                video_prompt=sub.video_prompt,
            ))

    db.commit()


def update_character_image(db: DBSession, session_id: str, name: str, minio_key: str) -> None:
    row = db.query(models.Character).filter_by(session_id=session_id, name=name).first()
    if row:
        row.image_minio_key = minio_key
        db.commit()


def update_narration_key(db: DBSession, session_id: str, scene_index: int, minio_key: str) -> None:
    row = db.query(models.Scene).filter_by(session_id=session_id, scene_index=scene_index).first()
    if row:
        row.narration_minio_key = minio_key
        db.commit()


def update_subscene_image(db: DBSession, session_id: str, scene_idx: int, sub_idx: int, minio_key: str) -> None:
    scene = db.query(models.Scene).filter_by(session_id=session_id, scene_index=scene_idx).first()
    if scene:
        sub = db.query(models.SubScene).filter_by(scene_id=scene.id, sub_index=sub_idx).first()
        if sub:
            sub.image_minio_key = minio_key
            db.commit()


def update_subscene_video(db: DBSession, session_id: str, scene_idx: int, sub_idx: int, minio_key: str) -> None:
    scene = db.query(models.Scene).filter_by(session_id=session_id, scene_index=scene_idx).first()
    if scene:
        sub = db.query(models.SubScene).filter_by(scene_id=scene.id, sub_index=sub_idx).first()
        if sub:
            sub.video_minio_key = minio_key
            db.commit()


# ---------------------------------------------------------------------------
# pipeline_steps
# ---------------------------------------------------------------------------

def record_step(
    db: DBSession,
    session_id: str,
    step: str,
    status: str,
    message: str = "",
) -> models.PipelineStep:
    now = _now()
    # If status is "running", it's a new step start
    if status == "running":
        row = models.PipelineStep(
            session_id=session_id, step=step, status=status,
            message=message, started_at=now,
        )
        db.add(row)
    else:
        # Update the most recent running entry for this step
        row = (
            db.query(models.PipelineStep)
            .filter_by(session_id=session_id, step=step, status="running")
            .order_by(models.PipelineStep.id.desc())
            .first()
        )
        if row:
            row.status = status
            row.message = message
            row.finished_at = now
        else:
            # No running entry — just insert
            row = models.PipelineStep(
                session_id=session_id, step=step, status=status,
                message=message, started_at=now, finished_at=now,
            )
            db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# edit_history
# ---------------------------------------------------------------------------

def record_edit(
    db: DBSession,
    session_id: str,
    user_message: str,
    reasoning: str,
    dirty_keys: list[str],
) -> models.EditHistory:
    row = models.EditHistory(
        session_id=session_id,
        user_message=user_message,
        reasoning=reasoning,
        dirty_keys=dirty_keys,
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

def record_error(db: DBSession, session_id: str, message: str, step: str | None = None) -> models.Error:
    row = models.Error(session_id=session_id, step=step, message=message)
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# page_views (user stage tracking)
# ---------------------------------------------------------------------------

def track_page_view(db: DBSession, session_id: str | None, page: str) -> models.PageView:
    row = models.PageView(session_id=session_id, page=page)
    db.add(row)
    db.commit()
    return row


def get_page_views(db: DBSession, session_id: str | None = None, limit: int = 100) -> list[models.PageView]:
    q = db.query(models.PageView)
    if session_id:
        q = q.filter_by(session_id=session_id)
    return q.order_by(models.PageView.id.desc()).limit(limit).all()


def get_current_page(db: DBSession, session_id: str) -> str | None:
    row = (
        db.query(models.PageView)
        .filter_by(session_id=session_id)
        .order_by(models.PageView.id.desc())
        .first()
    )
    return row.page if row else None

