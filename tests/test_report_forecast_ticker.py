"""Tests for `extract-report-agent-forecast-and-ticker-coordinator` (Phase 4 step 28).

Covers the two moved modules, `deepear.src.agents.report.ticker_utils` and
`deepear.src.agents.report.forecast_requests`, directly, plus the
patchability/delegation-identity of the four `ReportAgent` attributes left
behind as one-line delegators (`_clean_ticker`, `_signal_mentions_ticker`,
`_extract_forecast_requests`, `_build_forecast_map`). `_get_forecast_agent`
itself is untouched by this step and is not re-tested here --
`tests/test_report_agent_characterization.py::TestForecastMap` already pins
its "construct at most once" behavior one layer up, through a real
`ReportAgent` instance.

`tests/test_report_agent_characterization.py` has no direct coverage of
`_clean_ticker` or `_signal_mentions_ticker` at all (grep confirms zero
hits), and only one shape-level scenario for `_extract_forecast_requests`
and two instance-level scenarios for `_build_forecast_map`. This file adds:

- Direct `clean_ticker` coverage: comma truncation, dot/suffix truncation,
  digit-only extraction, non-digit passthrough, empty/whitespace/`None`.
- Direct `signal_mentions_ticker` coverage: structured `impact_tickers`
  match (with exchange-suffix noise), dict-vs-attribute signal access,
  text-fallback match, no-match case, empty `ticker_digits` short-circuit,
  exception-swallowing.
- Direct `extract_forecast_requests` coverage: well-formed shape,
  invalid-ticker-length rejection, structured scenario/selection_reason
  context taking priority over the raw snippet, empty/`None`/no-match-text
  short-circuits, and context-window snippet truncation at 3500 chars.
- The plan's MANDATORY call-counting test: `build_forecast_map` exercised
  directly with a hand-written, lazily-constructing counting
  `get_forecast_agent` callable, proving the underlying (would-be
  Kronos-backed) forecast model is constructed at MOST ONCE across
  multiple distinct forecast requests, and ZERO times when there are no
  forecast requests at all -- complementing, not duplicating, the
  instance-level equivalents in
  `tests/test_report_agent_characterization.py::TestForecastMap`.
- Delegation-identity: each of the four `ReportAgent` attributes produces
  output identical to the corresponding module function given the same
  inputs.
"""

from __future__ import annotations

from types import SimpleNamespace

from deepear.src.agents.report.forecast_requests import (
    build_forecast_map,
    extract_forecast_requests,
)
from deepear.src.agents.report.ticker_utils import clean_ticker, signal_mentions_ticker
from deepear.src.agents.report_agent import ReportAgent
from tests.report_agent_harness import make_report_agent

# ---------------------------------------------------------------------------
# clean_ticker
# ---------------------------------------------------------------------------


class TestCleanTicker:
    def test_comma_separated_string_keeps_only_first_entrys_digits(self):
        assert clean_ticker("600001,000002") == "600001"

    def test_dotted_exchange_suffix_keeps_only_the_digits_before_the_dot(self):
        assert clean_ticker("002371.SZ") == "002371"

    def test_comma_split_is_applied_before_dot_split(self):
        assert clean_ticker("600001.SH,000002.SZ") == "600001"

    def test_non_numeric_string_with_no_digits_is_returned_unchanged(self):
        assert clean_ticker("ABC") == "ABC"

    def test_empty_whitespace_and_none_input_return_empty_string(self):
        assert clean_ticker("") == ""
        assert clean_ticker("   ") == ""
        assert clean_ticker(None) == ""


# ---------------------------------------------------------------------------
# signal_mentions_ticker
# ---------------------------------------------------------------------------


