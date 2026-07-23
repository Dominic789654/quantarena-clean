"""Shared low-level SQLite infrastructure (pragmas, path helpers).

Domain persistence layers stay separate by design (deepfund's SQLiteDB,
deepear's DatabaseManager) — see docs/refactor_program_plan.md Phase 1.
"""

from .sqlite_pragmas import (
    DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_SYNCHRONOUS,
    configure_sqlite_connection,
    ensure_parent_dir,
)

__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DEFAULT_SYNCHRONOUS",
    "configure_sqlite_connection",
    "ensure_parent_dir",
]
