## 1. Monkeypatch audit

- [x] 1.1 `git grep -n "_clean_ticker\|_signal_mentions_ticker\|_extract_forecast_requests\|_build_forecast_map\|_get_forecast_agent" tests/ deepear/ backtest/ deepfund/ shared/`
  — hits: the five method definitions and their internal
  `self.`/`cls.`-qualified call sites inside
  `deepear/src/agents/report_agent.py` (`_extract_forecast_requests`'s
  `self._clean_ticker`; `_build_forecast_map`'s
  `self._extract_forecast_requests`, `self._clean_ticker`,
  `self._signal_mentions_ticker`, `self._get_forecast_agent()`;
  `generate_report`'s one `self._build_forecast_map` call;
  `_process_charts`'s two direct `self._get_forecast_agent()` calls, which
  belong to step 29's chart renderer and stay untouched);
  `tests/report_agent_harness.py` references `_get_forecast_agent` only in
  docstrings (it patches `ForecastAgent`, not `_get_forecast_agent`
  itself); `tests/test_report_agent_characterization.py` calls
  `harness.agent._extract_forecast_requests(text)` once and
  `agent._build_forecast_map(text, signals=...)` twice directly on a real
  instance, plus reads `agent._forecast_agent` directly to assert the
  lazy-cache identity/count invariant.
- [x] 1.2 Confirm no literal `monkeypatch.setattr("...")` string path and
  no class-attribute patch of any of the five names exists anywhere in the
  repo today — none found.
- [x] 1.3 `grep -n "self\."` restricted to `_extract_forecast_requests`'s
  and `_build_forecast_map`'s bodies — four reads total:
  `self._clean_ticker` (both methods), `self._extract_forecast_requests`,
  `self._signal_mentions_ticker`, `self._get_forecast_agent()` (all three
  in `_build_forecast_map`); `_clean_ticker`/`_signal_mentions_ticker`
  themselves read no `self`/`cls` state except `_signal_mentions_ticker`'s
  nested `norm` closure calling `cls._clean_ticker(s)`.
- [x] 1.4 Confirm `_get_forecast_agent` reads/writes `self._forecast_agent`,
  `self.db`, `self.model` and is the seam
  `tests/report_agent_harness.py`'s `make_report_agent` patches *around*
  (by swapping module-level `ForecastAgent`, not `_get_forecast_agent`
  itself) — confirms it must stay on the class per the plan's explicit
  "inject the lazy callable" instruction, not move.
- [x] 1.5 Confirm all chart-rendering code in `_process_charts` (step 29,
  `extract-report-agent-chart-renderer`) is left untouched.

## 2. Implementation

- [x] 2.1 Create `deepear/src/agents/report/ticker_utils.py`: move
  `_clean_ticker`'s body verbatim into module-level `clean_ticker
  (ticker_raw)`; move `_signal_mentions_ticker`'s body verbatim into
  module-level `signal_mentions_ticker(signal, ticker_digits)`, rewriting
  the nested `norm` closure's `cls._clean_ticker(s)` call to a direct
  `clean_ticker(s)` call (no other change to the closure or the rest of
  the body).
- [x] 2.2 Create `deepear/src/agents/report/forecast_requests.py`:
  import `clean_ticker`/`signal_mentions_ticker` from
  `deepear.src.agents.report.ticker_utils` (leaf-to-leaf import, no cycle);
  move `_extract_forecast_requests`'s body verbatim into module-level
  `extract_forecast_requests(text, context_window_chars=1200)`, rewriting
  its one `self._clean_ticker(...)` read to a direct `clean_ticker(...)`
  call; move `_build_forecast_map`'s body verbatim into module-level
  `build_forecast_map(report_text, signals=None, *, get_forecast_agent)`,
  rewriting `self._extract_forecast_requests(...)` to a direct
  `extract_forecast_requests(...)` call, `self._clean_ticker(...)` to a
  direct `clean_ticker(...)` call, `self._signal_mentions_ticker(...)` to
  a direct `signal_mentions_ticker(...)` call, and
  `self._get_forecast_agent()` to `get_forecast_agent()` (the one
  ground-rule-6-mandated parameter-threading rewrite).
- [x] 2.3 `report_agent.py`: add `from deepear.src.agents.report
  .ticker_utils import (clean_ticker as _clean_ticker_impl,
  signal_mentions_ticker as _signal_mentions_ticker_impl)` and `from
  deepear.src.agents.report.forecast_requests import
  (extract_forecast_requests as _extract_forecast_requests_impl,
  build_forecast_map as _build_forecast_map_impl)`; replace the four
  method bodies with one-line delegators, preserving each method's
  original binding kind (`@staticmethod` for `_clean_ticker`,
  `@classmethod` for `_signal_mentions_ticker`, bound instance methods for
  `_extract_forecast_requests`/`_build_forecast_map`, the latter
  forwarding `get_forecast_agent=self._get_forecast_agent`). Leave
  `_get_forecast_agent` itself untouched.

## 3. Tests

- [x] 3.1 Add `tests/test_report_forecast_ticker.py`: direct
  `clean_ticker` coverage (comma truncation, dot/suffix truncation,
  digit-only extraction, non-digit passthrough, empty/whitespace/`None`
  input); direct `signal_mentions_ticker` coverage (structured
  `impact_tickers` match with exchange-suffix noise, dict-vs-attribute
  signal access, text-fallback match, no-match case, empty
  `ticker_digits` short-circuit, exception-swallowing via a signal whose
  attribute access raises).
- [x] 3.2 Same file: direct `extract_forecast_requests` coverage on
  scripted markdown text (well-formed single request shape,
  invalid-ticker-length rejection, structured scenario/selection_reason
  context taking priority over raw snippet, empty/`None`/no-match-text
  short-circuits, context-window snippet truncation at 3500 chars) — grep
  confirmed `tests/test_report_agent_characterization.py` only covers the
  single well-formed-shape scenario, so this file's coverage is additive.
- [x] 3.3 Same file: direct `build_forecast_map` coverage with a
  hand-written counting `get_forecast_agent` callable proving (a) zero
  requests means the callable is never invoked, (b) two distinct
  `(ticker, pred_len)` groups each generate once while the underlying
  construction counter stays at `1`, (c) duplicate blocks for the same key
  generate only once, (d) a signal-backed allowlist skips ungrounded
  tickers. This is the plan's mandatory call-counting test, exercising the
  moved module function directly — complementing, not duplicating,
  `tests/test_report_agent_characterization.py::TestForecastMap`'s
  instance-level equivalents.
- [x] 3.4 Same file: delegation-identity tests for `_clean_ticker`,
  `_signal_mentions_ticker`, `_extract_forecast_requests`, and
  `_build_forecast_map` proving each `ReportAgent` attribute's output
  matches the corresponding module function's output on the same inputs
  (using `tests/report_agent_harness.py`'s `make_report_agent` for the
  two instance methods, since `_build_forecast_map` needs a real
  `self._get_forecast_agent`).
- [x] 3.5 Confirm `tests/test_report_agent_characterization.py` (22
  tests), `tests/test_report_agent_citations.py` (1 test),
  `tests/test_report_retry_helper.py` (7 tests), and
  `tests/test_report_pure_functions.py` (24 tests) all still pass
  unchanged.

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_forecast_ticker.py tests/test_report_agent_characterization.py tests/test_report_agent_citations.py tests/test_report_retry_helper.py tests/test_report_pure_functions.py tests/test_report_citations_module.py -q`
  — all pass (new + pre-existing).
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` — 1022 baseline + new
  tests passed, 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
- [x] 4.5 `python -W error::SyntaxWarning -c "import deepear.src.agents.report.ticker_utils; import deepear.src.agents.report.forecast_requests; import deepear.src.agents.report_agent"`
  — no warning raised.