class TestSignalMentionsTicker:
    def test_structured_impact_tickers_entry_matches_despite_exchange_suffix(self):
        signal = {"impact_tickers": [{"ticker": "600001.SH"}]}
        assert signal_mentions_ticker(signal, "600001") is True

    def test_attribute_style_signal_matches_the_same_way_as_dict_signal(self):
        obj_signal = SimpleNamespace(impact_tickers=[{"ticker": "600001"}])
        dict_signal = {"impact_tickers": [{"ticker": "600001"}]}

        assert signal_mentions_ticker(obj_signal, "600001") is True
        assert signal_mentions_ticker(dict_signal, "600001") is True

    def test_no_structured_match_falls_back_to_text_substring_match(self):
        signal = {"title": "600001 rallies", "summary": "", "analysis": ""}
        assert signal_mentions_ticker(signal, "600001") is True

    def test_no_structured_data_and_no_text_mention_returns_false(self):
        signal = {"title": "unrelated", "summary": "", "analysis": ""}
        assert signal_mentions_ticker(signal, "600001") is False

    def test_empty_ticker_digits_short_circuits_to_false(self):
        assert signal_mentions_ticker({"title": "600001"}, "") is False

    def test_exception_during_lookup_is_swallowed_and_returns_false(self):
        class RaisingSignal:
            @property
            def impact_tickers(self):
                raise RuntimeError("boom")

        assert signal_mentions_ticker(RaisingSignal(), "600001") is False


# ---------------------------------------------------------------------------
# extract_forecast_requests
# ---------------------------------------------------------------------------


class TestExtractForecastRequests:
    def test_well_formed_forecast_block_yields_one_request_with_expected_shape(self):
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "T1"}\n'
            "```\n"
        )
        requests = extract_forecast_requests(text)

        assert len(requests) == 1
        req = requests[0]
        assert req["ticker"] == "600001"
        assert req["pred_len"] == 5
        assert req["title"] == "T1"
        assert "context_snippet" in req

    def test_ticker_that_is_not_5_or_6_digits_after_cleaning_is_rejected(self):
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "12", "pred_len": 5}\n'
            "```\n"
        )
        assert extract_forecast_requests(text) == []

    def test_structured_scenario_and_selection_reason_take_priority_over_raw_snippet(self):
        text = (
            "在正文中讨论了多种情景，此处大量无关的散文用于填充上下文窗口。\n"
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "selected_scenario": "乐观情景", '
            '"selection_reason": "业绩超预期"}\n'
            "```\n"
        )
        requests = extract_forecast_requests(text)

        assert len(requests) == 1
        snippet = requests[0]["context_snippet"]
        assert "最可能情景: 乐观情景" in snippet
        assert "归因: 业绩超预期" in snippet
        assert "无关的散文" not in snippet

    def test_empty_none_and_no_match_text_return_empty_list(self):
        assert extract_forecast_requests("") == []
        assert extract_forecast_requests(None) == []
        assert extract_forecast_requests("plain text, no chart blocks") == []

    def test_context_snippet_is_truncated_at_3500_chars(self):
        block = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5}\n'
            "```\n"
        )
        text = ("x" * 5000) + block + ("y" * 5000)

        requests = extract_forecast_requests(text, context_window_chars=4000)

        assert len(requests) == 1
        snippet = requests[0]["context_snippet"]
        assert snippet.endswith("（上下文过长已截断）")
        assert len(snippet) == 3500 + len("\n\n（上下文过长已截断）")


# ---------------------------------------------------------------------------
# build_forecast_map: the mandatory call-counting test, exercised directly
# against the moved module function via a hand-written, lazily-constructing
# counting `get_forecast_agent` callable.
# ---------------------------------------------------------------------------


def _make_counting_get_forecast_agent(forecast_result=None):
    """Return (get_forecast_agent callable, construct_counter, calls list).

    Mimics `ReportAgent._get_forecast_agent`'s own lazy-cache shape: the
    underlying fake agent is constructed at most once (on first call to the
    returned callable) and reused on every subsequent call.
    """
    construct_counter = {"count": 0}
    calls: list[dict] = []
    cache: dict = {}

    class _CountingFakeForecastAgent:
        def __init__(self):
            construct_counter["count"] += 1

        def generate_forecast(self, ticker, related_signals, pred_len=5, extra_context=""):
            calls.append({"ticker": ticker, "pred_len": pred_len, "related_signals": related_signals})
            return forecast_result

    def get_forecast_agent():
        if "agent" not in cache:
            cache["agent"] = _CountingFakeForecastAgent()
        return cache["agent"]

    return get_forecast_agent, construct_counter, calls


