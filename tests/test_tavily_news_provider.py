"""Unit tests for Tavily-backed company news provider."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import Mock, patch

import sys
import types
from pathlib import Path
import pytest
import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

# Provide a lightweight stub so apis.__init__ can be imported without optional deps.
if "yfinance" not in sys.modules:
    yfinance_stub = types.ModuleType("yfinance")

    class _Search:
        def __init__(self, *args, **kwargs):
            self.news = []

    yfinance_stub.Search = _Search
    sys.modules["yfinance"] = yfinance_stub

from deepfund.src.apis.common_model import MediaNews
from deepfund.src.apis.tavily.api import TavilyNewsAPI
from deepfund.src.apis import router as router_mod


@pytest.fixture(autouse=True)
def clear_tavily_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_NEWS_SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("TAVILY_NEWS_SNAPSHOT_MODE", "prefer_local")
    monkeypatch.setenv("TAVILY_NEWS_CACHE_ENABLED", "true")
    with TavilyNewsAPI._cache_lock:
        TavilyNewsAPI._news_cache.clear()
        TavilyNewsAPI._cache_order.clear()
        TavilyNewsAPI._cache_source.clear()
    yield


def test_tavily_news_api_parses_and_filters_future_news(monkeypatch):
    """Tavily parser should normalize records and filter future timestamps."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "贵州茅台发布业绩预告",
                "url": "https://finance.example.com/a",
                "content": "业绩稳健增长",
                "source": "Finance Example",
                "published_date": "2025-09-01T09:00:00Z",
            },
            {
                "title": "未来日期新闻应被过滤",
                "url": "https://finance.example.com/future",
                "content": "future",
                "published_date": "2025-09-10T09:00:00Z",
            },
        ]
    }

    api = TavilyNewsAPI()
    with patch.object(api._session, "post", return_value=mock_response):
        news = api.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )

    assert len(news) == 1
    assert news[0].title == "贵州茅台发布业绩预告"
    assert news[0].publisher == "Finance Example"
    assert api.last_cache_hit is False


def test_tavily_news_api_uses_cache_for_same_day_same_ticker(monkeypatch):
    """Second request for same key should be served from in-memory cache."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "cached news",
                "url": "https://finance.example.com/a",
                "content": "foo",
                "source": "Finance Example",
                "published_date": "2025-09-01T09:00:00Z",
            },
        ]
    }

    api = TavilyNewsAPI()
    with patch.object(api._session, "post", return_value=mock_response) as mock_post:
        first = api.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )
        assert api.last_cache_hit is False

        second = api.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )
        assert api.last_cache_hit is True

    assert mock_post.call_count == 1
    assert len(first) == len(second) == 1
    assert first[0].title == second[0].title == "cached news"


def test_tavily_news_api_retries_once_on_timeout(monkeypatch):
    """Tavily request should retry on timeout and succeed on the second attempt."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_MAX_RETRIES", "1")
    monkeypatch.setenv("TAVILY_RETRY_BACKOFF_SECONDS", "0")

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "retry success",
                "url": "https://finance.example.com/retry",
                "content": "ok",
                "source": "Finance Example",
                "published_date": "2025-09-01T09:00:00Z",
            },
        ]
    }

    api = TavilyNewsAPI()
    with patch.object(
        api._session,
        "post",
        side_effect=[requests.Timeout("timeout"), mock_response],
    ) as mock_post:
        news = api.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )

    assert mock_post.call_count == 2
    assert len(news) == 1
    assert news[0].title == "retry success"


