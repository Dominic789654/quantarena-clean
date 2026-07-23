## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "report_agent\._run_agent_with_retry\|_run_agent_with_retry" tests/ deepear/`
  — hits in `tests/report_agent_harness.py` (docstring mentions only),
  `tests/test_report_agent_characterization.py` (four direct
  `agent._run_agent_with_retry(...)` calls, no monkeypatch of the name),
  and `deepear/src/agents/report_agent.py` (the method definition plus
  three internal `self._run_agent_with_retry(...)` call sites inside
  `generate_report`'s incremental branch).
- [x] 1.2 Confirm no literal `monkeypatch.setattr("...")` string path and
  no class-attribute patch of `_run_agent_with_retry` exists anywhere in
  the repo today — none found.
- [x] 1.3 Check `deepear/src/agents/__init__.py` convention (real package,
  explicit re-exports) and `tests/test_report_agent_citations.py` /
  `deepear/src/agents/report_agent.py`'s own import spelling
  (`deepear.src.agents.*`) to confirm the new `report/` subpackage must be
  reachable the same way, given the `pin-agents-package-resolution` rule
  that bare `agents.*` resolves to `deepfund`.

## 2. Implementation

- [x] 2.1 Create `deepear/src/agents/report/__init__.py` (docstring only,
  no re-exports) and `deepear/src/agents/report/retry.py`.
- [x] 2.2 `retry.py`: move `_run_agent_with_retry`'s body verbatim into
  `run_agent_with_retry(agent, prompt, context="LLM call", *, max_retries,
  timeout_seconds, retry_delay)`; rewrite the three `self.LLM_*` reads to
  the corresponding parameter names (the one ground-rule-6-mandated
  rewrite); move the function-local `import threading` to module level.
- [x] 2.3 `report_agent.py`: add `from deepear.src.agents.report.retry
  import run_agent_with_retry`; replace `_run_agent_with_retry`'s body
  with a one-line delegator forwarding `self.LLM_MAX_RETRIES`,
  `self.LLM_TIMEOUT_SECONDS`, `self.LLM_RETRY_DELAY`.

## 3. Tests

- [x] 3.1 Add `tests/test_report_retry_helper.py`: direct
  `run_agent_with_retry` coverage (success, retry-then-succeed,
  exhaustion, default `context`) via `tests/report_agent_harness.py`'s
  `FakeAgent`/`raising`.
- [x] 3.2 Same file: instance-method delegation test, per-instance
  `LLM_*`-override forwarding test, and a class-attribute patchability
  regression test proving a patched `ReportAgent._run_agent_with_retry`
  intercepts all three internal call sites during a real
  `generate_report` run.
- [x] 3.3 Confirm `tests/test_report_agent_characterization.py`'s
  `TestRunAgentWithRetry` (4 tests) still passes unchanged.

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_retry_helper.py tests/test_report_agent_characterization.py -q`
  — 29 passed (7 new + 22 characterization).
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` — 974 passed (967 baseline
  + 7 new), 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
