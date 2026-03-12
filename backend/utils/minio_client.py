"""
MinIO client utilities for the storyteller backend.
Handles uploading session artifacts and generating presigned URLs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from minio import Minio
from minio.error import S3Error

from backend.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------

_client: Optional[Minio] = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
    return _client


def _ensure_bucket() -> None:
    client = _get_client()
    try:
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
    except S3Error as exc:
        raise RuntimeError(f"Failed to ensure MinIO bucket '{MINIO_BUCKET}': {exc}") from exc


# ---------------------------------------------------------------------------
# Object key helpers
# ---------------------------------------------------------------------------

def session_object_key(session_id: str, relative_path: str) -> str:
    """Return the MinIO object key for a session artifact."""
    return f"sessions/{session_id}/{relative_path.lstrip('/')}"


def object_exists_sync(object_key: str) -> bool:
    """Check if an object exists in MinIO (synchronous)."""
    try:
        _get_client().stat_object(MINIO_BUCKET, object_key)
        return True
    except S3Error:
        return False


# ---------------------------------------------------------------------------
# Upload helpers (async wrappers around synchronous MinIO SDK)
# ---------------------------------------------------------------------------

async def upload_session_artifact(
    session_id: str,
    local_path: str,
    relative_path: str,
) -> str:
    """
    Upload a single file to MinIO under sessions/{session_id}/{relative_path}.
    Returns the object key.
    """
    object_key = session_object_key(session_id, relative_path)
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot upload: file not found: {local_path}")

    def _upload():
        _ensure_bucket()
        _get_client().fput_object(
            MINIO_BUCKET,
            object_key,
            str(path),
        )

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    return object_key


async def upload_session_directory(
    session_id: str,
    local_dir: str,
    prefix: str,
) -> list[str]:
    """
    Recursively upload all files in local_dir to MinIO under
    sessions/{session_id}/{prefix}/...
    Returns list of uploaded object keys.
    """
    base = Path(local_dir)
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {local_dir}")

    uploaded: list[str] = []

    def _upload_all():
        _ensure_bucket()
        for file_path in base.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(base)
            key = session_object_key(session_id, f"{prefix.rstrip('/')}/{rel}")
            _get_client().fput_object(MINIO_BUCKET, key, str(file_path))
            uploaded.append(key)

    await asyncio.get_event_loop().run_in_executor(None, _upload_all)
    return uploaded


# ---------------------------------------------------------------------------
# Presigned URL (async)
# ---------------------------------------------------------------------------

async def presigned_url(object_key: str, expires_seconds: int = 3600) -> str:
    """Generate a presigned GET URL for a MinIO object."""
    from datetime import timedelta

    def _generate():
        return _get_client().presigned_get_object(
            MINIO_BUCKET,
            object_key,
            expires=timedelta(seconds=expires_seconds),
        )

    return await asyncio.get_event_loop().run_in_executor(None, _generate)
