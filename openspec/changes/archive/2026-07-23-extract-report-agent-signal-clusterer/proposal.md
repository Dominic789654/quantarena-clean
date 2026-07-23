## Why

Phase 4 step 30 (docs/refactor_program_plan.md). Steps 24-29 landed the
characterization harness (`tests/report_agent_harness.py`,
`tests/test_report_agent_characterization.py`, 22 tests) and six leaf
modules -- `deepear/src/agents/report/retry.py`, `chart_sanitizer.py` /
`structured_report.py`, `citations.py`, `ticker_utils.py` /
`forecast_requests.py`, and `chart_renderer.py` -- out of
`deepear/src/agents/report_agent.py`'s `ReportAgent` class (now 747
lines). This step extracts `_cluster_signals` into a new
`deepear/src/agents/report/clustering.py`, per the plan's explicit
instruction to "share the exact `self.planner` instance by reference; add
an identity-assertion test."

## What Changes

- Add `deepear/src/agents/report/clustering.py` exposing one module-level
  function, `cluster_signals(signals, user_query=None, *, planner)`,
  `_cluster_signals`'s body moved verbatim. `grep -n "self\."` restricted
  to the original method body finds exactly one `self.`-qualified name,
  `self.planner`, touched twice: an assignment
  (`self.planner.instructions = [instruction]`) and a call
  (`self.planner.run(get_cluster_task(signals_preview))`). No other
  instance state is read -- notably, the body calls `self.planner.run(...)`
  directly, never `self._run_agent_with_retry(...)`, so unlike
  `forecast_requests.py`'s `get_forecast_agent` or `chart_renderer.py`'s
  `agent_cls`/`get_forecast_agent`, there is no factory/class/bound-retry
  callable to thread here -- only the live `Agent` instance itself. Per
  ground rule 6 and the plan's explicit instruction, `self.planner`
  becomes a required keyword-only `planner: Agent` parameter that the
  function reads/mutates in place; `ReportAgent._cluster_signals` forwards
  `planner=self.planner` -- the same object, by reference, not a copy or a
  freshly constructed `Agent` -- so the function's `.instructions`
  mutation and `.run(...)` call land on, and are answered by, the exact
  `Agent` instance `ReportAgent.__init__` built and every other
  `ReportAgent` method (e.g. the planner-phase code in `generate_report`)
  keeps reading as `self.planner` afterward.
- `ReportAgent._cluster_signals(self, signals, user_query=None)` becomes a
  one-line delegator to `cluster_signals(signals, user_query,
  planner=self.planner)`, kept as a real bound instance method (not a bare
  attribute alias) so the internal `self._cluster_signals(signals,
  user_query)` call site inside `generate_report`, and
  `tests/test_report_agent_characterization.py`'s three direct
  `agent._cluster_signals(...)` / `harness.agent._cluster_signals(...)`
  calls, keep working unchanged.
- Add `tests/test_report_clustering.py`: direct `cluster_signals` coverage
  not already characterized (empty-signals input, dict-vs-attribute-style
  `title` access while building the preview text, multi-cluster JSON
  parsing); the mandatory **planner identity-assertion test** proving the
  `Agent` instance `cluster_signals` calls `.run()` on, and mutates
  `.instructions` on, *is* (`is`, not `==`) the exact object passed as
  `planner`; and a **delegation-identity test** proving
  `ReportAgent._cluster_signals` forwards the real `self.planner` by
  reference (same invariant, one layer up, through a real `ReportAgent`
  built by `tests/report_agent_harness.py`).
- No behavior change. `tests/test_report_agent_characterization.py` (22
  tests, including its three `_cluster_signals` scenarios),
  `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_retry_helper.py` (7 tests),
  `tests/test_report_pure_functions.py` (24 tests),
  `tests/test_report_citations_module.py` (24 tests),
  `tests/test_report_forecast_ticker.py` (24 tests), and
  `tests/test_report_chart_renderer.py` (20 tests) are left completely
  unmodified and must keep passing unchanged.

## Capabilities

### New Capabilities
- `report-agent-signal-clusterer`: the Planner-driven signal-clustering
  step `ReportAgent.generate_report` uses to group raw signals into a
  small number of named themes (each `{theme_title, signal_ids,
  rationale}`) before the writer phase, sharing the caller's own
  `Agent` planner instance by reference and falling back to an empty
  cluster list (which `generate_report` treats as "one cluster per
  signal") on any parse failure or exception.

### Modified Capabilities
- None.

## Impact

- New files: `deepear/src/agents/report/clustering.py`,
  `tests/test_report_clustering.py`.
- Modified: `deepear/src/agents/report_agent.py` (one new fully-qualified
  import; one method body replaced by a one-line delegator; three
  imports that only the moved method body used --
  `deepear.src.utils.json_utils.extract_json`,
  `get_cluster_planner_instructions`, `get_cluster_task` -- removed as
  now-unused, per `ruff check .`).
- Monkeypatch audit (ground rule 2): `git grep -n
  "_cluster_signals\|cluster_signals" tests/ deepear/ backtest/ deepfund/
  shared/` shows: the method definition and its two internal call sites
  inside `deepear/src/agents/report_agent.py` (the definition itself at
  line 288, and `generate_report`'s one `self._cluster_signals(signals,
  user_query)` call); three unrelated same-substring matches
  (`cluster_signals_text`, a local variable name inside
  `generate_report` that has nothing to do with the method -- it just
  happens to contain the substring "cluster_signals"); and
  `tests/test_report_agent_characterization.py`'s three direct
  `agent._cluster_signals(...)` / `harness.agent._cluster_signals(...)`
  calls on a real instance. No literal `monkeypatch.setattr("...")` string
  path and no class-attribute patch of `_cluster_signals` exists anywhere
  in the repo today. `ReportAgent` keeps `_cluster_signals` as a real bound
  instance method (a one-line delegator, not a bare attribute alias), so
  every existing internal call site, every existing direct-instance-method
  test call, and any future monkeypatch of the name keeps working exactly
  as before.
