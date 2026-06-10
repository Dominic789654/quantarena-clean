"""In-process diagnostics for benchmark data provider behavior."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from backtest.providers import _redact_provider_message


_LOCK = Lock()
_RECORDS: list[dict[str, Any]] = []


def record_benchmark_diagnostic(record: dict[str, Any]) -> None:
    """Append a benchmark diagnostic record."""
    payload = dict(record)
    payload.setdefault("recorded_at", datetime.now(UTC).isoformat())
    if payload.get("message"):
        payload["message"] = _redact_provider_message(str(payload["message"]))
    with _LOCK:
        _RECORDS.append(payload)


def drain_benchmark_diagnostics() -> list[dict[str, Any]]:
    """Return and clear all accumulated benchmark diagnostics."""
    with _LOCK:
        records = deepcopy(_RECORDS)
        _RECORDS.clear()
    return records


def peek_benchmark_diagnostics() -> list[dict[str, Any]]:
    """Return accumulated benchmark diagnostics without clearing them."""
    with _LOCK:
        return deepcopy(_RECORDS)


def clear_benchmark_diagnostics() -> None:
    """Clear accumulated diagnostics."""
    with _LOCK:
        _RECORDS.clear()
