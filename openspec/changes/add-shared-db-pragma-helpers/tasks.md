## 1. Implementation

- [x] 1.1 Add `shared/db/sqlite_pragmas.py` with `configure_sqlite_connection` + `ensure_parent_dir`; `shared/db/__init__.py` exports.
- [x] 1.2 Unit tests (`tests/test_sqlite_pragmas.py`): defaults, wal=False, invalid synchronous, parent-dir no-ops.

## 2. Verification

- [ ] 2.1 Full suite green at baseline; ruff clean.
