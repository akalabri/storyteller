"""
Firestore CRUD helpers for the storyteller database.

Every function takes an explicit Firestore client — no global state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud.firestore_v1 import Client as FirestoreClient
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _delete_collection(col_ref, batch_size: int = 100) -> None:
    """Delete all documents in a Firestore collection."""
    while True:
        docs = list(col_ref.limit(batch_size).stream())
        if not docs:
            break
        for doc in docs:
            # Delete subcollections first (Firestore doesn't cascade)
            for subcol in doc.reference.collections():
                _delete_collection(subcol, batch_size)
            doc.reference.delete()
        if len(docs) < batch_size:
            break


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def upsert_session(db: FirestoreClient, session_id: str, status: str = "idle") -> dict:
    ref = db.collection("sessions").document(session_id)
    doc = ref.get()
    now = _now()
    if doc.exists:
        ref.update({"status": status, "updated_at": now})
    else:
        ref.set({"status": status, "created_at": now, "updated_at": now})
    return {"id": session_id, "status": status}


def update_session_status(db: FirestoreClient, session_id: str, status: str) -> None:
    db.collection("sessions").document(session_id).update(
        {"status": status, "updated_at": _now()}
    )


# ---------------------------------------------------------------------------
# conversations
# ---------------------------------------------------------------------------

def save_conversation(db: FirestoreClient, session_id: str, transcript: str) -> dict:
    ref = (
        db.collection("sessions").document(session_id)
        .collection("conversations").document("main")
    )
    data = {"session_id": session_id, "transcript": transcript, "created_at": _now()}
    ref.set(data, merge=True)
    return data


# ---------------------------------------------------------------------------
# stories / scenes / characters / props / subscenes
# ---------------------------------------------------------------------------

def save_story_breakdown(
    db: FirestoreClient,
    session_id: str,
    breakdown,  # StoryBreakdown from state.py
) -> None:
    """Persist the full story breakdown (story, characters, props) to Firestore."""
    sess_ref = db.collection("sessions").document(session_id)
    now = _now()

    # -- story --
    sess_ref.collection("story").document("main").set({
        "special_instructions": breakdown.special_instructions,
        "created_at": now,
    }, merge=True)

    # -- scenes (delete + recreate) --
    _delete_collection(sess_ref.collection("scenes"))
    for i, text in enumerate(breakdown.story, start=1):
        sess_ref.collection("scenes").document(f"scene_{i}").set({
            "scene_index": i,
            "text": text,
            "summary": "",
            "narration_minio_key": None,
            "created_at": now,
        })

    # -- characters --
    _delete_collection(sess_ref.collection("characters"))
    for cp in breakdown.characters_prompts:
        sess_ref.collection("characters").add({
            "name": cp.name,
            "description": cp.description,
            "image_minio_key": None,
            "created_at": now,
        })

    # -- props --
    _delete_collection(sess_ref.collection("props"))
    for p in breakdown.prop_descriptions:
        sess_ref.collection("props").add({
            "name": p.name,
            "description": p.description,
            "created_at": now,
        })


def save_visual_plan(db: FirestoreClient, session_id: str, visual_plan) -> None:
    """Persist subscenes from the visual plan."""
    sess_ref = db.collection("sessions").document(session_id)
    scenes_ref = sess_ref.collection("scenes")
    now = _now()

    for sp in visual_plan.scenes:
        scene_doc_id = f"scene_{sp.scene_index}"
        scene_ref = scenes_ref.document(scene_doc_id)

        doc = scene_ref.get()
        if not doc.exists:
            continue

        scene_ref.update({"summary": sp.scene_summary})

        # Delete old subscenes for this scene
        _delete_collection(scene_ref.collection("subscenes"))

        for sub in sp.subscenes:
            scene_ref.collection("subscenes").document(f"sub_{sub.index}").set({
                "sub_index": sub.index,
                "image_prompt": sub.image_prompt,
                "video_prompt": sub.video_prompt,
                "image_minio_key": None,
                "video_minio_key": None,
                "created_at": now,
            })


def update_character_image(db: FirestoreClient, session_id: str, name: str, minio_key: str) -> None:
    chars_ref = (
        db.collection("sessions").document(session_id)
        .collection("characters")
    )
    docs = list(chars_ref.where(filter=FieldFilter("name", "==", name)).limit(1).stream())
    if docs:
        docs[0].reference.update({"image_minio_key": minio_key})


def update_narration_key(db: FirestoreClient, session_id: str, scene_index: int, minio_key: str) -> None:
    scene_ref = (
        db.collection("sessions").document(session_id)
        .collection("scenes").document(f"scene_{scene_index}")
    )
    doc = scene_ref.get()
    if doc.exists:
        scene_ref.update({"narration_minio_key": minio_key})


def update_subscene_image(db: FirestoreClient, session_id: str, scene_idx: int, sub_idx: int, minio_key: str) -> None:
    sub_ref = (
        db.collection("sessions").document(session_id)
        .collection("scenes").document(f"scene_{scene_idx}")
        .collection("subscenes").document(f"sub_{sub_idx}")
    )
    doc = sub_ref.get()
    if doc.exists:
        sub_ref.update({"image_minio_key": minio_key})


def update_subscene_video(db: FirestoreClient, session_id: str, scene_idx: int, sub_idx: int, minio_key: str) -> None:
    sub_ref = (
        db.collection("sessions").document(session_id)
        .collection("scenes").document(f"scene_{scene_idx}")
        .collection("subscenes").document(f"sub_{sub_idx}")
    )
    doc = sub_ref.get()
    if doc.exists:
        sub_ref.update({"video_minio_key": minio_key})


# ---------------------------------------------------------------------------
# pipeline_steps
# ---------------------------------------------------------------------------

def record_step(
    db: FirestoreClient,
    session_id: str,
    step: str,
    status: str,
    message: str = "",
) -> dict:
    """Record a pipeline step.

    Uses the step name as the document ID so updates are simple upserts
    and no composite index is needed.
    """
    now = _now()
    step_ref = (
        db.collection("sessions").document(session_id)
        .collection("pipeline_steps").document(step)
    )

    doc = step_ref.get()
    if status == "running":
        step_ref.set({
            "step": step,
            "status": status,
            "message": message,
            "started_at": now,
            "finished_at": None,
        })
    elif doc.exists and doc.to_dict().get("status") == "running":
        step_ref.update({
            "status": status,
            "message": message,
            "finished_at": now,
        })
    else:
        step_ref.set({
            "step": step,
            "status": status,
            "message": message,
            "started_at": now,
            "finished_at": now,
        })

    return {"id": step, "step": step, "status": status}


# ---------------------------------------------------------------------------
# edit_history
# ---------------------------------------------------------------------------

def record_edit(
    db: FirestoreClient,
    session_id: str,
    user_message: str,
    reasoning: str,
    dirty_keys: list[str],
) -> dict:
    data = {
        "user_message": user_message,
        "reasoning": reasoning,
        "dirty_keys": dirty_keys,
        "created_at": _now(),
    }
    (
        db.collection("sessions").document(session_id)
        .collection("edit_history").add(data)
    )
    return data


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

def record_error(db: FirestoreClient, session_id: str, message: str, step: str | None = None) -> dict:
    data = {
        "step": step,
        "message": message,
        "created_at": _now(),
    }
    (
        db.collection("sessions").document(session_id)
        .collection("errors").add(data)
    )
    return data


# ---------------------------------------------------------------------------
# page_views (user stage tracking)
# ---------------------------------------------------------------------------

def track_page_view(db: FirestoreClient, session_id: str | None, page: str) -> dict:
    data = {
        "session_id": session_id,
        "page": page,
        "created_at": _now(),
    }
    _, doc_ref = db.collection("page_views").add(data)
    data["id"] = doc_ref.id
    return data


def get_page_views(db: FirestoreClient, session_id: str | None = None, limit: int = 100) -> list[dict]:
    ref = db.collection("page_views")
    if session_id:
        # Single-field filter only — avoids composite index requirement
        ref = ref.where(filter=FieldFilter("session_id", "==", session_id))
    docs = ref.limit(limit).stream()
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        results.append(d)
    # Sort in Python to avoid needing a composite index
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results


def get_current_page(db: FirestoreClient, session_id: str) -> str | None:
    docs = list(
        db.collection("page_views")
        .where(filter=FieldFilter("session_id", "==", session_id))
        .limit(50)
        .stream()
    )
    if not docs:
        return None
    # Find the most recent by created_at in Python
    latest = max(docs, key=lambda d: d.to_dict().get("created_at", ""))
    return latest.to_dict().get("page")
