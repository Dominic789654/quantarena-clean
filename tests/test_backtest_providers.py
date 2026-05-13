from datetime import datetime, timezone

import pandas as pd
import pytest

from backtest.providers import (
    ProviderDataError,
    ProviderFailure,
    ReplayDailyCandleProvider,
    ReplayFundamentalsProvider,
    ReplayMacroProvider,
    ReplayNewsProvider,
)


def test_replay_daily_candle_provider_filters_by_end_date_from_date_column():
    provider = ReplayDailyCandleProvider(
        {
            "AAA": pd.DataFrame(
                {
                    "date": ["2026-01-01", "2026-01-02", "2026-01-05"],
                    "open": [10, 11, 12],
                    "high": [11, 12, 13],
                    "low": [9, 10, 11],
                    "close": [10.5, 11.5, 12.5],
                    "volume": [1000, 1001, 1002],
                }
            )
        }
    )

    frame = provider.get_daily_candles("AAA", datetime(2026, 1, 2))

    assert frame.index.name == "Date"
    assert frame["close"].tolist() == [10.5, 11.5]
    assert "date" not in frame.columns


def test_replay_daily_candle_provider_filters_by_datetime_index():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"])
    provider = ReplayDailyCandleProvider(
        {
            "AAA": pd.DataFrame(
                {
                    "open": [10, 11, 12],
                    "high": [11, 12, 13],
                    "low": [9, 10, 11],
                    "close": [10.5, 11.5, 12.5],
                    "volume": [1000, 1001, 1002],
                },
                index=dates,
            )
        }
    )

    frame = provider.get_daily_candles("AAA", datetime(2026, 1, 2))

    assert frame["close"].tolist() == [10.5, 11.5]


def test_replay_daily_candle_provider_accepts_uppercase_date_column():
    provider = ReplayDailyCandleProvider(
        {
            "AAA": pd.DataFrame(
                {
                    "Date": ["2026-01-01", "2026-01-02", "2026-01-05"],
                    "open": [10, 11, 12],
                    "high": [11, 12, 13],
                    "low": [9, 10, 11],
                    "close": [10.5, 11.5, 12.5],
                    "volume": [1000, 1001, 1002],
                }
            )
        }
    )

    frame = provider.get_daily_candles("AAA", datetime(2026, 1, 2))

    assert frame.index.name == "Date"
    assert frame["close"].tolist() == [10.5, 11.5]
    assert "Date" not in frame.columns


def test_replay_daily_candle_provider_raises_for_missing_ticker():
    provider = ReplayDailyCandleProvider({})

    with pytest.raises(ProviderDataError, match="Replay candles missing for AAA"):
        provider.get_daily_candles("AAA", datetime(2026, 1, 2))


def test_replay_news_provider_filters_sorts_and_limits_items():
    provider = ReplayNewsProvider(
        {
            "AAA": [
                {"title": "future", "publish_time": "2026-01-05", "publisher": "replay"},
                {"title": "latest", "publish_time": "2026-01-02", "publisher": "replay"},
                {"title": "older", "publish_time": "2026-01-01", "publisher": "replay"},
            ]
        }
    )

    news = provider.get_news("AAA", datetime(2026, 1, 2), limit=1, market="us")

    assert [item["title"] for item in news] == ["latest"]


def test_replay_news_provider_handles_timezone_aware_publish_time():
    provider = ReplayNewsProvider(
        {
            "AAA": [
                {"title": "included", "publish_time": "2026-01-02T09:00:00Z", "publisher": "replay"},
                {"title": "future", "publish_time": "2026-01-03T00:00:00Z", "publisher": "replay"},
            ]
        }
    )

    news = provider.get_news("AAA", datetime(2026, 1, 2, 12, 0, 0), limit=10, market="us")

    assert [item["title"] for item in news] == ["included"]


