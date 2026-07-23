"""Canonical SQLite connection pragmas shared by both persistence layers.

Extracted from deepfund's SQLiteDB._get_connection (the values below match
its long-standing behavior). deepear's DatabaseManager adopts the same
pragmas in a separate, explicitly-gated change because enabling WAL there
is a behavior change (see openspec change add-wal-busytimeout-to-deepear-db).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Union

# Values mirror deepfund/src/database/sqlite_helper.py's historical settings.
DEFAULT_BUSY_TIMEOUT_MS = 30000
DEFAULT_SYNCHRONOUS = "NORMAL"

_ALLOWED_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}


def configure_sqlite_connection(
    conn: sqlite3.Connection,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    wal: bool = True,
    synchronous: str = DEFAULT_SYNCHRONOUS,
) -> sqlite3.Connection:
    """Apply the canonical concurrency pragmas to an open connection.

    WAL + busy_timeout lets concurrent readers coexist with a writer and
    turns immediate "database is locked" errors into bounded waits —
    required because backtests open connections from worker processes
    (ProcessPoolExecutor in multi_personality_engine, worker-process
    imports in technical.py).
    """
    synchronous = synchronous.upper()
    if synchronous not in _ALLOWED_SYNCHRONOUS:
        raise ValueError(f"Invalid synchronous mode {synchronous!r}; expected one of {sorted(_ALLOWED_SYNCHRONOUS)}")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA synchronous = {synchronous}")
    return conn


def ensure_parent_dir(db_path: Union[str, Path]) -> None:
    """Create the parent directory of a database file if missing.

    A no-op for bare filenames and in-memory databases.
    """
    path_str = str(db_path)
    if path_str == ":memory:" or not path_str:
        return
    parent = os.path.dirname(path_str)
    if parent:
        os.makedirs(parent, exist_ok=True)
