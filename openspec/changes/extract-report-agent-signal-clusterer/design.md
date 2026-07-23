## Context

`ReportAgent._cluster_signals` (`deepear/src/agents/report_agent.py:288`)
is the first phase of `generate_report`'s Write-Plan-Edit pipeline: it
builds a short numbered preview of every signal's title, asks the
`self.planner` Agent (constructed once in `ReportAgent.__init__`,
`tools=[self.rag.search]`, `output_schema=ClusterContext` when the
model supports it) to group them into named themes via a prompt built by
`get_cluster_planner_instructions`/`get_cluster_task`, parses the JSON
response with `extract_json`, and returns the `"clusters"` list -- or `[]`
on any parse failure or exception (which `generate_report` documents
elsewhere as "fallback to individual signal mode").

`grep -n "self\."` restricted to the original method body:

```
self.planner.instructions = [instruction]                 [1 write]
self.planner.run(get_cluster_task(signals_preview))        [1 read+call]
```

Nothing else -- no `self.db`, `self.model`, `self.rag`, and, notably, no
`self._run_agent_with_retry`. This last point distinguishes this step
from every prior forecast/chart-rendering step: `_cluster_signals` calls
`self.planner.run(...)` directly inside its own `try`/`except`, not
through the retry-and-timeout wrapper the plan called out for step 30's
sibling steps to thread as a bound-method callable. There is therefore no
retry-callable regression to guard here -- confirmed by grepping the
method body for `_run_agent_with_retry` (zero matches) and cross-checked
against `tests/test_report_agent_characterization.py`'s three
`TestClusterSignals` scenarios, none of which touch
`LLM_MAX_RETRIES`/`LLM_TIMEOUT_SECONDS`/`LLM_RETRY_DELAY` or patch
`_run_agent_with_retry`.

`self.planner` itself is different in kind from every dependency threaded
so far in Phase 4: `_get_forecast_agent` (step 28) and `agent_cls`/`Agent`
(step 29) are *factories* -- a bound method or a class, called to produce
or construct something fresh (or fetch a lazily-cached instance) each
time. `self.planner` is not a factory; it *is* the long-lived collaborator
itself, built exactly once in `ReportAgent.__init__` and reused,
stateful, across every `generate_report` call on that instance (its
`.instructions` attribute is reassigned on every phase that uses it --
clustering here, the separate planner-phase call later in
`generate_report` -- and whatever the most recent caller left there is
what the *next* caller sees, by design: there is only ever one `Agent`
object backing `self.planner`).

## Goals / Non-Goals

**Goals:** move `_cluster_signals` verbatim into
`deepear/src/agents/report/clustering.py` as module-level
`cluster_signals(signals, user_query=None, *, planner)`; thread
`self.planner` by reference -- not a copy, not a freshly constructed
`Agent`, not a factory/getter -- so the moved function's `.instructions`
mutation and `.run(...)` call operate on the identical object
`ReportAgent.planner` names before, during, and after the call; keep
`ReportAgent._cluster_signals` as a real bound instance method forwarding
`planner=self.planner`; add the mandatory identity-assertion test proving
this by-reference sharing with an `is` check (not `==`), plus a
delegation-identity test one layer up.

**Non-Goals:** changing clustering behavior, prompt construction, or JSON
parsing in any way; touching `self.planner`'s construction in
`ReportAgent.__init__` (its `tools=[self.rag.search]`, `output_schema=
ClusterContext if hasattr(...)` gate, etc. -- untouched, out of scope);
introducing a retry-callable parameter (there is nothing to thread -- the
original body never calls `self._run_agent_with_retry`); building out
`deepear/src/agents/report/__init__.py` re-exports (deferred to
`finalize-report-agent-package-and-shim`, step 31).

## Decisions

1. **`planner: Agent` is threaded as a required keyword-only parameter,
   passed by reference.** This is the literal reading of the plan's
   instruction ("share the exact `self.planner` instance by reference").
   In Python, passing an object as an argument already shares it by
   reference -- there is no copy step to accidentally introduce -- so the
   discipline this decision protects is entirely about *not* doing
   anything that would break that sharing: not accepting a *description*
   of a planner (e.g. a model/tools/instructions bundle) and constructing
   a fresh `Agent` inside `cluster_signals`, and not wrapping `self.planner`
   in a factory/getter the way `_get_forecast_agent` wraps
   `self._forecast_agent`. `ReportAgent._cluster_signals` forwards
   `planner=self.planner` -- the attribute read once, at call time, handed
   through unchanged.
2. **No retry-callable parameter.** Unlike `forecast_requests.py`'s
   `get_forecast_agent` or `chart_renderer.py`'s `agent_cls`/
   `get_forecast_agent`, `_cluster_signals`'s body never calls
   `self._run_agent_with_retry`; it calls `self.planner.run(...)` directly
   inside its own exception handler. The task brief's caveat ("if
   `_cluster_signals` calls `self._run_agent_with_retry(...)`, thread the
   bound method...") is conditional on a call site that does not exist in
   this method's body -- confirmed by grep, see Context above -- so no
   such parameter is added, and no regression test for a patched
   `_run_agent_with_retry` intercepting clustering is added either (there
   is nothing for such a patch to intercept: clustering never goes through
   that method).
3. **`ReportAgent._cluster_signals` stays a real bound instance method**,
   not a bare attribute alias -- mirroring every prior delegator in this
   file -- so `generate_report`'s internal `self._cluster_signals(signals,
   user_query)` call site, and
   `tests/test_report_agent_characterization.py`'s three direct
   `agent._cluster_signals(...)`/`harness.agent._cluster_signals(...)`
   calls, keep resolving through the class exactly as before, and any
   future `monkeypatch.setattr(ReportAgent, "_cluster_signals", ...)` or
   `monkeypatch.setattr(agent, "_cluster_signals", ...)` patch would still
   intercept every call site.
4. **New test file, not an extension of the characterization suite** --
   `tests/test_report_clustering.py`, following the
   `test_report_forecast_ticker.py` / `test_report_chart_renderer.py`
   precedent. The mandatory identity-assertion test lives here, built with
   a small recording fake `Agent`-shaped object (reusing
   `tests/report_agent_harness.py`'s `FakeAgent`/`ScriptedAgentRouter`
   where convenient) that records the exact object passed in as `planner`
   and asserts, via `is`, that it matches the caller's own reference --
   both directly against the module function and, one layer up, against
   `ReportAgentHarness.agent.planner` through the real delegator.

## Risks / Trade-offs

- Threading a live, mutable `Agent` object by reference (rather than a
  factory that could, e.g., defensively snapshot/restore `.instructions`)
  means `cluster_signals` leaves `planner.instructions` mutated as a
  side effect after it returns -- exactly the original method's behavior,
  and exactly what `generate_report`'s later planner-phase call already
  depends on (it reassigns `self.planner.instructions` again before its
  own call, so the leftover mutation from clustering is never read as-is).
  Preserving this exactly, rather than "fixing" it into something more
  hygienic, is required by ground rule 1 (verbatim move) and the
  characterization suite's charter of pinning current behavior.
- Because there is no retry-callable to thread, this step's dependency
  surface is narrower than every other Phase 4 extraction step so far
  (which threaded at least one factory/callable). That asymmetry is a
  property of the method being moved, not a gap in this change --
  confirmed by grep, not assumed.
