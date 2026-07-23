## Context

`ReportAgent` (`deepear/src/agents/report_agent.py`, 1660 lines) is the last
class-sized file Phase 4 needs to split into a package, and it is also the
worst-tested one in the codebase for its size: before this change, only
`tests/test_report_agent_citations.py` constructs a real instance, and it
exercises exactly one branch (`generate_report` with `incremental_edit=False`,
under the 80k-char incremental threshold). `deepear/tests/test_deepear_workflow.py`
replaces the class wholesale via `sys.modules` stubbing, so it tests the
workflow around `ReportAgent`, never `ReportAgent` itself.

`ReportAgent.__init__` builds four `agno.agent.Agent` instances (planner,
writer, editor, section_editor) sharing one `InMemoryRAG`, and lazily
constructs a `ForecastAgent` (which can itself lazily load a Kronos time-series
model, gated by `ENABLE_KRONOS_FORECAST`) only when a forecast is actually
requested. `generate_report` orchestrates all of them plus `StockTools` (a
thin `DatabaseManager`-backed cache) and `VisualizerTools` (real file I/O under
`reports/charts/`) through a many-branch pipeline: signal clustering, per-
cluster drafting, incremental-vs-global editing, citation normalization,
bibliography injection, json-chart-block sanitization, forecast generation,
and chart rendering.

## Goals / Non-Goals

**Goals:** a reusable, importable fixtures module plus a first wave of
characterization tests covering every method that later Phase 4 steps will
move verbatim, so each of those steps can prove "verbatim move, behavior
unchanged" instead of taking it on faith.

**Non-Goals:**
- Real chart file I/O. `VisualizerTools.render_chart_to_file` writes to
  `reports/charts/*.html` relative to the process CWD; step 29
  (`extract-report-agent-chart-renderer`) is the step that owns snapshot
  coverage for that 460+ line method. This change avoids ever reaching a
  chart-rendering call by scripting only chart-block inputs whose ticker/data
  resolution fails fast (e.g. an unparseable ticker), which is enough to
  characterize that `_process_charts` ran and produced its documented
  fallback comment, without needing a real chart object or a file write.
- The real Kronos forecast model / real `ForecastAgent`. `ForecastAgent`
  itself conditionally imports `KronosPredictorUtility` (a heavy, optional
  ML dependency) only when `ENABLE_KRONOS_FORECAST` is truthy, and even in
  LLM-only mode it builds its own real `agno.agent.Agent`. This change patches
  the `ForecastAgent` *class* referenced from `report_agent.py`'s module
  namespace, not `ReportAgent._get_forecast_agent` itself, so the real
  lazy-cache logic in `_get_forecast_agent` (`if self._forecast_agent is None:
  self._forecast_agent = ForecastAgent(...)`) is exactly what gets
  characterized as "constructs at most once."
- Extracting or modifying any `ReportAgent` method.
- The Chinese-language quality of any scripted LLM response text -- it exists
  only to route through the correct code branch, not to look like a real
  research report.

## Decisions

1. **`tests/report_agent_harness.py` is a plain importable module, not a
   pytest plugin or a `conftest.py` fixture set.** Later Phase 4 changes
   (steps 25-31) each add their own test file under `tests/` and need the same
   fakes; a plain module with factory functions/classes lets them write
   `from tests.report_agent_harness import make_report_agent, ScriptedAgentRouter`
   directly, with no plugin registration or fixture-scope coupling to worry
   about. `tests/` is already on `pythonpath` (see `pyproject.toml`
   `[tool.pytest.ini_options]`), so this import works from any test file in
   the directory without extra configuration.

