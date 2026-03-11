"""
MinIO client helpers for uploading/downloading session artifacts.

Best-effort: failures are logged but never crash the pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from backend.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------

_client: Minio | None = None


def _get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        # Ensure bucket exists
        try:
            if not _client.bucket_exists(MINIO_BUCKET):
                _client.make_bucket(MINIO_BUCKET)
                logger.info("Created MinIO bucket: %s", MINIO_BUCKET)
        except Exception as exc:
            logger.warning("MinIO bucket check failed: %s", exc)
    return _client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def session_object_key(session_id: str, relative_path: str) -> str:
    return f"sessions/{session_id}/{relative_path}"


def object_exists_sync(object_key: str) -> bool:
    try:
        _get_client().stat_object(MINIO_BUCKET, object_key)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sync operations (run in executor for async)
# ---------------------------------------------------------------------------

def _upload_sync(object_key: str, local_path: str) -> str:
    client = _get_client()
    client.fput_object(MINIO_BUCKET, object_key, local_path)
    return object_key


def _download_sync(object_key: str, local_path: str) -> str:
    client = _get_client()
    client.fget_object(MINIO_BUCKET, object_key, local_path)
    return local_path


def _presigned_sync(object_key: str, expires_hours: int = 6) -> str:
    client = _get_client()
    return client.presigned_get_object(
        MINIO_BUCKET, object_key, expires=timedelta(hours=expires_hours)
    )


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

async def upload_file(object_key: str, local_path: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _upload_sync, object_key, local_path)


async def download_file(object_key: str, local_path: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download_sync, object_key, local_path)


async def presigned_url(object_key: str, expires_hours: int = 6) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _presigned_sync, object_key, expires_hours)


async def upload_session_artifact(
    session_id: str, local_path: str, relative_path: str | None = None
) -> str:
    p = Path(local_path)
    rel = relative_path or p.name
    key = session_object_key(session_id, rel)
    logger.debug("Uploading %s → %s/%s", local_path, MINIO_BUCKET, key)
    return await upload_file(key, local_path)


async def upload_session_directory(
    session_id: str, local_dir: str, prefix: str
) -> list[str]:
    keys = []
    for f in Path(local_dir).iterdir():
        if f.is_file():
            key = session_object_key(session_id, f"{prefix}/{f.name}")
            await upload_file(key, str(f))
            keys.append(key)
    return keys

