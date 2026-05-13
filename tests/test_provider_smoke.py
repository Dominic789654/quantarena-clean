from datetime import datetime

import pandas as pd

from quantarena.provider_smoke import run_provider_smoke_check


def test_provider_smoke_skips_when_required_key_is_missing():
    result = run_provider_smoke_check(
        market="us",
        provider="fmp",
        ticker="AAPL",
        date="2026-01-02",
        env={},
    )

    assert result.ok is True
    assert result.skipped is True
    assert result.provider == "fmp"
    assert result.reason == "missing credential: FMP_API_KEY"


def test_provider_smoke_reports_invalid_date_when_credentials_exist():
    result = run_provider_smoke_check(
        market="us",
        provider="fmp",
        ticker="AAPL",
        date="2026/01/02",
        env={"FMP_API_KEY": "test-key"},
    )

    assert result.ok is False
    assert result.skipped is False
    assert result.reason == "date must use YYYY-MM-DD format"


def test_provider_smoke_uses_router_when_credentials_exist(monkeypatch):
    observed = {}

    class FakeRouter:
        def __init__(self, source):
            observed["source"] = source

        def get_us_stock_daily_candles_df(self, ticker, trading_date):
            observed["ticker"] = ticker
            observed["trading_date"] = trading_date
            return pd.DataFrame(
                {
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "volume": [1000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )

    monkeypatch.setattr("apis.router.Router", FakeRouter)

    result = run_provider_smoke_check(
        market="us",
        provider="fmp",
        ticker="AAPL",
        date="2026-01-02",
        env={"FMP_API_KEY": "test-key"},
    )

    assert result.ok is True
    assert result.skipped is False
    assert result.rows == 1
    assert result.columns == ["open", "high", "low", "close", "volume"]
    assert observed["source"] == "fmp"
    assert observed["ticker"] == "AAPL"
    assert observed["trading_date"] == datetime(2026, 1, 2)


def test_provider_smoke_reports_empty_frame_as_failure(monkeypatch):
    class EmptyRouter:
        def __init__(self, source):
            pass

        def get_us_stock_daily_candles_df(self, ticker, trading_date):
            return pd.DataFrame()

    monkeypatch.setattr("apis.router.Router", EmptyRouter)

    result = run_provider_smoke_check(
        market="us",
        provider="fmp",
        ticker="AAPL",
        date="2026-01-02",
        env={"FMP_API_KEY": "test-key"},
    )

    assert result.ok is False
    assert result.rows == 0
    assert result.reason == "provider returned no candle rows"


def test_provider_smoke_rejects_incompatible_explicit_provider_before_credentials():
    result = run_provider_smoke_check(
        market="cn",
        provider="fmp",
        ticker="600519",
        date="2026-01-02",
        env={"FMP_API_KEY": "test-key"},
    )

    assert result.ok is False
    assert result.provider == "fmp"
    assert result.reason == "provider fmp is not supported for market cn"


def test_provider_smoke_redacts_exception_text(monkeypatch):
    class FailingRouter:
        def __init__(self, source):
            pass

        def get_us_stock_daily_candles_df(self, ticker, trading_date):
            raise RuntimeError("failed url=https://example.test/query?apikey=super-secret&symbol=AAPL")

    monkeypatch.setattr("apis.router.Router", FailingRouter)

    result = run_provider_smoke_check(
        market="us",
        provider="fmp",
        ticker="AAPL",
        date="2026-01-02",
        env={"FMP_API_KEY": "super-secret"},
    )

    assert result.ok is False
    assert "super-secret" not in result.reason
    assert "apikey=<redacted>" in result.reason
