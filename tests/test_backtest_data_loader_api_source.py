from datetime import datetime

import pandas as pd

from backtest.base_engine import BaseBacktestEngine
from backtest.data_loader import APISource, DataPrefetcher
from backtest.providers import ReplayDailyCandleProvider, ReplayNewsProvider


class FakeRouter:
    def __init__(self, source):
        self.source = source

    def get_us_stock_daily_candles_df(self, ticker, trading_date):
        dates = pd.date_range("2026-02-23", "2026-02-27", freq="D")
        df = pd.DataFrame(
            {
                "open": [100, 101, 102, 103, 104],
                "high": [101, 102, 103, 104, 105],
                "low": [99, 100, 101, 102, 103],
                "close": [100.5, 101.5, 102.5, 103.5, 104.5],
                "volume": [1000, 1001, 1002, 1003, 1004],
            },
            index=dates,
        )
        df.index.name = "Date"
        return df[df.index <= trading_date]

    def get_us_stock_news(self, ticker, trading_date, news_count):
        return [
            {
                "title": f"{ticker} router news",
                "url": "https://example.test/router",
                "summary": "router summary",
                "publish_time": trading_date.strftime("%Y-%m-%d"),
                "source": "router",
            }
        ]


def test_prefetch_klines_uses_us_router(monkeypatch, tmp_path):
    monkeypatch.setattr("backtest.data_loader.Router", FakeRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)
    monkeypatch.setattr("backtest.data_loader.time.sleep", lambda _: None)

    prefetcher = DataPrefetcher(db_path=str(tmp_path / "prices.db"), market="us")
    results = prefetcher.prefetch_klines(["AAPL"], "2026-02-23", "2026-02-27")

    assert prefetcher.api_source == APISource.FMP
    assert results == {"AAPL": 5}

    cached = prefetcher.db.get_stock_prices("AAPL", "2026-02-23", "2026-02-27")
    assert len(cached) == 5
    assert cached["date"].tolist() == [
        "2026-02-23",
        "2026-02-24",
        "2026-02-25",
        "2026-02-26",
        "2026-02-27",
    ]

    prefetcher.close()


def test_get_trading_days_uses_us_router_when_cache_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("backtest.data_loader.Router", FakeRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.ALPHA_VANTAGE)

    prefetcher = DataPrefetcher(db_path=str(tmp_path / "calendar.db"), market="us")
    trading_days = prefetcher.get_trading_days("2026-02-23", "2026-02-27", ticker="AAPL")

    assert trading_days == [
        "2026-02-23",
        "2026-02-24",
        "2026-02-25",
        "2026-02-26",
        "2026-02-27",
    ]

    cached = prefetcher.db.get_stock_prices("AAPL", "2026-02-23", "2026-02-27")
    assert len(cached) == 5

    prefetcher.close()


def test_prefetch_klines_uses_injected_replay_provider_without_router(monkeypatch, tmp_path):
    def fail_router(*args, **kwargs):
        raise AssertionError("replay provider should bypass live router")

    monkeypatch.setattr("backtest.data_loader.Router", fail_router)
    monkeypatch.setattr("backtest.data_loader.time.sleep", lambda _: None)
    provider = ReplayDailyCandleProvider(
        {
            "AAPL": pd.DataFrame(
                {
                    "date": ["2026-02-23", "2026-02-24", "2026-02-25"],
                    "open": [100, 101, 102],
                    "high": [101, 102, 103],
                    "low": [99, 100, 101],
                    "close": [100.5, 101.5, 102.5],
                    "volume": [1000, 1001, 1002],
                }
            )
        }
    )

    prefetcher = DataPrefetcher(
        db_path=str(tmp_path / "replay.db"),
        market="us",
        daily_candle_provider=provider,
    )
    results = prefetcher.prefetch_klines(["AAPL"], "2026-02-23", "2026-02-25")

    assert prefetcher.api_source == "replay"
    assert results == {"AAPL": 3}
    cached = prefetcher.db.get_stock_prices("AAPL", "2026-02-23", "2026-02-25")
    assert cached["close"].tolist() == [100.5, 101.5, 102.5]

    prefetcher.close()


