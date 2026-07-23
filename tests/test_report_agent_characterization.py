"""Characterization tests for `deepear.src.agents.report_agent.ReportAgent`.

Seeded by `tests/test_report_agent_citations.py` (the only prior test that built a
*real* `ReportAgent`) and built on the reusable fakes in
`tests/report_agent_harness.py`. These tests pin CURRENT behavior ahead of the
Phase 4 verbatim-move extractions (docs/refactor_program_plan.md, step 24) -- no
production code changes are made here. Where current behavior looks like a latent
bug, the test's docstring/comment says so explicitly instead of "fixing" it.
"""

from __future__ import annotations

from deepear.src.agents.report_agent import ReportAgent
from tests.report_agent_harness import (
    FakeAgent,
    FakeDatabaseManager,
    FakeModel,
    ScriptedAgentRouter,
    make_report_agent,
    make_scripted_agent_class,
    raising,
)

# ---------------------------------------------------------------------------
# Shared fixtures: two bibliography sources / signals, mirroring
# tests/test_report_agent_citations.py's shape.
# ---------------------------------------------------------------------------

_SOURCE_ONE = {
    "title": "Source One Headline",
    "url": "https://example.com/source-one",
    "source_name": "ExampleWire",
    "publish_time": "2026-07-20",
}
_SOURCE_TWO = {
    "title": "Source Two Headline",
    "url": "https://example.com/source-two",
    "source_name": "ExampleWire",
    "publish_time": "2026-07-21",
}

_KEY_ONE = ReportAgent._make_cite_key(
    url=_SOURCE_ONE["url"], title=_SOURCE_ONE["title"], source_name=_SOURCE_ONE["source_name"]
)
_KEY_TWO = ReportAgent._make_cite_key(
    url=_SOURCE_TWO["url"], title=_SOURCE_TWO["title"], source_name=_SOURCE_TWO["source_name"]
)


def _make_signals() -> list[dict]:
    return [
        {
            "title": "Signal One Title",
            "summary": "Signal one summary",
            "url": _SOURCE_ONE["url"],
            "source": _SOURCE_ONE["source_name"],
            "publish_time": _SOURCE_ONE["publish_time"],
            "sources": [_SOURCE_ONE],
            "sentiment_score": 0.4,
            "confidence": 0.7,
            "intensity": 3,
            "impact_tickers": [],
            "expected_horizon": "T+3",
        },
        {
            "title": "Signal Two Title",
            "summary": "Signal two summary",
            "url": _SOURCE_TWO["url"],
            "source": _SOURCE_TWO["source_name"],
            "publish_time": _SOURCE_TWO["publish_time"],
            "sources": [_SOURCE_TWO],
            "sentiment_score": -0.2,
            "confidence": 0.5,
            "intensity": 2,
            "impact_tickers": [],
            "expected_horizon": "T+1",
        },
    ]


# ---------------------------------------------------------------------------
# 1. Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_incremental_edit_true_by_default(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        agent = harness.agent

        assert agent.incremental_edit is True
        assert agent.db is harness.db
        assert agent.model is harness.model
        assert agent.tool_model is harness.tool_model
        # Four internal agents, all built (planner/writer/editor/section_editor).
        assert agent.planner is not None
        assert agent.writer is not None
        assert agent.editor is not None
        assert agent.section_editor is not None
        # Forecast agent is lazy: never constructed just from __init__.
        assert agent._forecast_agent is None
        assert harness.forecast_construct_counter["count"] == 0

    def test_incremental_edit_false_is_honored(self, monkeypatch):
        harness = make_report_agent(monkeypatch, incremental_edit=False)
        assert harness.agent.incremental_edit is False

    def test_tool_model_defaults_to_model_when_omitted(self, monkeypatch):
        model = FakeModel()
        router = ScriptedAgentRouter()
        # Patched on `deepear.src.agents.report.agent` -- ReportAgent's real
        # home since `finalize-report-agent-package-and-shim` -- not on the
        # `report_agent` shim, whose re-export of `Agent` (if it had one)
        # would not affect the name the class body actually reads.
        monkeypatch.setattr(
            "deepear.src.agents.report.agent.Agent",
            make_scripted_agent_class(router),
        )
        agent = ReportAgent(FakeDatabaseManager(), model, incremental_edit=True)
        assert agent.tool_model is model

    def test_planner_output_schema_gated_by_tool_model_response_format(self, monkeypatch):
        # Without `response_format` on the tool_model, output_schema stays None
        # (characterizes the `hasattr(self.tool_model, 'response_format')` gate).
        harness_without = make_report_agent(monkeypatch, tool_model=FakeModel(with_response_format=False))
        assert harness_without.agent.planner.kwargs.get("output_schema") is None

    def test_planner_output_schema_set_when_tool_model_has_response_format(self, monkeypatch):
        from deepear.src.schema.models import ClusterContext

        harness_with = make_report_agent(monkeypatch, tool_model=FakeModel(with_response_format=True))
        assert harness_with.agent.planner.kwargs.get("output_schema") is ClusterContext


