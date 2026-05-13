from datetime import datetime

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from apis.fmp.api import FMPAPI


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
