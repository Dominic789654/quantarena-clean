"""Snapshot/characterization tests for `ReportAgent._process_charts`.

Written BEFORE `extract-report-agent-chart-renderer` (Phase 4 step 29) moves
`_process_charts`'s body out of `deepear/src/agents/report_agent.py` into
`deepear/src/agents/report/chart_renderer.py`, per the program plan's
explicit instruction to pin behavior with snapshot tests ahead of relying on
the move. Every test below calls `harness.agent._process_charts(...)` on a
real `ReportAgent` built by `tests/report_agent_harness.py`'s
`make_report_agent` -- the same call spelling works completely unchanged
both before and after the move, since the plan requires `ReportAgent` to
keep a real bound-method delegator for every moved name.

`_process_charts` does two lazy in-function imports whose bare spelling is
load-bearing (`from utils.visualizer import VisualizerTools` and `from
utils.stock_tools import StockTools`) -- these resolve to
`deepear/src/utils/visualizer.py` / `deepear/src/utils/stock_tools.py` via
the `tests/conftest.py` `_pin_ambiguous_package_resolution` fixture, but as
*separate* module objects from `deepear.src.utils.visualizer` /
`deepear.src.utils.stock_tools` (same source file, different `sys.modules`
key: `"utils.visualizer"` vs `"deepear.src.utils.visualizer"`). Every test
here therefore monkeypatches the `VisualizerTools`/`StockTools` *attributes*
on the bare `utils.visualizer`/`utils.stock_tools` module objects directly
(never via `deepear.src.utils.*`), exactly as the program plan instructs --
this is also how the lazy import keeps resolving to the fake after the
production code moves to a different file, since the import spelling itself
does not change.

No real file I/O (all chart-rendering classes are replaced with recording
fakes -- no `reports/charts/*.html` file is ever written), no real DB (the
harness's `FakeDatabaseManager`), no real network, no real LLM call (the
harness's `FakeAgent`/`ScriptedAgentRouter`, which intercepts the nested
throwaway `Agent(...)` construction the "transmission" chart type makes,
via the module-level `Agent` name `tests/report_agent_harness.py` patches in
`deepear.src.agents.report.agent`'s namespace -- `ReportAgent`'s real home
since `finalize-report-agent-package-and-shim`, Phase 4 step 31).

`TestChartRendererModuleFunctionDirectly` at the bottom of this file was
added *after* the move landed (all classes above it were written and passed
against the pre-move `ReportAgent._process_charts` body first, then re-run
unchanged against the post-move delegator with identical results) -- it
exercises `deepear.src.agents.report.chart_renderer.process_charts` directly
and proves the `agent_cls` injection decision: the delegator resolves
`Agent` from its own module's globals (`deepear.src.agents.report.agent`,
where `ReportAgent._process_charts` itself is defined) at call time, not at
import time, so the harness's existing `Agent` patch point keeps working
with zero changes to the harness itself.
"""

from __future__ import annotations

import pandas as pd

from deepear.src.schema.models import ForecastResult
from tests.report_agent_harness import (
    FakeDatabaseManager,
    ScriptedAgentRouter,
    make_report_agent,
)

# ---------------------------------------------------------------------------
# Fakes for the two lazy in-function imports `_process_charts` makes.
# ---------------------------------------------------------------------------


