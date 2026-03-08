"""
File I/O helpers for the storyteller backend.
"""

from __future__ import annotations

import re
from pathlib import Path


def safe_filename(name: str) -> str:
    """Convert any string (including Arabic) to a safe ASCII filename slug."""
    slug = re.sub(r"[^\w\- ]", "", name, flags=re.ASCII).strip()
    slug = re.sub(r"\s+", "_", slug)
    return slug if slug else f"character_{hash(name) & 0xFFFF}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
