## Context

`backtest/workflow_adapter.py` defines five signal-scoring helpers used
by the smart-priority phase-1 signal collection path
(`_process_single_ticker_for_signals_v2` and
`run_single_day_with_smart_priority`): two `@staticmethod`s
(`_signal_label`, `_aggregate_signal_from_summary`) that are already
pure; two instance methods (`_calculate_priority_score`,
`_calculate_signal_consistency`) whose only "instance" dependency is
calling `self._signal_label(...)` — a bare-static-method call routed
through `self` purely as a matter of style, not state; and one instance
method (`_get_smart_priority_order`) whose only instance-state read is
`self.tickers.copy()` in the empty-`signals` fallback branch.

## Goals / Non-Goals

**Goals:** make all five callable as plain module functions in
`backtest/workflow/scoring.py`; perform the one rewrite the plan calls
out (`self._signal_label(...)` -> direct `_signal_label(...)` calls
inside the two ported instance methods); lift `_get_smart_priority_order`'s
implicit `self.tickers` read into an explicit parameter; keep every
`adapter.<name>(...)` call site and every existing monkeypatch (class-
or instance-level) working via same-named delegators on
`BacktestWorkflowAdapter`; switch `test_priority_sorting.py` onto the
real functions.

**Non-Goals:** changing scoring math, thresholds, or the sort key used
by `_get_smart_priority_order`; changing `collect_signals_only`'s or
`_process_single_ticker_for_signals_v2`'s call sites beyond the
rewrite already covered by the delegator (they keep calling
`self._calculate_priority_score(...)` / `self._signal_label(...)` etc.
unchanged — only the *implementation* those names resolve to moves).

## Decisions

1. **Module functions keep their original (underscore-prefixed) names**
   in `backtest/workflow/scoring.py`, matching
   docs/refactor_program_plan.md's Phase 3 execution brief listing
   `_calculate_priority_score`, `_calculate_signal_consistency`,
   `_signal_label`, `_aggregate_signal_from_summary`,
   `_get_smart_priority_order` as the five names to move — this keeps
   the audit trail (`git grep` for these exact names) valid before and
   after the move, and keeps the delegator methods a visually trivial
   diff (`return scoring._calculate_priority_score(analyst_signals)`).
2. **`self._signal_label(...)` -> `_signal_label(...)` rewrite**: inside
   the ported `_calculate_priority_score` and
   `_calculate_signal_consistency` function bodies, every call site
   that read `self._signal_label(signal)` becomes a direct call to the
   module-level `_signal_label(signal)` in the same module. This is
   the one explicitly-mandated non-verbatim edit — semantically a
   no-op (same function object, no dispatch difference) but
   mechanically required because the ported functions are no longer
   methods and have no `self`.
3. **`_get_smart_priority_order(signals, tickers)`**: the instance
   method's `return self.tickers.copy()` fallback becomes
   `return list(tickers)` in the module function — `list(tickers)` is
   used instead of a hypothetical `tickers.copy()` because the
   delegator passes `self.tickers` (a `List[str]`) positionally and
   `list(...)` is the copy-idiom that works for any sequence the
   caller might pass, matching what `.copy()` would have done for the
   `List[str]` case that is the only one ever exercised. No behavior
   change for existing callers (`self.tickers` is always a `list`).
4. **Delegators**: `BacktestWorkflowAdapter._signal_label =
   staticmethod(scoring._signal_label)` and
   `BacktestWorkflowAdapter._aggregate_signal_from_summary =
   staticmethod(scoring._aggregate_signal_from_summary)` are class-body
   assignments (identical calling convention to the original
   `@staticmethod` defs — `adapter._signal_label(x)` and
   `BacktestWorkflowAdapter._signal_label(x)` both keep working).
   `_calculate_priority_score`, `_calculate_signal_consistency`, and
   `_get_smart_priority_order` become one-line instance methods (not
   `staticmethod` assignments) because the last one still needs
   `self.tickers` to build its call, and keeping all three as regular
   `def` methods is more consistent to read than mixing assignment- and
   def-style delegators for methods with different signatures.
5. **`test_priority_sorting.py`**: replaces its local
   `calculate_priority_score(analyst_signals)` and
   `get_smart_priority_order(signals, original_tickers)` function
   definitions with `from backtest.workflow.scoring import
   _calculate_priority_score as calculate_priority_score` and
   `from backtest.workflow.scoring import _get_smart_priority_order as
   get_smart_priority_order` — the real functions' parameter order and
   names (`_get_smart_priority_order(signals, tickers)`) match the
   shadow implementation's `(signals, original_tickers)` exactly, so
   no test-body changes are needed beyond the two import lines.

## Risks / Trade-offs

- `MockAnalystSignal` in `test_priority_sorting.py` sets `.signal` to
  an already-uppercase string with no surrounding whitespace, so the
  real `_signal_label`'s `.strip().upper()` (present in the original,
  absent from the shadow's bare `str(...)`) is a no-op for every
  existing test case — confirmed by running the suite after the
  switch; no test assertions needed adjustment.