2. **`FakeAgent` is scripted via a shared `ScriptedAgentRouter`, not per-
   instance canned responses.** `ReportAgent.__init__` builds four `Agent`
   instances internally; the harness does not control that construction
   directly (it can only swap the `Agent` name at module scope, per the seed
   test's own pattern). All four instances therefore end up as the same
   `FakeAgent` subclass, and the only way to give them distinct behavior is to
   dispatch on the *prompt text* each one receives -- exactly what
   `test_report_agent_citations.py`'s `FakeAgent.run` already does by
   matching substrings like `"聚类"`, `"撰写深度分析章节"`, `"终稿大纲"`,
   `"生成最终研报"`. `ScriptedAgentRouter.when_contains(substring, responder)`
   generalizes that pattern into a reusable, ordered rule list, and records
   every prompt it resolves in `.calls` so tests can assert *which* agent was
   exercised (e.g. `_cluster_signals` characterization asserts `len(router.
   calls) == 1` to prove only the planner ran).

3. **`FakeAgent` also supports a direct `run_fn` callable, bypassing the
   router entirely, for standalone `_run_agent_with_retry` tests.**
   `_run_agent_with_retry(agent, prompt, context)` takes any object with a
   `.run(prompt) -> object-with-.content`; it does not need a full
   `ReportAgent` to test in isolation. Building a bare `FakeAgent(run_fn=...)`
   keeps those tests from having to route a specific prompt through the
   router just to control one call's timing/exception behavior.

4. **`make_report_agent` patches `Agent` and `ForecastAgent`, not
   `_get_forecast_agent` or `generate_report` internals.** Patching at the
   "external heavy dependency" boundary (the two classes `report_agent.py`
   imports) rather than at ReportAgent's own methods means every method under
   test still runs its real, current implementation -- which is the entire
   point of a characterization harness. The one instance-level patch tests
   apply themselves (never inside the harness) is `agent.LLM_TIMEOUT_SECONDS`
   / `agent.LLM_RETRY_DELAY`, overridden per-test to keep retry/timeout tests
   fast; these are plain instance attribute overrides shadowing the class
   constants, not monkeypatches of shared state.

5. **Bibliography/citation and chart-sanitization scenarios reuse the exact
   `_make_cite_key` derivation from `tests/test_report_agent_citations.py`**
   (same two-source, two-signal shape) rather than inventing a new one, so a
   reader who already understands the seed test recognizes the pattern
   immediately in the new characterization suite.

6. **The `generate_report` end-to-end test exercises the *incremental*
   branch (`incremental_edit=True`, the constructor default), not the
   non-incremental branch the seed test already covers.** This maximizes new
   coverage per test: the incremental branch is `_incremental_edit`'s own
   ~180-line method (section-by-section editing with retry, summary
   generation, tail/quick-scan splitting, programmatic reference injection
   inside `_incremental_edit` *and* again after it returns in
   `generate_report`), none of which the seed test touches.

7. **The scripted json-chart block in the end-to-end test uses an
   unparseable ticker (`"N/A"`) rather than a real 5/6-digit code.** This
   keeps the test hermetic (no `StockTools.get_stock_price` call, hence no
   dependency on `FakeDatabaseManager.get_stock_prices` returning realistic
   OHLC data) while still proving three things at once: (a)
   `_sanitize_json_chart_blocks` repairs the deliberately-unclosed fence
   (without the repair, the regex in `_process_charts` would never match at
   all, and the raw ` ```json-chart ` fence would leak into the final report
   as literal text -- this is the exact class of bug the sanitizer exists to
   prevent); (b) `_process_charts` then runs its "stock" branch, fails ticker
   resolution via `StockTools.search_ticker` -> `FakeDatabaseManager.
   search_stock` (empty results, no network), and emits its documented
   `<!-- 无法解析股票代码: ... -->` fallback comment; (c) the prose
   immediately after the chart block in the source text survives untouched.

## Characterized vs. Out of Scope

Characterized (pinned by a new test in this change):
- `ReportAgent.__init__`: `incremental_edit` true/false, `tool_model`
  defaulting to `model`, the `hasattr(tool_model, 'response_format')` ->
  `output_schema` gate on the Planner agent, lazy (never-at-construction)
  `_forecast_agent`.
- `_run_agent_with_retry`: success; exception-then-success retry; all
  retries exhausted returns `None` (not a raised exception); the
  thread-based timeout path also returns `None` after retries (with the note,
  in the test itself, that the timed-out background thread is never joined
  again or cancelled -- see "Known characterized quirks" below).
- `generate_report`, incremental branch: citation normalization (legacy
  `[@KEY]` markers replaced, programmatic bibliography injected, LLM
  placeholder reference text discarded), quick-scan/other-tail splitting,
  `[TOC]` + title template, chart-block sanitize-then-process pipeline,
  `build_structured_report`'s title/signals/clusters shape.
- `_cluster_signals`: valid-JSON success path (using `self.planner`
  specifically, confirmed via call recording), unparsable-response fallback
  to `[]`, planner-exception fallback to `[]`.
- `_build_forecast_map` / `_extract_forecast_requests`: request shape
  (`ticker`, `pred_len`, `title`, `context_snippet`); no request -> the real
  `ForecastAgent` class is never constructed; two distinct requests -> exactly
  one construction (proving `_get_forecast_agent`'s lazy cache, not the
  harness, is what limits it) and two `generate_forecast` calls.
- `_clean_markdown`: markdown-fence stripping (both `` ```markdown `` and
  bare `` ``` ``), no-op on already-clean text.
- `_sanitize_json_chart_blocks`: no-op on a well-formed block, no-op when no
  `json-chart` marker is present at all, and the missing-closing-fence repair
  (also exercised indirectly by the end-to-end test).

Deliberately out of scope (see Non-Goals):
- Real chart rendering / file I/O (`VisualizerTools.render_chart_to_file`,
  `generate_stock_chart`, `generate_isq_radar_chart`, `generate_transmission_graph`).
- The real, optionally Kronos-backed `ForecastAgent`.
- The non-incremental `generate_report` branch's global-planning/editing path
  beyond what `test_report_agent_citations.py` already covers (not
  duplicated here).
- `_process_charts`'s "sentiment", "isq", and "transmission" chart types, and
  its "forecast" chart type's actual rendering (all reach
  `VisualizerTools`/file I/O, out of scope per above); only the "stock" type's
  early-exit (invalid ticker) path is exercised, since that is what proves the
  sanitize-then-process pipeline ran without needing a render.

## Known characterized quirks (not fixed, intentionally)

- `_run_agent_with_retry`'s timeout path leaves the timed-out background
  `threading.Thread` running detached (Python cannot forcibly kill a thread);
  it eventually finishes on its own and its result is discarded. Under
  repeated real timeouts in production this could accumulate lingering
  threads; this change characterizes the current return value (`None` after
  retries) and documents the thread behavior in the test's own comment/
  docstring, per the task's instruction to characterize actual behavior
  rather than silently "fix" it.
- `generate_report` calls `_normalize_citations` + `_inject_references` twice
  on the incremental path -- once inside `_incremental_edit` (into
  `other_tail`) and once more on the fully-assembled `final_response_content`
  after `_incremental_edit` returns (lines ~998-1003 of
  `report_agent.py`). This is idempotent in practice (the second pass finds
  no more `[@KEY]`/`[[n]]` markers and the reference-section regex replaces
  its own prior output), so it produces no visible bug, but it is redundant
  work worth a later extraction step noticing.

## Risks / Trade-offs

- `ScriptedAgentRouter`'s prompt-substring dispatch is coupled to the literal
  Chinese strings baked into `deepear/src/prompts/report_agent.py`'s task
  functions (`get_cluster_task`, `get_writer_task`, etc.). If a later,
  non-Phase-4 change edits those prompt strings, both this harness's default
  scripts and the seed citations test would need updating in lockstep. This
  mirrors a risk the seed test already carries; the harness does not make it
  worse, and centralizing the substrings in one reusable module (rather than
  every Phase 4 test file re-deriving its own) reduces the number of places
  that would need to change.
- The harness's `FakeForecastAgent`/`ForecastAgent`-class-patch approach means
  a future change to `ForecastAgent`'s own constructor signature
  (`__init__(self, db, model)`) would need a matching update to
  `make_fake_forecast_agent_class`; this is intentional (it is exactly the
  seam step 28, `extract-report-agent-forecast-and-ticker-coordinator`, is
  expected to touch, and that step's own task list should include updating
  this harness).
