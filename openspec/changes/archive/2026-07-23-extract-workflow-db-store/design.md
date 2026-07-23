## Context

`backtest/workflow_adapter.py`'s five db methods (~lines 164-345 at the
start of this change) each open a fresh `sqlite3.connect(self.db_path)`,
do their work, `conn.commit()`, and `conn.close()` — no connection is
held open across calls. `_setup_database` creates four tables
(`config`, `portfolio`, `decision`, `signal`) and five indices.
`_ensure_config` is idempotent (checks for an existing row by
`exp_name` before inserting). `_get_or_create_portfolio` always inserts
a new portfolio row per trading date and mutates
`self.current_portfolio["id"]`. `_update_portfolio` is a plain
read-existing-state, `UPDATE ... WHERE id = ?`.

None of these five methods currently apply any pragmas — the
connections use sqlite3's defaults (`journal_mode=DELETE`,
`synchronous=FULL`). `shared/db/sqlite_pragmas.py` (Phase 1,
`add-shared-db-pragma-helpers`) already provides
`configure_sqlite_connection` (WAL + busy_timeout=30000ms +
synchronous=NORMAL) and `ensure_parent_dir`, adopted by
`deepfund/src/database/sqlite_helper.py` and `sqlite_setup.py` in Phase
1's `adopt-shared-pragmas-in-deepfund-sqlite` change.

## Goals / Non-Goals

**Goals:** lift the five methods' `self.*` reads into explicit
parameters so they can live as module functions in
`backtest/workflow/db_store.py`; adopt `shared.db`'s pragma helpers at
every raw `sqlite3.connect` site in these five functions; keep every
`self._<name>(...)` / `adapter._<name>(...)` call site working via
same-named delegators; add the missing DDL schema-smoke test.

**Non-Goals:** changing the DDL itself (table/column/index
definitions stay byte-for-byte identical); changing `_ensure_config`'s
idempotency check or `_get_or_create_portfolio`'s always-insert
semantics; touching `util.db_helper`/`database.sqlite_helper`'s own
`SQLiteDB` class (a separate persistence layer entirely — this
adapter's `config`/`portfolio`/`decision`/`signal` tables are its own
private schema, distinct from `SQLiteDB`'s, even though both may
target the same physical db file when a caller passes
`db_path="data/signal_flux.db"`).

## Decisions

1. **Parameter lifting.** Each function's signature takes exactly the
   `self.*` attributes its body reads, in the order they were
   originally accessed, with no renaming:
   `_setup_database(db_path)`; `_ensure_config(db_path, exp_name,
   tickers, llm_model, llm_provider)`;
   `_get_or_create_portfolio(db_path, config_id, trading_date,
   current_portfolio)`; `_update_portfolio(db_path, current_portfolio,
   trading_date)`. `_get_or_create_portfolio` mutates the
   `current_portfolio` dict passed in (setting `["id"]`) exactly as
   the original mutated `self.current_portfolio["id"]` — callers pass
   `self.current_portfolio`, the same mutable object, so the observable
   effect on the adapter instance is identical.
2. **`configure_sqlite_connection` adoption is safe for this db file
   because:**
   - The four call sites are all short-lived, non-overlapping
     connections (open, one or two statements, commit, close) — WAL's
     benefit (readers don't block a writer, writer doesn't block
     readers) only helps here, it does not change any observable
     query result.
   - `busy_timeout=30000ms` only changes behavior when a `SQLITE_BUSY`
     would otherwise be raised immediately; with the previous
     zero-timeout default, any contention was already a correctness
     risk (an uncaught `sqlite3.OperationalError: database is locked`),
     so bounding the wait instead of failing immediately is strictly
     safer, matching the exact justification already accepted for
     `deepfund/src/database/sqlite_helper.py` in Phase 1.
   - `synchronous=NORMAL` (down from sqlite's default `FULL`) is the
     same trade-off Phase 1 already made for the `signal_flux.db`
     family — WAL mode's NORMAL synchronous setting still guarantees
     durability across application crashes (only an OS crash or power
     loss could lose the last commit), which this adapter's own
     `close()`/`__del__` never relied on stronger guarantees than that
     for (it never asserts durability across a kernel panic in any
     test).
   - This adapter's db file is either an isolated per-run temp file
     (`_create_temp_db()`, one adapter, no concurrent writers by
     construction) or an explicit `db_path` the caller supplies
     (commonly `data/signal_flux.db`, the same file family multiple
     other writers in this codebase already access under WAL since
     Phase 1) — in both cases enabling WAL here cannot introduce a
     *new* multi-writer hazard; it only means this adapter's own
     short-lived connections now behave the same way as every other
     writer already touching that file family.
3. **DDL schema-smoke test** (new,
   `tests/test_workflow_db_store_schema.py`): calls `_setup_database`
   (via the module function, using a `tmp_path` db file) and asserts,
   via `sqlite_master`, that all four tables (`config`, `portfolio`,
   `decision`, `signal`) and all five indices
   (`idx_config_exp_name`, `idx_portfolio_config`,
   `idx_portfolio_trading_date`, `idx_decision_portfolio`,
   `idx_signal_portfolio`) exist. This is additive coverage the plan
   explicitly calls out as missing; it exercises the module function
   directly (not through `BacktestWorkflowAdapter.__init__`) so it
   also incidentally documents the module's public contract.

## Risks / Trade-offs

- The WAL adoption is the one behavior change in this batch. It is
  scoped tightly (four call sites, one file) and justified above;
  full-suite verification (ground rule 1) is the safety net if any
  test implicitly depended on `journal_mode=DELETE` — none found in
  `tests/` (grep confirms no assertion on this adapter's own db file's
  journal mode).
