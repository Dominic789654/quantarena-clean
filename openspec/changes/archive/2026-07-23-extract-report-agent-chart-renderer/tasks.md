## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_process_charts\|process_charts" tests/ deepear/ backtest/ deepfund/ shared/` (run before any code change)
  — hits: the method definition and one internal call site
  (`self._process_charts(...)` inside `generate_report`) in
  `deepear/src/agents/report_agent.py`; `tests/report_agent_harness.py`'s
  docstring mentioning `_process_charts` as one of the two `StockTools`
  collaborators constructed with `auto_update=False` (no monkeypatch of the
  name itself). No test file calls `_process_charts` directly yet.
- [x] 1.2 Confirm no literal `monkeypatch.setattr("...")` string path and
  no class-attribute patch of `_process_charts`/`process_charts` exists
  anywhere in the repo today — none found.
- [x] 1.3 `grep -n "self\."` restricted to `_process_charts`'s body — six
  reads across three instance attributes: `self.db` (once constructing
  `StockTools(self.db, auto_update=False)`, twice more in the "sentiment"
  type's initial and fallback `self.db.execute_query(...)` calls),
  `self.tool_model` (once, the "transmission" type's throwaway Agent's
  `model=` kwarg), `self._get_forecast_agent()` (twice: "stock" type's
  optional inline-forecast-overlay path, "forecast" type's
  `forecast_map`-miss fallback path).
- [x] 1.4 Confirm the "transmission" type's bare `Agent(...)` construction
  resolves to `report_agent.py`'s own module-level `from agno.agent import
  Agent` import — the same seam `tests/report_agent_harness.py`'s
  `make_report_agent` already monkeypatches
  (`monkeypatch.setattr(report_agent_module, "Agent", ...)`) for the four
  long-lived agents built in `ReportAgent.__init__`.
- [x] 1.5 Confirm `_incremental_edit` (a separate method, out of scope per
  the task) neither calls nor is called by `_process_charts`.

## 2. Snapshot tests (written and run green BEFORE the move)

- [x] 2.1 Add `tests/test_report_chart_renderer.py` against the *unmoved*
  `ReportAgent._process_charts`, using `tests/report_agent_harness.py`'s
  `make_report_agent` plus monkeypatched `utils.visualizer.VisualizerTools`
  / `utils.stock_tools.StockTools` module attributes (never
  `deepear.src.utils.*` — those are separate module objects from the bare
  `utils.*` ones the lazy in-function imports resolve to). Covers:
  no-chart-blocks passthrough; the invalid-forecast-ticker HTML-comment
  substitution; a well-formed `isq` block rendering; an unrecognized chart
  type falling back to raw JSON; a chart-rendering exception falling back
  to the original block (generic + `stock`-type-specific); `stock`-type
  ticker resolution (valid ticker, no-data fallback, unparseable-ticker
  fallback); `forecast`-type `forecast_map`-hit/-miss/duplicate-block-cache/
  invalid-ticker/empty-history; `sentiment`-type query shape and no-results
  placeholder; `transmission`-type success and LLM-failure-fallback (both
  via the harness's patched `Agent` seam). 18 tests.
- [x] 2.2 Run `tests/test_report_chart_renderer.py` against the unmoved
  method — all 18 pass.
- [x] 2.3 Run the full pre-existing report suite (characterization,
  citations, retry, pure functions, citations module, forecast/ticker) plus
  the new file together — all still pass, confirming no interference.

## 3. Implementation (the move)

- [x] 3.1 Create `deepear/src/agents/report/chart_renderer.py`: move
  `_process_charts`'s body verbatim into module-level `process_charts(content,
  signals=None, forecast_map=None, *, db, tool_model, get_forecast_agent,
  agent_cls)`, rewriting exactly six lines (`self.db` → `db` ×3,
  `self._get_forecast_agent()` → `get_forecast_agent()` ×2, `self.tool_model`
  → `tool_model` ×1) plus the one `Agent(...)` construction → `agent_cls(...)`.
  Verified via a scripted diff against the original (dedented) body: only
  those substitutions differ, confirmed byte-for-byte including the
  eight-line smart-quote-normalization chain's apparent redundancy
  (`“`-escaped forms followed by the literal-character forms) and the
  "transmission" branch's inline `import time`.
- [x] 3.2 `report_agent.py`: add `from deepear.src.agents.report.chart_renderer
  import process_charts as _process_charts_impl`; replace `_process_charts`'s
  ~449-line body with a one-line-body delegator forwarding
  `db=self.db, tool_model=self.tool_model,
  get_forecast_agent=self._get_forecast_agent, agent_cls=Agent`. Remove
  `hashlib`, `json`, `import pandas as pd` from `report_agent.py`'s
  module-level imports — nothing else in the file uses them after the move
  (confirmed via `ruff check`, which flagged them as unused).
- [x] 3.3 Re-run `tests/test_report_chart_renderer.py` (all 18, unchanged)
  against the post-move delegator — identical pass results.

## 4. Tests added after the move

- [x] 4.1 Same file: `TestChartRendererModuleFunctionDirectly` — a
  delegation-identity test (`chart_renderer.process_charts(...)` called
  directly with the harness's own `db`/`tool_model`/`_get_forecast_agent`/
  `Agent` produces byte-identical output to `harness.agent._process_charts
  (...)`), and a call-time-resolution test proving `agent_cls` is read fresh
  from `report_agent_module.Agent` on every call — re-patching that module
  global *after* a `ReportAgent` instance already exists still changes what
  the next `_process_charts` call's nested throwaway Agent construction
  resolves to. 2 tests (20 total in the file).
- [x] 4.2 Confirm `tests/test_report_agent_characterization.py` (22 tests),
  `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_retry_helper.py` (7 tests),
  `tests/test_report_pure_functions.py` (24 tests),
  `tests/test_report_citations_module.py` (24 tests), and
  `tests/test_report_forecast_ticker.py` (24 tests) all still pass
  unchanged.

## 5. Gates

- [x] 5.1 `ruff check .` clean.
- [x] 5.2 `rtk proxy python -m pytest tests/test_report_chart_renderer.py tests/test_report_agent_characterization.py tests/test_report_agent_citations.py tests/test_report_retry_helper.py tests/test_report_pure_functions.py tests/test_report_citations_module.py tests/test_report_forecast_ticker.py -q`
  — all pass (120: 20 new + 100 pre-existing).
- [x] 5.3 `rtk proxy python -m pytest tests/ -q` — 1046 baseline + 20 new =
  1066 passed, 10 skipped, 0 failed.
- [x] 5.4 `openspec validate --changes` passes.
- [x] 5.5 `python -W error::SyntaxWarning -c "import deepear.src.agents.report.chart_renderer; import deepear.src.agents.report_agent"`
  — no warning raised.
- [x] 5.6 `git grep -n --untracked "from utils\.\|import utils\." -- deepear/src/agents/report/`
  confirms `chart_renderer.py`'s two lazy imports keep the exact bare
  spelling `from utils.visualizer import VisualizerTools` / `from
  utils.stock_tools import StockTools` (character-for-character, same as
  the pre-move method body).
