## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_create_temp_db\|_setup_database\|
  _ensure_config\|_get_or_create_portfolio\|_update_portfolio\b"
  tests/` — direct calls only:
  `tests/test_workflow_adapter_smart_priority.py:101-111`
  (`adapter._create_temp_db()` x50, uniqueness assertion). No
  monkeypatch of any of the five names exists.
- [x] 1.2 Confirm no test asserts on this adapter's own db file's
  `journal_mode`/`synchronous`/`busy_timeout` pragmas (the one
  behavior change in this batch) — `git grep -n "journal_mode\|PRAGMA"
  tests/` hits only `test_cache_health.py`, `test_db_connection_cleanup.py`
  (deepear's `DatabaseManager`), and `test_sqlite_pragmas.py` (the
  Phase-1 helper's own unit tests) — none target
  `BacktestWorkflowAdapter`.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/db_store.py` with `_create_temp_db()`,
  `_setup_database(db_path)`, `_ensure_config(db_path, exp_name,
  tickers, llm_model, llm_provider)`, `_get_or_create_portfolio(db_path,
  config_id, trading_date, current_portfolio)`, `_update_portfolio(
  db_path, current_portfolio, trading_date)` — DDL/CRUD bodies moved
  verbatim except the mandated parameter lifting and the
  `configure_sqlite_connection`/`ensure_parent_dir` adoption at every
  `sqlite3.connect` site.
- [x] 2.2 `backtest/workflow_adapter.py`: replace the five method
  bodies with delegators calling the module functions with the
  relevant `self.*` attributes.
- [x] 2.3 Add `tests/test_workflow_db_store_schema.py`: DDL
  schema-smoke test asserting the four tables and five indices exist
  in `sqlite_master` after `_setup_database` runs against a `tmp_path`
  db file.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 937 passed
  (baseline) + new schema-smoke test(s), 10 skipped, 0 failed.
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
