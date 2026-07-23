## Why

Phase 3 step 2 (docs/refactor_program_plan.md). Five signal-scoring
helpers in `backtest/workflow_adapter.py` are nearly pure functions of
their arguments — none read `BacktestWorkflowAdapter` instance state
except `_get_smart_priority_order`'s empty-input fallback
(`self.tickers.copy()`). Extracting them into `backtest/workflow/
scoring.py` continues the Phase 3 package build-out and, per the plan,
requires switching `tests/test_priority_sorting.py` off its
hand-copied shadow implementation onto the real code — closing a test
gap where the "unit tests" for this logic were testing a maintained-by-
hand duplicate, not the production functions.

## What Changes

- Add `backtest/workflow/scoring.py` with five module-level functions,
  ported from the corresponding `BacktestWorkflowAdapter` methods:
  - `_signal_label(signal)` — moved verbatim (was `@staticmethod`).
  - `_aggregate_signal_from_summary(summary)` — moved verbatim (was
    `@staticmethod`).
  - `_calculate_priority_score(analyst_signals)` — ported from the
    instance method; every internal `self._signal_label(...)` call
    becomes a direct call to the module-level `_signal_label(...)`
    (the one explicitly-called-out rewrite in the plan). No other
    logic changes.
  - `_calculate_signal_consistency(analyst_signals)` — same rewrite
    (`self._signal_label` -> `_signal_label`).
  - `_get_smart_priority_order(signals, tickers)` — ported from the
    instance method `_get_smart_priority_order(self, signals)`; the
    only instance-state read (`self.tickers.copy()` in the empty-input
    fallback) becomes an explicit `tickers` parameter used the same
    way (`list(tickers)` — see design.md for why `list(...)` replaces
    `.copy()`).
- `BacktestWorkflowAdapter` keeps same-named delegator methods for all
  five: `_signal_label` and `_aggregate_signal_from_summary` become
  `staticmethod` assignments pointing at the module functions;
  `_calculate_priority_score` and `_calculate_signal_consistency`
  become one-line instance methods that call the module function with
  `analyst_signals`; `_get_smart_priority_order(self, signals)` becomes
  a one-line instance method that calls
  `scoring._get_smart_priority_order(signals, self.tickers)`. Every
  existing `adapter._calculate_priority_score(...)`,
  `adapter._get_smart_priority_order(...)`, and instance-level
  monkeypatch (`monkeypatch.setattr(adapter, "_get_smart_priority_order",
  ...)`) keeps working unchanged.
- `tests/test_priority_sorting.py` drops its hand-copied
  `calculate_priority_score` / `get_smart_priority_order` module-level
  functions and instead imports the real
  `backtest.workflow.scoring._calculate_priority_score` /
  `._get_smart_priority_order` (aliased to the test's existing local
  names so the test bodies are otherwise unchanged).
- No behavior change beyond the mandated `self._signal_label` ->
  `_signal_label` rewrite, which is a no-op rewrite (same function,
  called directly instead of through `self`).

## Capabilities

### New Capabilities
- `workflow-scoring-functions`: the pure signal-scoring/prioritization
  helpers (`_signal_label`, `_aggregate_signal_from_summary`,
  `_calculate_priority_score`, `_calculate_signal_consistency`,
  `_get_smart_priority_order`) used by the backtest workflow adapter's
  smart-priority phase.

### Modified Capabilities
- None.

## Impact

- New `backtest/workflow/scoring.py`. Modified
  `backtest/workflow_adapter.py` (five method bodies replaced by
  delegators) and `tests/test_priority_sorting.py` (shadow
  implementation replaced by real imports).
- Monkeypatch audit (ground rule 3):
  `git grep -n "_calculate_priority_score\|_signal_label\|
  _get_smart_priority_order\|_calculate_signal_consistency\|
  _aggregate_signal_from_summary" tests/` shows:
  `tests/test_priority_sorting.py` — the shadow-implementation file,
  addressed by this change (no monkeypatch, only local duplicate
  functions being replaced with real imports).
  `tests/test_workflow_adapter_smart_priority.py:220` —
  `monkeypatch.setattr(adapter, "_get_smart_priority_order", lambda
  signals: ["AAA", "BBB"])`: an **instance-attribute** patch on a live
  `adapter` object, not a class-attribute or bare-global string path.
  Instance-attribute patching works identically regardless of whether
  the class attribute being shadowed is a plain method or a
  `staticmethod`/delegator — verified by re-running this test after
  the change.
  No test patches `_calculate_priority_score`, `_signal_label`,
  `_calculate_signal_consistency`, or `_aggregate_signal_from_summary`
  by any string path.
