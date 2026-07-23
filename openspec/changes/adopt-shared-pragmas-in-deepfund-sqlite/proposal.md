## Why

deepfund's `SQLiteDB._get_connection` and `sqlite_setup` duplicate the pragma/path knowledge now owned by `shared/db` (change add-shared-db-pragma-helpers). Adoption removes the duplication before Phase 3's db_store extraction builds on this layer.

## What Changes

- `sqlite_helper._get_connection` delegates pragmas to `configure_sqlite_connection` (same values — behavior preserving).
- `sqlite_setup.get_db_path` uses `ensure_parent_dir`; `init_database`'s connection gains the same pragmas (WAL was already the journal mode of the shared db file, set by SQLiteDB on first use).
- No API or schema changes.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- None (implementation-only; the shared-sqlite-pragmas capability's requirements already cover the values).

## Impact

- deepfund/src/database/{sqlite_helper.py, sqlite_setup.py}. Gated by the workflow-adapter test files, which drive SQLiteDB CRUD indirectly.
