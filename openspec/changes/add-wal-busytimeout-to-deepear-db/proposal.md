## Why

`deepear/src/utils/database_manager.py`'s `_connect()` opens a bare
`sqlite3.connect(...)` with no pragmas at all — no `busy_timeout`, no WAL.
`shared/db/sqlite_pragmas.py` already exists and is adopted by deepfund's
`SQLiteDB`. deepear's `DatabaseManager` is opened from multiple processes
concurrently (backtest worker processes read cached prices via
`technical.py:81`'s `DatabaseManager` while a live run's main process may
still be writing signals/news through its own `DatabaseManager` on the
same file), so a bare connection is one concurrent write away from
`sqlite3.OperationalError: database is locked`. The spike
`spike-deepear-importlib-shared-import` proved `shared.db` resolves under
every one of deepear's real load mechanisms, clearing the way to adopt it
here unconditionally.

## What Changes

- `database_manager.py._connect()`: apply
  `shared.db.configure_sqlite_connection` to every new connection (WAL,
  busy_timeout=30000ms, synchronous=NORMAL) and replace the manual
  `self.db_path.parent.mkdir(parents=True, exist_ok=True)` with
  `shared.db.ensure_parent_dir(self.db_path)`.
- **This is the only behavior change**: deepear's DB file gains WAL +
  busy_timeout(30000) + synchronous=NORMAL, matching deepfund's
  long-standing values exactly.
- Add a multiprocess (not thread) concurrency regression test,
  `tests/test_deepear_db_concurrency.py`, proving concurrent read-during-write
  and concurrent-writer access to the same `DatabaseManager`-backed file no
  longer raises "database is locked".

## Capabilities

### New Capabilities
- `deepear-db-concurrency`: every `DatabaseManager` connection gets the
  canonical WAL/busy_timeout pragmas, and concurrent multiprocess access to
  the same DB file doesn't error.

### Modified Capabilities
- None (deepear's DB behavior itself changes, but it has no existing
  OpenSpec capability spec to modify — this is the first one).

## Impact

- `deepear/src/utils/database_manager.py` (the only production file
  touched). New test file `tests/test_deepear_db_concurrency.py`. Every
  deepear DB file on disk transitions to WAL journal mode the next time
  it's opened (creates a `-wal`/`-shm` sidecar file next to the `.db` file
  — a normal SQLite WAL artifact, not a schema change).
