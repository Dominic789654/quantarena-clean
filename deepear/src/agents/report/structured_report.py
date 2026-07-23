"""Structured-report builder -- extract-report-agent-pure-chart-and-structured-report-functions (Phase 4 step 26).

`build_structured_report` is `ReportAgent.build_structured_report`'s body
(docs/refactor_program_plan.md, step 26) moved verbatim out of
`deepear/src/agents/report_agent.py`. `grep -n "self\\."` restricted to the
original staticmethod's body finds zero matches -- the method never read or
wrote any `ReportAgent` instance/class state (it only touches its own
`report_md`/`signals`/`clusters` parameters and locals), so this move needed
no parameter-threading at all: the signature is unchanged except for the
removed `@staticmethod` decorator and the leading-underscore-free module
scope.

Title extraction (first `# ` line, defaulting to `"研报"`), section parsing
(`#{2,4}` headings, with an implicit leading `"摘要"` section for any content
before the first heading), summary-bullet extraction (`- `/`* `/`• `
list markers, capped at 8), the dict-or-attribute-style `signal_map` built
via `hasattr`/`getattr` fallbacks (signals may be plain dicts or objects,
e.g. Pydantic-model instances), and the `clusters` -> `structured_clusters`
mapping (`theme_title`/`rationale`/`signal_ids` looked up against
`signal_map`) all move character-for-character.

Monkeypatch audit (ground rule 2): `git grep -n "build_structured_report"`
across `tests/`, `deepear/`, `backtest/`, `deepfund/`, `shared/` finds only:
the method definition and one internal call site
(`self.build_structured_report(...)` inside `generate_report`) in
`deepear/src/agents/report_agent.py`, plus one characterization-test comment
mentioning the name (no call, no monkeypatch) in
`tests/test_report_agent_characterization.py`. No literal
`monkeypatch.setattr("...")` string path and no class-attribute patch of the
name exists anywhere in the repo today. `ReportAgent` keeps a real
`build_structured_report` staticmethod (a one-line delegator to this
module's `build_structured_report`, imported under an aliased name to avoid
shadowing, not a bare attribute alias) so a future
`monkeypatch.setattr(ReportAgent, "build_structured_report", ...)`
class-attribute patch would still intercept the internal
`self.build_structured_report(...)` call site.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def build_structured_report(report_md: str, signals: List[Dict[str, Any]], clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构建结构化研报输出（便于前端渲染）"""
    text = (report_md or "").strip()
    lines = text.splitlines() if text else []

    # 标题
    title = "研报"
    for line in lines:
        if line.startswith("# "):
            title = line.replace("# ", "").strip()
            break

    # 章节解析
    sections: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    for line in lines:
        heading = re.match(r"^(#{2,4})\s+(.*)$", line.strip())
        if heading:
            if current:
                sections.append(current)
            current = {"title": heading.group(2).strip(), "content": []}
            continue
        if current is None:
            current = {"title": "摘要", "content": []}
        current["content"].append(line)
    if current:
        sections.append(current)

    # 摘要要点
    bullets = [
        re.sub(r"^[-*•]\s+", "", text.strip())
        for text in lines
        if text.strip().startswith(("- ", "* ", "• "))
    ]
    bullets = [b for b in bullets if b]

    # 信号映射
    signal_map = {}
    for i, s in enumerate(signals, 1):
        title_s = s.title if hasattr(s, "title") else s.get("title", "")
        signal_map[i] = {
            "id": i,
            "title": title_s,
            "summary": getattr(s, "summary", "") if not isinstance(s, dict) else s.get("summary", ""),
            "sentiment_score": getattr(s, "sentiment_score", None) if not isinstance(s, dict) else s.get("sentiment_score"),
            "confidence": getattr(s, "confidence", None) if not isinstance(s, dict) else s.get("confidence"),
            "intensity": getattr(s, "intensity", None) if not isinstance(s, dict) else s.get("intensity"),
            "impact_tickers": getattr(s, "impact_tickers", []) if not isinstance(s, dict) else s.get("impact_tickers", []),
            "expected_horizon": getattr(s, "expected_horizon", "") if not isinstance(s, dict) else s.get("expected_horizon", "")
        }

    # 聚类
    structured_clusters = []
    for c in clusters or []:
        ids = c.get("signal_ids", []) or []
        structured_clusters.append({
            "title": c.get("theme_title", ""),
            "rationale": c.get("rationale", ""),
            "signal_ids": ids,
            "signals": [signal_map.get(i) for i in ids if i in signal_map]
        })

    return {
        "title": title,
        "summary_bullets": bullets[:8],
        "sections": [
            {"title": s["title"], "content": "\n".join(s["content"]).strip()}
            for s in sections
        ],
        "clusters": structured_clusters,
        "signals": list(signal_map.values())
    }
