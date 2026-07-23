## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_calculate_priority_score\|_signal_label\|
  _get_smart_priority_order\|_calculate_signal_consistency\|
  _aggregate_signal_from_summary" tests/` — hits in
  `tests/test_priority_sorting.py` (shadow implementation, addressed
  by this change) and `tests/test_workflow_adapter_smart_priority.py:220`
  (`monkeypatch.setattr(adapter, "_get_smart_priority_order", lambda
  signals: ["AAA", "BBB"])` — instance-attribute patch, survives any
  refactor of the class-level implementation).
- [x] 1.2 Confirm no class-attribute or `monkeypatch.setattr("backtest.
  workflow_adapter.BacktestWorkflowAdapter._<name>", ...)` string-path
  patches exist for any of the five names — none found.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/scoring.py` with `_signal_label` and
  `_aggregate_signal_from_summary` moved verbatim.
- [x] 2.2 Port `_calculate_priority_score(analyst_signals)` and
  `_calculate_signal_consistency(analyst_signals)` into
  `scoring.py` as module functions; rewrite every internal
  `self._signal_label(...)` call to `_signal_label(...)` (the mandated
  rewrite) — no other logic change.
- [x] 2.3 Port `_get_smart_priority_order(signals, tickers)` into
  `scoring.py`; replace the empty-input fallback
  `return self.tickers.copy()` with `return list(tickers)`.
- [x] 2.4 `backtest/workflow_adapter.py`: replace the five method
  bodies with delegators — `_signal_label` and
  `_aggregate_signal_from_summary` as `staticmethod(scoring.<name>)`
  class-body assignments; `_calculate_priority_score`,
  `_calculate_signal_consistency`, `_get_smart_priority_order` as
  one-line instance methods calling the module functions (the last one
  passing `self.tickers`).
- [x] 2.5 `tests/test_priority_sorting.py`: delete the local
  `calculate_priority_score`/`get_smart_priority_order` function
  bodies; import the real functions from `backtest.workflow.scoring`
  aliased to the same local names.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 937 passed,
  10 skipped, 0 failed (test_priority_sorting.py's existing tests now
  exercise the real production code; no new tests added since coverage
  is unchanged in shape, only in target).
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
