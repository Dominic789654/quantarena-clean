## Context

`ReportAgent._run_agent_with_retry` (`deepear/src/agents/report_agent.py`,
~52 lines including its nested `run_in_thread` closure) wraps a single
`agent.run(prompt)` call with a background-thread timeout
(`self.LLM_TIMEOUT_SECONDS`) and up to `self.LLM_MAX_RETRIES` retries with
linear backoff (`self.LLM_RETRY_DELAY * (attempt + 1)`), swallowing every
exception and returning `None` once attempts are exhausted rather than
raising. `grep -n "self\." deepear/src/agents/report_agent.py` restricted to
the method body shows exactly three `self.` reads —
`self.LLM_MAX_RETRIES`, `self.LLM_TIMEOUT_SECONDS`, `self.LLM_RETRY_DELAY` —
all class-level constants (`LLM_TIMEOUT_SECONDS = 120`, `LLM_MAX_RETRIES =
2`, `LLM_RETRY_DELAY = 2`) that `tests/test_report_agent_characterization.py`
already overrides per-instance (e.g. `agent.LLM_RETRY_DELAY = 0.01`) to keep
tests fast. No other instance state (no `self.db`, `self.model`, `self.rag`,
etc.) is touched.

## Goals / Non-Goals

**Goals:** move the method body verbatim into a pure function
`run_agent_with_retry` in `deepear/src/agents/report/retry.py`; thread the
three `self.LLM_*` reads through as explicit keyword-only parameters (ground
rule 6); keep `ReportAgent._run_agent_with_retry` as a real bound method so
every existing `self._run_agent_with_retry(...)` call site and any future
class-/instance-attribute monkeypatch of the name keeps working; add direct
tests for the new module plus a patchability regression test.

**Non-Goals:** changing the retry count, timeout, backoff formula, or the
documented "never raise, return `None`" contract; touching the detached
timed-out-thread quirk (Python threads cannot be force-killed, so a
timed-out `run_in_thread` keeps running until it finishes on its own — this
moves unchanged); building out `deepear/src/agents/report/__init__.py`
re-exports (deferred to `finalize-report-agent-package-and-shim`, step 31);
extracting any other `ReportAgent` method (charts, citations, forecast
coordination, signal clustering — later steps 26-30).

## Decisions

1. **Pure function, keyword-only timing parameters**: `run_agent_with_retry
   (agent, prompt, context="LLM call", *, max_retries, timeout_seconds,
   retry_delay)`. `agent`/`prompt`/`context` keep the original method's
   positional-or-keyword shape and default (`context="LLM call"`) so
   existing call sites (`self._run_agent_with_retry(fake, "some prompt",
   context="test")` in the characterization tests) need no changes when
   called through the delegator. The three `self.LLM_*` reads become
   required keyword-only parameters — required (no default) so a caller
   can never silently fall back to a value that isn't the caller's own
   instance state, matching how `_get_smart_priority_order(signals,
   tickers)` in the Phase 3 scoring extraction made `self.tickers.copy()`
   an explicit required parameter rather than giving it a made-up default.
2. **Delegator forwards `self.LLM_*` at call time, not at import time**:
   `ReportAgent._run_agent_with_retry` reads `self.LLM_MAX_RETRIES` /
   `self.LLM_TIMEOUT_SECONDS` / `self.LLM_RETRY_DELAY` fresh on every call
   (not cached), so a test that does `agent.LLM_RETRY_DELAY = 0.01` *after*
   constructing the `ReportAgent` (as every characterization test does)
   still has that override honored. This is the one property that makes
   the split behavior-preserving rather than just body-preserving.
3. **`import threading` moves to module level**: the original method had
   `import threading` as its first line (a function-local import, likely a
   historical accident rather than a deliberate lazy-import). Moving it to
   `retry.py`'s top-level imports (alongside `time`, already a top-level
   import in `report_agent.py`) is "surrounding glue," explicitly allowed
   to differ by ground rule 1, and is the idiomatic module shape used by
   every prior Phase 2/3 leaf module (e.g. `backtest/workflow/scoring.py`).
4. **Class keeps a real bound method, not a bare alias**: unlike the
   Phase-3 `staticmethod(scoring._signal_label)` pattern (used there
   because those functions took no instance state at all),
   `_run_agent_with_retry` is defined here as a normal `def` method whose
   body is a single `return run_agent_with_retry(...)` call, because it
   must read `self.LLM_*` to build the call. This is exactly the
   `_calculate_priority_score`-style delegator from the scoring
   extraction, not the `_signal_label`-style static delegator.
5. **New test file, not an extension of the characterization suite**:
   `tests/test_report_retry_helper.py` is new rather than folding into
   `tests/test_report_agent_characterization.py`, because the
   characterization suite's charter (per its own module docstring) is
   pinning `ReportAgent`'s *current* behavior ahead of extraction and
   should not itself change shape as extractions land; this step's own
   tests (direct-function coverage + the class-attribute patchability
   regression) belong with the step that motivates them.

## Risks / Trade-offs

- Making `max_retries`/`timeout_seconds`/`retry_delay` keyword-only with no
  defaults means any *other* future caller of `run_agent_with_retry` must
  supply all three explicitly — acceptable because the only current caller
  (`ReportAgent._run_agent_with_retry`) already has these values available
  as `self.LLM_*` attributes, and requiring them explicitly is exactly the
  point of hoisting them out of `self`.
- `deepear/src/agents/report/__init__.py` stays a docstring-only leaf; if a
  later step needs a package-level re-export (e.g. `from
  deepear.src.agents.report import run_agent_with_retry`), that is
  additive and deferred rather than guessed at now.
