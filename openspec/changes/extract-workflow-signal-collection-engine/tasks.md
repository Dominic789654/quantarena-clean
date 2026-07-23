## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "collect_signals_only\b\|
  collect_signals_only_parallel_v2\|_process_single_ticker_for_signals_v2\|
  _load_shared_analyst_signals\|_save_shared_analyst_signals\|
  _signal_has_error" tests/` — no class-attribute patches of any of
  the six names on `BacktestWorkflowAdapter`. Direct calls on real
  instances throughout `tests/test_workflow_adapter_smart_priority.py`;
  instance-level `monkeypatch.setattr(adapter,
  "collect_signals_only_parallel_v2", fake_collect)` in
  `tests/test_multi_personality_day_orchestrator.py` (5 occurrences);
  fully separate duck-typed fake adapter classes (never inheriting
  `BacktestWorkflowAdapter`) in `tests/test_fof_engine.py`,
  `tests/test_multi_personality_day_orchestrator.py`, and
  `tests/test_shared_phase_specialized_audit.py`.
- [x] 1.2 Identify the one genuinely new patch-propagation risk this
  step introduces: the `ThreadPoolExecutor.submit(...)` call site.
  Confirm by inspection that it currently submits the bound instance
  method `self._process_single_ticker_for_signals_v2`, and design the
  moved version to submit `adapter._process_single_ticker_for_signals_v2`
  (the delegator), not a bare module call.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/signal_collection.py` with all six
  functions. `_signal_has_error` keeps its original no-adapter
  `@staticmethod` signature (moved verbatim). The other five take
  `adapter` as their first parameter, replacing `self`; every internal
  call — including the `ThreadPoolExecutor.submit(...)` site — goes
  through `adapter.<name>(...)`.
- [x] 2.2 `backtest/workflow_adapter.py`: replace the six method bodies
  with delegators (`def` instance methods calling
  `signal_collection.<name>(self, ...)` for the five that need adapter
  state, `staticmethod(signal_collection._signal_has_error)` for the
  one that does not). Remove the now-unused top-level
  `ThreadPoolExecutor`/`as_completed`/`Lock` imports (their only
  remaining uses moved with the functions).
- [x] 2.3 Experimentally verify the patch-propagation discipline at the
  thread-pool submission site: temporarily change the
  `ThreadPoolExecutor.submit(...)` call from
  `adapter._process_single_ticker_for_signals_v2` to
  `_process_single_ticker_for_signals_v2` (bare module call, `adapter`
  passed as an explicit argument), then class-attribute-patch
  `BacktestWorkflowAdapter._process_single_ticker_for_signals_v2` with
  a call-logging fake and run `collect_signals_only_parallel_v2`;
  confirm the fake's call log is empty (the regression is silent — no
  exception, just wrong signals). Revert, rerun the same experiment,
  confirm the fake's call log now has both tickers.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest
  tests/test_workflow_adapter_smart_priority.py
  tests/test_multi_personality_day_orchestrator.py
  tests/test_fof_engine.py tests/test_workflow_run_single_day.py
  tests/test_shared_phase_specialized_audit.py -q` — 52 passed, 0
  failed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` run **twice**,
  back to back, per the plan's explicit instruction for this
  highest-risk step — both runs: 945 passed, 10 skipped, 0 failed
  (identical).
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
