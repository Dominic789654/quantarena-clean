## Context

`ReportAgent._process_charts` (`deepear/src/agents/report_agent.py`, previously
lines 740-1188, ~449 lines) is the last decomposition step before the final
package/shim step (step 31) and the signal-clusterer step (step 30). It scans
the final report markdown for ` ```json-chart ` fenced blocks and replaces
each with rendered HTML (an `<iframe>` pointing at a file under
`reports/charts/`) or a fallback comment/warning, dispatching on the block's
`"type"` field: `stock` (ticker resolution + fuzzy search + optional inline
Kronos forecast overlay), `forecast` (Kronos-backed forecast chart, reading
from a pre-computed `forecast_map` or falling back to a fresh
`_get_forecast_agent()` call), `sentiment` (raw parameterized SQL against
`daily_news` via `self.db.execute_query`, with a keyword-broadening fallback
query), `isq` (a signal-quality radar chart, content-hashed to avoid
filename collisions within the same second), and `transmission` (a nested
throwaway `agno.agent.Agent(...)` that asks an LLM to generate Draw.io XML,
with a 2-attempt retry loop and a Pyecharts-graph fallback if the LLM never
returns parseable XML). Any exception anywhere in a single block's handling
is caught by one outer `try/except` and falls back to returning the
original, unrendered block text.

`grep -n "self\\."` restricted to the original method's body finds six reads
across exactly three instance attributes:

```
stock_tools = StockTools(self.db, auto_update=False)                         [1 read]
forecast_obj = self._get_forecast_agent().generate_forecast(ticker, ...)     [1 read, "stock" type]
forecast_obj = self._get_forecast_agent().generate_forecast(ticker, ...)     [1 read, "forecast" type]
results = self.db.execute_query(query, params)                               [1 read, initial sentiment query]
results = self.db.execute_query(query, params)                               [1 read, fallback sentiment query]
visualizer_agent = Agent(model=self.tool_model, ...)                         [1 read, "transmission" type]
```

A seventh dependency is not a `self.` read but still needs threading: the
bare `Agent` name the "transmission" chart type constructs resolves, inside
`report_agent.py`, to that module's own `from agno.agent import Agent`
import -- the exact seam `tests/report_agent_harness.py`'s `make_report_agent`
monkeypatches (`monkeypatch.setattr(report_agent_module, "Agent", <FakeAgent
subclass>)`) so none of `ReportAgent`'s five `Agent(...)` constructions (the
four long-lived planner/writer/editor/section_editor agents built in
`__init__`, plus this one throwaway construction) ever makes a real LLM call
in tests.

## Goals / Non-Goals

**Goals:** move `_process_charts`'s entire body -- the nested `replace_match`
closure, every chart-type branch, the raw sentiment SQL, the
`reports/charts/*.html` file-path construction, and the nested throwaway
`Agent(...)` construction -- verbatim into
`deepear/src/agents/report/chart_renderer.py`'s module-level
`process_charts(content, signals=None, forecast_map=None, *, db, tool_model,
get_forecast_agent, agent_cls)`; thread all three touched instance attributes
(`self.db`, `self.tool_model`, `self._get_forecast_agent`) plus the `Agent`
construction-seam as four required keyword-only parameters; keep
`ReportAgent._process_charts` as a real one-line bound-method delegator;
write snapshot/characterization tests (`tests/test_report_chart_renderer.py`)
against the *unmoved* method first, confirm they pass, then perform the move,
then confirm the identical tests still pass unchanged against the delegator.

**Non-Goals:** changing chart-rendering behavior in any way (ticker
resolution/fuzzy-matching logic, the sentiment SQL text or its
keyword-broadening fallback, the Draw.io XML retry/fallback logic, any
HTML/iframe markup, any file-path naming scheme); touching
`_get_forecast_agent` itself (step 28 already established it stays on
`ReportAgent` as the lazy per-instance cache); touching
`ReportAgent.__init__`'s four long-lived `Agent(...)` constructions; adding
`deepear/src/agents/report/__init__.py` re-exports (deferred to
`finalize-report-agent-package-and-shim`, step 31); the signal-clusterer
(`_cluster_signals`, step 30).

## Decisions

1. **Four threaded keyword-only parameters, matching each dependency's own
   nature.** `db` and `tool_model` are plain values -- there is no lazy-cache
   semantics to preserve for either; the original method read
   `self.db`/`self.tool_model` fresh every time, so `process_charts` reads
   its `db`/`tool_model` parameters fresh every time it's called, which is
   the same thing. `get_forecast_agent` is a required keyword-only callable,
   exactly mirroring `forecast_requests.py`'s `build_forecast_map(..., *,
   get_forecast_agent)` precedent from step 28 -- `_get_forecast_agent`
   itself is not moved; it remains a bound method on `ReportAgent`, passed by
   reference (not called) so its own lazy per-instance caching keeps working
   unchanged. `agent_cls` is the fourth: a required keyword-only class/factory
   the "transmission" branch calls exactly where the original called
   `Agent(...)`.
2. **`agent_cls` is injected via the delegator reading `report_agent.py`'s
   own module-global `Agent` name at call time, not via a second monkeypatch
   point in `chart_renderer.py`.** The plan explicitly calls this out as the
   preferred approach over updating the harness to patch a second namespace.
   `ReportAgent._process_charts` forwards `agent_cls=Agent` -- a bare
   reference to the name `Agent` as it currently resolves in
   `report_agent.py`'s module namespace at the moment `_process_charts` is
   called. Because Python resolves bare global names at call time (not at
   function-definition time), this means: (a) the harness's existing
   `monkeypatch.setattr(report_agent_module, "Agent", <FakeAgent subclass>)`
   -- applied once, before `ReportAgent.__init__` even runs -- is picked up
   correctly by every `_process_charts` call with zero changes to
   `tests/report_agent_harness.py`; and (b) as
   `tests/test_report_chart_renderer.py::TestChartRendererModuleFunctionDirectly::
   test_agent_cls_is_resolved_at_call_time_from_report_agent_modules_global`
   proves directly, even a *second*, later re-patch of
   `report_agent_module.Agent` (after a `ReportAgent` instance already
   exists) still changes what the next `_process_charts` call's nested
   throwaway Agent construction resolves to -- confirming the read is
   genuinely late-bound, not captured once at construction time. This was
   the one candidate design point with real risk (the alternative --
   updating the harness to *also* patch `chart_renderer.Agent` -- would have
   worked too, but would have added a second patch point for every future
   test to remember, and diverged from the plan's explicit preference).
3. **No new default for any of the four threaded parameters.** Per ground
   rule 6 (established by every prior step in this phase --
   `retry.py`'s `run_agent_with_retry(..., *, max_retries, timeout_seconds,
   retry_delay)`, `citations.py`'s `build_bibliography(signals, *, db)`,
   `forecast_requests.py`'s `build_forecast_map(..., *, get_forecast_agent)`):
   a threaded dependency is required and keyword-only, never defaulted to
   something that isn't the caller's own instance state. All four of
   `db`/`tool_model`/`get_forecast_agent`/`agent_cls` are positional-or-keyword-
   forbidden (keyword-only, no default) on `process_charts`.
4. **`ReportAgent._process_charts` keeps its exact original signature and
   binding kind** -- a bound instance method,
   `_process_charts(self, content, signals=None, forecast_map=None)` --
   forwarding `content, signals, forecast_map` positionally and the four
   dependencies as keywords. This is a one-line delegator, not a bare
   attribute alias, so a future `monkeypatch.setattr(ReportAgent,
   "_process_charts", ...)` class-attribute patch (or an instance-level
   patch) still intercepts `generate_report`'s one internal
   `self._process_charts(...)` call site.
5. **The verbatim body includes one intentionally-redundant construct
   left untouched**: the smart-quote normalization chain
   (`json_str.replace("“", '"').replace("”", '"')...` followed by
   the same four replacements spelled as literal characters,
   `.replace("“", '"')` again as `.replace("“", '"')`) is a verbatim
   copy including its apparent redundancy -- the eight `.replace(...)` calls
   are byte-for-byte identical to the original, not "cleaned up" into four.
   Likewise the "transmission" branch's inline `import time` (redundant with
   the module-level `import time` already present via
   `from __future__ import annotations`-adjacent standard imports in the
   original file) is preserved as its own local `import time` statement
   inside the retry loop, exactly as written.
6. **Two of the three lazy in-function imports keep their bare spelling for
   a resolution reason that predates this step; the third for consistency.**
   `from utils.visualizer import VisualizerTools` and `from utils.stock_tools
   import StockTools` resolve via `tests/conftest.py`'s
   `_pin_ambiguous_package_resolution` session fixture, which pins bare
   `utils` to `deepear/src/utils` purely through `sys.path` order -- a
   property of the *interpreter's* `sys.path`, not of which file performs
   the `from utils... import ...` statement, so moving the statement to a
   different file changes nothing about how it resolves. `from
   prompts.visualizer import get_drawio_system_prompt, get_drawio_task` (the
   "transmission" branch's third lazy import) has no ambiguity to pin --
   only `deepear/src/prompts` exists on `sys.path` as `prompts` -- but is
   left with the identical bare spelling anyway, since ground rule 1 (verbatim
   move) applies to every import statement in the moved body, not only the
   two the plan calls out by name.
7. **`grep -n "self\\."` found zero reads inside `replace_match`'s nested
   helpers beyond the six listed above** -- there is no second nested
   function inside `_process_charts` analogous to
   `chart_sanitizer.py`'s `find_json_end` (step 26); `replace_match` is the
   only nested closure, and it closes over `stock_tools`,
   `rendered_forecast_html`, `content`/`signals`/`forecast_map` (the outer
   function's own parameters), and the four newly-threaded parameters -- all
   ordinary Python closure capture, unaffected by the move.
8. **`_incremental_edit` (~line 556 in the pre-move file) is confirmed out of
   scope**, per the task's explicit instruction -- it does not call or get
   called by `_process_charts`, and belongs to the final slimming step
   (`finalize-report-agent-package-and-shim`, step 31), not this one.

## Risks / Trade-offs

- `process_charts`'s four-parameter keyword-only signature is the widest
  threaded-dependency surface of any Phase 4 leaf module so far (`retry.py`
  and `forecast_requests.py` each thread one dependency; `citations.py`
  threads one). This is intrinsic to `_process_charts` itself touching three
  distinct instance attributes plus one construction seam -- collapsing them
  into a single "context object" parameter was considered and rejected: it
  would not match any existing precedent in this codebase's Phase 4 modules,
  and would obscure exactly which dependencies are threaded versus read
  fresh, which the explicit keyword-only parameters make immediately visible
  at every call site.
- The 449-line `process_charts` function (plus its nested `replace_match`
  closure) remains a single long function, not further decomposed by
  chart-type into five smaller functions. The task scope is a verbatim move,
  not a refactor; splitting it by chart type would change nothing about
  correctness but would not be a verbatim move and was explicitly out of
  scope.
- `tests/test_report_chart_renderer.py` cannot pin exact rendered filenames
  (every chart type embeds `datetime.now().strftime("%Y%m%d%H%M%S")`, and the
  "isq" type additionally embeds a content hash that IS deterministic per
  payload but combined with the non-deterministic timestamp). Tests assert
  on stable substrings/prefixes (e.g. `'<iframe src="charts/isq_'`) rather
  than exact full-string snapshots -- this is the same class of
  non-determinism every other timestamp-embedding path in this codebase's
  test suite already works around, not a new gap introduced here.
