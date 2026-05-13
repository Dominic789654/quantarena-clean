"""Unit tests for AKShare-backed company news provider."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

import sys
import types
from pathlib import Path
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

if "yfinance" not in sys.modules:
    yfinance_stub = types.ModuleType("yfinance")

    class _Search:
        def __init__(self, *args, **kwargs):
            self.news = []

    yfinance_stub.Search = _Search
    sys.modules["yfinance"] = yfinance_stub

from deepfund.src.apis.akshare import api as akshare_api_mod


@pytest.fixture(autouse=True)
def clear_akshare_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("AKSHARE_NEWS_CACHE_ENABLED", "true")
    monkeypatch.setenv("AKSHARE_NEWS_LOOKBACK_DAYS", "5")
    monkeypatch.setenv("AKSHARE_MAX_RETRIES", "1")
    monkeypatch.setenv("AKSHARE_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("AKSHARE_NOTICE_ENABLED", "true")
    monkeypatch.setenv("AKSHARE_NOTICE_HIGH_SIGNAL_ONLY", "true")
    monkeypatch.setenv("AKSHARE_NOTICE_CACHE_ENABLED", "true")
    monkeypatch.setenv("AKSHARE_NOTICE_CACHE_MAX_ENTRIES", "200")
    monkeypatch.setenv("AKSHARE_NEWS_SNAPSHOT_MODE", "prefer_local")
    monkeypatch.setenv("AKSHARE_NEWS_SNAPSHOT_DIR", str(tmp_path))
    with akshare_api_mod.AKShareNewsAPI._cache_lock:
        akshare_api_mod.AKShareNewsAPI._news_cache.clear()
        akshare_api_mod.AKShareNewsAPI._cache_order.clear()
        akshare_api_mod.AKShareNewsAPI._cache_source.clear()
    with akshare_api_mod.AKShareNewsAPI._notice_lock:
        akshare_api_mod.AKShareNewsAPI._notice_cache.clear()
        akshare_api_mod.AKShareNewsAPI._notice_order.clear()
    yield


def _build_df(rows: list[dict]):
    return pd.DataFrame(rows)


def test_akshare_news_api_retry_once_then_success():
    df = _build_df(
        [
            {
                "新闻标题": "retry success",
                "发布时间": "2025-09-01 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/retry",
                "新闻内容": "ok",
            }
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.side_effect = [RuntimeError("timeout"), df]

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")

    assert fake_ak.stock_news_em.call_count == 2
    assert len(news) == 1
    assert news[0].title == "retry success"


def test_akshare_news_api_prepares_pandas_backend_before_request():
    df = _build_df(
        [
            {
                "新闻标题": "ok",
                "发布时间": "2025-09-01 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/ok",
                "新闻内容": "ok",
            }
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        with patch.object(api, "_prepare_pandas_string_backend") as prepare_backend:
            news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")

    assert len(news) == 1
    prepare_backend.assert_called_once()


def test_akshare_news_api_handles_aware_datetime_without_type_error():
    df = _build_df(
        [
            {
                "新闻标题": "keep",
                "发布时间": "2025-09-01T10:00:00+00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/keep",
                "新闻内容": "x",
            },
            {
                "新闻标题": "future in cn timezone",
                "发布时间": "2025-09-01T16:00:00+00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/future",
                "新闻内容": "y",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")

    assert [item.title for item in news] == ["keep"]


def test_akshare_news_api_preserves_datetime_time_for_cutoff_filtering():
    df = _build_df(
        [
            {
                "新闻标题": "keep before cutoff",
                "发布时间": datetime(2025, 9, 2, 15, 0, 0),
                "文章来源": "em",
                "新闻链接": "https://example.com/keep",
                "新闻内容": "x",
            },
            {
                "新闻标题": "future should be filtered",
                "发布时间": datetime(2025, 9, 3, 1, 0, 0),
                "文章来源": "em",
                "新闻链接": "https://example.com/future",
                "新闻内容": "y",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 2), limit=5, market="cn")

    assert [item.title for item in news] == ["keep before cutoff"]
    assert news[0].publish_time == "2025-09-02T15:00:00"


def test_akshare_news_api_respects_lookback_days(monkeypatch):
    monkeypatch.setenv("AKSHARE_NEWS_LOOKBACK_DAYS", "5")
    df = _build_df(
        [
            {
                "新闻标题": "in window",
                "发布时间": "2025-09-07 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/in-window",
                "新闻内容": "x",
            },
            {
                "新闻标题": "too old",
                "发布时间": "2025-09-03 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/old",
                "新闻内容": "x",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 10), limit=5, market="cn")

    assert [item.title for item in news] == ["in window"]


def test_akshare_news_api_deduplicates_by_title_and_link():
    df = _build_df(
        [
            {
                "新闻标题": "dup",
                "发布时间": "2025-09-01 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/same",
                "新闻内容": "x",
            },
            {
                "新闻标题": "dup",
                "发布时间": "2025-09-01 09:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/same",
                "新闻内容": "x",
            },
            {
                "新闻标题": "dup",
                "发布时间": "2025-09-01 08:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/other",
                "新闻内容": "x",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=10, market="cn")

    assert len(news) == 2
    assert news[0].link == "https://example.com/same"
    assert news[1].link == "https://example.com/other"


def test_akshare_news_api_falls_back_to_notice_for_historical_window(monkeypatch):
    monkeypatch.setenv("AKSHARE_NEWS_LOOKBACK_DAYS", "1")
    news_df = _build_df(
        [
            {
                "新闻标题": "recent only",
                "发布时间": "2026-03-01 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/recent",
                "新闻内容": "x",
            }
        ]
    )
    notice_df = _build_df(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "公告标题": "贵州茅台:关于回购公司股份的公告",
                "公告类型": "回购实施公告",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/notice",
            }
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = news_df
    fake_ak.stock_notice_report.return_value = notice_df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 3), limit=5, market="cn")

    assert len(news) == 1
    assert news[0].title == "贵州茅台:关于回购公司股份的公告"
    assert news[0].publisher == "Eastmoney公告"
    assert api.last_source == "network:akshare_notice"
    fake_ak.stock_notice_report.assert_called_once()


def test_akshare_notice_filter_keeps_high_signal_only():
    news_df = _build_df([])
    notice_df = _build_df(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "公告标题": "贵州茅台:关于回购公司股份的公告",
                "公告类型": "回购实施公告",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/high",
            },
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "公告标题": "贵州茅台:关于召开2025年临时股东会的通知",
                "公告类型": "召开股东大会通知",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/low",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = news_df
    fake_ak.stock_notice_report.return_value = notice_df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 3), limit=5, market="cn")

    assert len(news) == 1
    assert "回购" in news[0].title


def test_akshare_notice_filter_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AKSHARE_NOTICE_HIGH_SIGNAL_ONLY", "false")
    news_df = _build_df([])
    notice_df = _build_df(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "公告标题": "贵州茅台:关于召开2025年临时股东会的通知",
                "公告类型": "召开股东大会通知",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/neutral",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = news_df
    fake_ak.stock_notice_report.return_value = notice_df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        news = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 3), limit=5, market="cn")

    assert len(news) == 1
    assert "股东会" in news[0].title


def test_akshare_notice_date_cache_reused_across_tickers(monkeypatch):
    monkeypatch.setenv("AKSHARE_NEWS_LOOKBACK_DAYS", "1")
    news_df = _build_df([])
    notice_df = _build_df(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "公告标题": "贵州茅台:关于回购公司股份的公告",
                "公告类型": "回购实施公告",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/600519",
            },
            {
                "代码": "000858",
                "名称": "五粮液",
                "公告标题": "五粮液:关于回购公司股份的公告",
                "公告类型": "回购实施公告",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/000858",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = news_df
    fake_ak.stock_notice_report.return_value = notice_df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        first = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 3), limit=5, market="cn")
        second = api.get_news(ticker="000858", trading_date=datetime(2025, 9, 3), limit=5, market="cn")

    assert len(first) == 1
    assert len(second) == 1
    # One market-wide announcement fetch for the same date, reused by date cache.
    fake_ak.stock_notice_report.assert_called_once()


def test_akshare_news_cache_preserves_notice_source_metadata():
    news_df = _build_df([])
    notice_df = _build_df(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "公告标题": "贵州茅台:关于回购公司股份的公告",
                "公告类型": "回购实施公告",
                "公告日期": "2025-09-03",
                "网址": "https://example.com/600519",
            },
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = news_df
    fake_ak.stock_notice_report.return_value = notice_df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        first = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 3), limit=5, market="cn")
        assert len(first) == 1
        assert api.last_source == "network:akshare_notice"

        second = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 3), limit=5, market="cn")
        assert len(second) == 1
        assert api.last_cache_hit is True
        assert api.last_source == "network:akshare_notice"


def test_akshare_news_api_local_only_reads_snapshot_without_network(monkeypatch):
    news_df = _build_df(
        [
            {
                "新闻标题": "snapshot hit",
                "发布时间": "2025-09-01 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/snapshot",
                "新闻内容": "ok",
            }
        ]
    )

    fake_ak = Mock()
    fake_ak.stock_news_em.return_value = news_df

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        first = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")
    assert len(first) == 1

    with akshare_api_mod.AKShareNewsAPI._cache_lock:
        akshare_api_mod.AKShareNewsAPI._news_cache.clear()
        akshare_api_mod.AKShareNewsAPI._cache_order.clear()
        akshare_api_mod.AKShareNewsAPI._cache_source.clear()

    monkeypatch.setenv("AKSHARE_NEWS_SNAPSHOT_MODE", "local_only")
    fake_ak_local = Mock()
    fake_ak_local.stock_news_em.side_effect = AssertionError("network should not be called")

    with patch.object(akshare_api_mod, "ak", fake_ak_local):
        api_local = akshare_api_mod.AKShareNewsAPI()
        second = api_local.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")

    assert len(second) == 1
    assert second[0].title == "snapshot hit"
    assert api_local.last_cache_hit is True
    assert api_local.last_source == "snapshot:network:akshare"


def test_akshare_news_api_local_only_raises_when_snapshot_missing(monkeypatch):
    monkeypatch.setenv("AKSHARE_NEWS_SNAPSHOT_MODE", "local_only")

    fake_ak = Mock()
    fake_ak.stock_news_em.side_effect = AssertionError("network should not be called")

    with patch.object(akshare_api_mod, "ak", fake_ak):
        api = akshare_api_mod.AKShareNewsAPI()
        with pytest.raises(FileNotFoundError):
            api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")


def test_akshare_news_api_refresh_rewrites_snapshot(monkeypatch):
    first_df = _build_df(
        [
            {
                "新闻标题": "old news",
                "发布时间": "2025-09-01 10:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/old",
                "新闻内容": "old",
            }
        ]
    )
    second_df = _build_df(
        [
            {
                "新闻标题": "new news",
                "发布时间": "2025-09-01 11:00:00",
                "文章来源": "em",
                "新闻链接": "https://example.com/new",
                "新闻内容": "new",
            }
        ]
    )

    with patch.object(akshare_api_mod, "ak", Mock(stock_news_em=Mock(return_value=first_df))):
        api = akshare_api_mod.AKShareNewsAPI()
        first = api.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")
    assert [item.title for item in first] == ["old news"]

    with akshare_api_mod.AKShareNewsAPI._cache_lock:
        akshare_api_mod.AKShareNewsAPI._news_cache.clear()
        akshare_api_mod.AKShareNewsAPI._cache_order.clear()
        akshare_api_mod.AKShareNewsAPI._cache_source.clear()

    monkeypatch.setenv("AKSHARE_NEWS_SNAPSHOT_MODE", "refresh")
    with patch.object(akshare_api_mod, "ak", Mock(stock_news_em=Mock(return_value=second_df))) as fake_ak_refresh:
        api_refresh = akshare_api_mod.AKShareNewsAPI()
        refreshed = api_refresh.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")
        assert fake_ak_refresh.stock_news_em.call_count == 1
    assert [item.title for item in refreshed] == ["new news"]

    with akshare_api_mod.AKShareNewsAPI._cache_lock:
        akshare_api_mod.AKShareNewsAPI._news_cache.clear()
        akshare_api_mod.AKShareNewsAPI._cache_order.clear()
        akshare_api_mod.AKShareNewsAPI._cache_source.clear()

    monkeypatch.setenv("AKSHARE_NEWS_SNAPSHOT_MODE", "local_only")
    fake_ak_local = Mock()
    fake_ak_local.stock_news_em.side_effect = AssertionError("network should not be called")
    with patch.object(akshare_api_mod, "ak", fake_ak_local):
        api_local = akshare_api_mod.AKShareNewsAPI()
        local_only = api_local.get_news(ticker="600519", trading_date=datetime(2025, 9, 1), limit=5, market="cn")
    assert [item.title for item in local_only] == ["new news"]