class TestBuildForecastMapCallCounting:
    def test_no_forecast_requests_never_invokes_get_forecast_agent(self):
        get_forecast_agent, construct_counter, calls = _make_counting_get_forecast_agent()

        forecasts = build_forecast_map(
            "no chart blocks here", signals=[{"title": "irrelevant"}], get_forecast_agent=get_forecast_agent
        )

        assert forecasts == {}
        assert construct_counter["count"] == 0
        assert calls == []

    def test_two_distinct_requests_each_generate_once_sharing_one_construction(self):
        get_forecast_agent, construct_counter, calls = _make_counting_get_forecast_agent(
            forecast_result="FORECAST"
        )
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5}\n'
            "```\n\n"
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600002", "pred_len": 5}\n'
            "```\n"
        )

        forecasts = build_forecast_map(text, signals=None, get_forecast_agent=get_forecast_agent)

        assert len(forecasts) == 2
        assert construct_counter["count"] == 1
        assert len(calls) == 2
        assert {c["ticker"] for c in calls} == {"600001", "600002"}

    def test_duplicate_blocks_for_the_same_key_generate_only_once(self):
        get_forecast_agent, construct_counter, calls = _make_counting_get_forecast_agent(
            forecast_result="FORECAST"
        )
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5}\n'
            "```\n\n"
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5}\n'
            "```\n"
        )

        forecasts = build_forecast_map(text, signals=None, get_forecast_agent=get_forecast_agent)

        assert len(forecasts) == 1
        assert construct_counter["count"] == 1
        assert len(calls) == 1

    def test_signal_backed_allowlist_skips_ungrounded_ticker(self):
        get_forecast_agent, construct_counter, calls = _make_counting_get_forecast_agent(
            forecast_result="FORECAST"
        )
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5}\n'
            "```\n\n"
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600002", "pred_len": 5}\n'
            "```\n"
        )
        signals = [{"title": "600001 bullish", "impact_tickers": [{"ticker": "600001"}]}]

        forecasts = build_forecast_map(text, signals=signals, get_forecast_agent=get_forecast_agent)

        assert set(forecasts.keys()) == {("600001", 5)}
        assert construct_counter["count"] == 1
        assert len(calls) == 1
        assert calls[0]["ticker"] == "600001"


# ---------------------------------------------------------------------------
# Delegation identity: every ReportAgent attribute this step moved must
# produce output identical to the corresponding module function.
# ---------------------------------------------------------------------------


class TestDelegationIdentity:
    def test_clean_ticker_delegator_matches_module_function(self):
        assert ReportAgent._clean_ticker("002371.SZ") == clean_ticker("002371.SZ")

    def test_signal_mentions_ticker_delegator_matches_module_function(self):
        signal = {"impact_tickers": [{"ticker": "600001"}]}
        assert ReportAgent._signal_mentions_ticker(signal, "600001") == signal_mentions_ticker(signal, "600001")

    def test_extract_forecast_requests_delegator_matches_module_function(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        text = (
            "```json-chart\n"
            '{"type": "forecast", "ticker": "600001", "pred_len": 5, "title": "T1"}\n'
            "```\n"
        )

        assert harness.agent._extract_forecast_requests(text) == extract_forecast_requests(text)

    def test_build_forecast_map_delegator_matches_module_function_given_same_agent(self, monkeypatch):
        # _build_forecast_map is an instance method (it threads
        # self._get_forecast_agent), so the delegation-identity check needs
        # a real ReportAgent instance whose own lazy-cache callable is
        # passed directly to the module function. Text with no forecast
        # blocks keeps this a pure identity check without exercising the
        # (already-covered) forecast-generation path itself.
        harness = make_report_agent(monkeypatch)
        text = "no chart blocks here"

        via_delegator = harness.agent._build_forecast_map(text, signals=None)
        via_module = build_forecast_map(text, signals=None, get_forecast_agent=harness.agent._get_forecast_agent)

        assert via_delegator == via_module == {}
