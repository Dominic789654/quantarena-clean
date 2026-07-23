## ADDED Requirements

### Requirement: run_agent_with_retry is a pure function taking timing parameters explicitly
`deepear.src.agents.report.retry.run_agent_with_retry(agent, prompt, context="LLM call", *, max_retries, timeout_seconds, retry_delay)` SHALL call `agent.run(prompt)` in a background thread bounded by `timeout_seconds`, SHALL return the response's `.content` (or `str(response)` if it has no `.content`) on success, SHALL retry (re-running `agent.run(prompt)`) up to `max_retries` additional times after either an exception raised by `agent.run` or a timeout, waiting `retry_delay * (attempt + 1)` seconds between attempts, and SHALL return `None` (never raise) once all attempts are exhausted, whether the final attempt raised or timed out.

#### Scenario: Successful call returns content on the first attempt
- **WHEN** `run_agent_with_retry(agent, prompt, max_retries=2, timeout_seconds=120, retry_delay=2)` is called and `agent.run(prompt)` returns a response with `.content == "the content"`
- **THEN** `run_agent_with_retry` returns `"the content"` and `agent.run` was called exactly once

#### Scenario: Transient exception is retried and then succeeds
- **WHEN** `agent.run(prompt)` raises on its first call and succeeds on its second
- **THEN** `run_agent_with_retry` returns the second call's content and `agent.run` was called exactly twice

#### Scenario: All attempts raising exhausts retries and returns None
- **WHEN** `agent.run(prompt)` always raises
- **THEN** `run_agent_with_retry` returns `None` and `agent.run` was called exactly `max_retries + 1` times

#### Scenario: All attempts timing out exhausts retries and returns None without cancelling threads
- **WHEN** `agent.run(prompt)` never returns within `timeout_seconds` on any attempt
- **THEN** `run_agent_with_retry` returns `None` after `max_retries + 1` attempts, and the background thread from each timed-out attempt is left running rather than being cancelled or joined again

### Requirement: ReportAgent._run_agent_with_retry stays a real bound method delegating to run_agent_with_retry
`ReportAgent._run_agent_with_retry(self, agent, prompt, context="LLM call")` SHALL remain a real instance method on the class (not a bare attribute alias) that returns `deepear.src.agents.report.retry.run_agent_with_retry(agent, prompt, context, max_retries=self.LLM_MAX_RETRIES, timeout_seconds=self.LLM_TIMEOUT_SECONDS, retry_delay=self.LLM_RETRY_DELAY)`, reading the three `self.LLM_*` attributes fresh on every call so per-instance overrides set after construction are honored, and SHALL remain patchable as either a class attribute (`monkeypatch.setattr(ReportAgent, "_run_agent_with_retry", ...)`) or an instance attribute such that every internal `self._run_agent_with_retry(...)` call site inside `generate_report` is intercepted by the patch.

#### Scenario: Instance method delegates correctly
- **WHEN** a test calls `agent._run_agent_with_retry(fake_agent, "some prompt", context="test")` directly on a real `ReportAgent`
- **THEN** it returns the same result `run_agent_with_retry` would have returned, and `fake_agent.run` was called with the same prompt

#### Scenario: Per-instance LLM_* overrides are honored
- **WHEN** a test sets `agent.LLM_MAX_RETRIES = 1` and `agent.LLM_RETRY_DELAY = 0.01` after constructing `agent`, then calls `agent._run_agent_with_retry(...)` against an `agent.run` that always raises
- **THEN** `agent.run` is called exactly `agent.LLM_MAX_RETRIES + 1` times, reflecting the overridden value rather than the class default

#### Scenario: Class-attribute patch intercepts internal generate_report call sites
- **WHEN** `ReportAgent._run_agent_with_retry` is patched as a class attribute with a wrapper that records every `context` argument it is called with, and `generate_report` is then run to completion on a real `ReportAgent`
- **THEN** the wrapper's recorded calls include the section-editing, summary-generation, and tail/reference-generation contexts from `generate_report`'s incremental branch, proving the patch was honored at every internal call site
