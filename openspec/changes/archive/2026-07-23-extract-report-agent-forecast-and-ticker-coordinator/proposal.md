## Why

Phase 4 step 28 (docs/refactor_program_plan.md). Steps 24-27 landed the
characterization harness (`tests/report_agent_harness.py`,
`tests/test_report_agent_characterization.py`, 22 tests) and three leaf
modules -- `deepear/src/agents/report/retry.py`,
`deepear/src/agents/report/chart_sanitizer.py` /
`deepear/src/agents/report/structured_report.py`, and
`deepear/src/agents/report/citations.py` -- out of
`deepear/src/agents/report_agent.py`'s `ReportAgent` class. This step
extracts the ticker-cleaning/matching helpers and the forecast-request
parsing/coordination logic -- `_clean_ticker`, `_signal_mentions_ticker`,
`_extract_forecast_requests`, and `_build_forecast_map` -- into two new
modules, `deepear/src/agents/report/ticker_utils.py` and
`deepear/src/agents/report/forecast_requests.py`. `_get_forecast_agent`
itself (the lazy `ForecastAgent`/Kronos-model cache) stays on `ReportAgent`
unchanged -- it is the seam `tests/report_agent_harness.py` patches around
and the plan calls out as the dependency to *inject*, not move.

## What Changes

- Add `deepear/src/agents/report/ticker_utils.py` exposing two
  module-level functions: `clean_ticker(ticker_raw)` (`_clean_ticker`'s
  body moved verbatim) and `signal_mentions_ticker(signal, ticker_digits)`
  (`_signal_mentions_ticker`'s body moved verbatim, with its nested `norm`
  closure's `cls._clean_ticker(s)` call rewritten to a direct in-module
  `clean_ticker(s)` call, since the classmethod's only use of `cls` was
  that one call and both functions now live together with no `self`/`cls`
  left to thread).
- Add `deepear/src/agents/report/forecast_requests.py` exposing
  `extract_forecast_requests(text, context_window_chars=1200)` and
  `build_forecast_map(report_text, signals=None, *, get_forecast_agent)`,
  both bodies moved verbatim. `grep -n "self\."` restricted to both
  original method bodies finds four reads total:
  `self._clean_ticker(...)` (both methods), `self._extract_forecast_requests
  (...)` (in `_build_forecast_map`), `self._signal_mentions_ticker(...)`
  (in `_build_forecast_map`), and `self._get_forecast_agent()` (in
  `_build_forecast_map`). The first three become direct in-module/
  leaf-to-leaf calls (`forecast_requests.py` imports `clean_ticker` and
  `signal_mentions_ticker` from `ticker_utils.py`, and calls its own
  `extract_forecast_requests` directly) because the callee is itself
  moving into a leaf module with no remaining instance state to read. Only
  `self._get_forecast_agent()` is threaded as an explicit required
  keyword-only `get_forecast_agent` callable parameter on
  `build_forecast_map`, per ground rule 6 and the plan's explicit
  instruction to "inject the lazy `_get_forecast_agent` callable" --
  `_get_forecast_agent` cannot become a plain module-level call because it
  is a genuine per-instance lazy cache (`self._forecast_agent`) that must
  keep living on `ReportAgent`.
- `ReportAgent` keeps all four moved names as real attributes of their
  original binding kind: `_clean_ticker` stays a `@staticmethod`;
  `_signal_mentions_ticker` stays a `@classmethod` (even though the module
  function it delegates to takes no `cls`); `_extract_forecast_requests`
  and `_build_forecast_map` stay bound instance methods, the latter
  forwarding `get_forecast_agent=self._get_forecast_agent`. Each is a
  one-line delegator, not a bare attribute alias. `_get_forecast_agent`
  itself is untouched -- still a real bound instance method reading/writing
  `self._forecast_agent`.
