## Why

Both persistence layers hand-roll SQLite connection setup: deepfund's `SQLiteDB._get_connection` applies WAL/busy_timeout/synchronous pragmas inline, while `sqlite_setup.init_database` and deepear's `DatabaseManager._connect` open bare connections with no pragmas at all. Backtests open connections from worker processes (`ProcessPoolExecutor`), so the pragma knowledge must live in one shared place before the workflow_adapter and report_agent decomposition tracks build on the DB layer (docs/refactor_program_plan.md Phase 1).

## What Changes

- Add `shared/db/sqlite_pragmas.py`: `configure_sqlite_connection` (busy_timeout, WAL, synchronous — defaults mirror deepfund's historical values) and `ensure_parent_dir`.
- Purely additive; no existing code path changes in this change (adoption follows in separate changes).

## Capabilities

### New Capabilities
- `shared-sqlite-pragmas`: canonical SQLite concurrency pragmas and path helpers shared by both persistence layers.

### Modified Capabilities
- None.

## Impact

- New `shared/db/` package + unit tests. Zero runtime behavior change.