def test_get_trading_days_uses_injected_replay_provider_when_cache_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backtest.data_loader.Router",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live router should not be used")),
    )
    provider = ReplayDailyCandleProvider(
        {
            "AAPL": pd.DataFrame(
                {
                    "date": ["2026-02-23", "2026-02-24", "2026-02-25"],
                    "open": [100, 101, 102],
                    "high": [101, 102, 103],
                    "low": [99, 100, 101],
                    "close": [100.5, 101.5, 102.5],
                    "volume": [1000, 1001, 1002],
                }
            )
        }
    )

    prefetcher = DataPrefetcher(
        db_path=str(tmp_path / "replay-calendar.db"),
        market="us",
        daily_candle_provider=provider,
    )
    trading_days = prefetcher.get_trading_days("2026-02-23", "2026-02-25", ticker="AAPL")

    assert trading_days == ["2026-02-23", "2026-02-24", "2026-02-25"]

    prefetcher.close()


def test_prefetch_news_uses_us_router(monkeypatch, tmp_path):
    monkeypatch.setattr("backtest.data_loader.Router", FakeRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)
    monkeypatch.setattr("backtest.data_loader.time.sleep", lambda _: None)

    prefetcher = DataPrefetcher(db_path=str(tmp_path / "news-router.db"), market="us")
    saved = prefetcher.prefetch_news(["AAPL"], "2026-02-23", "2026-02-27")

    assert saved == 1
    news = prefetcher.db.get_daily_news(limit=10, days=30)
    assert news[0]["title"] == "AAPL router news"

    prefetcher.close()


def test_prefetch_news_uses_injected_replay_provider_without_router(monkeypatch, tmp_path):
    monkeypatch.setattr("backtest.data_loader.Router", FakeRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)
    monkeypatch.setattr("backtest.data_loader.time.sleep", lambda _: None)
    provider = ReplayNewsProvider(
        {
            "AAPL": [
                {
                    "title": "future news",
                    "url": "https://example.test/future",
                    "summary": "future",
                    "publish_time": "2026-03-01",
                    "source": "replay",
                },
                {
                    "title": "included news",
                    "url": "https://example.test/included",
                    "summary": "included",
                    "publish_time": "2026-02-24",
                    "source": "replay",
                },
            ]
        }
    )

    prefetcher = DataPrefetcher(
        db_path=str(tmp_path / "news-replay.db"),
        market="us",
        news_provider=provider,
    )
    saved = prefetcher.prefetch_news(["AAPL"], "2026-02-23", "2026-02-27")

    assert prefetcher.api_source == APISource.FMP
    assert saved == 1
    news = prefetcher.db.get_daily_news(limit=10, days=30)
    assert [item["title"] for item in news] == ["included news"]

    prefetcher.close()


def test_news_provider_injection_keeps_live_candle_router(monkeypatch, tmp_path):
    monkeypatch.setattr("backtest.data_loader.Router", FakeRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)
    monkeypatch.setattr("backtest.data_loader.time.sleep", lambda _: None)
    provider = ReplayNewsProvider({"AAPL": []})

    prefetcher = DataPrefetcher(
        db_path=str(tmp_path / "news-only-keeps-candles.db"),
        market="us",
        news_provider=provider,
    )
    results = prefetcher.prefetch_klines(["AAPL"], "2026-02-23", "2026-02-27")

    assert results == {"AAPL": 5}
    assert prefetcher._request_interval_seconds() == 0.2
    assert prefetcher._news_request_interval_seconds() == 0.0

    prefetcher.close()


def test_prefetch_klines_records_provider_failure(monkeypatch, tmp_path):
    class FailingRouter(FakeRouter):
        def get_us_stock_daily_candles_df(self, ticker, trading_date):
            raise RuntimeError("GET https://example.test/query?apikey=secret-token failed")

    monkeypatch.setattr("backtest.data_loader.Router", FailingRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)

    prefetcher = DataPrefetcher(db_path=str(tmp_path / "price-failure.db"), market="us")
    results = prefetcher.prefetch_klines(["AAPL"], "2026-02-23", "2026-02-27")

    assert results == {"AAPL": 0}
    assert len(prefetcher.provider_failures) == 1
    failure = prefetcher.provider_failures[0]
    assert failure.provider == APISource.FMP
    assert failure.operation == "daily_candles"
    assert failure.ticker == "AAPL"
    assert failure.date == "2026-02-27"
    assert "secret-token" not in failure.message

    prefetcher.close()


