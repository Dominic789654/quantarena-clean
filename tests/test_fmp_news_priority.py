from datetime import datetime
from unittest.mock import Mock

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


def test_fmp_stock_news_passes_date_range_for_backdated_trading_date(monkeypatch):
    """Backdated trading dates must constrain the stock-news request window.

    Without from/to the endpoint returns only the latest articles, so a
    backtest replay over past dates has every row filtered out by
    _within_trading_date and the news channel silently degrades to
    "no news" (observed on the 2026-04 US 3M rerun).
    """
    api = _build_api(monkeypatch)
    captured = {}

    def fake_request_json(path, params=None):
        if path == "/stable/news/stock":
            captured.update(params or {})
            return [
                {
                    "symbol": "MSFT",
                    "publishedDate": "2026-04-27 08:00:00",
                    "publisher": "StockProvider",
                    "title": "MSFT backdated item",
                }
            ]
        return []

    monkeypatch.setattr(api, "_request_json", fake_request_json)
    results = api.get_news(ticker="MSFT", trading_date=datetime(2026, 4, 28), limit=5)

    assert captured["from"] == "2026-04-21"
    assert captured["to"] == "2026-04-28"
    assert len(results) == 1 and results[0].title == "MSFT backdated item"


def test_fmp_stock_news_omits_date_range_for_live_calls(monkeypatch):
    """trading_date=None (live mode) must keep the original request shape."""
    api = _build_api(monkeypatch)
    captured = {}

    def fake_request_json(path, params=None):
        if path == "/stable/news/stock":
            captured.update(params or {})
            return [
                {
                    "symbol": "MSFT",
                    "publishedDate": "2026-04-27 08:00:00",
                    "publisher": "StockProvider",
                    "title": "MSFT live item",
                }
            ]
        return []

    monkeypatch.setattr(api, "_request_json", fake_request_json)
    api.get_news(ticker="MSFT", trading_date=None, limit=5)

    assert "from" not in captured and "to" not in captured


def test_fmp_request_retries_transient_transport_errors(monkeypatch):
    """Intermittent SSL/connection drops must be retried, not surfaced.

    Observed on the 2026-04 US 3M replay: ~18% of news calls failed with
    SSLEOFError and degraded to [Error]->Neutral signals.
    """
    import requests as _requests

    api = _build_api(monkeypatch)
    monkeypatch.setattr("apis.fmp.api.time.sleep", lambda _s: None)

    ok_response = Mock()
    ok_response.status_code = 200
    ok_response.raise_for_status = Mock()
    ok_response.text = "[]"
    ok_response.json.return_value = []

    attempts = []

    def flaky_get(url, params=None, timeout=None):
        attempts.append(url)
        if len(attempts) < 3:
            raise _requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")
        return ok_response

    monkeypatch.setattr(api.session, "get", flaky_get)
    assert api._request_json("/stable/news/stock", {"symbols": "KO"}) == []
    assert len(attempts) == 3  # 2 retries then success


def test_fmp_request_raises_after_retry_exhaustion(monkeypatch):
    import requests as _requests

    import pytest as _pytest

    api = _build_api(monkeypatch)
    monkeypatch.setattr("apis.fmp.api.time.sleep", lambda _s: None)

    def always_broken(url, params=None, timeout=None):
        raise _requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING")

    monkeypatch.setattr(api.session, "get", always_broken)
    with _pytest.raises(_requests.exceptions.SSLError):
        api._request_json("/stable/news/stock", {"symbols": "KO"})
