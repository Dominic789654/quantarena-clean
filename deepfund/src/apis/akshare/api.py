"""AKShare news API wrapper for Chinese company news."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from apis.common_model import MediaNews

try:
    import akshare as ak
except ImportError:  # pragma: no cover - exercised when dependency missing at runtime
    ak = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover - exercised when dependency missing at runtime
    pd = None


class AKShareNewsAPI:
    """Wrapper around AKShare stock_news_em for A-share company news."""

    CN_TZ = timezone(timedelta(hours=8))
    _cache_lock = threading.Lock()
    _news_cache: Dict[Tuple[str, str, int, str], List[MediaNews]] = {}
    _cache_order: List[Tuple[str, str, int, str]] = []
    _cache_source: Dict[Tuple[str, str, int, str], str] = {}
    _snapshot_lock = threading.Lock()
    _notice_lock = threading.Lock()
    _notice_cache: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    _notice_order: List[Tuple[str, str]] = []
    _NOTICE_HIGH_SIGNAL_KEYWORDS = (
        "业绩",
        "预增",
        "预减",
        "扭亏",
        "亏损",
        "回购",
        "增持",
        "减持",
        "收购",
        "并购",
        "重组",
        "定增",
        "发行",
        "债券",
        "诉讼",
        "仲裁",
        "立案",
        "处罚",
        "停牌",
        "复牌",
        "分红",
        "派息",
        "注册",
        "获批",
        "获受理",
        "上市许可",
        "中标",
        "签署",
        "协议",
        "激励",
    )
    _NOTICE_LOW_SIGNAL_KEYWORDS = (
        "证券变动月报表",
        "公告摘要",
        "提示性公告",
        "补充公告",
        "更正公告",
        "关于召开",
        "股东大会通知",
    )

    def __init__(self):
        if ak is None:
            raise ImportError("akshare package is not installed. Run: pip install akshare")
        self.last_cache_hit = False
        self.last_source = "network:akshare"
        self.cache_enabled = self._get_bool_env("AKSHARE_NEWS_CACHE_ENABLED", True)
        self.cache_max_entries = self._get_int_env("AKSHARE_NEWS_CACHE_MAX_ENTRIES", 1024, min_value=1, max_value=10000)
        self.max_retries = self._get_int_env("AKSHARE_MAX_RETRIES", 1, min_value=0, max_value=5)
        self.retry_backoff_seconds = self._get_float_env("AKSHARE_RETRY_BACKOFF_SECONDS", 0.3, min_value=0.0)
        self.lookback_days = self._get_int_env("AKSHARE_NEWS_LOOKBACK_DAYS", 5, min_value=1, max_value=30)
        self.notice_enabled = self._get_bool_env("AKSHARE_NOTICE_ENABLED", True)
        self.notice_symbol = os.getenv("AKSHARE_NOTICE_SYMBOL", "全部").strip() or "全部"
        self.notice_high_signal_only = self._get_bool_env("AKSHARE_NOTICE_HIGH_SIGNAL_ONLY", True)
        self.notice_cache_enabled = self._get_bool_env("AKSHARE_NOTICE_CACHE_ENABLED", True)
        self.notice_cache_max_entries = self._get_int_env("AKSHARE_NOTICE_CACHE_MAX_ENTRIES", 400, min_value=50, max_value=5000)
        self.snapshot_mode = self._get_snapshot_mode()
        self.snapshot_dir = self._get_snapshot_dir()

    def get_news(
        self,
        ticker: Optional[str] = None,
        topic: Optional[str] = None,
        trading_date: Optional[datetime] = None,
        limit: Optional[int] = None,
        market: str = "cn",
    ) -> List[MediaNews]:
        """Fetch stock news from AKShare and normalize to MediaNews."""
        if market.lower() != "cn":
            return []

        symbol = self._normalize_symbol(ticker=ticker)
        if not symbol:
            # company_news calls always provide ticker; keep this conservative for now.
            return []

        max_results = max(1, min(limit or 10, 50))
        cache_key = self._build_cache_key(symbol=symbol, trading_date=trading_date, max_results=max_results)
        cached = self._cache_get(cache_key)
        if cached is not None:
            self.last_cache_hit = True
            self.last_source = self._cache_source_get(cache_key)
            return cached
        self.last_cache_hit = False

        snapshot_items, snapshot_source = self._load_snapshot(cache_key)
        if snapshot_items is not None:
            self.last_cache_hit = True
            self.last_source = f"snapshot:{snapshot_source}"
            self._cache_set(cache_key, snapshot_items, source=self.last_source)
            return snapshot_items

        if self.snapshot_mode == "local_only":
            raise FileNotFoundError(f"AKShare news snapshot not found for key={cache_key}")

        cutoff = None
        lower_bound = None
        if trading_date is not None:
            cutoff = self._to_cn_tz(trading_date.replace(hour=23, minute=59, second=59, microsecond=999999))
            lower_bound = self._to_cn_tz(
                trading_date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=self.lookback_days - 1)
            )

        items: List[MediaNews] = []
        dedup: Set[Tuple[str, str]] = set()
        news_em_error: Optional[Exception] = None
        try:
            df = self._request_with_retry(symbol=symbol)
        except Exception as exc:
            df = None
            news_em_error = exc

        if df is not None and not df.empty:
            self._append_stock_news_em_items(
                items=items,
                dedup=dedup,
                df=df,
                trading_date=trading_date,
                lower_bound=lower_bound,
                cutoff=cutoff,
                max_results=max_results,
            )

        source = "network:akshare"
        if not items and trading_date is not None and self.notice_enabled:
            notice_items = self._get_notice_items(
                symbol=symbol,
                lower_bound=lower_bound,
                cutoff=cutoff,
                max_results=max_results,
                dedup=dedup,
            )
            items.extend(notice_items)
            if notice_items:
                source = "network:akshare_notice"

        if not items and news_em_error is not None:
            raise news_em_error

        self._save_snapshot(cache_key, items, source=source)
        self.last_source = source
        self._cache_set(cache_key, items, source=source)
        return self._clone_news_list(items)

    def _append_stock_news_em_items(
        self,
        items: List[MediaNews],
        dedup: Set[Tuple[str, str]],
        df,
        trading_date: Optional[datetime],
        lower_bound: Optional[datetime],
        cutoff: Optional[datetime],
        max_results: int,
    ) -> None:
        title_col = "新闻标题" if "新闻标题" in df.columns else "title"
        content_col = "新闻内容" if "新闻内容" in df.columns else "content"
        time_col = "发布时间" if "发布时间" in df.columns else "publish_time"
        source_col = "文章来源" if "文章来源" in df.columns else "source"
        link_col = "新闻链接" if "新闻链接" in df.columns else "url"

        for _, row in df.iterrows():
            title = str(row.get(title_col, "")).strip()
            publisher = str(row.get(source_col, "")).strip() or "AKShare"
            if not title:
                continue

            publish_time = self._normalize_publish_time(row.get(time_col), trading_date=trading_date)
            publish_dt = self._parse_datetime(publish_time)

            link_raw = row.get(link_col)
            link = None
            if isinstance(link_raw, str) and link_raw.strip().startswith(("http://", "https://")):
                link = link_raw.strip()

            if cutoff is not None and publish_dt is not None:
                publish_dt_cn = self._to_cn_tz(publish_dt)
                if publish_dt_cn > cutoff:
                    continue
                if lower_bound is not None and publish_dt_cn < lower_bound:
                    continue

            if not self._register_dedup(dedup=dedup, title=title, link=link):
                continue

            content = row.get(content_col)
            summary = None
            if isinstance(content, str) and content.strip():
                summary = content.strip()[:400]

            items.append(
                MediaNews(
                    title=title,
                    publish_time=publish_time,
                    publisher=publisher,
                    link=link,
                    summary=summary,
                )
            )
            if len(items) >= max_results:
                return

    def _get_notice_items(
        self,
        symbol: str,
        lower_bound: Optional[datetime],
        cutoff: Optional[datetime],
        max_results: int,
        dedup: Set[Tuple[str, str]],
    ) -> List[MediaNews]:
        if cutoff is None:
            return []
        if lower_bound is None:
            lower_bound = cutoff - timedelta(days=self.lookback_days - 1)

        collected: List[MediaNews] = []
        current_date = cutoff.date()
        start_date = lower_bound.date()
        while current_date >= start_date:
            date_key = current_date.strftime("%Y%m%d")
            rows = self._get_notice_rows_for_date(date_key=date_key)
            for row in rows:
                if row.get("code") != symbol:
                    continue

                publish_time = row.get("publish_time", "")
                publish_dt = self._parse_datetime(publish_time)
                if publish_dt is None:
                    continue
                publish_dt_cn = self._to_cn_tz(publish_dt)
                if publish_dt_cn > cutoff or publish_dt_cn < lower_bound:
                    continue

                title = row.get("title", "").strip()
                notice_type = row.get("notice_type", "").strip()
                if not title:
                    continue
                if self.notice_high_signal_only and not self._is_high_signal_notice(title=title, notice_type=notice_type):
                    continue

                link = row.get("link")
                link = link if isinstance(link, str) and link.startswith(("http://", "https://")) else None
                if not self._register_dedup(dedup=dedup, title=title, link=link):
                    continue

                summary_parts: List[str] = []
                if notice_type:
                    summary_parts.append(f"公告类型: {notice_type}")
                name = row.get("name", "").strip()
                if name:
                    summary_parts.append(f"公司: {name}")

                collected.append(
                    MediaNews(
                        title=title,
                        publish_time=publish_time,
                        publisher="Eastmoney公告",
                        link=link,
                        summary=" | ".join(summary_parts) if summary_parts else None,
                    )
                )
                if len(collected) >= max_results:
                    return collected
            current_date -= timedelta(days=1)
        return collected

    def _get_notice_rows_for_date(self, date_key: str) -> List[Dict[str, str]]:
        cache_key = (self.notice_symbol, date_key)
        cached = self._notice_cache_get(cache_key)
        if cached is not None:
            return cached

        df = self._request_notice_with_retry(date_key=date_key)
        if df is None or df.empty:
            self._notice_cache_set(cache_key, [])
            return []

        code_col = "代码" if "代码" in df.columns else ("证券代码" if "证券代码" in df.columns else "stock_code")
        title_col = "公告标题" if "公告标题" in df.columns else "title"
        date_col = "公告日期" if "公告日期" in df.columns else "date"
        type_col = "公告类型" if "公告类型" in df.columns else "type"
        link_col = "网址" if "网址" in df.columns else "url"
        name_col = "名称" if "名称" in df.columns else "name"

        rows: List[Dict[str, str]] = []
        for _, row in df.iterrows():
            code_raw = row.get(code_col, "")
            code_match = re.search(r"(\d{6})", str(code_raw))
            if not code_match:
                continue

            title = str(row.get(title_col, "")).strip()
            if not title:
                continue

            publish_time = self._normalize_publish_time(row.get(date_col), trading_date=None)
            rows.append(
                {
                    "code": code_match.group(1),
                    "title": title,
                    "publish_time": publish_time,
                    "notice_type": str(row.get(type_col, "")).strip(),
                    "link": str(row.get(link_col, "")).strip(),
                    "name": str(row.get(name_col, "")).strip(),
                }
            )

        self._notice_cache_set(cache_key, rows)
        return self._clone_notice_rows(rows)

    def _request_notice_with_retry(self, date_key: str):
        attempt = 0
        while True:
            try:
                self._prepare_pandas_string_backend()
                return ak.stock_notice_report(symbol=self.notice_symbol, date=date_key)
            except Exception:
                if attempt >= self.max_retries:
                    raise
                self._sleep_before_retry(attempt)
                attempt += 1

    def _request_with_retry(self, symbol: str):
        attempt = 0
        while True:
            try:
                self._prepare_pandas_string_backend()
                return ak.stock_news_em(symbol=symbol)
            except Exception:
                if attempt >= self.max_retries:
                    raise
                self._sleep_before_retry(attempt)
                attempt += 1

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * (2 ** attempt))

    def _build_cache_key(
        self,
        symbol: str,
        trading_date: Optional[datetime],
        max_results: int,
    ) -> Tuple[str, str, int, str]:
        date_key = ""
        if trading_date is not None:
            date_key = trading_date.strftime("%Y-%m-%d") if hasattr(trading_date, "strftime") else str(trading_date)
        return symbol, date_key, max_results, self._cache_config_signature()

    def _cache_get(self, key: Tuple[str, str, int, str]) -> Optional[List[MediaNews]]:
        if not self.cache_enabled:
            return None
        with self._cache_lock:
            cached = self._news_cache.get(key)
            if cached is None:
                return None
            return self._clone_news_list(cached)

    def _cache_source_get(self, key: Tuple[str, str, int, str]) -> str:
        if not self.cache_enabled:
            return "memory_cache"
        with self._cache_lock:
            return self._cache_source.get(key, "memory_cache")

    def _cache_set(self, key: Tuple[str, str, int, str], news_items: List[MediaNews], source: str = "network:akshare") -> None:
        if not self.cache_enabled:
            return
        with self._cache_lock:
            if key not in self._news_cache:
                self._cache_order.append(key)
            self._news_cache[key] = self._clone_news_list(news_items)
            self._cache_source[key] = source
            while len(self._cache_order) > self.cache_max_entries:
                evict = self._cache_order.pop(0)
                self._news_cache.pop(evict, None)
                self._cache_source.pop(evict, None)

    def _snapshot_enabled(self) -> bool:
        return self.snapshot_mode in {"prefer_local", "refresh", "local_only"}

    def _load_snapshot(self, key: Tuple[str, str, int, str]) -> Tuple[Optional[List[MediaNews]], str]:
        if not self._snapshot_enabled():
            return None, ""
        if self.snapshot_mode == "refresh":
            return None, ""

        path = self._snapshot_path(key)
        if not path.exists():
            return None, ""

        with self._snapshot_lock:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None, ""

        items = payload.get("items")
        if not isinstance(items, list):
            return None, ""

        source = "unknown"
        meta = payload.get("meta")
        if isinstance(meta, dict):
            raw_source = meta.get("source")
            if isinstance(raw_source, str) and raw_source.strip():
                source = raw_source.strip().lower()

        news_items: List[MediaNews] = []
        for item in items:
            try:
                news_items.append(MediaNews.model_validate(item))
            except Exception:
                continue
        return news_items, source

    def _save_snapshot(
        self,
        key: Tuple[str, str, int, str],
        news_items: List[MediaNews],
        source: str = "network:akshare",
    ) -> None:
        if not self._snapshot_enabled():
            return
        if self.snapshot_mode == "local_only":
            return

        path = self._snapshot_path(key)
        payload = {
            "key": {
                "ticker": key[0],
                "date": key[1],
                "limit": key[2],
                "config": key[3],
            },
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "meta": {
                "source": source,
            },
            "items": [item.model_dump() for item in news_items],
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with self._snapshot_lock:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(path)

    def _snapshot_path(self, key: Tuple[str, str, int, str]) -> Path:
        symbol, date_key, max_results, config_sig = key
        safe_symbol = self._safe_filename(symbol or "unknown")
        safe_date = self._safe_filename(date_key or "latest")
        safe_config = self._safe_filename(config_sig)
        digest = hashlib.sha1("|".join(map(str, key)).encode("utf-8")).hexdigest()[:12]
        filename = f"{safe_symbol}_{max_results}_{digest}.json"
        return self.snapshot_dir / safe_date / safe_config / filename

    def _cache_config_signature(self) -> str:
        return "|".join(
            [
                str(self.lookback_days),
                "notice_on" if self.notice_enabled else "notice_off",
                "high_signal_only" if self.notice_high_signal_only else "all_notice",
                self.notice_symbol,
            ]
        )

    def _notice_cache_get(self, key: Tuple[str, str]) -> Optional[List[Dict[str, str]]]:
        if not self.notice_cache_enabled:
            return None
        with self._notice_lock:
            cached = self._notice_cache.get(key)
            if cached is None:
                return None
            return self._clone_notice_rows(cached)

    def _notice_cache_set(self, key: Tuple[str, str], rows: List[Dict[str, str]]) -> None:
        if not self.notice_cache_enabled:
            return
        with self._notice_lock:
            if key not in self._notice_cache:
                self._notice_order.append(key)
            self._notice_cache[key] = self._clone_notice_rows(rows)
            while len(self._notice_order) > self.notice_cache_max_entries:
                evict = self._notice_order.pop(0)
                self._notice_cache.pop(evict, None)

    @staticmethod
    def _clone_news_list(news_items: List[MediaNews]) -> List[MediaNews]:
        return [item.model_copy(deep=True) for item in news_items]

    @staticmethod
    def _clone_notice_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        return [dict(item) for item in rows]

    @staticmethod
    def _normalize_symbol(ticker: Optional[str]) -> str:
        if not ticker:
            return ""
        raw = str(ticker).strip().upper()
        m = re.search(r"(\d{6})", raw)
        if m:
            return m.group(1)
        return raw

    @staticmethod
    def _normalize_publish_time(value, trading_date: Optional[datetime]) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=AKShareNewsAPI.CN_TZ).isoformat()
        if isinstance(value, str) and value.strip():
            return value.strip()
        if trading_date is not None:
            return trading_date.isoformat()
        return datetime.utcnow().isoformat()

    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if not isinstance(value, str):
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            try:
                return datetime.strptime(normalized[:10], "%Y-%m-%d")
            except ValueError:
                return None

    @classmethod
    def _to_cn_tz(cls, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=cls.CN_TZ)
        return dt.astimezone(cls.CN_TZ)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip().lower()

    def _register_dedup(self, dedup: Set[Tuple[str, str]], title: str, link: Optional[str]) -> bool:
        dedup_key = (self._normalize_text(title), self._normalize_text(link or ""))
        if dedup_key in dedup:
            return False
        dedup.add(dedup_key)
        return True

    def _is_high_signal_notice(self, title: str, notice_type: str) -> bool:
        text = f"{title} {notice_type}".strip()
        high = any(keyword in text for keyword in self._NOTICE_HIGH_SIGNAL_KEYWORDS)
        low = any(keyword in text for keyword in self._NOTICE_LOW_SIGNAL_KEYWORDS)
        return high and not low

    @staticmethod
    def _prepare_pandas_string_backend() -> None:
        """
        AKShare stock_news_em uses '\\u3000' regex replacement.
        PyArrow regex backend rejects '\\u' escapes, so force python storage.
        """
        if pd is None:
            return
        try:
            pd.options.mode.string_storage = "python"
        except Exception:
            return

    @staticmethod
    def _get_bool_env(name: str, default: bool) -> bool:
        raw = os.getenv(name, "")
        if not raw.strip():
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(min_value, min(max_value, value))

    @staticmethod
    def _get_float_env(name: str, default: float, min_value: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return max(min_value, value)

    @staticmethod
    def _safe_filename(text: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
        return cleaned[:80] if cleaned else "item"

    @staticmethod
    def _get_snapshot_mode() -> str:
        raw = os.getenv("AKSHARE_NEWS_SNAPSHOT_MODE", "prefer_local").strip().lower()
        if raw in {"off", "prefer_local", "refresh", "local_only"}:
            return raw
        return "prefer_local"

    @staticmethod
    def _get_snapshot_dir() -> Path:
        raw = os.getenv("AKSHARE_NEWS_SNAPSHOT_DIR", "data/cache/akshare_news")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
