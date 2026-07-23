"""Unit tests for the shared SQLite pragma helpers."""

from __future__ import annotations

import sqlite3

import pytest

from shared.db import (
    DEFAULT_BUSY_TIMEOUT_MS,
    configure_sqlite_connection,
    ensure_parent_dir,
)


def _pragma(conn, name):
    return conn.execute(f"PRAGMA {name}").fetchone()[0]


def test_configure_applies_canonical_pragmas(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    try:
        configure_sqlite_connection(conn)
        assert _pragma(conn, "busy_timeout") == DEFAULT_BUSY_TIMEOUT_MS
        assert _pragma(conn, "journal_mode").lower() == "wal"
        assert _pragma(conn, "synchronous") == 1  # NORMAL
    finally:
        conn.close()


def test_configure_without_wal(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    try:
        configure_sqlite_connection(conn, wal=False, busy_timeout_ms=1234)
        assert _pragma(conn, "busy_timeout") == 1234
        assert _pragma(conn, "journal_mode").lower() != "wal"
    finally:
        conn.close()


def test_configure_rejects_bad_synchronous(tmp_path):
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(ValueError, match="Invalid synchronous"):
            configure_sqlite_connection(conn, synchronous="TURBO")
    finally:
        conn.close()


def test_ensure_parent_dir(tmp_path):
    target = tmp_path / "a" / "b" / "x.db"
    ensure_parent_dir(target)
    assert target.parent.is_dir()

    # No-ops must not raise.
    ensure_parent_dir(":memory:")
    ensure_parent_dir("bare.db")
    ensure_parent_dir("")
