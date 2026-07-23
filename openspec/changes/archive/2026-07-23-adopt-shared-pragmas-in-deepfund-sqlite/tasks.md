## 1. Adoption

- [x] 1.1 `sqlite_helper._get_connection` delegates to `configure_sqlite_connection` (passing BUSY_TIMEOUT_MS through).
- [x] 1.2 `sqlite_setup.get_db_path` uses `ensure_parent_dir`; `init_database` connection configured with shared pragmas.

## 2. Verification

- [ ] 2.1 Full suite green (workflow-adapter test files exercise SQLiteDB CRUD indirectly); ruff clean.
