## Context

`BacktestWorkflowAdapter.run_single_day` (currently
`backtest/workflow_adapter.py:192-359`) is the sequential, one-workflow-
per-ticker path: for each ticker with a price, it builds a real
`graph.workflow.AgentWorkflow`, runs it through `build().invoke(state)`,
and either records the resulting `BacktestDecision` (updating the
working `Portfolio` via `workflow.update_portfolio_ticker`) or falls
back to a HOLD decision if that ticker's processing raised. If the
DeepFund modules (`graph.workflow`, `graph.schema`, `util.db_helper`,
`database.sqlite_helper`) fail to import at all, every ticker gets a
HOLD decision with an `"Import error: ..."` justification instead.

This method has never been exercised by any test — `run_single_day_with_
precollected_signals` and `run_single_day_with_smart_priority` (its two
siblings, both added later) have coverage in
`tests/test_workflow_adapter_smart_priority.py`, but the plain
sequential path does not. The upcoming
`extract-workflow-signal-collection-engine` step (Phase 3's
highest-risk step) touches code that `run_single_day`'s siblings share
(`_process_single_ticker_for_signals_v2`, the shared analyst/phase1
caches); characterizing `run_single_day` itself first — even though it
does not call into the signal-collection engine — locks down a
regression net for the surrounding file before that step lands.

## Goals / Non-Goals

**Goals:** cover all three observable branches of `run_single_day`
(happy path, `ImportError` fallback, per-ticker exception fallback)
with tests that construct a real `BacktestWorkflowAdapter` against a
`tmp_path` SQLite file and only stub the one seam that would otherwise
require live DeepFund/LLM/API infrastructure —
`graph.workflow.AgentWorkflow` itself.

**Non-Goals:** testing `AgentWorkflow`'s own internals (covered, if at
all, elsewhere); changing `run_single_day`'s behavior; testing
`run_single_day_with_precollected_signals` or
`run_single_day_with_smart_priority` (already covered).

## Decisions

1. **Stub `graph.workflow.AgentWorkflow` at its existing import site,
   not via a new injection seam.** `run_single_day` does
   `from graph.workflow import AgentWorkflow` inside its own body on
   every call — this always re-reads the `AgentWorkflow` attribute off
   the `graph.workflow` module object already cached in `sys.modules`
   (importing `deepfund/src/graph/workflow.py` is cheap and has no
   side effects beyond its own module-level imports, which are already
   exercised elsewhere in the suite). Monkeypatching that attribute
   directly (`monkeypatch.setattr(graph_workflow_module, "AgentWorkflow",
   FakeAgentWorkflow)`) is sufficient to control every ticker's workflow
   without any production code change — confirming the task's
   instruction that no testability blocker exists here.
2. **Force the `ImportError` branch via `sys.modules["graph.workflow"]
   = None`**, the standard technique for making a cached module name
   raise `ImportError` on the next `import`/`from ... import` — no
   production code change needed, and `monkeypatch.setitem` reverts it
   automatically after the test regardless of pass/fail.
3. **The fake workflow's `update_portfolio_ticker` mirrors, rather than
   imports, the real logic** (`graph.workflow.AgentWorkflow.
   update_portfolio_ticker` / `backtest.workflow.decision_apply.
   _update_portfolio_ticker`): BUY adds shares and spends cash, SELL
   removes shares and receives cash, position value is repriced,
   cashflow is rounded. This keeps the fake's contract obvious from
   its own body (a few lines) rather than silently depending on
   another module's implementation being unchanged, while still using
   `graph.schema.Position` (the same bare-`graph` import path
   `workflow_adapter.py` itself uses) so the returned `Portfolio`
   object's positions are the same class the rest of the adapter
   expects — avoiding a `deepfund.src.graph.schema.Position` vs.
   `graph.schema.Position` type mismatch (these are distinct Python
   classes despite sharing a source file, because `deepfund/src` is
   also on `sys.path` as its own root; confirmed by comparing
   `graph.schema.Position is deepfund.src.graph.schema.Position` ->
   `False` in this environment).
4. **Decisions are plain `types.SimpleNamespace` objects, not real
   `graph.schema.Decision` pydantic models.** `run_single_day` only
   ever does attribute access on the returned decision
   (`decision.action`, `.shares`, `.price`, `.justification`), never an
   isinstance check, so a `SimpleNamespace` is sufficient and keeps the
   tests independent of the real `Decision`/`Action` classes' import
   path ambiguity described in point 3.
5. **No production code change.** The task instructed to STOP and
   report if a genuine testability blocker were found; none was — the
   existing in-method import statement is already a stubbable seam.

## Risks / Trade-offs

- The fake workflow's `update_portfolio_ticker` duplicates (rather than
  imports) a few lines of business logic already present in two other
  places (`graph.workflow.AgentWorkflow.update_portfolio_ticker` and
  `backtest.workflow.decision_apply._update_portfolio_ticker`). This is
  intentional per point 3 above — the test's fake should not depend on
  another module's implementation staying byte-identical for its own
  assertions to remain meaningful — but it does mean a future change to
  either real implementation would not automatically flow through to
  this fake. Acceptable: the fake exists to characterize
  `run_single_day`'s own orchestration logic (does it call
  `update_portfolio_ticker`, does it thread the returned portfolio to
  the next ticker, does it commit the final state), not to re-verify
  the update arithmetic itself.
