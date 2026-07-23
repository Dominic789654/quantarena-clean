## Context

`database_manager.py._connect()` (previously lines 35-44):

```python
self.db_path.parent.mkdir(parents=True, exist_ok=True)
self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
self._conn.row_factory = sqlite3.Row
self._init_db()
```

No pragmas at all. Meanwhile `deepfund/src/database/sqlite_helper.py`
(already adopted in `adopt-shared-pragmas-in-deepfund-sqlite`) and the
shared helper itself (`add-shared-db-pragma-helpers`) establish
busy_timeout=30000 / WAL / synchronous=NORMAL as this codebase's canonical
concurrency posture for SQLite. deepear never got the same treatment
because doing so is a behavior change (previous changes explicitly
deferred it — see `shared/db/sqlite_pragmas.py`'s module docstring and
`add-shared-db-pragma-helpers`'s non-goals). The spike
`spike-deepear-importlib-shared-import` cleared the only real blocker:
proof that `from shared.db import ...` resolves under all of deepear's
load mechanisms.

`check_same_thread=False` is already set, so `DatabaseManager` was already
tolerant of being handed across threads within one process; it was never
tolerant of two *processes* each holding their own connection to the same
file, which is the actual production shape (backtest workers in
`technical.py`, `data_loader.py`, plus a live run's own `DatabaseManager`).

## Goals / Non-Goals

**Goals:** adopt the shared pragma helper so deepear's connections behave
like deepfund's; keep the change to exactly the `_connect()` method (import
+ two call sites); prove the fix with a real multiprocess (not
multi-thread) regression test, since `DatabaseManager` is already
thread-tolerant via `check_same_thread=False` and the actual failure mode
this fixes only shows up across process boundaries.

**Non-Goals:** changing `DatabaseManager`'s public API; adding retry/backoff
logic beyond what `busy_timeout` already provides; touching any other
deepear module.

## Decisions

1. **Apply pragmas unconditionally, not behind a flag.** The spike proved
   `shared.db` always resolves for `database_manager.py`'s own load
   mechanisms; there's no reason to gate this behind a config toggle the
   way `add-shared-db-pragma-helpers` gated the *addition* of the shared
   module (that change was purely additive and explicitly deferred
   deepear's adoption — this change is that deferred adoption).
2. **`ensure_parent_dir` replaces the manual `mkdir`** for consistency with
   `sqlite_setup.get_db_path` in deepfund — purely cosmetic, same
   behavior (`ensure_parent_dir` no-ops for `:memory:`/bare filenames,
   which the manual `Path.mkdir` call on `self.db_path.parent` didn't
   handle as gracefully for `:memory:` — though `DatabaseManager` in
   practice is never constructed with `:memory:`).
3. **Regression test uses `multiprocessing.Process`, not threads.**
   `DatabaseManager` already sets `check_same_thread=False`, so a
   thread-based test would not exercise the failure mode this change
   fixes (SQLite's file-level locking only bites across separate
   connections from separate OS processes competing for the same file,
   which is what production's ProcessPoolExecutor workers + a live run's
   own process actually do). Worker functions are module-level (picklable
   under `fork`) and call `sys.path.insert` themselves rather than relying
   on pytest's `conftest.setup_paths()`, mirroring how a real subprocess
   bootstraps.
4. **`save_signal`/`get_recent_signals` (the `signals` table) chosen as the
   write/read pair for the test** — simple, already-existing methods with
   no external dependencies (no pandas DataFrame shaping, no network),
   keeping the test fast and focused on lock behavior rather than data
   shape.

## Risks / Trade-offs

- WAL leaves `-wal`/`-shm` sidecar files next to each `.db` file after
  first use. Existing backups/rsync scripts that only copy the `.db` file
  could miss in-flight WAL data — same trade-off deepfund already accepted
  when it adopted WAL; no deepear-specific tooling in this repo assumes a
  single-file DB.
- `synchronous=NORMAL` (vs. the sqlite default `FULL`) trades a small
  durability window (WAL frames not yet checkpointed can be lost on OS
  crash, not on process crash) for throughput — again, byte-identical to
  deepfund's long-standing, already-accepted trade-off.
