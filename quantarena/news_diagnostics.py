"""In-process diagnostics for company-news fetch/filter behavior."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, UTC
from threading import Lock
from typing import Any


_LOCK = Lock()
_RECORDS: list[dict[str, Any]] = []


def classify_zero_reason(
    *,
    raw_count: int,
    date_filtered_count: int,
    final_count: int,
    ticker_filtered_count: int | None = None,
    topic_filtered_count: int | None = None,
) -> str:
    """Classify why a news request returned no usable items."""
    raw = _safe_count(raw_count)
    date_filtered = _safe_count(date_filtered_count)
    final = _safe_count(final_count)
    ticker_filtered = _safe_count(ticker_filtered_count)
    topic_filtered = _safe_count(topic_filtered_count)

    if final > 0:
        return "not_zero"
    if raw <= 0:
        return "provider_empty"
    if date_filtered <= 0:
        return "future_only"
    if ticker_filtered_count is not None and ticker_filtered <= 0:
        return "ticker_miss"
    if topic_filtered_count is not None and topic_filtered <= 0:
        return "filtered_empty"
    return "filtered_empty"


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


def _safe_count(value: int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
