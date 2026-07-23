## Why

Phase 4 step 29 (docs/refactor_program_plan.md) -- flagged there as the
second long pole and the riskiest step in the phase: 460+ lines of
chart-rendering logic with file I/O (well, file-path construction handed to
a faked-in-tests renderer), raw SQL, a nested throwaway `Agent`, and lazy
`utils.*` imports. Steps 24-28 landed the characterization harness
(`tests/report_agent_harness.py`, `tests/test_report_agent_characterization.py`,
22 tests) and five leaf modules -- `deepear/src/agents/report/retry.py`,
`chart_sanitizer.py`, `structured_report.py`, `citations.py`,
`ticker_utils.py`, `forecast_requests.py` -- out of
`deepear/src/agents/report_agent.py`'s `ReportAgent` class. This step
extracts `_process_charts` -- the ` ```json-chart ` block renderer for all
five chart types (`stock`, `forecast`, `sentiment`, `isq`, `transmission`)
-- into `deepear/src/agents/report/chart_renderer.py`.

## What Changes

- Add `deepear/src/agents/report/chart_renderer.py` exposing one
  module-level function, `process_charts(content, signals=None,
  forecast_map=None, *, db, tool_model, get_forecast_agent, agent_cls)`
  -- `_process_charts`'s body moved verbatim, including its nested
  `replace_match` closure, every chart-type branch, the raw parameterized
  sentiment SQL and its keyword-broadening fallback, the
  `reports/charts/*.html` file-path construction, and the "transmission"
  branch's nested throwaway Draw.io-XML-generation Agent construction and
  its 2-attempt retry loop.
- `grep -n "self\\."` restricted to the original method body finds six
  reads across three instance attributes: `self.db` (once for the internal
  `StockTools(self.db, auto_update=False)` collaborator, twice more for the
  "sentiment" type's initial and fallback `self.db.execute_query(...)`
  calls), `self.tool_model` (once, as the "transmission" type's throwaway
  Agent's `model=` kwarg), and `self._get_forecast_agent()` (twice: the
  "stock" type's optional inline-forecast-overlay path, and the "forecast"
  type's `forecast_map`-miss fallback path). All three are threaded as
  required keyword-only parameters (`db`, `tool_model`,
  `get_forecast_agent`) -- `_get_forecast_agent` itself is not moved; it
  stays on `ReportAgent` as the lazy per-instance `ForecastAgent` cache
  established in step 28, passed by reference so its caching keeps working.
- A fourth dependency is threaded even though it is not a `self.` read: the
  bare `Agent(...)` construction the "transmission" branch makes resolves,
  in the original file, to `report_agent.py`'s own module-global `Agent`
  import -- the exact seam `tests/report_agent_harness.py` monkeypatches so
  no `Agent(...)` construction anywhere in `ReportAgent` makes a real LLM
  call in tests. Per the plan's explicit preference for injection over a
  second patch point, `process_charts` takes a required keyword-only
  `agent_cls` parameter and calls `agent_cls(...)` where the original called
  `Agent(...)`; the delegator forwards `agent_cls=Agent`, reading
  `report_agent.py`'s own module-global `Agent` name fresh at call time (not
  captured once at import/construction time) -- so the harness's existing
  patch of `report_agent_module.Agent` keeps working, with zero changes to
  the harness.
- `ReportAgent` keeps `_process_charts(self, content, signals=None,
  forecast_map=None)` as a real bound instance method -- a one-line
  delegator to `chart_renderer.process_charts`, not a bare attribute alias
  -- forwarding `db=self.db, tool_model=self.tool_model,
  get_forecast_agent=self._get_forecast_agent, agent_cls=Agent`.
- Add `tests/test_report_chart_renderer.py` (20 tests): written and run
  green against the *unmoved* `_process_charts` method first (per the
  plan's snapshot-tests-before-relying-on-the-move instruction), then
  re-run unchanged (identical pass/fail results) against the post-move
  delegator. Covers: no-chart-blocks passthrough; the
  invalid-forecast-ticker HTML-comment-to-warning substitution; a
  well-formed `isq` block rendering via a faked (monkeypatched)
  `utils.visualizer.VisualizerTools`; an unknown chart type falling back to
  raw JSON display; a chart-rendering exception falling back to the
  original, unrendered block (both a generic and a `stock`-type-specific
  case); `stock`-type ticker resolution (valid digit ticker, no-data
  fallback, unparseable-ticker fallback); `forecast`-type
  `forecast_map`-hit-skips-`get_forecast_agent`, `forecast_map`-miss-calls-
  it-once, duplicate-blocks-share-a-per-call cache, invalid-ticker warning,
  and empty-history fallback; `sentiment`-type SQL query shape/params and
  the no-results placeholder; `transmission`-type success (via the
  harness's patched `Agent` seam) and LLM-failure-falls-back-to-Pyecharts;
  plus two tests added after the move exercising
  `chart_renderer.process_charts` directly -- one proving the delegator's
  output matches the module function's output byte-for-byte, one proving
  `agent_cls` is resolved fresh from `report_agent_module.Agent` at call
  time (a second, later re-patch of that module global still changes what
  the next call's nested Agent construction resolves to).
- No behavior change. `tests/test_report_agent_characterization.py` (22
  tests), `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_retry_helper.py` (7 tests),
  `tests/test_report_pure_functions.py` (24 tests),
  `tests/test_report_citations_module.py` (24 tests), and
  `tests/test_report_forecast_ticker.py` (24 tests) are left completely
  unmodified and keep passing unchanged.

## Capabilities

### New Capabilities
- `report-agent-chart-renderer`: the standalone ` ```json-chart ` block
  renderer that turns report markdown's five chart-type blocks (`stock`,
  `forecast`, `sentiment`, `isq`, `transmission`) into rendered HTML
  iframes or typed fallback markers, given an injected database
  collaborator, tool model, lazy forecast-agent accessor, and Agent
  factory.

### Modified Capabilities
- None.

## Impact

- New files: `deepear/src/agents/report/chart_renderer.py`,
  `tests/test_report_chart_renderer.py`.
- Modified: `deepear/src/agents/report_agent.py` (one new fully-qualified
  import; `_process_charts`'s ~449-line body replaced by a one-line-body
  delegator; three now-unused module-level imports -- `hashlib`, `json`,
  `pandas` -- removed since nothing else in the file used them after the
  move).
- Monkeypatch audit (ground rule 2): `git grep -n
  "_process_charts\|process_charts" tests/ deepear/ backtest/ deepfund/
  shared/` shows: the method/function definitions and their internal call
  sites (`self._process_charts(...)` inside `generate_report`;
  `_process_charts_impl(...)` inside the new delegator);
  `tests/report_agent_harness.py`'s docstring mentioning `_process_charts`
  as one of the two `StockTools` collaborators constructed with
  `auto_update=False` (no monkeypatch of the name itself); and
  `tests/test_report_chart_renderer.py` calling
  `harness.agent._process_charts(...)` directly on a real instance (plus,
  post-move, `chart_renderer.process_charts(...)` directly). No literal
  `monkeypatch.setattr("...")` string path and no class-attribute patch of
  either name exists anywhere in the repo today. `ReportAgent` keeps
  `_process_charts` as a real bound instance method (not a bare attribute
  alias), so the existing internal call site and any future monkeypatch of
  the name keep working exactly as before.
- `git grep -n "from utils\.\|import utils\."
  deepear/src/agents/report/chart_renderer.py` confirms the two
  plan-mandated bare spellings (`from utils.visualizer import
  VisualizerTools`, `from utils.stock_tools import StockTools`) moved
  character-for-character; the "transmission" branch's third lazy import
  (`from prompts.visualizer import get_drawio_system_prompt,
  get_drawio_task`) also kept its bare spelling, for the same
  verbatim-move reason even though no resolution-pin regression test names
  it specifically.
