"""Tests for `extract-report-agent-retry-helper` (Phase 4 step 25).

Covers the moved pure function directly
(`deepear.src.agents.report.retry.run_agent_with_retry`) and the
patchability of `ReportAgent._run_agent_with_retry`, the one-line delegator
left behind on the class. The existing pinned-behavior coverage in
`tests/test_report_agent_characterization.py::TestRunAgentWithRetry` keeps
exercising the same success/retry/exhaustion/timeout paths through the
`ReportAgent` method and is intentionally left untouched by this change --
this file adds direct-function coverage plus a class-attribute patchability
regression test that characterization suite doesn't cover.
"""

from __future__ import annotations

from deepear.src.agents.report.retry import run_agent_with_retry
from deepear.src.agents.report_agent import ReportAgent
from tests.report_agent_harness import FakeAgent, make_report_agent, raising

# Keep the retry/timeout knobs tiny so these tests run fast without
# depending on any ReportAgent instance.
_MAX_RETRIES = 2
_TIMEOUT_SECONDS = 5
_RETRY_DELAY = 0.01


class TestRunAgentWithRetryDirect:
    """Exercise the moved module-level function without a ReportAgent."""

    def test_returns_content_on_success(self):
        fake = FakeAgent(run_fn=lambda prompt: "the content")

        result = run_agent_with_retry(
            fake,
            "some prompt",
            context="test",
            max_retries=_MAX_RETRIES,
            timeout_seconds=_TIMEOUT_SECONDS,
            retry_delay=_RETRY_DELAY,
        )

        assert result == "the content"
        assert fake.calls == ["some prompt"]

    def test_retries_on_exception_then_succeeds(self):
        attempts = {"count": 0}

        def flaky(prompt: str) -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient failure")
            return "recovered"

        fake = FakeAgent(run_fn=flaky)
        result = run_agent_with_retry(
            fake,
            "prompt",
            context="test",
            max_retries=_MAX_RETRIES,
            timeout_seconds=_TIMEOUT_SECONDS,
            retry_delay=_RETRY_DELAY,
        )

        assert result == "recovered"
        assert attempts["count"] == 2
        assert len(fake.calls) == 2

    def test_exhausts_retries_returns_none(self):
        # Characterizes CURRENT behavior (moved verbatim): after max_retries
        # retries (i.e. max_retries + 1 total attempts) all raising, the
        # function swallows the final exception and returns None rather than
        # re-raising.
        fake = FakeAgent(run_fn=raising(RuntimeError("always fails")))

        result = run_agent_with_retry(
            fake,
            "prompt",
            context="test",
            max_retries=_MAX_RETRIES,
            timeout_seconds=_TIMEOUT_SECONDS,
            retry_delay=_RETRY_DELAY,
        )

        assert result is None
        assert len(fake.calls) == _MAX_RETRIES + 1

    def test_default_context_is_llm_call(self):
        # `context` defaults to "LLM call" in both the original method
        # signature and the moved function signature.
        fake = FakeAgent(run_fn=lambda prompt: "ok")

        result = run_agent_with_retry(
            fake,
            "prompt",
            max_retries=_MAX_RETRIES,
            timeout_seconds=_TIMEOUT_SECONDS,
            retry_delay=_RETRY_DELAY,
        )

        assert result == "ok"


class TestReportAgentDelegatorPatchability:
    """`ReportAgent._run_agent_with_retry` must remain a real, patchable method."""

    def test_instance_method_still_delegates_correctly(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        agent = harness.agent
        fake = FakeAgent(run_fn=lambda prompt: "delegated content")

        result = agent._run_agent_with_retry(fake, "some prompt", context="test")

        assert result == "delegated content"
        assert fake.calls == ["some prompt"]

    def test_instance_method_forwards_per_instance_overrides(self, monkeypatch):
        # The delegator reads self.LLM_MAX_RETRIES/self.LLM_RETRY_DELAY at
        # call time (not baked-in class constants), so per-instance
        # overrides -- as used throughout
        # tests/test_report_agent_characterization.py -- keep working.
        harness = make_report_agent(monkeypatch)
        agent = harness.agent
        agent.LLM_MAX_RETRIES = 1
        agent.LLM_RETRY_DELAY = 0.01

        fake = FakeAgent(run_fn=raising(RuntimeError("always fails")))
        result = agent._run_agent_with_retry(fake, "prompt", context="test")

        assert result is None
        assert len(fake.calls) == agent.LLM_MAX_RETRIES + 1 == 2

    def test_class_attribute_patch_intercepts_internal_generate_report_calls(self, monkeypatch):
        # Regression test for ground rule 5/2: patching
        # `ReportAgent._run_agent_with_retry` as a class attribute must still
        # intercept every internal `self._run_agent_with_retry(...)` call
        # site inside `generate_report`'s incremental branch (section
        # editing, summary generation, tail/reference generation -- see
        # deepear/src/agents/report_agent.py lines ~1040/1062/1079).
        original = ReportAgent._run_agent_with_retry
        calls: list[str] = []

        def spy(self, agent, prompt, context="LLM call"):
            calls.append(context)
            return original(self, agent, prompt, context=context)

        monkeypatch.setattr(ReportAgent, "_run_agent_with_retry", spy)

        router = _build_incremental_router()
        harness = make_report_agent(monkeypatch, router=router, incremental_edit=True)

        signals = _make_signals()
        result = harness.agent.generate_report(signals, user_query="test query")

        assert result.content.startswith("# DeepEar")
        # The class-attribute patch was honored for all three call sites.
        assert "Section 1/1 editing" in calls
        assert "Summary generation" in calls
        assert "Tail content generation" in calls
        assert len(calls) == 3


# ---------------------------------------------------------------------------
# Minimal incremental-mode fixtures, mirroring
# tests/test_report_agent_characterization.py::_build_incremental_router /
# _make_signals so this file can drive `generate_report` end to end without
# importing test-module-private helpers from another test file.
# ---------------------------------------------------------------------------


def _build_incremental_router():
    from tests.report_agent_harness import ScriptedAgentRouter

    router = ScriptedAgentRouter()

    cluster_json = (
        '{"clusters": [{"theme_title": "主题A", '
        '"signal_ids": [1, 2], "rationale": "关联信号"}]}'
    )
    router.when_contains("聚类", cluster_json)

    writer_section = (
        "## 主题分析\n\n正文内容。\n"
    )
    router.when_contains("撰写深度分析章节", writer_section)

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


def _make_signals():
    return [
        {
            "title": "Signal One Title",
            "summary": "Signal one summary",
            "url": "https://example.com/source-one",
            "source": "ExampleWire",
            "publish_time": "2026-07-20",
            "sources": [
                {
                    "title": "Source One Headline",
                    "url": "https://example.com/source-one",
                    "source_name": "ExampleWire",
                    "publish_time": "2026-07-20",
                }
            ],
            "sentiment_score": 0.4,
            "confidence": 0.7,
            "intensity": 3,
            "impact_tickers": [],
            "expected_horizon": "T+3",
        },
        {
            "title": "Signal Two Title",
            "summary": "Signal two summary",
            "url": "https://example.com/source-two",
            "source": "ExampleWire",
            "publish_time": "2026-07-21",
            "sources": [
                {
                    "title": "Source Two Headline",
                    "url": "https://example.com/source-two",
                    "source_name": "ExampleWire",
                    "publish_time": "2026-07-21",
                }
            ],
            "sentiment_score": -0.2,
            "confidence": 0.5,
            "intensity": 2,
            "impact_tickers": [],
            "expected_horizon": "T+1",
        },
    ]