- Add `tests/test_report_forecast_ticker.py`: direct `clean_ticker`
  coverage (comma/dot truncation, digit-only extraction, empty input);
  direct `signal_mentions_ticker` coverage (structured `impact_tickers`
  match, dict-vs-attribute signal access, text-fallback match, empty
  `ticker_digits` short-circuit, exception-swallowing); direct
  `extract_forecast_requests` coverage on scripted markdown text
  (multi-request parsing, invalid-ticker-length rejection, scenario/
  selection-reason structured context, context-window snippet
  extraction/truncation); and direct `build_forecast_map` coverage with an
  injected counting `get_forecast_agent` callable proving the underlying
  (would-be Kronos-backed) forecast model is constructed **at most once**
  across multiple distinct forecast requests, and **zero times** when no
  forecast requests are present -- the mandatory call-counting test the
  plan calls for, exercising the moved module function directly rather
  than duplicating the existing instance-level characterization coverage
  of the same guarantee. Plus delegation-identity tests per moved
  `ReportAgent` attribute.
- No behavior change. `tests/test_report_agent_characterization.py` (22
  tests), `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_retry_helper.py` (7 tests), and
  `tests/test_report_pure_functions.py` (24 tests) are left completely
  unmodified and must keep passing unchanged.

## Capabilities

### New Capabilities
- `report-agent-forecast-ticker-coordinator`: the standalone ticker-string
  normalization/matching helpers and the forecast-request parsing/
  deduplication/coordination logic `ReportAgent` uses to turn `json-chart`
  forecast blocks embedded in report markdown into a `(ticker, pred_len) ->
  ForecastResult` map, generating each unique forecast exactly once per
  report while loading the underlying forecast model at most once per
  `ReportAgent` instance.

### Modified Capabilities
- None.

## Impact

- New files: `deepear/src/agents/report/ticker_utils.py`,
  `deepear/src/agents/report/forecast_requests.py`,
  `tests/test_report_forecast_ticker.py`.
- Modified: `deepear/src/agents/report_agent.py` (two new fully-qualified
  import blocks; four method bodies replaced by one-line delegators).
- Monkeypatch audit (ground rule 2): `git grep -n
  "_clean_ticker\|_signal_mentions_ticker\|_extract_forecast_requests\|
  _build_forecast_map\|_get_forecast_agent" tests/ deepear/ backtest/
  deepfund/ shared/` shows: the five method definitions and their internal
  `self.`/`cls.`-qualified call sites inside
  `deepear/src/agents/report_agent.py` (`_extract_forecast_requests`'s
  `self._clean_ticker`; `_build_forecast_map`'s `self._extract_forecast_requests`,
  `self._clean_ticker`, `self._signal_mentions_ticker`,
  `self._get_forecast_agent()`; `generate_report`'s
  `self._build_forecast_map`; `_process_charts`'s two direct
  `self._get_forecast_agent()` calls, which belong to step 29's chart
  renderer and are untouched here); `tests/report_agent_harness.py`'s
  docstrings/`FakeForecastAgent` machinery reference `_get_forecast_agent`
  by name (no monkeypatch of it -- it patches `ForecastAgent`, the class
  `_get_forecast_agent` constructs, one level removed); and
  `tests/test_report_agent_characterization.py` calls
  `harness.agent._extract_forecast_requests(text)` and
  `agent._build_forecast_map(text, signals=...)` directly on a real
  instance (three call sites total), plus reads `agent._forecast_agent`
  directly to assert the lazy-cache identity/count invariant. No literal
  `monkeypatch.setattr("...")` string path and no class-attribute patch of
  any of `_clean_ticker`/`_signal_mentions_ticker`/
  `_extract_forecast_requests`/`_build_forecast_map`/`_get_forecast_agent`
  exists anywhere in the repo today. `ReportAgent` keeps every one of the
  four moved names as a real attribute of its original binding kind (not a
  bare attribute alias) and leaves `_get_forecast_agent` completely
  untouched, so every existing internal call site, every existing
  direct-instance-method test call, and any future monkeypatch of any of
  the five names keeps working exactly as before.
