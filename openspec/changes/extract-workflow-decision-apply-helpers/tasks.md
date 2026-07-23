## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_normalize_decision_for_portfolio\|
  _update_portfolio_ticker" tests/` — direct calls only in
  `tests/test_workflow_adapter_smart_priority.py:279,284`
  (`adapter._normalize_decision_for_portfolio(...)`); the
  `_update_portfolio_ticker` hit in `tests/test_type_annotations.py:93`
  is an unrelated method on `deepfund.src.graph.workflow.AgentWorkflow`
  (different class, same name — confirmed by reading the test body).
  No monkeypatch of either `BacktestWorkflowAdapter` name exists.

## 2. Implementation

- [x] 2.1 Add `backtest/workflow/decision_apply.py` with
  `_normalize_decision_for_portfolio` and `_update_portfolio_ticker`
  moved verbatim as plain module functions (local
  `graph.constants`/`graph.schema` imports kept inside each function
  body, unchanged).
- [x] 2.2 `backtest/workflow_adapter.py`: replace both `@staticmethod`
  bodies with `staticmethod(decision_apply.<name>)` class-body
  assignments at the same source position.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest tests/ -q` — 937 passed,
  10 skipped, 0 failed (baseline unchanged; existing coverage in
  `test_workflow_adapter_smart_priority.py` exercises both functions
  directly).
- [x] 3.2 `.venv_unified/bin/ruff check .` clean.
