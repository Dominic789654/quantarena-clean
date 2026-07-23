"""Regression test for the non-incremental ReportAgent citation-normalization bug.

`ReportAgent._normalize_citations(report_md, signal_to_keys, key_to_num)` requires all
three arguments. The non-incremental final-assembly branch in `generate_report`
(deepear/src/agents/report_agent.py) used to call it with only two, so any
`ReportAgent(..., incremental_edit=False)` run whose joined section length stayed under
the 80k-char incremental threshold raised a `TypeError` at final assembly. This test
builds a *real* `ReportAgent` (only the `agno.agent.Agent` class is stubbed, via
monkeypatch on the module attribute -- no sys.modules replacement) and drives
`generate_report` down that exact branch.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from deepear.src.agents.report_agent import ReportAgent

# Two example bibliography sources; keys are derived deterministically from
# (url, title, source_name) the same way ReportAgent._build_bibliography does it.
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

_SIGNALS = [
    {
        "title": "Signal One Title",
        "url": _SOURCE_ONE["url"],
        "source": _SOURCE_ONE["source_name"],
        "publish_time": _SOURCE_ONE["publish_time"],
        "sources": [_SOURCE_ONE],
    },
    {
        "title": "Signal Two Title",
        "url": _SOURCE_TWO["url"],
        "source": _SOURCE_TWO["source_name"],
        "publish_time": _SOURCE_TWO["publish_time"],
        "sources": [_SOURCE_TWO],
    },
]

# Canned Writer section: short, references both cite keys with the `[@KEY]` marker
# that `_normalize_citations` is responsible for turning into `[N](#ref-KEY)`.
_WRITER_SECTION_MD = (
    "## 主题草稿\n\n"
    f"核心判断依据信号支撑 [@{_KEY_ONE}] 以及 [@{_KEY_TWO}]。\n"
)

# Canned final-assembly (Editor) response for the non-incremental branch. This is
# the content that flows straight into the buggy call site at report_agent.py:970.
_FINAL_EDITOR_MD = (
    "# 测试研报标题\n\n"
    "## 核心观点摘要\n\n"
    f"综合两条信号 [@{_KEY_ONE}] 与 [@{_KEY_TWO}]，判断趋势延续。\n\n"
    "## 风险提示\n\n"
    "本报告由 AI 自动生成，仅供参考，不构成投资建议。\n"
)


class FakeModel:
    """Minimal stand-in for agno.models.base.Model."""

    id = "fake-model"


class FakeAgent:
    """Minimal stand-in for agno.agent.Agent.

    Dispatches canned responses based on distinctive substrings in the task
    prompt, mirroring the prompts produced by deepear.src.prompts.report_agent.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.instructions = kwargs.get("instructions", [])

    def run(self, prompt: str):
        if "聚类" in prompt:
            # Force cluster-JSON parsing to fail so generate_report falls back to
            # one cluster per signal -- this exercises the Writer path below.
            content = "（无法完成聚类，请忽略此响应）"
        elif "撰写深度分析章节" in prompt:
            content = _WRITER_SECTION_MD
        elif "终稿大纲" in prompt:
            content = "（终稿大纲：保持原有章节顺序，无重大分歧）"
        elif "生成最终研报" in prompt:
            content = _FINAL_EDITOR_MD
        else:
            content = ""
        return SimpleNamespace(content=content)


def _make_fake_db() -> Mock:
    """Minimal DatabaseManager stub: only `lookup_reference_by_url` is touched on
    this code path (via ReportAgent._build_bibliography), and it must return None
    so the bibliography falls back to the signal-provided title/source/url.
    """
    db = Mock(name="FakeDatabaseManager")
    db.lookup_reference_by_url = Mock(return_value=None)
    return db


def test_non_incremental_report_generation_normalizes_citations(monkeypatch):
    monkeypatch.setattr("deepear.src.agents.report_agent.Agent", FakeAgent)

    db = _make_fake_db()
    model = FakeModel()
    tool_model = FakeModel()

    agent = ReportAgent(db, model, incremental_edit=False, tool_model=tool_model)

    # Sanity check: our two small signals must stay far below the 80k-char
    # incremental threshold (report_agent.py:917) so the non-incremental branch
    # -- the one with the fixed call site -- is the one that actually runs.
    assert len(_WRITER_SECTION_MD) * len(_SIGNALS) < 80_000

    result = agent.generate_report(_SIGNALS, user_query="test query")

    report_md = result.content

    # Citation markers were normalized into numbered, anchored links, not left
    # as raw `[@KEY]` markers.
    assert f"[@{_KEY_ONE}]" not in report_md
    assert f"[@{_KEY_TWO}]" not in report_md
    assert f"(#ref-{_KEY_ONE})" in report_md
    assert f"(#ref-{_KEY_TWO})" in report_md

    # Programmatic bibliography section was injected with the same keys.
    assert "## 参考文献" in report_md
    assert f'<a id="ref-{_KEY_ONE}"></a>' in report_md
    assert f'<a id="ref-{_KEY_TWO}"></a>' in report_md