# ---------------------------------------------------------------------------
# 2. `_run_agent_with_retry`
# ---------------------------------------------------------------------------


class TestRunAgentWithRetry:
    def test_returns_content_on_success(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        agent = harness.agent
        fake = FakeAgent(run_fn=lambda prompt: "the content")

        result = agent._run_agent_with_retry(fake, "some prompt", context="test")

        assert result == "the content"
        assert fake.calls == ["some prompt"]

    def test_retries_on_exception_then_succeeds(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        agent = harness.agent
        agent.LLM_RETRY_DELAY = 0.01  # keep the exponential-backoff sleep tiny

        attempts = {"count": 0}

        def flaky(prompt: str) -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient failure")
            return "recovered"

        fake = FakeAgent(run_fn=flaky)
        result = agent._run_agent_with_retry(fake, "prompt", context="test")

        assert result == "recovered"
        assert attempts["count"] == 2
        assert len(fake.calls) == 2

    def test_exhausts_retries_returns_none(self, monkeypatch):
        # Characterizes CURRENT behavior: after LLM_MAX_RETRIES retries (i.e.
        # LLM_MAX_RETRIES + 1 total attempts) all raising, the method swallows
        # the final exception and returns None rather than re-raising.
        harness = make_report_agent(monkeypatch)
        agent = harness.agent
        agent.LLM_RETRY_DELAY = 0.01

        fake = FakeAgent(run_fn=raising(RuntimeError("always fails")))
        result = agent._run_agent_with_retry(fake, "prompt", context="test")

        assert result is None
        assert len(fake.calls) == agent.LLM_MAX_RETRIES + 1

    def test_timeout_path_returns_none_after_retries(self, monkeypatch):
        # Characterizes CURRENT behavior: a run() that never returns within
        # LLM_TIMEOUT_SECONDS is retried LLM_MAX_RETRIES times (each also
        # timing out) and then the method returns None. Note: the background
        # thread from each timed-out attempt is never joined again or
        # cancelled -- Python threads cannot be force-killed -- so it keeps
        # running detached until its own sleep finishes; this is pre-existing
        # behavior, not something this test fixes.
        harness = make_report_agent(monkeypatch)
        agent = harness.agent
        agent.LLM_TIMEOUT_SECONDS = 0.05
        agent.LLM_RETRY_DELAY = 0.01

        import time

        def never_finishes_in_time(prompt: str) -> str:
            time.sleep(0.3)
            return "too late"

        fake = FakeAgent(run_fn=never_finishes_in_time)
        result = agent._run_agent_with_retry(fake, "prompt", context="test")

        assert result is None


# ---------------------------------------------------------------------------
# 3. `generate_report` end-to-end happy path (incremental mode, the default)
# ---------------------------------------------------------------------------


def _build_incremental_router() -> ScriptedAgentRouter:
    router = ScriptedAgentRouter()

    cluster_json = (
        '{"clusters": [{"theme_title": "主题A", '
        '"signal_ids": [1, 2], "rationale": "关联信号"}]}'
    )
    router.when_contains("聚类", cluster_json)

    writer_section = (
        "## 主题分析\n\n"
        f"正文内容，支持依据 [@{_KEY_ONE}] "
        f"以及 [@{_KEY_TWO}]。\n\n"
        "```json-chart\n"
        '{"type": "stock", "ticker": "N/A", "title": "占位图"}\n'
        "\n后续段落内容，紧跟着未闭合的图表块。\n"
    )
    router.when_contains("撰写深度分析章节", writer_section)

    # Incremental section-editing pass-through: echo back the section body
    # verbatim, characterizing an editor that keeps content unchanged.
    def echo_section(prompt: str) -> str:
        marker = "请编辑以下章节内容：\n\n"
        return prompt.split(marker, 1)[1]

    router.when_contains("请编辑以下章节内容", echo_section)

    router.when_contains("请生成核心观点摘要", "## 核心观点摘要\n\n测试摘要内容。\n")

    tail = (
        "## 参考文献\n\n（占位，将被程序化覆盖）\n\n"
        "## 风险提示\n\n本报告仅供参考。\n\n"
        "## 快速扫描\n\n| 主题 | 观点 |\n|---|---|\n| 主题A | 看多 |\n"
    )
    router.when_contains("请生成参考文献、风险提示和快速扫描表格", tail)

    return router


class TestGenerateReportEndToEnd:
    def test_happy_path_incremental(self, monkeypatch):
        router = _build_incremental_router()
        harness = make_report_agent(monkeypatch, router=router, incremental_edit=True)
        agent = harness.agent

        signals = _make_signals()
        result = agent.generate_report(signals, user_query="test query")
        report_md = result.content

        # Title + TOC always present for the incremental assembly template.
        assert report_md.startswith("# DeepEar")
        assert "[TOC]" in report_md

        # Summary and quick-scan content landed.
        assert "## 核心观点摘要" in report_md
        assert "快速扫描" in report_md

        # Citation normalization: legacy `[@KEY]` markers are gone, replaced
        # by numbered anchored links, and the programmatic bibliography (not
        # the LLM's placeholder text) was injected.
        assert f"[@{_KEY_ONE}]" not in report_md
        assert f"[@{_KEY_TWO}]" not in report_md
        assert f"(#ref-{_KEY_ONE})" in report_md
        assert f"(#ref-{_KEY_TWO})" in report_md
        assert "（占位，将被程序化覆盖）" not in report_md

        # Chart-block sanitization + processing: the unclosed json-chart fence
        # was repaired and consumed (no literal fence survives), the invalid
        # ticker produced the documented fallback comment, and the trailing
        # prose after the chart block survived untouched.
        assert "```json-chart" not in report_md
        assert "<!-- 无法解析股票代码: N/A -->" in report_md
        assert "后续段落内容" in report_md

        # Structured report shape from build_structured_report.
        structured = result.structured
        assert structured["title"].startswith("DeepEar")
        assert len(structured["signals"]) == 2
        assert structured["signals"][0]["title"] == "Signal One Title"
        assert len(structured["clusters"]) == 1
        assert structured["clusters"][0]["title"] == "主题A"
        assert structured["clusters"][0]["signal_ids"] == [1, 2]

        # No heavy forecast/Kronos pipeline was touched by this scenario.
        assert harness.forecast_construct_counter["count"] == 0


# ---------------------------------------------------------------------------
# 4. `_cluster_signals`
# ---------------------------------------------------------------------------


class TestClusterSignals:
    def test_uses_planner_and_parses_cluster_json(self, monkeypatch):
        router = ScriptedAgentRouter()
        router.when_contains(
            "聚类",
            '{"clusters": [{"theme_title": "T", "signal_ids": [1, 2]}]}',
        )
        harness = make_report_agent(monkeypatch, router=router)
        agent = harness.agent

        clusters = agent._cluster_signals(_make_signals(), user_query="q")

        assert clusters == [{"theme_title": "T", "signal_ids": [1, 2]}]
        # Only the planner agent was exercised for clustering.
        assert len(router.calls) == 1
        assert "聚类" in router.calls[0]
        assert agent.planner.calls == router.calls

    def test_falls_back_to_empty_list_on_unparsable_json(self, monkeypatch):
        # Characterizes the fallback path `generate_report` relies on to build
        # one cluster per signal when the planner's response isn't valid JSON.
        router = ScriptedAgentRouter()
        router.when_contains("聚类", "（无法完成聚类）")
        harness = make_report_agent(monkeypatch, router=router)

        clusters = harness.agent._cluster_signals(_make_signals(), user_query=None)

        assert clusters == []

    def test_returns_empty_list_when_planner_raises(self, monkeypatch):
        router = ScriptedAgentRouter()
        router.when_contains("聚类", raising(RuntimeError("planner exploded")))
        harness = make_report_agent(monkeypatch, router=router)

        clusters = harness.agent._cluster_signals(_make_signals(), user_query=None)

        assert clusters == []


# ---------------------------------------------------------------------------
# 5. `_build_forecast_map` / `_extract_forecast_requests`
# ---------------------------------------------------------------------------


class TestForecastMap:
    def test_extract_forecast_requests_shape(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "T1"}\n'
            "```\n"
        )
        requests = harness.agent._extract_forecast_requests(text)

        assert len(requests) == 1
        req = requests[0]
        assert req["ticker"] == "600001"
        assert req["pred_len"] == 5
        assert req["title"] == "T1"
        assert "context_snippet" in req

    def test_no_forecast_request_never_constructs_forecast_agent(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        agent = harness.agent

        forecasts = agent._build_forecast_map("no chart blocks here", signals=_make_signals())

        assert forecasts == {}
        assert harness.forecast_construct_counter["count"] == 0
        assert agent._forecast_agent is None

    def test_forecast_agent_constructed_at_most_once_across_multiple_requests(self, monkeypatch):
        harness = make_report_agent(monkeypatch, forecast_result=None)
        agent = harness.agent

        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5}\n'
            "```\n\n"
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600002", "pred_len": 5}\n'
            "```\n"
        )
        signals = [
            {
                "title": "600001 bullish",
                "analysis": "600001 outlook is strong",
                "impact_tickers": [{"ticker": "600001"}],
            },
            {
                "title": "600002 bearish",
                "analysis": "600002 outlook is weak",
                "impact_tickers": [{"ticker": "600002"}],
            },
        ]

        agent._build_forecast_map(text, signals=signals)

        # Two distinct (ticker, pred_len) groups both called generate_forecast,
        # but the underlying (would-be Kronos-backed) ForecastAgent was only
        # constructed once -- ReportAgent._get_forecast_agent's own lazy-cache
        # (untouched by the harness) is what makes this true.
        assert harness.forecast_construct_counter["count"] == 1
        assert agent._forecast_agent is not None
        assert len(agent._forecast_agent.calls) == 2
        called_tickers = {c["ticker"] for c in agent._forecast_agent.calls}
        assert called_tickers == {"600001", "600002"}


