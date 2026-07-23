## 1. Coverage audit

- [x] 1.1 `git grep -rn "ReportAgent(" tests/ deepear/tests/` — confirmed exactly
  one test file constructs a real `ReportAgent`
  (`tests/test_report_agent_citations.py`); `deepear/tests/test_deepear_workflow.py`
  stubs the class via `sys.modules` replacement instead.
- [x] 1.2 `grep -n "self\.db\." deepear/src/agents/report_agent.py` — enumerated
  the `DatabaseManager` surface touched directly (`lookup_reference_by_url`,
  `execute_query`); enumerated the indirect surface via the `StockTools`
  collaborator `ReportAgent` constructs itself (`get_stock_prices`,
  `save_stock_prices`, `search_stock`).
- [x] 1.3 `git grep -rln "_sanitize_json_chart_blocks\|build_structured_report" tests/ deepear/tests/`
  — confirmed no existing coverage to avoid duplicating.
- [x] 1.4 Read `deepear/src/prompts/report_agent.py`'s task functions
  (`get_cluster_task`, `get_writer_task`, `get_planner_task`, `get_editor_task`,
  and the incremental-mode prompt strings) to derive the exact substrings the
  seed test's `FakeAgent` dispatches on, for reuse in the harness's default
  scripts.

## 2. Harness

- [x] 2.1 Add `tests/report_agent_harness.py`: `FakeModel`, `FakeRunResponse`,
  `ScriptedAgentRouter`, `FakeAgent`, `make_scripted_agent_class`,
  `FakeForecastAgent`, `make_fake_forecast_agent_class`,
  `FakeDatabaseManager`, `ReportAgentHarness`, `make_report_agent`.
- [x] 2.2 Verify `make_report_agent` patches only
  `deepear.src.agents.report_agent.Agent` and
  `deepear.src.agents.report_agent.ForecastAgent`, both via the pytest
  `monkeypatch` fixture (no `sys.modules` replacement), mirroring the seed
  test's pattern.
- [x] 2.3 Verify the real `ReportAgent._get_forecast_agent` lazy-cache logic is
  left untouched (only the `ForecastAgent` class it constructs is faked), so a
  call-counting test on it characterizes real production caching behavior.

## 3. Characterization tests

- [x] 3.1 Add `tests/test_report_agent_characterization.py`.
- [x] 3.2 Construction: `incremental_edit` true/false, `tool_model` default,
  `output_schema`/`response_format` gate, lazy `_forecast_agent`.
- [x] 3.3 `_run_agent_with_retry`: success; retry-then-succeed; retries
  exhausted returns `None`; timeout path returns `None` (tiny
  `LLM_TIMEOUT_SECONDS`/`LLM_RETRY_DELAY` overrides to keep the test fast).
- [x] 3.4 `generate_report` end-to-end incremental happy path: citation
  normalization, programmatic bibliography injection, `[TOC]`/title template,
  quick-scan splitting, chart-block sanitize-then-process pipeline (unclosed
  fence, unparseable ticker, no file I/O), `build_structured_report` shape.
- [x] 3.5 `_cluster_signals`: valid-JSON success via `self.planner`
  (call-recorded), unparsable-response fallback to `[]`, planner-exception
  fallback to `[]`.
- [x] 3.6 `_build_forecast_map` / `_extract_forecast_requests`: request shape;
  no request never constructs a `ForecastAgent`; two distinct requests
  construct exactly one `ForecastAgent` and call `generate_forecast` twice.
- [x] 3.7 `_clean_markdown` / `_sanitize_json_chart_blocks` edge cases not
  already covered elsewhere: fence stripping, no-op cases, missing-fence
  repair.

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_agent_characterization.py tests/test_report_agent_citations.py -q`
  — 23 passed (22 new + 1 seed).
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` — 967 passed (945 baseline +
  22 new), 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
