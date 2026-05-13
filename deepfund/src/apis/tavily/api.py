"""Tavily news API wrapper for company news analysis."""

from __future__ import annotations

import os
import time
import threading
import json
import hashlib
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from apis.common_model import MediaNews


class TavilyNewsAPI:
    """Wrapper around Tavily search API focused on financial news retrieval."""

    BASE_URL = "https://api.tavily.com/search"
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    _cache_lock = threading.Lock()
    _news_cache: Dict[Tuple[str, str, str, str, int], List[MediaNews]] = {}
    _cache_order: List[Tuple[str, str, str, str, int]] = []
    _cache_source: Dict[Tuple[str, str, str, str, int], str] = {}
    _snapshot_lock = threading.Lock()

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or os.getenv("TAVILY_API_KEY", "")).strip()
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY is not configured")
        self._session = requests.Session()
        self.last_cache_hit = False
        self.last_source = "network:tavily"
        self.cache_enabled = self._get_bool_env("TAVILY_NEWS_CACHE_ENABLED", True)
        self.cache_max_entries = self._get_int_env("TAVILY_NEWS_CACHE_MAX_ENTRIES", 1024, min_value=1, max_value=10000)
        self.connect_timeout = self._get_float_env("TAVILY_CONNECT_TIMEOUT_SECONDS", 3.0, min_value=0.1)
        self.read_timeout = self._get_float_env("TAVILY_READ_TIMEOUT_SECONDS", 8.0, min_value=0.1)
        self.max_retries = self._get_int_env("TAVILY_MAX_RETRIES", 1, min_value=0, max_value=5)
        self.retry_backoff_seconds = self._get_float_env("TAVILY_RETRY_BACKOFF_SECONDS", 0.4, min_value=0.0)
        self.snapshot_mode = self._get_snapshot_mode()
        self.snapshot_dir = self._get_snapshot_dir()

    def get_news(
        self,
        ticker: Optional[str] = None,
        topic: Optional[str] = None,
        trading_date: Optional[datetime] = None,
        limit: Optional[int] = None,
        market: str = "us",
    ) -> List[MediaNews]:
        """
        Search recent financial news and normalize into MediaNews objects.

        Notes:
        - Tavily results may not always include publish timestamps.
        - When publish timestamps are missing, we fallback to trading_date for stability.
        """
        max_results = max(1, min(limit or 10, 20))
        query = self._build_query(ticker=ticker, topic=topic, market=market)
        cache_key = self._build_cache_key(
            ticker=ticker,
            topic=topic,
            market=market,
            trading_date=trading_date,
            max_results=max_results,
        )

        cached_news = self._cache_get(cache_key)
        if cached_news is not None:
            self.last_cache_hit = True
            return cached_news
        self.last_cache_hit = False

        snapshot_news, snapshot_source = self._load_snapshot(cache_key)
        if snapshot_news is not None:
            self.last_cache_hit = True
            self.last_source = f"snapshot:{snapshot_source}"
            self._cache_set(cache_key, snapshot_news, source=self.last_source)
            return snapshot_news

        if self.snapshot_mode == "local_only":
            raise FileNotFoundError(f"Tavily news snapshot not found for key={cache_key}")

        response = self._request_with_retry(
            payload={
                "api_key": self.api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_raw_content": False,
                "include_images": False,
            }
        )
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results", [])
        news_items: List[MediaNews] = []
        cutoff = trading_date.replace(hour=23, minute=59, second=59, microsecond=999999) if trading_date else None

        for item in results:
            publish_time = self._extract_publish_time(item, trading_date)
            publish_dt = self._parse_datetime(publish_time)

            # Avoid accidental forward-looking data in backtest mode.
            if cutoff and publish_dt:
                compare_cutoff = cutoff
                if publish_dt.tzinfo is not None and compare_cutoff.tzinfo is None:
                    compare_cutoff = compare_cutoff.replace(tzinfo=timezone.utc)
                if publish_dt > compare_cutoff:
                    continue

            url = item.get("url")
            content = item.get("content") or item.get("raw_content") or ""
            news_items.append(
                MediaNews(
                    title=(item.get("title") or "Untitled").strip(),
                    publish_time=publish_time,
                    publisher=self._extract_publisher(item, url),
                    link=url,
                    summary=content[:400] if content else None,
                )
            )

        normalized = news_items[:max_results]
        self.last_source = "network:tavily"
        self._save_snapshot(cache_key, normalized, source="tavily_api")
        self._cache_set(cache_key, normalized, source=self.last_source)
        return normalized

    def _request_with_retry(self, payload: Dict[str, Any]) -> requests.Response:
        attempt = 0
        while True:
            try:
                response = self._session.post(
                    self.BASE_URL,
                    json=payload,
                    timeout=(self.connect_timeout, self.read_timeout),
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt >= self.max_retries:
                    raise
                self._sleep_before_retry(attempt)
                attempt += 1
                continue

            if response.status_code in self.RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                self._sleep_before_retry(attempt)
                attempt += 1
                continue

            return response

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * (2 ** attempt))

    def _build_cache_key(
        self,
        ticker: Optional[str],
        topic: Optional[str],
        market: str,
        trading_date: Optional[datetime],
        max_results: int,
    ) -> Tuple[str, str, str, str, int]:
        if trading_date is None:
            date_key = ""
        else:
            date_key = trading_date.strftime("%Y-%m-%d") if hasattr(trading_date, "strftime") else str(trading_date)
        return (
            (ticker or "").strip(),
            (topic or "").strip(),
            market.lower().strip(),
            date_key,
            max_results,
        )

    def _cache_get(self, key: Tuple[str, str, str, str, int]) -> Optional[List[MediaNews]]:
        if not self.cache_enabled:
            return None
        with self._cache_lock:
            cached = self._news_cache.get(key)
            if cached is None:
                return None
            self.last_source = self._cache_source.get(key, "memory_cache")
            return self._clone_news_list(cached)

    def _cache_set(self, key: Tuple[str, str, str, str, int], news_items: List[MediaNews], source: str = "memory_cache") -> None:
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

    def _load_snapshot(self, key: Tuple[str, str, str, str, int]) -> Tuple[Optional[List[MediaNews]], str]:
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

    def _save_snapshot(self, key: Tuple[str, str, str, str, int], news_items: List[MediaNews], source: str = "tavily_api") -> None:
        if not self._snapshot_enabled():
            return
        if self.snapshot_mode == "local_only":
            return

        path = self._snapshot_path(key)
        payload = {
            "key": {
                "ticker": key[0],
                "topic": key[1],
                "market": key[2],
                "date": key[3],
                "limit": key[4],
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

    def _snapshot_path(self, key: Tuple[str, str, str, str, int]) -> Path:
        ticker, topic, market, date_key, max_results = key
        identifier = ticker or topic or "news"
        safe_id = self._safe_filename(identifier)
        safe_market = self._safe_filename(market or "unknown")
        safe_date = self._safe_filename(date_key or "latest")
        digest = hashlib.sha1("|".join(map(str, key)).encode("utf-8")).hexdigest()[:12]
        filename = f"{safe_id}_{max_results}_{digest}.json"
        return self.snapshot_dir / safe_market / safe_date / filename

    @staticmethod
    def _clone_news_list(news_items: List[MediaNews]) -> List[MediaNews]:
        # Defensive copy so callers do not mutate cache content by accident.
        cloned: List[MediaNews] = []
        for item in news_items:
            if hasattr(item, "model_copy"):
                cloned.append(item.model_copy(deep=True))
            else:
                cloned.append(deepcopy(item))
        return cloned

    @staticmethod
    def _build_query(
        ticker: Optional[str],
        topic: Optional[str],
        market: str,
    ) -> str:
        if topic:
            return f"{topic} financial market news"
        if not ticker:
            return "stock market company news"

        if market.lower() == "cn":
            return f"{ticker} A-share company news 财经 新闻"
        return f"{ticker} stock company news earnings guidance"

    @staticmethod
    def _extract_publish_time(item: Dict[str, Any], trading_date: Optional[datetime]) -> str:
        for field in ("published_date", "published_time", "publish_time", "date"):
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if trading_date:
            return trading_date.isoformat()
        return datetime.utcnow().isoformat()

    @staticmethod
    def _extract_publisher(item: Dict[str, Any], url: Optional[str]) -> str:
        source = item.get("source")
        if isinstance(source, str) and source.strip():
            return source.strip()

        if url:
            netloc = urlparse(url).netloc
            if netloc:
                return netloc
        return "Tavily"

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            # Best effort for date-only strings.
            try:
                return datetime.strptime(normalized[:10], "%Y-%m-%d")
            except ValueError:
                return None

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
        raw = os.getenv("TAVILY_NEWS_SNAPSHOT_MODE", "prefer_local").strip().lower()
        if raw in {"off", "prefer_local", "refresh", "local_only"}:
            return raw
        return "prefer_local"

    @staticmethod
    def _get_snapshot_dir() -> Path:
        raw = os.getenv("TAVILY_NEWS_SNAPSHOT_DIR", "data/cache/tavily_news")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
