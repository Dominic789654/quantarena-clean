## ADDED Requirements

### Requirement: Canonical connection pragmas
`shared.db.configure_sqlite_connection` SHALL apply busy_timeout (default 30000ms), WAL journal mode (unless disabled), and a validated synchronous mode (default NORMAL) to an open SQLite connection, matching deepfund's historical values.

#### Scenario: Defaults match deepfund's historical behavior
- **WHEN** a connection is configured with defaults
- **THEN** `PRAGMA busy_timeout` is 30000, `PRAGMA journal_mode` is `wal`, `PRAGMA synchronous` is NORMAL

#### Scenario: Invalid synchronous mode is rejected
- **WHEN** an unknown synchronous mode is passed
- **THEN** a ValueError is raised before any pragma executes

### Requirement: Parent directory helper
`shared.db.ensure_parent_dir` SHALL create a database file's parent directory when missing and no-op for `:memory:`, bare filenames, and empty paths.

#### Scenario: Nested path created
- **WHEN** called with a path whose parent directories do not exist
- **THEN** the parent directories exist afterwards