def test_replay_news_provider_handles_timezone_aware_datetime_object():
    provider = ReplayNewsProvider(
        {
            "AAA": [
                {
                    "title": "included",
                    "publish_time": datetime(2026, 1, 2, 9, 0, 0, tzinfo=timezone.utc),
                    "publisher": "replay",
                },
            ]
        }
    )

    news = provider.get_news("AAA", datetime(2026, 1, 2, 12, 0, 0), limit=10, market="us")

    assert [item["title"] for item in news] == ["included"]


def test_replay_news_provider_raises_for_missing_ticker():
    provider = ReplayNewsProvider({})

    with pytest.raises(ProviderDataError, match="Replay news missing for AAA"):
        provider.get_news("AAA", datetime(2026, 1, 2), limit=10, market="us")


def test_replay_fundamentals_provider_returns_payload_by_ticker():
    payload = {"pe_ratio": "12.5", "return_on_equity_ttm": "0.21"}
    provider = ReplayFundamentalsProvider({"AAA": payload})

    fundamentals = provider.get_fundamentals("AAA", "us")

    assert fundamentals.model_dump_json() == '{"pe_ratio": "12.5", "return_on_equity_ttm": "0.21"}'


def test_replay_fundamentals_provider_preserves_model_dump_payload():
    class Payload:
        def model_dump_json(self):
            return '{"pe_ratio": "12.5"}'

    payload = Payload()
    provider = ReplayFundamentalsProvider({"AAA": payload})

    assert provider.get_fundamentals("AAA", "us") is payload


def test_replay_fundamentals_provider_raises_for_missing_ticker():
    provider = ReplayFundamentalsProvider({"BBB": object()})

    with pytest.raises(ProviderDataError, match="Replay fundamentals missing for AAA"):
        provider.get_fundamentals("AAA", "us")


def test_replay_fundamentals_provider_rejects_incompatible_payload():
    provider = ReplayFundamentalsProvider({"AAA": object()})

    with pytest.raises(ProviderDataError, match="must be a mapping or expose model_dump_json"):
        provider.get_fundamentals("AAA", "us")


def test_replay_macro_provider_wraps_mapping_as_attribute_payload():
    provider = ReplayMacroProvider(
        {
            "cpi": {"value": "3.1"},
            "unemployment": {"value": "5.2"},
            "federal_funds_rate": {"value": "4.0"},
        }
    )

    indicators = provider.get_economic_indicators("us")

    assert indicators.cpi == {"value": "3.1"}
    assert indicators.unemployment == {"value": "5.2"}
    assert indicators.federal_funds_rate == {"value": "4.0"}


def test_replay_macro_provider_preserves_attribute_payload():
    class Payload:
        cpi = {"value": "3.1"}

    payload = Payload()
    provider = ReplayMacroProvider(payload)

    assert provider.get_economic_indicators("us") is payload


def test_replay_macro_provider_rejects_incompatible_payload():
    provider = ReplayMacroProvider(1.23)

    with pytest.raises(ProviderDataError, match="must be a mapping or attribute object"):
        provider.get_economic_indicators("us")


def test_provider_failure_redacts_sensitive_query_values():
    failure = ProviderFailure.from_exception(
        provider="fmp",
        operation="daily_candles",
        exc=RuntimeError(
            "GET https://example.test/query?apikey=secret-token&symbol=AAPL "
            "authorization: Bearer bearer-secret "
            "'api_key': 'json-secret' X-API-KEY: header-secret failed"
        ),
        ticker="AAPL",
        market="us",
        date="2026-01-02",
    )

    assert failure.error_type == "RuntimeError"
    assert "secret-token" not in failure.message
    assert "bearer-secret" not in failure.message
    assert "json-secret" not in failure.message
    assert "header-secret" not in failure.message
    assert "apikey=<redacted>" in failure.message
    assert "authorization: Bearer <redacted>" in failure.message
    assert "'api_key': '<redacted>'" in failure.message
    assert "X-API-KEY: <redacted>" in failure.message
    assert "provider=fmp" in failure.summary()
    assert "operation=daily_candles" in failure.summary()
    assert "ticker=AAPL" in failure.summary()
