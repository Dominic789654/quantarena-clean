## Why

Phase 3 step 19 (docs/refactor_program_plan.md). `run_single_day` is
`BacktestWorkflowAdapter`'s only public method with zero test coverage
today — `git grep -n "run_single_day\b" tests/` shows exactly one hit,
`tests/test_db_connection_cleanup.py:229`'s
`assert hasattr(adapter, 'run_single_day')`, which never calls it. It
is also the last consumer, inside `workflow_adapter.py`, of the real
`graph.workflow.AgentWorkflow` sequential (non-parallel, non-smart-
priority) path, and has three distinct branches worth characterizing
before the next, higher-risk extraction step touches the surrounding
code: the happy path, the outer `ImportError` fallback (DeepFund
modules unavailable), and the per-ticker `except Exception` fallback
(one ticker's workflow blows up, the rest still get real decisions).

## What Changes

- Add `tests/test_workflow_run_single_day.py` with three
  characterization tests:
  1. `test_run_single_day_happy_path_builds_decisions_and_updates_portfolio`
     — monkeypatches the `AgentWorkflow` attribute on the already-
     imported `graph.workflow` module with a fake workflow class, runs
     `run_single_day` for two tickers, and asserts the resulting
     `BacktestDecision` fields (`ticker`, `action`, `shares`, `price`,
     `justification`, `analyst_signals`) and the adapter's portfolio
     update (`cashflow`, per-ticker `shares`/`value`).
  2. `test_run_single_day_import_error_returns_hold_for_all_tickers` —
     forces `from graph.workflow import AgentWorkflow` to raise
     `ImportError` via `monkeypatch.setitem(sys.modules,
     "graph.workflow", None)`, and asserts every priced ticker gets a
     HOLD decision with an `"Import error: ..."` justification and the
     portfolio is left untouched.
  3. `test_run_single_day_per_ticker_exception_holds_only_that_ticker` —
     one ticker's fake workflow raises inside `load_analysts`; asserts
     that ticker alone gets a HOLD decision with an `"Error: ..."`
     justification while the other two tickers get their real BUY
     decisions and portfolio updates.
- No production code changes. This is a test-only change, per the
  task's constraint; no testability blocker was encountered
  (`graph.workflow.AgentWorkflow` is stubbable at its existing
  in-method import site without any adapter code change).

## Capabilities

### New Capabilities
- None (test-only change adding characterization coverage for an
  existing, unspecified public method's behavior — no new spec-level
  capability is introduced; see design.md for why this change still
  carries a spec delta documenting the now-characterized behavior of
  `run_single_day`, framed as an addition to the existing
  `workflow-run-single-day` capability).

### Modified Capabilities
- None.

## Impact

- New `tests/test_workflow_run_single_day.py` only. No changes to
  `backtest/workflow_adapter.py` or any other production file.
- Monkeypatch audit (ground rule 3): this change does not touch any
  production code, so there is nothing to audit for breakage; the new
  tests themselves use `monkeypatch.setattr` (on `graph.workflow.
  AgentWorkflow`, a module attribute, not a `BacktestWorkflowAdapter`
  class attribute) and `monkeypatch.setitem` (on `sys.modules`), both
  scoped to each test via pytest's `monkeypatch` fixture and
  automatically reverted afterward.