def install_fake_visualizer(monkeypatch, *, raise_on: str | None = None):
    """Monkeypatch the bare `utils.visualizer` module's `VisualizerTools`
    attribute with a recording fake. `raise_on`, if set to one of the
    chart-drawing method names, makes that method raise instead of
    returning a sentinel chart object -- used to exercise
    `_process_charts`' outer per-block exception fallback.

    Returns (calls, rendered): `calls` records every chart-drawing method
    invocation as `(method_name, args, kwargs)`; `rendered` records every
    `render_chart_to_file`/`render_drawio_to_html` invocation.
    """
    import utils.visualizer as visualizer_mod

    calls: list[tuple] = []
    rendered: list[tuple] = []

    class FakeVisualizerTools:
        @staticmethod
        def generate_stock_chart(*args, **kwargs):
            calls.append(("generate_stock_chart", args, kwargs))
            if raise_on == "generate_stock_chart":
                raise RuntimeError("boom-stock-chart")
            return "STOCK_CHART_OBJ"

        @staticmethod
        def generate_sentiment_trend_chart(*args, **kwargs):
            calls.append(("generate_sentiment_trend_chart", args, kwargs))
            if raise_on == "generate_sentiment_trend_chart":
                raise RuntimeError("boom-sentiment-chart")
            return "SENTIMENT_CHART_OBJ"

        @staticmethod
        def generate_isq_radar_chart(*args, **kwargs):
            calls.append(("generate_isq_radar_chart", args, kwargs))
            if raise_on == "generate_isq_radar_chart":
                raise RuntimeError("boom-isq-chart")
            return "ISQ_CHART_OBJ"

        @staticmethod
        def generate_transmission_graph(*args, **kwargs):
            calls.append(("generate_transmission_graph", args, kwargs))
            if raise_on == "generate_transmission_graph":
                raise RuntimeError("boom-transmission-graph")
            return "TRANSMISSION_CHART_OBJ"

        @staticmethod
        def render_chart_to_file(chart, filename):
            rendered.append(("render_chart_to_file", chart, filename))
            return filename

        @staticmethod
        def render_drawio_to_html(xml_content, filename, title):
            rendered.append(("render_drawio_to_html", xml_content, filename, title))
            return filename

    monkeypatch.setattr(visualizer_mod, "VisualizerTools", FakeVisualizerTools)
    return calls, rendered


def install_fake_stock_tools(monkeypatch, *, price_df_by_ticker: dict | None = None, search_results: list | None = None):
    """Monkeypatch the bare `utils.stock_tools` module's `StockTools`
    attribute with a recording fake. `price_df_by_ticker` maps ticker ->
    DataFrame returned by `get_stock_price`; any ticker not present gets an
    empty DataFrame (mirroring "no data for ticker").
    """
    import utils.stock_tools as stock_tools_mod

    calls: list[tuple] = []
    price_df_by_ticker = price_df_by_ticker or {}

    class FakeStockTools:
        def __init__(self, db, auto_update=True):
            calls.append(("__init__", db, auto_update))

        def search_ticker(self, query, limit=5):
            calls.append(("search_ticker", query, limit))
            return list(search_results or [])

        def get_stock_price(self, ticker, start_date=None, end_date=None, force_sync=False):
            calls.append(("get_stock_price", ticker, start_date, end_date))
            if ticker in price_df_by_ticker:
                return price_df_by_ticker[ticker]
            return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume", "change_pct"])

    monkeypatch.setattr(stock_tools_mod, "StockTools", FakeStockTools)
    return calls


def _sample_price_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-07-20", "2026-07-21"],
            "open": [10.0, 10.5],
            "close": [10.5, 10.8],
            "high": [10.6, 10.9],
            "low": [9.9, 10.4],
            "volume": [1000, 1200],
            "change_pct": [0.5, 0.3],
        }
    )


