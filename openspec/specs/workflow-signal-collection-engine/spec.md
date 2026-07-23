# workflow-signal-collection-engine Specification

## Purpose
TBD - created by archiving change extract-workflow-signal-collection-engine. Update Purpose after archive.
## Requirements
### Requirement: Parallel signal collection processes every priced ticker concurrently via a per-call ThreadPoolExecutor
`backtest.workflow.signal_collection.collect_signals_only_parallel_v2(adapter, trading_date, prices, max_workers=5, prefetched_analyst_inputs=None)` SHALL submit one `adapter._process_single_ticker_for_signals_v2` call per ticker present in both `adapter.tickers` and `prices` to a `ThreadPoolExecutor` sized `max_workers`, collect each result under a function-local `Lock` guarding the shared result dict, and return a dict keyed by ticker.

#### Scenario: All priced tickers appear in the result
- **WHEN** `collect_signals_only_parallel_v2(adapter, trading_date, prices, max_workers=3)` is called with `prices` covering every ticker in `adapter.tickers`
- **THEN** the returned dict has exactly one entry per ticker in `adapter.tickers`

### Requirement: A single ticker's worker exception does not affect other tickers' results
`backtest.workflow.signal_collection.collect_signals_only_parallel_v2` SHALL, if a given ticker's future raises any exception, record a zero-signal placeholder result (`analyst_signals=[]`, `priority_score=0.0`, all-zero summary) for that ticker only, and SHALL still return normal results for every other ticker whose future succeeded.

#### Scenario: One ticker's thread raises, others still return real results
- **WHEN** ticker `BBB`'s submitted future raises an exception while `AAA`'s future completes normally
- **THEN** the returned dict has a zero-signal placeholder for `BBB` and `AAA`'s real result unchanged

### Requirement: DeepFund module import failure returns zero-signal placeholders for every priced ticker
`backtest.workflow.signal_collection.collect_signals_only_parallel_v2` SHALL, if importing `util.db_helper` or `database.sqlite_helper` raises `ImportError`, return a zero-signal placeholder result for every ticker present in `prices`, without submitting any work to a thread pool.

#### Scenario: Import failure short-circuits before any thread is spawned
- **WHEN** `from util.db_helper import db_initialize, get_db` raises `ImportError` during `collect_signals_only_parallel_v2`
- **THEN** every ticker in `prices` gets a zero-signal placeholder result and no `ThreadPoolExecutor` is created

### Requirement: Per-ticker signal processing checks the shared analyst cache before invoking an analyst, and calls only adapter delegators for cache and signature resolution
`backtest.workflow.signal_collection._process_single_ticker_for_signals_v2(adapter, ticker, trading_date, trading_date_dt, price, config, portfolio_dict)` SHALL, for each valid configured analyst, resolve an input signature via `adapter._resolve_analyst_input_signature`, check `adapter._load_shared_analyst_signals` for a cache hit before running the analyst function, and — on a cache miss that runs successfully — persist the result via `adapter._save_shared_analyst_signals`, using the delegator on each call (never a bare module-level call), so that class-attribute patches of any of these names on `BacktestWorkflowAdapter` are honored.

#### Scenario: Cache hit skips the analyst function entirely
- **WHEN** `adapter._load_shared_analyst_signals` returns a non-`None` list of signals for a given analyst/ticker
- **THEN** `_process_single_ticker_for_signals_v2` extends its collected signals with that list and does not call the analyst function for that analyst

#### Scenario: Class-attribute patch of _process_single_ticker_for_signals_v2 is honored by the thread-pool submission
- **WHEN** `_process_single_ticker_for_signals_v2` is monkeypatched as a class attribute on `BacktestWorkflowAdapter`, and `collect_signals_only_parallel_v2` is called
- **THEN** the `ThreadPoolExecutor` submission invokes the monkeypatched function for every ticker, not the original

### Requirement: Shared analyst signal save is skipped for empty or error-tagged signal batches
`backtest.workflow.signal_collection._save_shared_analyst_signals(adapter, trading_date, ticker, analyst_key, llm_config, analyst_signals, input_signature=None)` SHALL do nothing if `adapter.shared_analyst_cache` is `None`, if `analyst_signals` is empty, or if any signal in `analyst_signals` is `_signal_has_error`-tagged (justification starting with `"[Error]"`), and SHALL otherwise call `adapter.shared_analyst_cache.save(...)`.

#### Scenario: An error-tagged signal batch is never cached
- **WHEN** `analyst_signals` contains at least one signal whose `justification` starts with `"[Error]"`
- **THEN** `_save_shared_analyst_signals` does not call `adapter.shared_analyst_cache.save`

### Requirement: collect_signals_only reshapes the enhanced-signal dict into the backward-compatible single-signal format via the adapter delegator
`backtest.workflow.signal_collection.collect_signals_only(adapter, trading_date, prices)` SHALL call `adapter.collect_signals_only_parallel_v2(trading_date, prices)` and return, for each ticker, a dict with `ticker`, `signal` (via `adapter._aggregate_signal_from_summary`), `justification`, `confidence`, `summary`, `priority_score`, and `analyst_signals` keys.

#### Scenario: Output shape matches the legacy single-signal contract
- **WHEN** `collect_signals_only(adapter, trading_date, prices)` is called
- **THEN** every ticker's entry in the returned dict has exactly the keys `ticker`, `signal`, `justification`, `confidence`, `summary`, `priority_score`, `analyst_signals`

### Requirement: workflow_adapter delegators keep every existing call site and monkeypatch working
`BacktestWorkflowAdapter` SHALL expose `_process_single_ticker_for_signals_v2`, `_load_shared_analyst_signals`, `_save_shared_analyst_signals`, `_signal_has_error`, `collect_signals_only`, and `collect_signals_only_parallel_v2` as same-named class attributes (static or instance methods) that delegate to `backtest.workflow.signal_collection`'s module functions, so that instance-level monkeypatches (`monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2", fake_collect)`), class-attribute monkeypatches, and direct calls (`adapter._process_single_ticker_for_signals_v2(...)`) all keep working exactly as before the extraction.

#### Scenario: Instance-level monkeypatch of collect_signals_only_parallel_v2 keeps working
- **WHEN** a test does `monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2", fake_collect)` and then calls `adapter.run_single_day_with_smart_priority(...)`
- **THEN** `fake_collect`'s return value is used, exactly as before this extraction

