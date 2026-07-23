## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_cluster_signals\|cluster_signals" tests/ deepear/ backtest/ deepfund/ shared/`
  — hits: the method definition (`report_agent.py:288`) and its one
  internal call site inside `generate_report`
  (`self._cluster_signals(signals, user_query)`); three unrelated
  same-substring matches on the local variable `cluster_signals_text`
  inside `generate_report` (nothing to do with the method); three direct
  `agent._cluster_signals(...)`/`harness.agent._cluster_signals(...)`
  calls in `tests/test_report_agent_characterization.py`'s
  `TestClusterSignals` class.
- [x] 1.2 Confirm no literal `monkeypatch.setattr("...")` string path and
  no class-attribute patch of `_cluster_signals` exists anywhere in the
  repo today — none found.
- [x] 1.3 `grep -n "self\."` restricted to `_cluster_signals`'s body —
  exactly one name, `self.planner`, touched twice (an `.instructions`
  assignment, then a `.run(...)` call); confirm zero
  `self._run_agent_with_retry` calls in the body (the task brief's
  retry-callable-threading caveat does not apply to this method).
- [x] 1.4 Confirm `self.planner` is constructed exactly once, in
  `ReportAgent.__init__`, and is not wrapped in any lazy-cache/getter (no
  `_get_planner`-style method exists) — confirms it must thread as the
  live instance itself, not a factory.

## 2. Implementation

- [x] 2.1 Create `deepear/src/agents/report/clustering.py`: move
  `_cluster_signals`'s body verbatim into module-level
  `cluster_signals(signals, user_query=None, *, planner)`, rewriting its
  two `self.planner` reads to the `planner` parameter (no other change).
- [x] 2.2 `report_agent.py`: add `from deepear.src.agents.report
  .clustering import cluster_signals as _cluster_signals_impl`; replace
  `_cluster_signals`'s body with a one-line delegator forwarding
  `planner=self.planner`, keeping it a real bound instance method (not a
  bare attribute alias).

## 3. Tests

- [x] 3.1 Add `tests/test_report_clustering.py`: direct `cluster_signals`
  coverage not already characterized by
  `tests/test_report_agent_characterization.py::TestClusterSignals`
  (dict-vs-attribute-style `title` access while building the preview,
  multi-cluster JSON parsing shape, empty-signals input).
- [x] 3.2 Same file: the mandatory **planner identity-assertion test** --
  a recording fake planner object passed directly into `cluster_signals`,
  asserting via `is` that the object the `.run(...)` call and the
  `.instructions` mutation land on is the exact object passed in.
- [x] 3.3 Same file: a **delegation-identity test** proving
  `ReportAgent._cluster_signals` forwards `self.planner` by reference --
  built via `tests/report_agent_harness.py`'s `make_report_agent`, patching
  `deepear.src.agents.report.clustering.cluster_signals` (the name
  `report_agent.py` imports it as, `_cluster_signals_impl`) to record the
  `planner` object it was called with and asserting `is
  harness.agent.planner`.
- [x] 3.4 Confirm `tests/test_report_agent_characterization.py` (22
  tests), `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_retry_helper.py` (7 tests),
  `tests/test_report_pure_functions.py` (24 tests),
  `tests/test_report_citations_module.py` (24 tests),
  `tests/test_report_forecast_ticker.py` (24 tests), and
  `tests/test_report_chart_renderer.py` (20 tests) all still pass
  unchanged.

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_clustering.py tests/test_report_agent_characterization.py tests/test_report_agent_citations.py tests/test_report_retry_helper.py tests/test_report_pure_functions.py tests/test_report_citations_module.py tests/test_report_forecast_ticker.py tests/test_report_chart_renderer.py -q`
  — all pass (new + pre-existing).
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` — 1066 baseline + new
  tests passed, 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
- [x] 4.5 `python -W error::SyntaxWarning -c "import deepear.src.agents.report.clustering; import deepear.src.agents.report_agent"`
  — no warning raised.
