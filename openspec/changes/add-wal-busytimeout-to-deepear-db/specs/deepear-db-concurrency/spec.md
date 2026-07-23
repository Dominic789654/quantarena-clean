## ADDED Requirements

### Requirement: Every DatabaseManager connection gets the canonical concurrency pragmas
`deepear/src/utils/database_manager.py`'s `DatabaseManager._connect()` SHALL configure every new `sqlite3.Connection` via `shared.db.configure_sqlite_connection` (busy_timeout=30000ms, WAL journal mode, synchronous=NORMAL) and SHALL create the database file's parent directory via `shared.db.ensure_parent_dir`.

#### Scenario: New connection has WAL and busy_timeout active
- **WHEN** a `DatabaseManager` opens a connection to a database file
- **THEN** `PRAGMA journal_mode` is `wal`, `PRAGMA busy_timeout` is 30000,
  and `PRAGMA synchronous` is NORMAL on that connection

### Requirement: Concurrent multiprocess access does not raise "database is locked"
Two or more OS processes, each holding its own `DatabaseManager` connection to the same database file, performing reads and/or writes concurrently, SHALL NOT raise `sqlite3.OperationalError: database is locked`.

#### Scenario: Read during concurrent write succeeds
- **WHEN** one process writes rows via `DatabaseManager.save_signal` while
  a second process concurrently reads via
  `DatabaseManager.get_recent_signals` against the same database file
- **THEN** both processes complete without error, and the reader observes
  rows written by the writer during the overlap window

#### Scenario: Concurrent writers do not deadlock or error
- **WHEN** two processes each hold their own `DatabaseManager` and write to
  the same database file concurrently
- **THEN** both processes complete without a "database is locked" error,
  and the database file's journal mode is `wal` afterwards
