"""In-process diagnostics for company-news fetch/filter behavior."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, UTC
from threading import Lock
from typing import Any


_LOCK = Lock()
_RECORDS: list[dict[str, Any]] = []


def record_news_diagnostic(record: dict[str, Any]) -> None:
    """Append a count-only news diagnostic record."""
    payload = dict(record)
    payload.setdefault("recorded_at", datetime.now(UTC).isoformat())
    with _LOCK:
        _RECORDS.append(payload)


def drain_news_diagnostics() -> list[dict[str, Any]]:
    """Return and clear all accumulated news diagnostics."""
    with _LOCK:
        records = deepcopy(_RECORDS)
        _RECORDS.clear()
    return records


def peek_news_diagnostics() -> list[dict[str, Any]]:
    """Return accumulated diagnostics without clearing them."""
    with _LOCK:
        return deepcopy(_RECORDS)


def clear_news_diagnostics() -> None:
    """Clear accumulated diagnostics."""
    with _LOCK:
        _RECORDS.clear()
