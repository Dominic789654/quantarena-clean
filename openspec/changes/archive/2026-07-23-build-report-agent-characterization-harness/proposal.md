## Why

Phase 4 step 24 (docs/refactor_program_plan.md). Phase 4 splits
`deepear/src/agents/report_agent.py` (1660 lines, one `ReportAgent` class) into
a `deepear/src/agents/report/` package via ~7 later verbatim-move changes. Every
one of those changes needs a regression net around the class's actual behavior
before it can move a single line. Today, `git grep -rn "ReportAgent(" tests/`
shows exactly one test file that constructs a real `ReportAgent` --
`tests/test_report_agent_citations.py`, a single regression test seeded by a
Phase 0 bug fix that only exercises the non-incremental final-assembly branch.
`deepear/tests/test_deepear_workflow.py` stubs the whole class out via
`sys.modules` replacement, so it exercises none of `ReportAgent`'s own logic.
There is no reusable fixture for the four `agno.agent.Agent` instances
`ReportAgent.__init__` builds, no fake `DatabaseManager`, and no fake
`ForecastAgent`/Kronos seam -- every later extraction step would otherwise have
to re-derive these from scratch, and would have no way to prove a verbatim move
did not change behavior.

## What Changes

- Add `tests/report_agent_harness.py`, a plain (non-plugin) fixtures module
  providing `FakeModel`, `FakeAgent`, `ScriptedAgentRouter`,
  `FakeDatabaseManager`, `FakeForecastAgent`, and a `make_report_agent(...)`
  factory that builds a *real* `ReportAgent` wired entirely with fakes. It is
  importable as `from tests.report_agent_harness import ...` by any later
  Phase 4 change's test file (extract-report-agent-retry-helper,
  extract-report-agent-citation-manager, extract-report-agent-forecast-and-
  ticker-coordinator, etc.) without re-deriving the same seams.
- Add `tests/test_report_agent_characterization.py`, characterizing (pinning
  current behavior of, making no production-code behavior changes):
  construction (both `incremental_edit` values, the `tool_model` default, the
  `output_schema`/`response_format` gate on the Planner agent);
  `_run_agent_with_retry` (success, retry-then-succeed, retries exhausted
  returns `None`, timeout path); `generate_report`'s end-to-end incremental
  happy path (citation normalization, programmatic bibliography injection,
  chart-block sanitization + processing, `build_structured_report` shape);
  `_cluster_signals` (planner JSON success, unparsable-JSON fallback to `[]`,
  planner-exception fallback to `[]`); `_build_forecast_map` /
  `_extract_forecast_requests` (no request never constructs a `ForecastAgent`;
  multiple requests construct one at most once, via `_get_forecast_agent`'s own
  untouched lazy-cache); `_clean_markdown` and `_sanitize_json_chart_blocks`
  edge cases not already covered by `tests/test_report_agent_citations.py`
  (confirmed via `git grep -rn "_sanitize_json_chart_blocks\|build_structured_report" tests/`
  returning no hits before this change).
- No production code changes. `deepear/src/agents/report_agent.py` is
  untouched; every seam this harness needs (`Agent`, `ForecastAgent`, the
  bound `_get_forecast_agent`/`_run_agent_with_retry`/`_cluster_signals`
  methods) is already reachable via `monkeypatch.setattr` on the module or the
  instance, the same technique the seed test already uses.

## Capabilities

### New Capabilities
- `report-agent-characterization` -- the set of `ReportAgent` behaviors now
  pinned by test, framed as a spec so later Phase 4 extraction changes can
  diff their own spec deltas against a documented baseline instead of only
  against test code.

### Modified Capabilities
- None.

## Impact

- New files only: `tests/report_agent_harness.py`,
  `tests/test_report_agent_characterization.py`. No changes to
  `deepear/src/agents/report_agent.py` or any other production file.
- Monkeypatch audit (ground rule 3): this change touches no production code,
  so there is nothing in `deepear/src/agents/report_agent.py` for a later
  change to accidentally break by renaming. The harness itself performs two
  `monkeypatch.setattr` calls per constructed `ReportAgent` --
  `deepear.src.agents.report_agent.Agent` (module attribute, swapped for a
  `FakeAgent` subclass) and `deepear.src.agents.report_agent.ForecastAgent`
  (module attribute, swapped for a counting `FakeForecastAgent` subclass) --
  both scoped to the pytest `monkeypatch` fixture and reverted automatically
  after each test, exactly mirroring `test_report_agent_citations.py`'s
  existing pattern (no `sys.modules` replacement, no permanent global state).
  Later Phase 4 changes that rename `Agent`, `ForecastAgent`, or
  `_get_forecast_agent` inside `report_agent.py` (or move them into the new
  `report/` package) MUST grep this harness module and update both the
  patched attribute paths and the literal string
  `"deepear.src.agents.report_agent.Agent"` used in
  `test_tool_model_defaults_to_model_when_omitted`, or the harness will start
  silently constructing real, network-calling `agno.agent.Agent` instances
  instead of fakes.

## Non-Goals

- Real chart file I/O (`VisualizerTools.render_chart_to_file` writing to
  `reports/charts/...`) and the real Kronos forecast model are deliberately
  out of scope; see design.md for how the harness avoids exercising either.
- Extracting, renaming, or otherwise modifying any method of
  `ReportAgent` -- that is the job of the later `extract-report-agent-*`
  changes this harness exists to unblock.
