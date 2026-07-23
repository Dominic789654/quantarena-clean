## Context

deepfund/src/database/sqlite_helper.py:30-37 already applies `busy_timeout=30000`, `journal_mode=WAL`, `synchronous=NORMAL`. sqlite_setup.py:36 and deepear/src/utils/database_manager.py:41 do not.

## Goals / Non-Goals

**Goals:** one canonical implementation of connection pragmas + parent-dir creation; defaults byte-compatible with deepfund's current behavior.
**Non-Goals:** merging the two domain persistence layers (explicitly rejected by the program plan); changing deepear behavior (separate gated change).

## Decisions

1. Helpers operate on an already-open connection (`configure_sqlite_connection(conn)`) rather than wrapping `sqlite3.connect` — callers keep their own connect kwargs (`check_same_thread`, `timeout`, row_factory).
2. `synchronous` value validated against SQLite's allowed set to prevent silent pragma no-ops from typos.
3. `ensure_parent_dir` no-ops for `:memory:` and bare filenames.

## Risks / Trade-offs

- None material: additive module, defaults copied from existing production values.
