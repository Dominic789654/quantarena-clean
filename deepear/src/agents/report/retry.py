"""LLM retry helper -- extract-report-agent-retry-helper (Phase 4 step 25).

`run_agent_with_retry` is `ReportAgent._run_agent_with_retry`'s body moved
verbatim (docs/refactor_program_plan.md, step 25) out of
`deepear/src/agents/report_agent.py`. The only `self.` state the original
method touched was three class-level timeout/retry constants
(`self.LLM_MAX_RETRIES`, `self.LLM_TIMEOUT_SECONDS`, `self.LLM_RETRY_DELAY`) --
per ground rule 6, those become explicit keyword-only parameters
(`max_retries`, `timeout_seconds`, `retry_delay`) instead of being read off an
instance, since this is now a pure function with no `self`. The
characterization tests override these per-instance (e.g. `agent.LLM_RETRY_DELAY
= 0.01` in `tests/test_report_agent_characterization.py`), so
`ReportAgent._run_agent_with_retry` (kept as a real bound method, see below)
forwards its own `self.LLM_*` values at call time -- those overrides keep
working unchanged.

The nested `run_in_thread` closure, the detached-timed-out-thread behavior (a
thread that times out is never joined again or cancelled -- Python threads
cannot be force-killed -- so it keeps running until its own work finishes),
and the exponential-backoff `time.sleep(retry_delay * (attempt + 1))` all move
character-for-character; only `self.LLM_MAX_RETRIES` / `self.LLM_TIMEOUT_SECONDS`
/ `self.LLM_RETRY_DELAY` were mechanically rewritten to the corresponding
parameter names.

Monkeypatch audit (ground rule 2): `git grep -n
"report_agent._run_agent_with_retry\\|_run_agent_with_retry"` across `tests/`
and `deepear/` finds only direct method calls --
`agent._run_agent_with_retry(...)` in
`tests/test_report_agent_characterization.py` and
`self._run_agent_with_retry(...)` inside `report_agent.py`'s own
`generate_report` (three call sites). No literal
`monkeypatch.setattr("...")` string path and no class-attribute patch of
`_run_agent_with_retry` exists anywhere in the repo today. `ReportAgent` keeps
a real `_run_agent_with_retry` bound method (a one-line delegator, not a bare
attribute alias) specifically so a future `monkeypatch.setattr(ReportAgent,
"_run_agent_with_retry", ...)` class-attribute patch -- or an instance-level
`monkeypatch.setattr(agent, "_run_agent_with_retry", ...)` patch -- would still
intercept every internal `self._run_agent_with_retry(...)` call site.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from agno.agent import Agent
from loguru import logger


def run_agent_with_retry(
    agent: Agent,
    prompt: str,
    context: str = "LLM call",
    *,
    max_retries: int,
    timeout_seconds: float,
    retry_delay: float,
) -> Optional[str]:
    """
    带超时和重试的 Agent 调用

    Args:
        agent: agno Agent 实例
        prompt: 输入提示
        context: 用于日志的上下文描述
        max_retries: 最大重试次数（对应原 `self.LLM_MAX_RETRIES`）
        timeout_seconds: 单次 LLM 调用超时（对应原 `self.LLM_TIMEOUT_SECONDS`）
        retry_delay: 重试延迟（秒）（对应原 `self.LLM_RETRY_DELAY`）

    Returns:
        响应内容，如果所有重试都失败则返回 None
    """

    for attempt in range(max_retries + 1):
        try:
            # 使用线程和超时控制
            result = [None]
            exception = [None]

            def run_in_thread():
                try:
                    response = agent.run(prompt)
                    result[0] = response.content if hasattr(response, 'content') else str(response)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join(timeout=timeout_seconds)

            if thread.is_alive():
                # 超时
                logger.warning(f"⚠️ {context} timed out after {timeout_seconds}s (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    time.sleep(retry_delay * (attempt + 1))  # 指数退避
                    continue
                return None

            if exception[0] is not None:
                raise exception[0]

            return result[0]

        except Exception as e:
            logger.warning(f"⚠️ {context} failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                time.sleep(retry_delay * (attempt + 1))  # 指数退避
                continue

    logger.error(f"❌ {context} failed after all retries")
    return None