def test_provider_failures_are_read_only_and_accumulate_in_order(monkeypatch, tmp_path):
    class FailingRouter(FakeRouter):
        def get_us_stock_daily_candles_df(self, ticker, trading_date):
            raise RuntimeError(f"price failure token={ticker}-secret")

    monkeypatch.setattr("backtest.data_loader.Router", FailingRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)

    prefetcher = DataPrefetcher(db_path=str(tmp_path / "ordered-failures.db"), market="us")
    results = prefetcher.prefetch_klines(["AAPL", "MSFT"], "2026-02-23", "2026-02-27")

    failures = prefetcher.provider_failures
    assert results == {"AAPL": 0, "MSFT": 0}
    assert isinstance(failures, tuple)
    assert [failure.ticker for failure in failures] == ["AAPL", "MSFT"]
    assert "AAPL-secret" not in failures[0].message
    assert "MSFT-secret" not in failures[1].message

    prefetcher.close()


def test_prefetch_news_records_provider_failure(monkeypatch, tmp_path):
    class FailingNewsProvider:
        name = "failing_news"

        def get_news(self, ticker, trading_date, limit, market):
            raise RuntimeError("news failure token=secret-token")

    monkeypatch.setattr("backtest.data_loader.Router", FakeRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)

    prefetcher = DataPrefetcher(
        db_path=str(tmp_path / "news-failure.db"),
        market="us",
        news_provider=FailingNewsProvider(),
    )
    saved = prefetcher.prefetch_news(["AAPL"], "2026-02-23", "2026-02-27")

    assert saved == 0
    assert len(prefetcher.provider_failures) == 1
    failure = prefetcher.provider_failures[0]
    assert failure.provider == "failing_news"
    assert failure.operation == "news"
    assert failure.ticker == "AAPL"
    assert "secret-token" not in failure.message

    prefetcher.close()


def test_reference_trading_days_records_provider_failure(monkeypatch, tmp_path):
    class FailingRouter(FakeRouter):
        def get_us_stock_daily_candles_df(self, ticker, trading_date):
            raise RuntimeError("reference failure api_key=secret-token")

    monkeypatch.setattr("backtest.data_loader.Router", FailingRouter)
    monkeypatch.setattr("backtest.data_loader.resolve_api_source", lambda market, cfg: APISource.FMP)

    prefetcher = DataPrefetcher(db_path=str(tmp_path / "reference-failure.db"), market="us")
    trading_days = prefetcher.get_trading_days("2026-02-23", "2026-02-27", ticker="AAPL")

    assert trading_days == [
        "2026-02-23",
        "2026-02-24",
        "2026-02-25",
        "2026-02-26",
        "2026-02-27",
    ]
    assert len(prefetcher.provider_failures) == 1
    failure = prefetcher.provider_failures[0]
    assert failure.operation == "reference_trading_days"
    assert "secret-token" not in failure.message

    prefetcher.close()


class _DummyEngine(BaseBacktestEngine):
    def run(self, *args, **kwargs):
        raise NotImplementedError


def test_base_engine_passes_api_source_config_to_prefetcher(monkeypatch, tmp_path):
    captured = {}

    class FakePrefetcher:
        def __init__(self, db_path, market, api_source_config=None):
            captured["db_path"] = db_path
            captured["market"] = market
            captured["api_source_config"] = dict(api_source_config or {})

    monkeypatch.setattr("backtest.base_engine.DataPrefetcher", FakePrefetcher)
    monkeypatch.setattr("backtest.base_engine.PortfolioTracker", lambda initial_cash: {"initial_cash": initial_cash})
    monkeypatch.setattr("backtest.base_engine.ReportGenerator", lambda: object())

    _DummyEngine(
        tickers=["MSFT"],
        start_date="2026-02-23",
        end_date="2026-02-27",
        initial_cash=100000.0,
        market="us",
        config={"api_source": {"default": "fmp", "us_source": "fmp"}},
        db_path=str(tmp_path / "prices.db"),
    )

    assert captured["market"] == "us"
    assert captured["api_source_config"]["us_source"] == "fmp"