# ---------------------------------------------------------------------------
# 1. No chart blocks: passthrough.
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_no_chart_blocks_returns_content_unchanged(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        content = "# Report\n\nJust plain markdown, no chart blocks at all.\n"

        result = harness.agent._process_charts(content)

        assert result == content

    def test_invalid_forecast_ticker_html_comment_is_replaced_with_a_warning(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        content = "Body text.\n<!-- NO VALID TICKER FOR FORECAST: FOOBAR -->\nMore text."

        result = harness.agent._process_charts(content)

        assert "<!-- NO VALID TICKER FOR FORECAST" not in result
        assert "暂不支持该股票代码：FOOBAR" in result
        assert "Body text." in result
        assert "More text." in result


# ---------------------------------------------------------------------------
# 2. A well-formed json-chart block renders via the faked visualizer.
# ---------------------------------------------------------------------------


class TestIsqChartRenders:
    def test_isq_chart_renders_to_an_iframe(self, monkeypatch):
        calls, rendered = install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        content = (
            "Intro.\n\n"
            "```json-chart\n"
            '{"type": "isq", "sentiment": 0.6, "confidence": 0.8, "intensity": 4, '
            '"expectation_gap": 0.3, "timeliness": 0.9, "title": "My ISQ"}\n'
            "```\n\nOutro.\n"
        )

        result = harness.agent._process_charts(content)

        assert "Intro." in result
        assert "Outro." in result
        assert "```json-chart" not in result
        assert '<iframe src="charts/isq_' in result
        assert "信号质量雷达图: My ISQ" in result
        assert len(calls) == 1
        method, args, kwargs = calls[0]
        assert method == "generate_isq_radar_chart"
        assert args == (0.6, 0.8, 4)
        assert kwargs == {"expectation_gap": 0.3, "timeliness": 0.9, "title": "My ISQ"}
        assert len(rendered) == 1
        assert rendered[0][0] == "render_chart_to_file"
        assert rendered[0][1] == "ISQ_CHART_OBJ"

    def test_unknown_chart_type_falls_back_to_raw_json_display(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        json_str = '{"type": "widget", "foo": "bar"}'
        content = f"```json-chart\n{json_str}\n```"

        result = harness.agent._process_charts(content)

        assert result == f"```json\n{json_str}\n```"


# ---------------------------------------------------------------------------
# 3. A chart block whose rendering raises falls back to the original block.
# ---------------------------------------------------------------------------


class TestErrorPathFallback:
    def test_rendering_exception_returns_original_block_unchanged(self, monkeypatch):
        install_fake_visualizer(monkeypatch, raise_on="generate_isq_radar_chart")
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        block = (
            "```json-chart\n"
            '{"type": "isq", "sentiment": 0.1, "confidence": 0.2, "intensity": 1, '
            '"title": "Boom"}\n'
            "```"
        )
        content = f"Before.\n\n{block}\n\nAfter."

        result = harness.agent._process_charts(content)

        assert result == content
        assert block in result

    def test_stock_chart_render_exception_returns_original_block_unchanged(self, monkeypatch):
        install_fake_visualizer(monkeypatch, raise_on="generate_stock_chart")
        install_fake_stock_tools(monkeypatch, price_df_by_ticker={"600001": _sample_price_df()})
        harness = make_report_agent(monkeypatch)

        block = '```json-chart\n{"type": "stock", "ticker": "600001", "title": "600001 Trend"}\n```'
        content = f"Text.\n\n{block}\n\nMore."

        result = harness.agent._process_charts(content)

        assert result == content


# ---------------------------------------------------------------------------
# 4. Stock chart: ticker resolution + rendering.
# ---------------------------------------------------------------------------


class TestStockChart:
    def test_valid_digit_ticker_renders_one_chart(self, monkeypatch):
        calls, rendered = install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch, price_df_by_ticker={"600001": _sample_price_df()})
        harness = make_report_agent(monkeypatch)

        content = '```json-chart\n{"type": "stock", "ticker": "600001", "title": "600001 Trend"}\n```'

        result = harness.agent._process_charts(content)

        assert '<iframe src="charts/stock_600001_' in result
        assert "交互式图表: 600001 Trend" in result
        stock_chart_calls = [c for c in calls if c[0] == "generate_stock_chart"]
        assert len(stock_chart_calls) == 1
        _, args, kwargs = stock_chart_calls[0]
        assert args[1] == "600001"
        assert args[2] == "600001 Trend"
        assert kwargs["prediction"] is None
        assert kwargs["forecast"] is None
        assert len(rendered) == 1

    def test_no_data_for_ticker_emits_html_comment(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)  # no price data for any ticker
        harness = make_report_agent(monkeypatch)

        content = '```json-chart\n{"type": "stock", "ticker": "600002", "title": "T"}\n```'

        result = harness.agent._process_charts(content)

        assert "<!-- 无法获取股票数据: 600002 -->" in result

    def test_unparseable_ticker_emits_html_comment(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        content = '```json-chart\n{"type": "stock", "ticker": "?!?", "title": "T"}\n```'

        result = harness.agent._process_charts(content)

        assert "<!-- 无法解析股票代码: ?!? -->" in result


# ---------------------------------------------------------------------------
# 5. Forecast chart: `_get_forecast_agent()` interaction + dedup caching.
# ---------------------------------------------------------------------------


class TestForecastChart:
    def test_forecast_map_hit_skips_get_forecast_agent(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch, price_df_by_ticker={"600001": _sample_price_df()})
        harness = make_report_agent(monkeypatch)

        forecast_obj = ForecastResult(ticker="600001", rationale="Because reasons.")
        forecast_map = {("600001", 5): forecast_obj}
        content = '```json-chart\n{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "F1"}\n```'

        result = harness.agent._process_charts(content, forecast_map=forecast_map)

        assert harness.forecast_construct_counter["count"] == 0
        assert harness.agent._forecast_agent is None
        assert "AI 深度预测: F1" in result
        assert "Because reasons." in result

    def test_forecast_map_miss_falls_back_to_get_forecast_agent_once(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch, price_df_by_ticker={"600001": _sample_price_df()})
        forecast_obj = ForecastResult(ticker="600001", rationale="Fallback rationale.")
        harness = make_report_agent(monkeypatch, forecast_result=forecast_obj)

        content = '```json-chart\n{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "F1"}\n```'

        result = harness.agent._process_charts(content)

        assert harness.forecast_construct_counter["count"] == 1
        assert "Fallback rationale." in result

    def test_duplicate_forecast_blocks_render_via_local_cache(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch, price_df_by_ticker={"600001": _sample_price_df()})
        forecast_obj = ForecastResult(ticker="600001", rationale="Cached rationale.")
        harness = make_report_agent(monkeypatch, forecast_result=forecast_obj)

        block = '```json-chart\n{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "F1"}\n```'
        content = f"{block}\n\n{block}\n"

        result = harness.agent._process_charts(content)

        assert result.count("Cached rationale.") == 2
        # The forecast agent itself is constructed once (lazy cache on
        # ReportAgent) and `generate_forecast` is only called once per
        # unique (ticker, pred_len) thanks to `_process_charts`' own
        # per-call `rendered_forecast_html` cache.
        assert harness.forecast_construct_counter["count"] == 1
        assert len(harness.agent._forecast_agent.calls) == 1

    def test_invalid_forecast_ticker_shows_unsupported_warning(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        content = '```json-chart\n{"type": "forecast", "ticker": "ABC", "title": "T"}\n```'

        result = harness.agent._process_charts(content)

        assert "暂不支持该股票代码的预测渲染：ABC" in result

    def test_forecast_history_empty_emits_html_comment(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)  # no price data
        harness = make_report_agent(monkeypatch)

        content = '```json-chart\n{"type": "forecast", "ticker": "600009", "pred_len": 5, "title": "T"}\n```'

        result = harness.agent._process_charts(content)

        assert "<!-- 无法获取股票数据: 600009 -->" in result


# ---------------------------------------------------------------------------
# 6. Sentiment chart: raw SQL via `self.db.execute_query`.
# ---------------------------------------------------------------------------


class TestSentimentChart:
    def test_sentiment_chart_queries_db_and_renders(self, monkeypatch):
        calls, rendered = install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        db = FakeDatabaseManager(
            sentiment_rows=[("2026-07-20", 0.5), ("2026-07-20", 0.3), ("2026-07-21", -0.1)]
        )
        harness = make_report_agent(monkeypatch, db=db)

        content = '```json-chart\n{"type": "sentiment", "keywords": ["宁德时代"], "title": "Mood"}\n```'

        result = harness.agent._process_charts(content)

        assert len(db.executed_queries) == 1
        query, params = db.executed_queries[0]
        assert "sentiment_score" in query
        assert params == ("%宁德时代%",)
        assert '<iframe src="charts/sentiment_' in result
        assert "交互式图表: Mood" in result
        sentiment_calls = [c for c in calls if c[0] == "generate_sentiment_trend_chart"]
        assert len(sentiment_calls) == 1

    def test_sentiment_chart_no_results_shows_placeholder(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        db = FakeDatabaseManager(sentiment_rows=[])
        harness = make_report_agent(monkeypatch, db=db)

        content = '```json-chart\n{"type": "sentiment", "keywords": ["宁德时代"], "title": "Mood"}\n```'

        result = harness.agent._process_charts(content)

        assert "暂无足够历史数据生成" in result
        assert "Mood" in result
        # The initial query comes back empty, so the fallback broadened
        # query (splitting keywords on whitespace) is also attempted --
        # for a single-token keyword it re-queries with the same token,
        # for two queries total.
        assert len(db.executed_queries) == 2


# ---------------------------------------------------------------------------
# 7. Transmission chart: nested throwaway `Agent(...)` construction.
# ---------------------------------------------------------------------------


class TestTransmissionChart:
    def test_transmission_chart_uses_the_patched_agent_seam(self, monkeypatch):
        calls, rendered = install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        router = ScriptedAgentRouter()
        drawio_xml = (
            "```xml\n"
            '<mxGraphModel dx="1" dy="1"><root><mxCell id="0"/></root></mxGraphModel>\n'
            "```"
        )
        router.when_contains("Draw.io XML diagram", drawio_xml)
        harness = make_report_agent(monkeypatch, router=router)

        content = (
            "```json-chart\n"
            '{"type": "transmission", "nodes": [{"label": "A"}, {"label": "B"}], '
            '"title": "Logic Chain"}\n'
            "```"
        )

        result = harness.agent._process_charts(content)

        assert '<iframe src="charts/trans_' in result
        assert "交互式逻辑推演图: Logic Chain (AI Generated)" in result
        assert len(rendered) == 1
        assert rendered[0][0] == "render_drawio_to_html"
        assert "<mxGraphModel" in rendered[0][1]
        # The router saw exactly one prompt asking for a Draw.io diagram --
        # proof the nested throwaway `Agent(...)` construction went through
        # the harness's patched `Agent` seam, not a real agno Agent/LLM call.
        drawio_prompts = [p for p in router.calls if "Draw.io XML diagram" in p]
        assert len(drawio_prompts) == 1

    def test_transmission_chart_llm_failure_falls_back_to_pyecharts_graph(self, monkeypatch):
        calls, rendered = install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        router = ScriptedAgentRouter()
        router.when_contains("Draw.io XML diagram", "not valid xml at all")
        harness = make_report_agent(monkeypatch, router=router)

        content = (
            "```json-chart\n"
            '{"type": "transmission", "nodes": [{"label": "A"}, {"label": "B"}], '
            '"title": "Logic Chain"}\n'
            "```"
        )

        result = harness.agent._process_charts(content)

        assert '<iframe src="charts/trans_legacy_' in result
        assert "逻辑传导拓扑图: Logic Chain" in result
        graph_calls = [c for c in calls if c[0] == "generate_transmission_graph"]
        assert len(graph_calls) == 1


# ---------------------------------------------------------------------------
# 8. Added after the move: direct module-function coverage + the
#    agent_cls-injection decision.
# ---------------------------------------------------------------------------


class TestChartRendererModuleFunctionDirectly:
    def test_delegator_output_matches_module_function_output(self, monkeypatch):
        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch, price_df_by_ticker={"600001": _sample_price_df()})
        harness = make_report_agent(monkeypatch)
        content = '```json-chart\n{"type": "stock", "ticker": "600001", "title": "600001 Trend"}\n```'

        import deepear.src.agents.report.agent as report_agent_module
        from deepear.src.agents.report.chart_renderer import process_charts

        direct_result = process_charts(
            content,
            None,
            None,
            db=harness.db,
            tool_model=harness.tool_model,
            get_forecast_agent=harness.agent._get_forecast_agent,
            agent_cls=report_agent_module.Agent,
        )
        delegator_result = harness.agent._process_charts(content)

        assert direct_result == delegator_result

    def test_agent_cls_is_resolved_at_call_time_from_report_agent_modules_global(self, monkeypatch):
        """Proves the injection decision: the delegator forwards
        `agent_cls=Agent`, reading `deepear.src.agents.report.agent`'s own
        module-global `Agent` name (the module `ReportAgent` -- and
        `_process_charts` -- are defined in) each time `_process_charts` is
        called -- not a value captured once at construction time. Re-patching
        `report_agent_module.Agent` *after* the `ReportAgent` (and its
        four long-lived agents) already exist still changes what the
        "transmission" chart type's nested throwaway Agent construction
        resolves to, exactly like it would for the harness's original
        patch applied before construction.
        """
        from tests.report_agent_harness import FakeRunResponse

        install_fake_visualizer(monkeypatch)
        install_fake_stock_tools(monkeypatch)
        harness = make_report_agent(monkeypatch)

        import deepear.src.agents.report.agent as report_agent_module

        second_fake_calls: list[dict] = []

        class SecondFakeAgent:
            def __init__(self, **kwargs):
                second_fake_calls.append(kwargs)

            def run(self, prompt):
                return FakeRunResponse('<mxGraphModel dx="1" dy="1"></mxGraphModel>')

        # Re-patch *after* harness.agent was already constructed with the
        # first FakeAgent -- this only affects future `Agent(...)` calls
        # that read the name fresh, i.e. the nested throwaway construction.
        monkeypatch.setattr(report_agent_module, "Agent", SecondFakeAgent)

        content = (
            "```json-chart\n"
            '{"type": "transmission", "nodes": [{"label": "A"}], "title": "T"}\n'
            "```"
        )

        result = harness.agent._process_charts(content)

        assert len(second_fake_calls) == 1
        assert '<iframe src="charts/trans_' in result