# ---------------------------------------------------------------------------
# 6. `_clean_markdown` / `_sanitize_json_chart_blocks` edge cases
# ---------------------------------------------------------------------------


class TestCleanMarkdownAndSanitize:
    def test_clean_markdown_strips_markdown_fence(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        text = "```markdown\n# Title\n\ncontent\n```"
        assert harness.agent._clean_markdown(text) == "# Title\n\ncontent"

    def test_clean_markdown_strips_bare_fence(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        text = "```\nplain content\n```"
        assert harness.agent._clean_markdown(text) == "plain content"

    def test_clean_markdown_no_fence_is_unchanged(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        text = "  already clean  "
        assert harness.agent._clean_markdown(text) == "already clean"

    def test_sanitize_leaves_well_formed_block_unchanged(self):
        # Note: a trailing newline after the closing fence is NOT preserved --
        # phase 0's line-by-line fence normalization rejoins with `"\n".join`,
        # which drops a final trailing newline. Characterized here rather than
        # asserted away; callers that care about trailing whitespace should
        # `.strip()` (as `generate_report` itself does before returning).
        text = '```json-chart\n{"type": "stock", "ticker": "600001"}\n```'
        assert ReportAgent._sanitize_json_chart_blocks(text) == text

    def test_sanitize_repairs_missing_closing_fence(self):
        text = (
            "```json-chart\n"
            '{"type": "stock", "ticker": "600001"}\n'
            "\ntrailing prose with no fence at all\n"
        )
        repaired = ReportAgent._sanitize_json_chart_blocks(text)

        assert "```json-chart" in repaired
        # A closing fence was inserted right after the JSON object...
        assert '{"type": "stock", "ticker": "600001"}\n```' in repaired
        # ...and the trailing prose survived, outside the (now-closed) block.
        assert "trailing prose with no fence at all" in repaired

    def test_sanitize_noop_without_json_chart_marker(self):
        text = "plain markdown with no chart blocks\n"
        assert ReportAgent._sanitize_json_chart_blocks(text) == text
