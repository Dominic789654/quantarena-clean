## Context

`ReportAgent` (`deepear/src/agents/report_agent.py`) renders forecast
charts by scanning the final report markdown for ` ```json-chart ` blocks
with `"type": "forecast"`, deduplicating them by `(ticker, pred_len)` so
the same forecast is generated exactly once even if the writer/editor
LLMs emit the same chart block more than once, and only then calling into
`ForecastAgent.generate_forecast` (the Kronos-backed pipeline) for each
unique key. Two ticker-string helpers back this: `_clean_ticker` strips
suffix/exchange noise from a raw ticker string down to its digit code (or
the original string if it has no digits), and `_signal_mentions_ticker`
decides whether a given signal (dict or attribute-style object) is
attributable to a cleaned ticker, first via structured `impact_tickers`
entries, then via a text-substring fallback over `title`/`summary`/
`analysis`.

`grep -n "self\."` restricted to the four original method bodies:

```
_extract_forecast_requests: self._clean_ticker(ticker_raw)              [1 read]
_build_forecast_map:        self._extract_forecast_requests(report_text) [1 read]
                             self._clean_ticker(str(t or ""))            [1 read]
                             self._signal_mentions_ticker(s, str(ticker)) [1 read]
                             self._get_forecast_agent()                  [1 read]
```

`_clean_ticker` and `_signal_mentions_ticker` themselves read no `self`/
`cls` state beyond `_signal_mentions_ticker`'s nested `norm` closure
calling `cls._clean_ticker(s)` -- and that closure's only reason to exist
is to give `_clean_ticker` a short local name inside the closure body, not
to dispatch through subclass overrides.

`_get_forecast_agent` is different in kind from the other four: it is a
genuine per-instance lazy cache --

```python
def _get_forecast_agent(self) -> ForecastAgent:
    if self._forecast_agent is None:
        self._forecast_agent = ForecastAgent(self.db, self.model)
    return self._forecast_agent
