"""Signal clustering -- extract-report-agent-signal-clusterer (Phase 4 step 30).

`cluster_signals` is `ReportAgent._cluster_signals`'s body
(docs/refactor_program_plan.md, step 30) moved verbatim out of
`deepear/src/agents/report_agent.py`.

`grep -n "self\\."` restricted to the original method's body finds exactly one
`self.`-qualified name, `self.planner`, touched twice: once to reassign
`self.planner.instructions = [instruction]`, and once to call
`self.planner.run(get_cluster_task(signals_preview))`. No other instance state
-- not `self.db`, `self.model`, `self.rag`, and notably not
`self._run_agent_with_retry` -- is read anywhere in the body: the original
method calls `self.planner.run(...)` directly inside its own `try`/`except`,
never through the retry-and-timeout wrapper other Phase 4 steps threaded as a
bound-method callable, so there is no retry-callable to thread here.

Per the program plan's explicit instruction ("share the exact `self.planner`
instance by reference; add an identity-assertion test"), `cluster_signals`
takes a required keyword-only `planner` parameter. Passing `self.planner` into
it already shares it by reference -- Python passes object references, not
copies -- and `report_agent.py` still constructs exactly one `Agent` for the
planner role, in `ReportAgent.__init__`; nothing here reconstructs, copies, or
wraps that instance behind a factory/getter (unlike `_get_forecast_agent`'s
lazy cache). `cluster_signals` reads and mutates the *same* `agno.agent.Agent`
object `ReportAgent.planner` names, before, during, and after the call --
which matters because `self.planner` is a long-lived, stateful collaborator
reused across every phase of `generate_report` that touches it (its
`.instructions` attribute is reassigned by whichever phase runs last, by
design), not a fresh object created per call.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.agent import Agent
from loguru import logger

from deepear.src.utils.json_utils import extract_json
from deepear.src.prompts.report_agent import get_cluster_planner_instructions, get_cluster_task


def cluster_signals(
    signals: List[Dict[str, Any]],
    user_query: Optional[str] = None,
    *,
    planner: Agent,
) -> List[Dict[str, Any]]:
    """
    使用 Planner 将信号聚类为几个核心主题
    返回: [{"theme_title": "主题A", "signal_ids": [1, 2], "rationale": "..."}]
    """
    # 准备简要输入
    signals_preview = ""
    for i, s in enumerate(signals, 1):
        title = s.title if hasattr(s, 'title') else s.get('title', '')
        signals_preview += f"[{i}] {title}\n"

    logger.info(f"🧠 Clustering {len(signals)} signals into themes...")

    instruction = get_cluster_planner_instructions(signals_preview, user_query)
    planner.instructions = [instruction]

    try:
        response = planner.run(get_cluster_task(signals_preview))
        content = response.content

        cluster_data = extract_json(content)
        if cluster_data and "clusters" in cluster_data:
            clusters = cluster_data["clusters"]
            logger.info(f"✅ Created {len(clusters)} signal clusters.")
            return clusters
        else:
            logger.warning("⚠️ Failed to parse cluster JSON, fallback to individual signal mode.")
            return []

    except Exception as e:
        logger.error(f"Signal clustering failed: {e}")
        return []
