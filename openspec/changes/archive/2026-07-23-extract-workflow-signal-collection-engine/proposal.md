## Why

Phase 3 step 20 (docs/refactor_program_plan.md) — the highest-risk step
of the whole decomposition program, and the reason it ships alone with
the full suite run at least twice. `_process_single_ticker_for_signals_v2`,
`_load_shared_analyst_signals`, `_save_shared_analyst_signals`,
`_signal_has_error`, and the two public methods `collect_signals_only`
and `collect_signals_only_parallel_v2` are the parallel analyst-signal
collection engine backing the smart-priority phase 1 pipeline: a
`ThreadPoolExecutor` (one worker per ticker) runs
`_process_single_ticker_for_signals_v2` concurrently, guarded by a
`Lock` around the shared `signals` result dict, with an outer
`ImportError` fallback (DeepFund modules unavailable) and a per-future
exception fallback (one ticker's thread raised). These six names are
heavily coupled to adapter instance state
(`self.market`/`self.api_source`/`self.personality`/`self.db_path`/
`self.shared_analyst_cache`/`self.tickers`/`self.exp_name`/
`self.current_portfolio`/`self.analysts`/`self.llm_provider`/
`self.llm_model`) and to delegator methods extracted in earlier Phase 3
steps (`_resolve_analyst_input_signature`,
`_calculate_priority_score`, `_signal_label`,
`_calculate_signal_consistency`, `_aggregate_signal_from_summary`).
Several tests replace `collect_signals_only_parallel_v2` with an
instance-level `monkeypatch.setattr(adapter, ...)` or a duck-typed fake
adapter entirely (`tests/test_multi_personality_day_orchestrator.py`,
`tests/test_fof_engine.py`), so the same-named-delegator discipline
established in the previous two Phase 3 steps applies here too.

## What Changes

- Add `backtest/workflow/signal_collection.py` with all six functions,
  moved verbatim except for the mandated adapter-passing:
  `_process_single_ticker_for_signals_v2(adapter, ticker, trading_date,
  trading_date_dt, price, config, portfolio_dict)`,
  `_load_shared_analyst_signals(adapter, trading_date, ticker,
  analyst_key, llm_config, input_signature=None)`,
  `_save_shared_analyst_signals(adapter, trading_date, ticker,
  analyst_key, llm_config, analyst_signals, input_signature=None)`,
  `_signal_has_error(signal)` (kept static — no instance state read),
  `collect_signals_only(adapter, trading_date, prices)`,
  `collect_signals_only_parallel_v2(adapter, trading_date, prices,
  max_workers=5, prefetched_analyst_inputs=None)`.
- Every call from one of these six functions to another, or to any
  other adapter delegator (`_resolve_analyst_input_signature`,
  `_calculate_priority_score`, `_signal_label`,
  `_calculate_signal_consistency`, `_aggregate_signal_from_summary`),
  goes through `adapter.<name>(...)`, never a direct module-level call
  — including the `ThreadPoolExecutor.submit(...)` call site, which
  submits the bound delegator `adapter._process_single_ticker_for_signals_v2`
  exactly as the original submitted the bound instance method.
- The thread-pool structure (one `ThreadPoolExecutor` with
  `max_workers` workers, `as_completed` iteration), the `Lock` scope
  (guarding only the `signals` dict writes, created fresh inside
  `collect_signals_only_parallel_v2` — never shared across calls or
  promoted to class/module scope), and both exception-handling layers
  (outer `ImportError`, per-future `Exception`) are preserved exactly.
- `BacktestWorkflowAdapter` keeps same-named delegator methods for all
  six names.

## Capabilities

### New Capabilities
- `workflow-signal-collection-engine`: the parallel analyst-signal
  collection engine (thread-pool orchestration, per-ticker analyst
  execution, shared-cache read/write, both public entry points).

### Modified Capabilities
- None.

## Impact

- New `backtest/workflow/signal_collection.py`. Modified
  `backtest/workflow_adapter.py` (six method bodies replaced by
  delegators; the now-unused top-level `ThreadPoolExecutor`/
  `as_completed`/`Lock` imports removed, since their only remaining
  uses moved with the functions).
- Monkeypatch audit (ground rule 3): `git grep -n
  "collect_signals_only\b\|collect_signals_only_parallel_v2\|
  _process_single_ticker_for_signals_v2\|_load_shared_analyst_signals\|
  _save_shared_analyst_signals\|_signal_has_error" tests/` shows no
  class-attribute monkeypatch of any of the six names on
  `BacktestWorkflowAdapter` — only (a) direct calls on real instances
  (`adapter._process_single_ticker_for_signals_v2(...)`,
  `adapter.collect_signals_only_parallel_v2(...)`, throughout
  `tests/test_workflow_adapter_smart_priority.py`), (b) instance-level
  `monkeypatch.setattr(adapter, "collect_signals_only_parallel_v2",
  fake_collect)` (`tests/test_multi_personality_day_orchestrator.py`
  lines 644/689/709/749/796), and (c) fully separate duck-typed fake
  adapter classes that never call into `BacktestWorkflowAdapter` at
  all (`tests/test_fof_engine.py`'s `_FakeWorkflowAdapter`,
  `tests/test_multi_personality_day_orchestrator.py`'s
  `FakeSharedSignalAdapter`, `tests/test_shared_phase_specialized_
  audit.py`'s `CollectSignalsForbidden`). Instance-level patches work
  identically regardless of the class method's body (instance
  `__dict__` lookup wins over the class attribute), so they are not at
  risk from this move; the risk this change's internal-call discipline
  actually defends against is the *thread-pool submission* and the
  *mutual calls between the six functions and the earlier Phase 3
  steps' delegators* (`_resolve_analyst_input_signature` et al.),
  verified experimentally (see below).
  Experimentally verified during implementation: temporarily changing
  the `ThreadPoolExecutor.submit(...)` call from
  `adapter._process_single_ticker_for_signals_v2` to the bare module
  function `_process_single_ticker_for_signals_v2(adapter, ...)`, then
  separately swapping in a class-attribute-patched fake for
  `_process_single_ticker_for_signals_v2` — the fake was never called
  (empty call log) with the bare-call regression, and was called for
  both tickers once reverted to the delegator call. Reverted before
  landing this change.
- Per the plan (ground rule 1 / step 20's explicit instruction), the
  full suite was run **twice**, back to back, after landing this
  change: both runs report 945 passed, 10 skipped, 0 failed — no
  thread-pool-related nondeterminism observed.
