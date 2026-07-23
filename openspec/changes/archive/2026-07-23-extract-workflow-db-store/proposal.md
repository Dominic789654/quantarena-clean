## Why

Phase 3 step 4, last of this first batch (docs/refactor_program_plan.md).
`_create_temp_db`, `_setup_database`, `_ensure_config`,
`_get_or_create_portfolio`, and `_update_portfolio` are the sqlite
DDL+CRUD glue for `BacktestWorkflowAdapter`'s isolated per-run database
(config/portfolio/decision/signal tables). They are instance methods
that read `self.db_path`, `self.exp_name`, `self.tickers`,
`self.llm_model`, `self.llm_provider`, `self.config_id`, and
`self.current_portfolio` — extracting them requires lifting those into
explicit parameters (unlike the two previous changes in this batch,
which were pure/static). This is also the one change in the batch that
touches raw `sqlite3.connect(...)` call sites, so it is the place to
adopt the Phase-1 `shared.db` pragma helpers
(`configure_sqlite_connection`/`ensure_parent_dir`) that
`deepfund/src/database/sqlite_helper.py` and `sqlite_setup.py` already
use, closing a gap where this adapter's own db file was never upgraded
to WAL. Also adds the DDL schema-smoke test the plan calls out as
missing (none of today's tests assert on the four tables/indices
existing).

## What Changes

- Add `backtest/workflow/db_store.py` with five module functions,
  ported from the corresponding instance methods with explicit
  parameters replacing `self.*` reads:
  - `_create_temp_db() -> str` — unchanged signature (never read
    `self` in the original either).
  - `_setup_database(db_path: str) -> None` — DDL only; replaces
    `self.db_path` with the `db_path` parameter, and the manual
    `os.makedirs(os.path.dirname(db_path), exist_ok=True)` with
    `shared.db.ensure_parent_dir(db_path)`.
  - `_ensure_config(db_path: str, exp_name: str, tickers: List[str],
    llm_model: str, llm_provider: str) -> str` — replaces
    `self.db_path`/`self.exp_name`/`self.tickers`/`self.llm_model`/
    `self.llm_provider` with parameters.
  - `_get_or_create_portfolio(db_path: str, config_id: str,
    trading_date: str, current_portfolio: Dict[str, Any]) -> Dict[str,
    Any]` — replaces `self.db_path`/`self.config_id`/
    `self.current_portfolio` with parameters; mutates
    `current_portfolio["id"]` in place (same as the original mutating
    `self.current_portfolio["id"]`) and returns a shallow copy, exactly
    matching the original's contract.
  - `_update_portfolio(db_path: str, current_portfolio: Dict[str, Any],
    trading_date: str) -> None` — replaces `self.db_path`/
    `self.current_portfolio` with parameters; read-only with respect
    to `current_portfolio`.
  - Every raw `sqlite3.connect(db_path)` call site in these five
    functions becomes `configure_sqlite_connection(sqlite3.connect(
    db_path))` (WAL + busy_timeout + synchronous=NORMAL, matching
    `shared.db`'s canonical pragmas — see design.md for why this is
    safe for this specific db file).
- `BacktestWorkflowAdapter` keeps same-named delegator instance methods
  for all five, each supplying the relevant `self.*` attributes as
  arguments: `_create_temp_db(self)`, `_setup_database(self)`,
  `_ensure_config(self)`, `_get_or_create_portfolio(self,
  trading_date)`, `_update_portfolio(self, trading_date)`. Every
  existing `self._create_temp_db()`, `adapter._create_temp_db()` (used
  directly in `tests/test_workflow_adapter_smart_priority.py`), and
  internal `self._get_or_create_portfolio(...)`/`self._update_portfolio(
  ...)` call site keeps working unchanged.
- Add a new DDL schema-smoke test asserting the `config`, `portfolio`,
  `decision`, `signal` tables and their five indices exist after
  `_setup_database` runs (none exists today per the plan).

## Capabilities

### New Capabilities
- `workflow-db-store`: the sqlite DDL and CRUD glue
  (`_create_temp_db`, `_setup_database`, `_ensure_config`,
  `_get_or_create_portfolio`, `_update_portfolio`) backing
  `BacktestWorkflowAdapter`'s isolated per-run database.

### Modified Capabilities
- None.

## Impact

- New `backtest/workflow/db_store.py`, new test module for the DDL
  schema smoke test. Modified `backtest/workflow_adapter.py` (five
  method bodies replaced by delegators calling the module functions
  with explicit arguments).
- Behavior change (explicitly called out, not a verbatim move): these
  short-lived connections now get WAL/busy_timeout/synchronous=NORMAL
  pragmas via `configure_sqlite_connection`. See design.md for the
  safety argument (same `signal_flux`-family db-file pattern already
  WAL'd elsewhere in the codebase by Phase 1's
  `adopt-shared-pragmas-in-deepfund-sqlite` change).
- Monkeypatch audit (ground rule 3): `git grep -n "_create_temp_db\|
  _setup_database\|_ensure_config\|_get_or_create_portfolio\|
  _update_portfolio\b" tests/` shows only direct calls, no
  monkeypatches: `tests/test_workflow_adapter_smart_priority.py:101-111`
  (`test_create_temp_db_path_is_unique_when_called_rapidly`) calls
  `adapter._create_temp_db()` 50 times directly and asserts
  uniqueness — exercised unchanged since `_create_temp_db()` takes no
  parameters either way. No test patches `_setup_database`,
  `_ensure_config`, `_get_or_create_portfolio`, or `_update_portfolio`
  by any string path; they are exercised indirectly through
  `BacktestWorkflowAdapter.__init__` and `run_single_day*` across many
  other tests in that file and in
  `tests/test_multi_personality_day_orchestrator.py`.
