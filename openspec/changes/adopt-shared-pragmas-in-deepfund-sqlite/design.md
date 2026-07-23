## Context

sqlite_helper.py:30-37 applied pragmas inline; sqlite_setup.py:36 opened a bare connection for DDL.

## Goals / Non-Goals

**Goals:** single pragma implementation; byte-identical pragma values for SQLiteDB.
**Non-Goals:** touching deepear (separate gated change); changing BUSY_TIMEOUT_MS/CONNECT_TIMEOUT values.

## Decisions

1. Keep `SQLiteDB.BUSY_TIMEOUT_MS` class attr and pass it through — tests/subclasses may override it.
2. Give `init_database`'s DDL connection the same pragmas: WAL is a persistent database property; setting it at init instead of first CRUD access removes an ordering dependency.

## Risks / Trade-offs

- `init_database` now sets WAL where it previously didn't: same terminal state as before (SQLiteDB set it on first connection), just earlier. Covered by the existing db tests.
