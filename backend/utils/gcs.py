"""
Google Cloud Storage helpers (async-friendly wrappers).

The GCS SDK is synchronous, so we run uploads/downloads in a thread-pool
executor so they don't block the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from google.cloud import storage

from backend.config import GOOGLE_CLOUD_PROJECT

logger = logging.getLogger(__name__)


def _upload_sync(local_path: str, bucket_name: str, blob_name: str, project: str) -> str:
    client = storage.Client(project=project)
    blob = client.bucket(bucket_name).blob(blob_name)
    ext = Path(local_path).suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    blob.upload_from_filename(local_path, content_type=mime)
    uri = f"gs://{bucket_name}/{blob_name}"
    logger.debug("Uploaded %s → %s", local_path, uri)
    return uri


def _download_sync(gs_uri: str, local_path: str, project: str) -> None:
    parsed = urlparse(gs_uri)
    bucket_name = parsed.netloc
    blob_name = parsed.path.lstrip("/")
    client = storage.Client(project=project)
    client.bucket(bucket_name).blob(blob_name).download_to_filename(local_path)
    logger.debug("Downloaded %s → %s", gs_uri, local_path)


async def upload_to_gcs(
    local_path: str,
    bucket_name: str,
    blob_name: str,
    project: str = GOOGLE_CLOUD_PROJECT,
) -> str:
    """Upload a local file to GCS and return the gs:// URI."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _upload_sync, local_path, bucket_name, blob_name, project
    )


async def download_from_gcs(
    gs_uri: str,
    local_path: str,
    project: str = GOOGLE_CLOUD_PROJECT,
) -> None:
    """Download a GCS object to a local file."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _download_sync, gs_uri, local_path, project)
