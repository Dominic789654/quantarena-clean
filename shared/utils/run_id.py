"""Run identifier helpers."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4


def generate_run_id(prefix: str | None = None) -> str:
    """Generate a high-resolution run identifier safe for concurrent local runs."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    suffix = uuid4().hex[:8]
    run_id = f"{timestamp}_{suffix}"
    return f"{prefix}_{run_id}" if prefix else run_id
