"""Multiprocess concurrency regression test for deepear's DatabaseManager.

Change `add-wal-busytimeout-to-deepear-db` gives every DatabaseManager
connection WAL + busy_timeout(30000) + synchronous=NORMAL (via
shared.db.configure_sqlite_connection — see
deepear/src/utils/database_manager.py's `_connect`). Before that change,
concurrent access to the same .db file from separate *processes* (not just
threads — DatabaseManager itself is a single-connection, single-thread-safe
wrapper) could raise `sqlite3.OperationalError: database is locked` the
moment a writer held the file while a reader (or another writer) tried to
open it.

This test proves the fix: real OS processes (not threads — threads would
share the GIL and mask the failure mode this pragma set exists to fix),
each with their own DatabaseManager/connection to the same file, one
writing while another reads/writes concurrently, with zero lock errors.

Worker functions are module-level (required for pickling by
multiprocessing's `fork` start method) and set up sys.path themselves,
mirroring how a real subprocess would bootstrap rather than relying on
pytest's conftest.setup_paths().
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ensure_paths() -> None:
    """Subprocess-realistic sys.path bootstrap for a forked worker.

    Mirrors the manual `sys.path.insert` pattern in
    tests/test_db_connection_cleanup.py rather than depending on the test
    session's `shared.utils.path_manager.setup_paths()` call, since forked
    workers in production (backtest/multi_personality_engine.py's
    ProcessPoolExecutor) inherit the parent's sys.path rather than
    re-deriving it.
    """
    for candidate in (
        str(PROJECT_ROOT),
        str(PROJECT_ROOT / "deepear" / "src"),
        str(PROJECT_ROOT / "deepfund" / "src"),
    ):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)


def _writer_worker(db_path: str, prefix: str, count: int, result_queue) -> None:
    _ensure_paths()
    from deepear.src.utils.database_manager import DatabaseManager

    try:
        db = DatabaseManager(db_path)
        try:
            for i in range(count):
                db.save_signal(
                    {
                        "signal_id": f"{prefix}-{i}",
                        "title": f"signal {prefix}-{i}",
                        "summary": "concurrency regression spike",
                        "sentiment_score": 0.1,
                        "confidence": 0.5,
                        "intensity": 2,
                    }
                )
                time.sleep(0.02)
        finally:
            db.close()
        result_queue.put((f"writer-{prefix}", "OK", None))
    except Exception as exc:  # noqa: BLE001 - surface every failure to the parent
        result_queue.put((f"writer-{prefix}", "ERR", f"{exc!r}\n{traceback.format_exc()}"))


def _reader_worker(db_path: str, duration_s: float, result_queue) -> None:
    _ensure_paths()
    from deepear.src.utils.database_manager import DatabaseManager

    try:
        db = DatabaseManager(db_path)
        seen_any = False
        errors = []
        deadline = time.time() + duration_s
        try:
            while time.time() < deadline:
                try:
                    rows = db.get_recent_signals(limit=50)
                    if rows:
                        seen_any = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(repr(exc))
                time.sleep(0.01)
        finally:
            db.close()
        if errors:
            result_queue.put(("reader", "ERR", "; ".join(errors)))
        else:
            result_queue.put(("reader", "OK", seen_any))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("reader", "ERR", f"{exc!r}\n{traceback.format_exc()}"))


def _drain(result_queue) -> dict:
    results = {}
    while not result_queue.empty():
        who, status, detail = result_queue.get()
        results[who] = (status, detail)
    return results


def _assert_wal_active(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal", f"expected WAL journal mode, got {mode!r}"


class TestDeepearDbConcurrency:
    def test_concurrent_read_during_write_does_not_lock(self, tmp_path):
        """One process writes signals while another reads concurrently,
        each through its own DatabaseManager/connection to the same file.
        """
        db_path = str(tmp_path / "concurrency_read_write.db")

        # Pre-create schema synchronously so both workers race on an
        # existing file rather than on table creation.
        from deepear.src.utils.database_manager import DatabaseManager

        DatabaseManager(db_path).close()

        ctx = mp.get_context("fork")
        result_queue = ctx.Queue()

        writer = ctx.Process(target=_writer_worker, args=(db_path, "rw", 40, result_queue))
        reader = ctx.Process(target=_reader_worker, args=(db_path, 1.2, result_queue))

        start = time.time()
        writer.start()
        reader.start()
        writer.join(timeout=10)
        reader.join(timeout=10)
        elapsed = time.time() - start

        assert not writer.is_alive(), "writer process did not finish in time"
        assert not reader.is_alive(), "reader process did not finish in time"
        assert elapsed < 10, f"concurrency test took too long: {elapsed:.2f}s"

        results = _drain(result_queue)
        assert "writer-rw" in results and "reader" in results

        writer_status, writer_detail = results["writer-rw"]
        reader_status, reader_detail = results["reader"]

        assert writer_status == "OK", writer_detail
        assert reader_status == "OK", reader_detail
        assert reader_detail is True, "reader never observed any rows during concurrent writes"

        _assert_wal_active(db_path)

    def test_no_database_is_locked_errors_under_concurrent_writers(self, tmp_path):
        """Two independent writer processes hammering the same DB file
        concurrently must not surface 'database is locked' — busy_timeout
        makes them wait for the writer lock instead of failing immediately.
        """
        db_path = str(tmp_path / "concurrency_writers.db")

        from deepear.src.utils.database_manager import DatabaseManager

        DatabaseManager(db_path).close()

        ctx = mp.get_context("fork")
        result_queue = ctx.Queue()

        writers = [
            ctx.Process(target=_writer_worker, args=(db_path, f"w{n}", 20, result_queue))
            for n in range(2)
        ]

        start = time.time()
        for w in writers:
            w.start()
        for w in writers:
            w.join(timeout=10)
        elapsed = time.time() - start

        assert all(not w.is_alive() for w in writers), "a writer process did not finish in time"
        assert elapsed < 10, f"concurrency test took too long: {elapsed:.2f}s"

        results = _drain(result_queue)
        assert "writer-w0" in results and "writer-w1" in results
        for key in ("writer-w0", "writer-w1"):
            status, detail = results[key]
            assert status == "OK", detail
            if detail is not None:
                assert "database is locked" not in str(detail).lower()

        _assert_wal_active(db_path)
