"""SEC EDGAR API client implementation.

Free public endpoints, no API key required:
- Submissions (13F and other filings): https://data.sec.gov/submissions/CIK{cik}.json
- Full-text search (Form 4): https://efts.sec.gov/LATEST/search-index

SEC fair-access policy requires a User-Agent header with contact info
("AppName/1.0 (email@example.com)") and at most 10 requests per second.
Docs: https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import os
import threading
import time
import warnings
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

from apis.alt_snapshot import SnapshotStore
from .api_model import InstitutionalFiling, InsiderFiling

# Well-known institution CIKs for convenience lookups.
KNOWN_INSTITUTIONS: Dict[str, str] = {
    "berkshire_hathaway": "0001067983",
    "bridgewater": "0001354735",
    "blackrock": "0001364742",
    "renaissance_technologies": "0001037389",
    "soros_fund_management": "0001038659",
    "tiger_global": "0001395347",
    "pershing_square": "0001106357",
    "appaloosa": "0001004068",
}


class SECEdgarAPI:
    """SEC EDGAR wrapper for institutional (13F) and insider (Form 4) filings."""

    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
    ARCHIVE_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh_nodash}/{adsh}-index.htm"

    # Class-level cache shared across instances (submissions update slowly).
    _cache: Dict[str, tuple[float, Any]] = {}
    _cache_lock = threading.Lock()
    MAX_CACHE_ENTRIES = 256

    # Class-level throttle: analysts construct fresh Router/API instances per
    # call and run concurrently, so per-instance state cannot enforce SEC's
    # fair-access limit. Sleeping under the lock serializes bursts.
    _throttle_lock = threading.Lock()
    _last_request_ts = 0.0

    SUBMISSIONS_CACHE_TTL = 24 * 3600.0
    SEARCH_CACHE_TTL = 3600.0

    def __init__(self):
        self.user_agent = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
        if not self.user_agent:
            raise ValueError(
                "SEC_EDGAR_USER_AGENT is not set. SEC requires a User-Agent with "
                "contact info, e.g. 'QuantArena/0.1 (you@example.com)'"
            )

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.timeout = 15
        # Stay well below SEC's 10 req/s fair-access limit.
        self.min_request_interval = float(os.environ.get("SEC_EDGAR_MIN_INTERVAL", "0.15"))
        self.max_retries = 3
        # Date-partitioned snapshots (SEC_EDGAR_SNAPSHOT_MODE, default off)
        # enable offline replay of submissions and full-text search results.
        self.snapshots = SnapshotStore("SEC_EDGAR", "data/cache/sec_edgar")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        with SECEdgarAPI._throttle_lock:
            elapsed = time.monotonic() - SECEdgarAPI._last_request_ts
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            SECEdgarAPI._last_request_ts = time.monotonic()

    def _request_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET with throttling and backoff on transient SEC rejections."""
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

            if response.status_code in (429, 503):
                last_error = requests.exceptions.HTTPError(
                    f"SEC EDGAR throttled request ({response.status_code})", response=response
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid JSON from SEC EDGAR {url}: {response.text[:200]}"
                ) from exc

        raise RuntimeError(f"SEC EDGAR request failed after {self.max_retries} attempts: {last_error}")

    def _cached_json(self, cache_key: str, ttl: float, url: str,
                     params: Optional[Dict[str, Any]] = None,
                     as_of: Optional[datetime] = None) -> Any:
        # Key families ("submissions:{cik}", "form4:{sym}:{start}:{end}") are
        # structurally disjoint, so this simple mapping cannot collide.
        snapshot_key = cache_key.replace(":", "/")
        mode = self.snapshots.mode

        # Replay: serve the snapshot captured at (or just before) as_of.
        if mode == "local_only":
            payload = self.snapshots.load_nearest(snapshot_key, as_of)
            if payload is None:
                raise FileNotFoundError(
                    f"SEC EDGAR snapshot not found for {snapshot_key} as of {as_of or 'today'}"
                )
            return payload

        if mode == "prefer_local":
            payload = self.snapshots.load_exact(snapshot_key, as_of)
            if payload is not None:
                return payload

        saving = mode in {"prefer_local", "refresh"}
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < ttl:
                # A warm TTL cache (24h for submissions) must not skip daily
                # capture: backfill today's snapshot if it does not exist yet.
                if saving and not self.snapshots.has_for_day(snapshot_key):
                    self.snapshots.save(snapshot_key, hit[1])
                return hit[1]

        data = self._request_json(url, params=params)
        with self._cache_lock:
            while len(self._cache) >= self.MAX_CACHE_ENTRIES:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = (now, data)
        if saving:
            self.snapshots.save(snapshot_key, data)
        return data

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_cik(cik: str) -> str:
        """Zero-pad a CIK to the 10 digits SEC endpoints expect."""
        digits = str(cik).strip().lstrip("0") or "0"
        if not digits.isdigit():
            raise ValueError(f"Invalid CIK: {cik!r}")
        return digits.zfill(10)

    @classmethod
    def resolve_institution_cik(cls, name_or_cik: str) -> str:
        """Resolve a known institution alias or raw CIK to a normalized CIK."""
        key = name_or_cik.strip().lower().replace(" ", "_")
        if key in KNOWN_INSTITUTIONS:
            return KNOWN_INSTITUTIONS[key]
        return cls.normalize_cik(name_or_cik)

    def get_institutional_filings(
        self,
        cik: str,
        forms: tuple[str, ...] = ("13F-HR",),
        trading_date: Optional[datetime] = None,
        limit: int = 10,
    ) -> list[InstitutionalFiling]:
        """Get recent filings of the given forms for an institution.

        Args:
            cik: Institution CIK or a known alias (e.g. 'berkshire_hathaway').
            forms: Form types to keep (default 13F-HR holdings reports).
            trading_date: Only include filings on or before this date, so
                backtests never see filings from the future.
            limit: Maximum number of filings to return.
        """
        norm_cik = self.resolve_institution_cik(cik)
        data = self._cached_json(
            cache_key=f"submissions:{norm_cik}",
            ttl=self.SUBMISSIONS_CACHE_TTL,
            url=self.SUBMISSIONS_URL.format(cik=norm_cik),
            as_of=trading_date,
        )

        recent = (data.get("filings") or {}).get("recent") or {}
        form_list = recent.get("form", [])
        date_list = recent.get("filingDate", [])
        accession_list = recent.get("accessionNo", [])
        primary_docs = recent.get("primaryDocument", [])

        # The submissions endpoint only exposes the ~1000 most recent filings;
        # a trading_date older than that window would silently return nothing.
        if trading_date and date_list:
            oldest = self._parse_date(date_list[-1])
            if oldest and oldest >= trading_date:
                warnings.warn(
                    f"SEC EDGAR recent-filings window for CIK {norm_cik} starts at "
                    f"{date_list[-1]}, after trading_date {trading_date:%Y-%m-%d}; "
                    "older 13F history is not fetched and results may be incomplete.",
                    RuntimeWarning,
                    stacklevel=2,
                )

        results: list[InstitutionalFiling] = []
        for i, form in enumerate(form_list):
            if form not in forms:
                continue
            filing_date = date_list[i] if i < len(date_list) else ""
            if trading_date:
                # Strictly-before semantics matching the AlphaVantage insider
                # filter; unparseable dates fail closed to avoid lookahead.
                parsed = self._parse_date(filing_date) if filing_date else None
                if parsed is None or parsed >= trading_date:
                    continue
            accession = accession_list[i] if i < len(accession_list) else ""
            results.append(InstitutionalFiling(
                cik=norm_cik,
                form=form,
                filing_date=filing_date,
                accession_no=accession,
                primary_document=primary_docs[i] if i < len(primary_docs) else None,
                filing_url=self._build_filing_url(norm_cik, accession),
            ))
            if len(results) >= limit:
                break
        return results

    def get_insider_filings(
        self,
        ticker: str,
        trading_date: Optional[datetime] = None,
        days_back: int = 45,
        limit: int = 20,
    ) -> list[InsiderFiling]:
        """Search recent Form 4 insider filings mentioning a ticker.

        Args:
            ticker: Stock ticker symbol used as the full-text query.
            trading_date: End of the search window (defaults to now) so
                backtests never see filings from the future.
            days_back: Search window length in days.
            limit: Maximum number of filings to return.
        """
        symbol = ticker.strip().upper()
        end = trading_date or datetime.now()
        start = end - timedelta(days=days_back)
        params = {
            # Quoted phrase: an unquoted short token ("A", "ALL") full-text
            # matches unrelated issuers' documents.
            "q": f'"{symbol}"',
            "forms": "4",
            "dateRange": "custom",
            "startdt": start.strftime("%Y-%m-%d"),
            "enddt": end.strftime("%Y-%m-%d"),
        }
        data = self._cached_json(
            cache_key=f"form4:{symbol}:{params['startdt']}:{params['enddt']}",
            ttl=self.SEARCH_CACHE_TTL,
            url=self.FULL_TEXT_SEARCH_URL,
            params=params,
            as_of=trading_date,
        )

        hits = data.get("hits", {}).get("hits", [])
        issuer_marker = f"({symbol})"
        candidates: list[tuple[datetime, InsiderFiling]] = []
        for hit in hits:
            source = hit.get("_source", {})
            display_names = list(source.get("display_names") or [])
            # Full-text hits can come from any document mentioning the token;
            # keep only filings whose issuer line carries the "(TICKER)" tag.
            if not any(issuer_marker in name for name in display_names):
                continue

            filing_date = source.get("file_date")
            parsed = self._parse_date(filing_date) if filing_date else None
            if trading_date and (parsed is None or parsed >= trading_date):
                continue  # strictly-before, fail closed on unparseable dates

            ciks = source.get("ciks") or []
            cik = str(ciks[0]) if ciks else None
            accession = source.get("adsh")
            candidates.append((
                parsed or datetime.min,
                InsiderFiling(
                    ticker=symbol,
                    cik=cik,
                    filer_names=display_names,
                    form=str(source.get("file_type") or "4"),
                    filing_date=filing_date,
                    accession_no=accession,
                    filing_url=self._build_filing_url(cik, accession) if cik else None,
                ),
            ))

        # EDGAR full-text search ranks by relevance, not recency.
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [filing for _, filing in candidates[:limit]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filing_url(cik: Optional[str], accession_no: Optional[str]) -> Optional[str]:
        if not cik or not accession_no or not str(cik).strip().isdigit():
            return None
        return SECEdgarAPI.ARCHIVE_INDEX_URL.format(
            cik=str(int(cik)),
            adsh_nodash=accession_no.replace("-", ""),
            adsh=accession_no,
        )

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        try:
            return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
        except ValueError:
            return None
