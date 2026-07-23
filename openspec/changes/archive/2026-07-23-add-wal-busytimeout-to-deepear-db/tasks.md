## 1. Implementation

- [x] 1.1 `database_manager.py`: add `from shared.db import
  configure_sqlite_connection, ensure_parent_dir` at module top;
  `_connect()` calls `configure_sqlite_connection(self._conn)` after
  `sqlite3.connect(...)` and `ensure_parent_dir(self.db_path)` in place of
  the manual `self.db_path.parent.mkdir(...)`.
- [x] 1.2 Multiprocess concurrency regression test
  (`tests/test_deepear_db_concurrency.py`): module-level, picklable worker
  functions using `multiprocessing.get_context("fork")`, one process
  writing via `save_signal` while another reads via `get_recent_signals`
  concurrently, plus a two-concurrent-writers case; assert no "database is
  locked" errors and WAL journal mode active on the file afterwards.

## 2. Verification

- [x] 2.1 `tests/test_deepear_db_concurrency.py` green in isolation
  (2 passed, ~1.5s).
- [x] 2.2 Full suite green at baseline; ruff clean.
