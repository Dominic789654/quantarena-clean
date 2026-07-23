"""ApeWisdom API client implementation.

Free public API for Reddit retail-sentiment mention rankings
(r/wallstreetbets and other communities). No API key required.
Link: https://apewisdom.io/api/

The upstream data is crawler-based and refreshes on the order of minutes,
so responses are cached and requests are throttled to about 1 req/s.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, Optional, Union

import requests

from apis.alt_snapshot import SnapshotStore
from .api_model import SocialMention

AsOf = Union[date, datetime, None]

# Community filters documented by ApeWisdom.
VALID_FILTERS = {
    "all", "all-stocks", "all-crypto",
    "wallstreetbets", "stocks", "4chan",
    "CryptoCurrency", "CryptoCurrencies", "Bitcoin",
    "SatoshiStreetBets", "CryptoMoonShots",
}


class ApeWisdomAPI:
    """ApeWisdom API wrapper for Reddit mention rankings."""

    BASE_URL = "https://apewisdom.io/api/v1.0"

    # Class-level cache shared across instances.
    _cache: Dict[str, tuple[float, Any]] = {}
    _cache_lock = threading.Lock()
    MAX_CACHE_ENTRIES = 256

    # Class-level throttle: callers construct fresh instances per analyst
    # call, so per-instance state cannot enforce the request interval.
    _throttle_lock = threading.Lock()
    _last_request_ts = 0.0

    CACHE_TTL = 300.0  # WSB mention counts move on a ~5 minute cadence

    def __init__(self):
        self.session = requests.Session()
        self.timeout = 15
        self.min_request_interval = float(os.environ.get("APEWISDOM_MIN_INTERVAL", "1.0"))
        self.max_retries = 3
        # Date-partitioned snapshots (APEWISDOM_SNAPSHOT_MODE, default off)
        # enable daily capture and deterministic replay of mention rankings.
        self.snapshots = SnapshotStore("APEWISDOM", "data/cache/apewisdom")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        with ApeWisdomAPI._throttle_lock:
            elapsed = time.monotonic() - ApeWisdomAPI._last_request_ts
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            ApeWisdomAPI._last_request_ts = time.monotonic()

    def _request_json(self, url: str) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

            if response.status_code in (429, 503):
                last_error = requests.exceptions.HTTPError(
                    f"ApeWisdom throttled request ({response.status_code})", response=response
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid JSON from ApeWisdom {url}: {response.text[:200]}"
                ) from exc

        raise RuntimeError(f"ApeWisdom request failed after {self.max_retries} attempts: {last_error}")

    def _cached_page(self, filter_key: str, page: int, as_of: AsOf = None) -> Dict[str, Any]:
        if filter_key not in VALID_FILTERS:
            raise ValueError(
                f"Invalid ApeWisdom filter {filter_key!r}; expected one of {sorted(VALID_FILTERS)}"
            )
        page = int(page)
        if page < 1:
            raise ValueError(f"Invalid ApeWisdom page {page}; must be >= 1")

        snapshot_key = f"{filter_key}/page_{page}"
        mode = self.snapshots.mode

        # Replay: serve the snapshot captured at (or just before) as_of.
        if mode == "local_only":
            payload = self.snapshots.load_nearest(snapshot_key, as_of)
            if payload is None:
                raise FileNotFoundError(
                    f"ApeWisdom snapshot not found for {snapshot_key} as of {as_of or 'today'}"
                )
            return payload

        # Day-grain determinism: prefer a snapshot for the requested day.
        if mode == "prefer_local":
            payload = self.snapshots.load_exact(snapshot_key, as_of)
            if payload is not None:
                return payload

        cache_key = f"{filter_key}:{page}"
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < self.CACHE_TTL:
                return hit[1]

        data = self._request_json(f"{self.BASE_URL}/filter/{filter_key}/page/{page}")
        with self._cache_lock:
            while len(self._cache) >= self.MAX_CACHE_ENTRIES:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = (now, data)
        if mode in {"prefer_local", "refresh"}:
            self.snapshots.save(snapshot_key, data)
        return data

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_trending(self, filter_key: str = "wallstreetbets",
                     page: int = 1, limit: Optional[int] = None,
                     as_of: AsOf = None) -> list[SocialMention]:
        """Get the mention ranking for a community filter (one page).

        as_of selects the snapshot date when snapshots are enabled; live
        fetches always return current data regardless of as_of.
        """
        data = self._cached_page(filter_key, page, as_of=as_of)
        mentions = [self._parse_result(row) for row in data.get("results", [])]
        mentions = [m for m in mentions if m is not None]
        return mentions[:limit] if limit is not None else mentions

    def get_ticker_mentions(self, ticker: str, filter_key: str = "wallstreetbets",
                            max_pages: int = 3, as_of: AsOf = None) -> Optional[SocialMention]:
        """Find one ticker's mention stats, scanning up to max_pages pages."""
        symbol = ticker.strip().upper()
        for page in range(1, max_pages + 1):
            data = self._cached_page(filter_key, page, as_of=as_of)
            for row in data.get("results", []):
                if str(row.get("ticker", "")).upper() == symbol:
                    return self._parse_result(row)
            total_pages = self._to_optional_int(
                data.get("pages", data.get("total_pages"))
            )
            if page >= (total_pages if total_pages is not None else page):
                break
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_result(row: Dict[str, Any]) -> Optional[SocialMention]:
        try:
            return SocialMention(
                rank=int(row["rank"]),
                ticker=str(row["ticker"]).upper(),
                name=row.get("name"),
                mentions=int(row.get("mentions") or 0),
                upvotes=int(row.get("upvotes") or 0),
                rank_24h_ago=ApeWisdomAPI._to_optional_int(row.get("rank_24h_ago")),
                mentions_24h_ago=ApeWisdomAPI._to_optional_int(row.get("mentions_24h_ago")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _to_optional_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
