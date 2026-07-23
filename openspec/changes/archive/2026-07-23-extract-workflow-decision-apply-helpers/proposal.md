## Why

Phase 3 step 3 (docs/refactor_program_plan.md). `_normalize_decision_for_portfolio`
and `_update_portfolio_ticker` are both already `@staticmethod`s on
`BacktestWorkflowAdapter` with zero instance-state dependency — they
operate entirely on their `portfolio`/`ticker`/`decision` arguments.
They are the simplest possible extraction after the scoring functions:
pure verbatim moves, no rewrite required.

## What Changes

- Add `backtest/workflow/decision_apply.py` with
  `_normalize_decision_for_portfolio(portfolio, ticker, decision)` and
  `_update_portfolio_ticker(portfolio, ticker, decision)` moved
  verbatim (same bodies, same local `graph.constants`/`graph.schema`
  imports, same docstrings) as plain module functions.
- `BacktestWorkflowAdapter` keeps both names as class-body
  `staticmethod` assignments pointing at the module functions:
  `_normalize_decision_for_portfolio = staticmethod(decision_apply.
  _normalize_decision_for_portfolio)` and
  `_update_portfolio_ticker = staticmethod(decision_apply.
  _update_portfolio_ticker)`. Every existing
  `adapter._normalize_decision_for_portfolio(...)` /
  `self._update_portfolio_ticker(...)` call site (both instance- and
  class-level access) keeps working unchanged.
- No behavior change: identical clamping/rounding logic.

## Capabilities

### New Capabilities
- `workflow-decision-apply-helpers`: the pure portfolio-decision
  application helpers (share-clamping normalization and portfolio
  mutation) used after the portfolio-manager agent produces a
  decision.

### Modified Capabilities
- None.

## Impact

- New `backtest/workflow/decision_apply.py`. Modified
  `backtest/workflow_adapter.py` (two `@staticmethod` bodies replaced
  by `staticmethod(...)` assignments).
- Monkeypatch audit (ground rule 3):
  `git grep -n "_normalize_decision_for_portfolio\|
  _update_portfolio_ticker" tests/` shows only direct calls —
  `tests/test_workflow_adapter_smart_priority.py:279,284` call
  `adapter._normalize_decision_for_portfolio(...)` directly (not a
  monkeypatch); `tests/test_type_annotations.py:93`'s
  `test_update_portfolio_ticker_has_annotations` tests an unrelated
  method with the same name on `deepfund.src.graph.workflow.
  AgentWorkflow` (a completely different class — confirmed by reading
  the test body, which imports `AgentWorkflow` and calls
  `get_type_hints(AgentWorkflow.update_portfolio_ticker)`, not
  `BacktestWorkflowAdapter._update_portfolio_ticker`). No monkeypatch
  of either name exists anywhere in `tests/`.