```

-- reading and writing `self._forecast_agent`, `self.db`, and `self.model`.
It is the seam `tests/report_agent_harness.py`'s `make_report_agent`
patches *around* (by swapping the module-level `ForecastAgent` class, not
`_get_forecast_agent` itself) specifically so its "construct at most once"
behavior stays real and characterizable. The program plan is explicit that
step 28 must "inject the lazy `_get_forecast_agent` callable" rather than
move it -- moving it would either duplicate the per-instance cache as
module-level mutable state (a correctness hazard across concurrent/
multiple `ReportAgent` instances) or require passing `self` into the leaf
module, defeating the point of extraction.

## Goals / Non-Goals

**Goals:** move `_clean_ticker` and `_signal_mentions_ticker` verbatim
into `deepear/src/agents/report/ticker_utils.py`; move
`_extract_forecast_requests` and `_build_forecast_map` verbatim into
`deepear/src/agents/report/forecast_requests.py`, threading
*only* the `self._get_forecast_agent()` read through `build_forecast_map`
as an explicit required keyword-only `get_forecast_agent` callable
parameter (ground rule 6) and rewriting the other three `self.` reads to
direct calls against the already-moved sibling functions; keep all four
`ReportAgent` attributes as real, correctly-bound delegators; leave
`_get_forecast_agent` itself completely untouched on the class; add a
call-counting test proving the injected callable is invoked as many times
as there are unique `(ticker, pred_len)` groups while the underlying model
construction it gates happens at most once, exercised directly against
the moved module function (not just through `ReportAgent`).

**Non-Goals:** changing ticker-cleaning, ticker-matching, forecast-request
parsing, or forecast-map-building behavior in any way; moving
`_get_forecast_agent` off `ReportAgent`; touching `_process_charts`'s two
direct `self._get_forecast_agent()` calls (step 29,
`extract-report-agent-chart-renderer`, which also owns the surrounding
chart-rendering machinery); building out `deepear/src/agents/report/
__init__.py` re-exports (deferred to `finalize-report-agent-package-and-
shim`, step 31).

## Decisions

1. **`build_forecast_map(report_text, signals=None, *, get_forecast_agent)`
   is the only threaded dependency this step introduces**, mirroring
   `retry.py`'s `run_agent_with_retry(..., *, max_retries, timeout_seconds,
   retry_delay)` and `citations.py`'s `build_bibliography(signals, *, db)`
   precedent: a threaded dependency is required and keyword-only, never
   defaulted to something that isn't the caller's own instance state.
   `ReportAgent._build_forecast_map(self, report_text, signals=None)`
   forwards `get_forecast_agent=self._get_forecast_agent` -- the bound
   method itself, passed by reference, not called -- so `build_forecast_map`
   calls `get_forecast_agent()` exactly where the original body called
   `self._get_forecast_agent()`, preserving the lazy-cache's "construct at
   most once per `ReportAgent` instance" property unchanged: the callable
   still closes over the same `self`.
2. **The other three `self.` reads become direct calls, not threaded
   parameters**: `self._clean_ticker(...)` (in both methods),
   `self._extract_forecast_requests(...)`, and
   `self._signal_mentions_ticker(...)` all call a function that is itself
   moving into a leaf module in this same step -- `clean_ticker` and
   `signal_mentions_ticker` into `ticker_utils.py`,
   `extract_forecast_requests` into the same module
   (`forecast_requests.py`) as `build_forecast_map`. Once the callee has no
   `self`/`cls` left to read, there is nothing to thread: `forecast_requests
   .py` imports `clean_ticker`/`signal_mentions_ticker` from `ticker_utils
   .py` (a leaf-to-leaf import, not an import of `report_agent.py`, so no
   import cycle) and calls its own `extract_forecast_requests` directly by
   name. This mirrors `citations.py`'s precedent, where
   `_build_bibliography`'s `self._make_cite_key(...)` call became a direct
   `make_cite_key(...)` call once both functions moved into the same
   module together.
3. **`_signal_mentions_ticker`'s nested `norm` closure drops `cls`**: the
   module-level `signal_mentions_ticker(signal, ticker_digits)` function's
   nested `norm(s)` closure calls `clean_ticker(s)` directly instead of
   `cls._clean_ticker(s)`, since there is no `cls` in a plain module
   function. This is the one line of the four method bodies that is not a
   byte-for-byte copy (beyond the def-line/decorator/import glue every
   prior step's moves also touched) -- ground rule 1 permits this because
   it is glue (threading a call target), not a behavior change: `norm`
   still computes exactly what `_clean_ticker`/`clean_ticker` computes.
4. **All four `ReportAgent` attributes keep their original binding
   kind**: `_clean_ticker` stays `@staticmethod`. `_signal_mentions_ticker`
   stays `@classmethod` even though its body no longer needs `cls` for
   anything -- ground rule 2 says "classmethod stays classmethod
   delegator", and downgrading it to a staticmethod would be a gratuitous
   binding-kind change with no benefit and a (small) risk of breaking a
   future subclass or a `mock.patch.object(ReportAgent, "_signal_mentions_ticker",
   autospec=True)`-style patch that assumes the classmethod signature.
   `_extract_forecast_requests` and `_build_forecast_map` stay bound
   instance methods: the former to preserve its existing `self.
   _extract_forecast_requests(...)` call spelling inside
   `_build_forecast_map` even though its own body needs no instance state
   post-move; the latter because it must read `self._get_forecast_agent`
   to forward it.
5. **`_get_forecast_agent` is not touched, not re-exported, and not
   given a design section beyond this one** -- it remains exactly as it is
   today: a bound instance method on `ReportAgent` reading/writing
   `self._forecast_agent`, `self.db`, `self.model`. The harness
   (`tests/report_agent_harness.py`) continues to patch the module-level
   `ForecastAgent` name in `report_agent_module`'s namespace, not
   `_get_forecast_agent` itself, and that patch point does not move,
   because `_get_forecast_agent`'s body (and therefore the name it reads,
   `ForecastAgent`) is unchanged by this step.
6. **New test file, not an extension of the characterization suite**:
   `tests/test_report_forecast_ticker.py` is new, following the
   `test_report_retry_helper.py` / `test_report_pure_functions.py` /
   `test_report_citations_module.py` precedent, so the characterization
   suite's charter (pinning `ReportAgent`'s behavior ahead of extraction)
   stays unchanged in shape. The mandatory call-counting test lives here,
   built directly against `build_forecast_map` with a hand-written counting
   `get_forecast_agent` callable (no `ReportAgent`, no
   `tests/report_agent_harness.py` fakes needed for that specific test,
   since the callable itself is the thing being counted) -- this
   complements, rather than duplicates,
   `tests/test_report_agent_characterization.py::TestForecastMap::
   test_forecast_agent_constructed_at_most_once_across_multiple_requests`
   and `::test_no_forecast_request_never_constructs_forecast_agent`, which
   exercise the same guarantee one layer up, through a real `ReportAgent`
   instance and the harness's `FakeForecastAgent` construction counter.

## Risks / Trade-offs

- Passing `self._get_forecast_agent` (a bound method) as the
  `get_forecast_agent` callable, rather than e.g. `self._forecast_agent`
  directly or a fresh factory, means `build_forecast_map` has no way to
  observe or influence the caching policy -- which is exactly the point:
  the lazy-cache's implementation stays entirely inside `ReportAgent`, and
  the leaf module only ever sees "a callable that returns a forecast
  agent," matching the plan's "inject the lazy callable" instruction
  literally.
- Keeping `_signal_mentions_ticker` a `@classmethod` when its body no
  longer needs `cls` is a small persistent oddity (a classmethod that
  ignores its first argument), but changing it is explicitly out of scope
  per ground rule 2 and carries more downside (an unrequested binding-kind
  change) than upside (removing one unused parameter).
