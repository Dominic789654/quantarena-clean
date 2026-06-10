from datetime import datetime

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from apis.fmp.api import FMPAPI
from quantarena.news_diagnostics import clear_news_diagnostics, peek_news_diagnostics


def _build_api(monkeypatch) -> FMPAPI:
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    return FMPAPI()


def test_fmp_news_prefers_stock_over_general_and_articles(monkeypatch):
    api = _build_api(monkeypatch)
    calls = []

    def fake_request_json(path, params=None):
        calls.append(path)
        if path == "/stable/news/stock":
            return [
                {
                    "symbol": "AAPL",
                    "publishedDate": "2026-03-09 07:36:00",
                    "publisher": "StockProvider",
                    "title": "AAPL stock item",
                    "text": "Apple news",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(api, "_request_json", fake_request_json)

    news = api.get_news(ticker="AAPL", trading_date=datetime(2026, 3, 9), limit=3)

    assert calls == ["/stable/news/stock"]
    assert len(news) == 1
    assert news[0].publisher == "StockProvider"


def test_fmp_news_falls_back_to_general_before_articles(monkeypatch):
    api = _build_api(monkeypatch)
    calls = []

    general_calls = 0

    def fake_request_json(path, params=None):
        nonlocal general_calls
        calls.append(path)
        if path == "/stable/news/stock":
            return []
        if path == "/stable/news/general-latest":
            general_calls += 1
            if general_calls > 1:
                return []
            return [
                {
                    "publishedDate": "2026-03-08 08:00:00",
                    "publisher": "GeneralProvider",
                    "title": "Apple AAPL gains attention",
                    "text": "AAPL mentioned in general feed",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(api, "_request_json", fake_request_json)

    news = api.get_news(ticker="AAPL", trading_date=datetime(2026, 3, 9), limit=3)

    assert calls[0] == "/stable/news/stock"
    assert "/stable/news/general-latest" in calls
    assert "/stable/fmp-articles" not in calls
    assert len(news) == 1
    assert news[0].publisher == "GeneralProvider"


def test_fmp_news_uses_articles_after_general_miss(monkeypatch):
    api = _build_api(monkeypatch)
    calls = []

    article_calls = 0

    def fake_request_json(path, params=None):
        nonlocal article_calls
        calls.append(path)
        if path == "/stable/news/stock":
            raise PermissionError("restricted")
        if path == "/stable/news/general-latest":
            return []
        if path == "/stable/fmp-articles":
            article_calls += 1
            if article_calls > 1:
                return []
            return [
                {
                    "date": "2026-03-07 09:00:00",
                    "site": "ArticleProvider",
                    "title": "Apple AAPL article fallback",
                    "content": "Fallback article mentioning AAPL",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(api, "_request_json", fake_request_json)

    news = api.get_news(ticker="AAPL", trading_date=datetime(2026, 3, 9), limit=3)

    assert calls[0] == "/stable/news/stock"
    assert "/stable/news/general-latest" in calls
    assert calls[-1] == "/stable/fmp-articles"
    assert len(news) == 1
    assert news[0].publisher == "ArticleProvider"


def test_fmp_news_records_zero_result_filter_diagnostics(monkeypatch):
    clear_news_diagnostics()
    api = _build_api(monkeypatch)
    general_calls = 0

    def fake_request_json(path, params=None):
        nonlocal general_calls
        if path == "/stable/news/stock":
            return [
                {
                    "symbol": "AAPL",
                    "publishedDate": "2026-03-10 07:36:00",
                    "publisher": "FutureProvider",
                    "title": "AAPL future item",
                    "text": "Future Apple news",
                }
            ]
        if path == "/stable/news/general-latest":
            general_calls += 1
            if general_calls > 1:
                return []
            return [
                {
                    "publishedDate": "2026-03-08 08:00:00",
                    "publisher": "OtherProvider",
                    "title": "MSFT gains attention",
                    "text": "MSFT mentioned in general feed",
                }
            ]
        if path == "/stable/fmp-articles":
            return []
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(api, "_request_json", fake_request_json)

    news = api.get_news(ticker="AAPL", trading_date=datetime(2026, 3, 9), limit=3)

    diagnostics = peek_news_diagnostics()
    assert news == []
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert record["provider"] == "fmp"
    assert record["ticker"] == "AAPL"
    assert record["trading_date"] == "2026-03-09"
    assert record["raw_count"] == 2
    assert record["date_filtered_count"] == 1
    assert record["ticker_filtered_count"] == 0
    assert record["final_count"] == 0
    assert record["zero_reason"] == "ticker_miss"
    assert [stage["endpoint"] for stage in record["stages"]] == [
        "/stable/news/stock",
        "/stable/news/general-latest",
        "/stable/fmp-articles",
    ]
    clear_news_diagnostics()


def test_fmp_news_records_future_only_zero_reason(monkeypatch):
    clear_news_diagnostics()
    api = _build_api(monkeypatch)

    def fake_request_json(path, params=None):
        if path == "/stable/news/stock":
            return [
                {
                    "symbol": "AAPL",
                    "publishedDate": "2026-03-10 07:36:00",
                    "publisher": "FutureProvider",
                    "title": "AAPL future item",
                    "text": "Future Apple news",
                }
            ]
        if path == "/stable/news/general-latest":
            return []
        if path == "/stable/fmp-articles":
            return []
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(api, "_request_json", fake_request_json)

    news = api.get_news(ticker="AAPL", trading_date=datetime(2026, 3, 9), limit=3)

    diagnostics = peek_news_diagnostics()
    assert news == []
    assert diagnostics[-1]["raw_count"] == 1
    assert diagnostics[-1]["date_filtered_count"] == 0
    assert diagnostics[-1]["zero_reason"] == "future_only"
    clear_news_diagnostics()
