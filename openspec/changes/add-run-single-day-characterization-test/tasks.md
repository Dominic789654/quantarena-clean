## 1. Coverage audit

- [x] 1.1 `git grep -n "run_single_day\b" tests/` — exactly one hit
  before this change, `tests/test_db_connection_cleanup.py:229`
  (`assert hasattr(adapter, 'run_single_day')`), which never calls the
  method. Confirms the plan's claim that `run_single_day` is untested.
- [x] 1.2 Confirm `graph.workflow.AgentWorkflow` is importable standalone
  in this environment (`python -c "import graph.workflow as gw;
  print(gw.AgentWorkflow)"` after `setup_paths()`) — it is, so the
  method's existing in-body import statement is a usable stub seam with
  no production code change required.

## 2. Implementation

- [x] 2.1 Add `tests/test_workflow_run_single_day.py` with a
  `_make_fake_agent_workflow(decisions_by_ticker, fail_tickers=None)`
  factory and a `_make_adapter(tmp_path, tickers)` helper.
- [x] 2.2 `test_run_single_day_happy_path_builds_decisions_and_updates_portfolio`
  — monkeypatches `graph.workflow.AgentWorkflow`, runs two tickers (one
  BUY, one HOLD), asserts `BacktestDecision` fields and the resulting
  `cashflow`/positions.
- [x] 2.3 `test_run_single_day_import_error_returns_hold_for_all_tickers`
  — `monkeypatch.setitem(sys.modules, "graph.workflow", None)`, asserts
  HOLD for every priced ticker and an untouched portfolio.
- [x] 2.4 `test_run_single_day_per_ticker_exception_holds_only_that_ticker`
  — one ticker's fake `load_analysts` raises; asserts that ticker HOLDs
  with an `"Error: ..."` justification while the other two tickers'
  BUY decisions and portfolio updates land normally.

## 3. Verification

- [x] 3.1 `.venv_unified/bin/python -m pytest
  tests/test_workflow_run_single_day.py -q` — 3 passed.
- [x] 3.2 `.venv_unified/bin/python -m pytest tests/ -q` — 942 passed +
  3 new = 945 passed, 10 skipped, 0 failed.
- [x] 3.3 `.venv_unified/bin/ruff check .` clean.