def test_tavily_news_api_local_only_reads_snapshot_without_network(monkeypatch):
    """local_only mode should load existing snapshot and skip network."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "snapshot hit",
                "url": "https://finance.example.com/s",
                "content": "snap",
                "source": "Finance Example",
                "published_date": "2025-09-01T09:00:00Z",
            },
        ]
    }

    api = TavilyNewsAPI()
    with patch.object(api._session, "post", return_value=mock_response):
        first = api.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )
    assert len(first) == 1

    monkeypatch.setenv("TAVILY_NEWS_SNAPSHOT_MODE", "local_only")
    with TavilyNewsAPI._cache_lock:
        TavilyNewsAPI._news_cache.clear()
        TavilyNewsAPI._cache_order.clear()

    api_local = TavilyNewsAPI()
    with patch.object(api_local._session, "post", side_effect=AssertionError("network should not be called")):
        second = api_local.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )

    assert len(second) == 1
    assert second[0].title == "snapshot hit"
    assert api_local.last_cache_hit is True
    assert api_local.last_source == "snapshot:tavily_api"


def test_tavily_news_api_local_only_reads_snapshot_source_metadata(monkeypatch):
    """local_only mode should expose snapshot source metadata in last_source."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_NEWS_SNAPSHOT_MODE", "local_only")

    api = TavilyNewsAPI()
    key = api._build_cache_key(
        ticker="600519",
        topic=None,
        market="cn",
        trading_date=datetime(2025, 9, 3),
        max_results=5,
    )
    path = api._snapshot_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "key": {
                    "ticker": "600519",
                    "topic": "",
                    "market": "cn",
                    "date": "2025-09-03",
                    "limit": 5,
                },
                "saved_at": "2026-03-04T00:00:00+00:00",
                "meta": {"source": "kimi"},
                "items": [
                    {
                        "title": "snapshot from kimi",
                        "publish_time": "2025-09-03T00:00:00",
                        "publisher": "kimi",
                        "link": "https://example.com/1",
                        "summary": "x",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch.object(api._session, "post", side_effect=AssertionError("network should not be called")):
        news = api.get_news(
            ticker="600519",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )

    assert len(news) == 1
    assert api.last_cache_hit is True
    assert api.last_source == "snapshot:kimi"


def test_tavily_news_api_local_only_raises_when_snapshot_missing(monkeypatch):
    """local_only mode should fail fast when snapshot does not exist."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_NEWS_SNAPSHOT_MODE", "local_only")

    api = TavilyNewsAPI()
    with pytest.raises(FileNotFoundError):
        api.get_news(
            ticker="000001",
            trading_date=datetime(2025, 9, 3),
            limit=5,
            market="cn",
        )


def test_router_uses_tavily_for_us_news_when_enabled():
    """Router should route US news calls to Tavily when provider=tavily."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.YFINANCE
    router._api_category = "yfinance"
    router._tavily_news_api = None
    router._news_provider = "tavily"
    router.api = Mock()
    router.api.get_news.side_effect = AssertionError("fallback source should not be called")

    expected = [
        MediaNews(
            title="AAPL news",
            publish_time="2025-09-01T00:00:00",
            publisher="Tavily",
            link="https://example.com",
            summary="x",
        )
    ]

    with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
        mock_tavily_cls.return_value.get_news.return_value = expected
        mock_tavily_cls.return_value.last_cache_hit = False
        result = router.get_us_stock_news("AAPL", datetime(2025, 9, 1), 3)

    assert result == expected


def test_router_falls_back_to_tushare_when_tavily_fails():
    """Router should gracefully fall back to original CN source on Tavily errors."""

    class DummyTushare:
        def get_news(self, ticker, trading_date, limit):
            return [
                MediaNews(
                    title=f"{ticker} fallback news",
                    publish_time=trading_date.isoformat(),
                    publisher="fallback",
                )
            ]

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._news_provider = "tavily"
    router.api = DummyTushare()

    with patch.object(router_mod, "TushareAPI", DummyTushare):
        with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
            mock_tavily_cls.return_value.get_news.side_effect = RuntimeError("tavily unavailable")
            result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert len(result) == 1
    assert result[0].publisher == "fallback"


def test_router_falls_back_to_tushare_when_tavily_returns_empty():
    """Router should fall back when Tavily returns empty in non-strict mode."""

    class DummyTushare:
        def get_news(self, ticker, trading_date, limit):
            return [
                MediaNews(
                    title=f"{ticker} fallback news",
                    publish_time=trading_date.isoformat(),
                    publisher="fallback",
                )
            ]

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._news_provider = "tavily"
    router.api = DummyTushare()

    with patch.object(router_mod, "TushareAPI", DummyTushare):
        with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
            mock_tavily_cls.return_value.get_news.return_value = []
            result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert len(result) == 1
    assert result[0].publisher == "fallback"


def test_router_tavily_strict_raises_without_fallback():
    """Router should raise when provider=tavily_strict and Tavily fails."""

    class DummyTushare:
        def get_news(self, ticker, trading_date, limit):
            raise AssertionError("strict mode should not call fallback source")

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._news_provider = "tavily_strict"
    router.api = DummyTushare()

    with patch.object(router_mod, "TushareAPI", DummyTushare):
        with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
            mock_tavily_cls.return_value.get_news.side_effect = RuntimeError("tavily unavailable")
            with pytest.raises(RuntimeError, match="tavily unavailable"):
                router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)


def test_router_uses_akshare_for_cn_news_when_enabled():
    """Router should route CN news calls to AKShare when provider=akshare."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "akshare"
    router.api = Mock()
    router.api.get_news.side_effect = AssertionError("fallback source should not be called")

    expected = [
        MediaNews(
            title="AKS news",
            publish_time="2025-09-01T00:00:00",
            publisher="AKShare",
            link="https://example.com",
            summary="x",
        )
    ]

    with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
        mock_ak_cls.return_value.get_news.return_value = expected
        mock_ak_cls.return_value.last_cache_hit = False
        result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == expected


def test_router_akshare_strict_raises_without_fallback():
    """Router should raise when provider=akshare_strict and AKShare fails."""

    class DummyTushare:
        def get_news(self, ticker, trading_date, limit):
            raise AssertionError("strict mode should not call fallback source")

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "akshare_strict"
    router.api = DummyTushare()

    with patch.object(router_mod, "TushareAPI", DummyTushare):
        with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
            mock_ak_cls.return_value.get_news.side_effect = RuntimeError("akshare unavailable")
            with pytest.raises(RuntimeError, match="akshare unavailable"):
                router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)


def test_router_returns_empty_when_akshare_returns_empty():
    """Router should not fall back to Tushare when AKShare returns empty."""

    class DummyTushare:
        def get_news(self, ticker, trading_date, limit):
            raise AssertionError("fallback source should not be called")

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "akshare"
    router.api = DummyTushare()

    with patch.object(router_mod, "TushareAPI", DummyTushare):
        with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
            mock_ak_cls.return_value.get_news.return_value = []
            result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == []


def test_router_returns_empty_when_akshare_fails_non_strict():
    """Router should not fall back to Tushare when AKShare errors in non-strict mode."""

    class DummyTushare:
        def get_news(self, ticker, trading_date, limit):
            raise AssertionError("fallback source should not be called")

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "akshare"
    router.api = DummyTushare()

    with patch.object(router_mod, "TushareAPI", DummyTushare):
        with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
            mock_ak_cls.return_value.get_news.side_effect = RuntimeError("akshare unavailable")
            result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == []


def test_router_logs_akshare_notice_provider_source():
    """Router log should reflect AKShare notice fallback source."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "akshare"
    router.api = Mock()
    router.api.get_news.side_effect = AssertionError("fallback source should not be called")

    expected = [
        MediaNews(
            title="notice news",
            publish_time="2025-09-01T00:00:00",
            publisher="AKShare",
        )
    ]

    with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
        mock_ak = mock_ak_cls.return_value
        mock_ak.get_news.return_value = expected
        mock_ak.last_cache_hit = False
        mock_ak.last_source = "network:akshare_notice"
        with patch.object(router, "_log_news_fetch") as mock_log:
            result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == expected
    assert mock_log.call_count == 1
    assert mock_log.call_args.args[0] == "akshare_notice"


def test_router_logs_akshare_snapshot_provider_source():
    """Router log should reflect AKShare snapshot source."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "akshare"
    router.api = Mock()
    router.api.get_news.side_effect = AssertionError("fallback source should not be called")

    expected = [
        MediaNews(
            title="snapshot news",
            publish_time="2025-09-01T00:00:00",
            publisher="AKShare",
        )
    ]

    with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
        mock_ak = mock_ak_cls.return_value
        mock_ak.get_news.return_value = expected
        mock_ak.last_cache_hit = True
        mock_ak.last_source = "snapshot:network:akshare_notice"
        with patch.object(router, "_log_news_fetch") as mock_log:
            result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == expected
    assert mock_log.call_count == 1
    assert mock_log.call_args.args[0] == "snapshot_akshare_notice"


def test_router_auto_uses_akshare_when_tavily_key_missing(monkeypatch):
    """auto mode should choose AKShare for CN news when TAVILY_API_KEY is absent."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._akshare_news_api = None
    router._news_provider = "auto"
    router.api = Mock()
    router.api.get_news.side_effect = AssertionError("fallback source should not be called")

    expected = [
        MediaNews(
            title="auto aks",
            publish_time="2025-09-01T00:00:00",
            publisher="AKShare",
        )
    ]

    with patch.object(router_mod, "AKShareNewsAPI") as mock_ak_cls:
        mock_ak_cls.return_value.get_news.return_value = expected
        mock_ak_cls.return_value.last_cache_hit = False
        result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == expected


def test_router_records_news_stats_by_actual_provider():
    """Router should record company news stats by actual provider."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._news_provider = "tavily"
    router.api = Mock()

    expected = [
        MediaNews(
            title="news",
            publish_time="2025-09-01T00:00:00",
            publisher="Tavily",
        )
    ]

    mock_stats = Mock()
    with patch.object(router_mod, "STATS_AVAILABLE", True):
        with patch.object(router_mod, "get_stats", return_value=mock_stats):
            with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
                mock_tavily_cls.return_value.get_news.return_value = expected
                mock_tavily_cls.return_value.last_cache_hit = False
                result = router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    assert result == expected
    mock_stats.record_api_call.assert_called_once()
    args, kwargs = mock_stats.record_api_call.call_args
    assert args[0] == "tavily_news"
    assert kwargs["success"] is True


def test_router_records_cache_hit_metric_for_tavily_news():
    """Router should record cache-hit stats when Tavily serves cached result."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._news_provider = "tavily"
    router.api = Mock()

    expected = [
        MediaNews(
            title="cached",
            publish_time="2025-09-01T00:00:00",
            publisher="Tavily",
        )
    ]

    mock_stats = Mock()
    with patch.object(router_mod, "STATS_AVAILABLE", True):
        with patch.object(router_mod, "get_stats", return_value=mock_stats):
            with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
                mock_tavily_cls.return_value.get_news.return_value = expected
                mock_tavily_cls.return_value.last_cache_hit = True
                router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    categories = [call.args[0] for call in mock_stats.record_api_call.call_args_list]
    assert "tavily_news" in categories
    assert "tavily_news_cache_hit" in categories


def test_router_logs_snapshot_source_when_cache_hit(capsys):
    """Router should expose snapshot source in provider log label."""
    router = router_mod.Router.__new__(router_mod.Router)
    router._source = router_mod.APISource.TUSHARE
    router._api_category = "tushare"
    router._tavily_news_api = None
    router._news_provider = "tavily"
    router.api = Mock()

    expected = [
        MediaNews(
            title="cached",
            publish_time="2025-09-01T00:00:00",
            publisher="snapshot",
        )
    ]

    with patch.object(router_mod, "TavilyNewsAPI") as mock_tavily_cls:
        mock_tavily_cls.return_value.get_news.return_value = expected
        mock_tavily_cls.return_value.last_cache_hit = True
        mock_tavily_cls.return_value.last_source = "snapshot:kimi"
        router.get_cn_stock_news("600519", datetime(2025, 9, 1), 3)

    out = capsys.readouterr().out
    assert "provider=snapshot_kimi" in out
