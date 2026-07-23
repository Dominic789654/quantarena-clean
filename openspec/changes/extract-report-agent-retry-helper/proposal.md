## Why

Phase 4 step 25 (docs/refactor_program_plan.md). Step 24
(`build-report-agent-characterization-harness`) landed a reusable fixtures
module (`tests/report_agent_harness.py`) and 22 pinned-behavior tests
(`tests/test_report_agent_characterization.py`) covering
`deepear/src/agents/report_agent.py`'s `ReportAgent` class (1660 lines, no
package structure yet). This step begins the actual decomposition into
`deepear/src/agents/report/`: it extracts the first leaf,
`_run_agent_with_retry` (the LLM-call retry/timeout wrapper around
`agent.run(prompt)`, including its nested `run_in_thread` closure), into a new
module, `deepear/src/agents/report/retry.py`. `TestRunAgentWithRetry` in the
characterization suite already pins the success/retry/exhaustion/timeout
behavior this move must not change.

## What Changes

- Add `deepear/src/agents/report/__init__.py` (docstring only, no
  re-exports yet) and `deepear/src/agents/report/retry.py`.
- `retry.py` exposes `run_agent_with_retry(agent, prompt, context="LLM
  call", *, max_retries, timeout_seconds, retry_delay)`, `_run_agent_with_
  retry`'s body moved verbatim. The only `self.` state the original method
  touched was three class-level constants (`self.LLM_MAX_RETRIES`,
  `self.LLM_TIMEOUT_SECONDS`, `self.LLM_RETRY_DELAY`); per ground rule 6
  these become explicit keyword-only parameters instead of instance reads.
  The nested `run_in_thread` closure and the detached-timed-out-thread
  quirk (a timed-out background thread is never joined again or cancelled)
  move character-for-character.
- `ReportAgent._run_agent_with_retry(self, agent, prompt, context=...)`
  stays a real bound method on the class, reduced to a one-line delegator
  that forwards `self.LLM_MAX_RETRIES`/`self.LLM_TIMEOUT_SECONDS`/
  `self.LLM_RETRY_DELAY` as the new keyword arguments. All three existing
  internal call sites (section editing, summary generation, tail/reference
  generation inside `generate_report`'s incremental branch) keep calling
  `self._run_agent_with_retry(...)` unchanged.
- Add `tests/test_report_retry_helper.py`: direct coverage of
  `run_agent_with_retry` (success, retry-then-succeed, exhaustion, default
  `context`) imported straight from the new module, reusing
  `tests/report_agent_harness.py`'s `FakeAgent`/`raising`; plus a
  patchability regression suite proving the instance method still
  delegates correctly, still honors per-instance `LLM_*` overrides, and
  that patching `ReportAgent._run_agent_with_retry` as a **class
  attribute** still intercepts all three internal call sites inside a real
  `generate_report` run.
- No behavior change. `tests/test_report_agent_characterization.py`'s
  `TestRunAgentWithRetry` (success/retry/exhaustion/timeout, all via the
  `ReportAgent` method) is left completely unmodified and must keep
  passing unchanged.

## Capabilities

### New Capabilities
- `report-agent-retry-helper`: the standalone, pure LLM-call
  retry/timeout wrapper (`run_agent_with_retry`) used by `ReportAgent` for
  every `agent.run(prompt)` call it wants bounded and retried.

### Modified Capabilities
- None.

## Impact

- New files: `deepear/src/agents/report/__init__.py`,
  `deepear/src/agents/report/retry.py`, `tests/test_report_retry_helper.py`.
- Modified: `deepear/src/agents/report_agent.py` (one new fully-qualified
  import, `_run_agent_with_retry`'s body replaced by a one-line delegator).
- Monkeypatch audit (ground rule 2): `git grep -n
  "report_agent\._run_agent_with_retry\|_run_agent_with_retry"` across
  `tests/` and `deepear/` shows: `tests/report_agent_harness.py` (two
  docstring mentions, no code); `tests/test_report_agent_characterization.py`
  (four direct calls, `agent._run_agent_with_retry(fake, ...)` — no
  monkeypatch of the name itself); `deepear/src/agents/report_agent.py`
  (the method definition and its three internal
  `self._run_agent_with_retry(...)` call sites). No literal
  `monkeypatch.setattr("...")` string path and no class-attribute patch of
  `_run_agent_with_retry` exists anywhere in the repo today. `ReportAgent`
  keeps a real bound `_run_agent_with_retry` method (not a bare attribute
  alias to the module function) specifically so a future class-attribute
  or instance-attribute patch of the name keeps intercepting every
  internal call site — verified by this change's own new
  `test_class_attribute_patch_intercepts_internal_generate_report_calls`
  test.
