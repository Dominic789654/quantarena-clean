# workflow-db-store Specification

## Purpose
TBD - created by archiving change extract-workflow-db-store. Update Purpose after archive.
## Requirements
### Requirement: Temp database path generation is unique per call
`backtest.workflow.db_store._create_temp_db()` SHALL return a path under `<project_root>/data/backtest/` containing a timestamp and a random hex suffix such that repeated calls within the same process never collide.

#### Scenario: Rapid repeated calls produce unique paths
- **WHEN** `_create_temp_db()` is called 50 times in immediate succession
- **THEN** all 50 returned paths are distinct

### Requirement: Database setup creates the required schema
`backtest.workflow.db_store._setup_database(db_path)` SHALL create the `config`, `portfolio`, `decision`, and `signal` tables (if not already present) along with the `idx_config_exp_name`, `idx_portfolio_config`, `idx_portfolio_trading_date`, `idx_decision_portfolio`, and `idx_signal_portfolio` indices, using a connection configured via `shared.db.configure_sqlite_connection`, and SHALL create the database file's parent directory via `shared.db.ensure_parent_dir` if it does not already exist.

#### Scenario: Fresh db_path gets all tables and indices
- **WHEN** `_setup_database(db_path)` is called against a path whose file does not yet exist
- **THEN** querying `sqlite_master` for that database shows all four tables and all five indices

#### Scenario: Setup is idempotent
- **WHEN** `_setup_database(db_path)` is called twice against the same path
- **THEN** the second call does not raise and the schema is unchanged

### Requirement: Config lookup is idempotent by exp_name
`backtest.workflow.db_store._ensure_config(db_path, exp_name, tickers, llm_model, llm_provider)` SHALL return the existing config `id` when a row with the given `exp_name` already exists, and otherwise SHALL insert a new config row (with `has_planner=False`) and return its newly generated `id`.

#### Scenario: Second call with the same exp_name reuses the config
- **WHEN** `_ensure_config` is called twice with the same `db_path` and `exp_name`
- **THEN** both calls return the same config `id` and only one row exists in the `config` table

### Requirement: Portfolio creation inserts a new row per trading date and updates the given portfolio dict
`backtest.workflow.db_store._get_or_create_portfolio(db_path, config_id, trading_date, current_portfolio)` SHALL insert a new `portfolio` row for the given `trading_date` computed from `current_portfolio`'s cashflow and positions, set `current_portfolio["id"]` to the new row's id, and return a shallow copy of the (mutated) `current_portfolio`.

#### Scenario: Portfolio dict is mutated with the new id
- **WHEN** `_get_or_create_portfolio(db_path, config_id, trading_date, current_portfolio)` is called
- **THEN** `current_portfolio["id"]` equals the inserted portfolio row's `id`, and the returned dict is a distinct object with the same contents

### Requirement: Portfolio update persists cashflow and positions
`backtest.workflow.db_store._update_portfolio(db_path, current_portfolio, trading_date)` SHALL update the `portfolio` row identified by `current_portfolio["id"]` with the current `cashflow`, recomputed `total_assets`, and serialized `positions`, without mutating `current_portfolio`.

#### Scenario: Update reflects new cashflow and positions
- **WHEN** `current_portfolio`'s cashflow and positions change and `_update_portfolio(db_path, current_portfolio, trading_date)` is called
- **THEN** re-reading the `portfolio` row by `current_portfolio["id"]` shows the updated `cashflow`, `total_assets`, and `positions`

### Requirement: workflow_adapter delegators supply instance state as explicit arguments
`BacktestWorkflowAdapter` SHALL expose `_create_temp_db`, `_setup_database`, `_ensure_config`, `_get_or_create_portfolio`, and `_update_portfolio` as same-named instance methods that delegate to `backtest.workflow.db_store`'s module functions, supplying `self.db_path`, `self.exp_name`, `self.tickers`, `self.llm_model`, `self.llm_provider`, `self.config_id`, and `self.current_portfolio` as needed, so every existing `self.<name>(...)` and `adapter.<name>(...)` call site keeps working unchanged.

#### Scenario: Direct instance call keeps working
- **WHEN** a test calls `adapter._create_temp_db()` directly
- **THEN** it returns a valid, unique temp db path exactly as before the extraction

