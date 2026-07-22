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
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

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
        self._last_request_ts = 0.0

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

    def _request_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET with throttling and backoff on transient SEC rejections."""
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self._throttle()
            self._last_request_ts = time.monotonic()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                time.sleep(2 ** attempt)
                continue

            if response.status_code in (429, 503):
                last_error = requests.exceptions.HTTPError(
                    f"SEC EDGAR throttled request ({response.status_code})", response=response
                )
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
                     params: Optional[Dict[str, Any]] = None) -> Any:
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < ttl:
                return hit[1]

        data = self._request_json(url, params=params)
        with self._cache_lock:
            self._cache[cache_key] = (now, data)
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
        )

        recent = data.get("filings", {}).get("recent", {})
        form_list = recent.get("form", [])
        date_list = recent.get("filingDate", [])
        accession_list = recent.get("accessionNo", [])
        primary_docs = recent.get("primaryDocument", [])

        results: list[InstitutionalFiling] = []
        for i, form in enumerate(form_list):
            if form not in forms:
                continue
            filing_date = date_list[i] if i < len(date_list) else ""
            if trading_date and filing_date:
                parsed = self._parse_date(filing_date)
                if parsed and parsed > trading_date:
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
        end = trading_date or datetime.now()
        start = end - timedelta(days=days_back)
        params = {
            "q": ticker,
            "forms": "4",
            "dateRange": "custom",
            "startdt": start.strftime("%Y-%m-%d"),
            "enddt": end.strftime("%Y-%m-%d"),
        }
        data = self._cached_json(
            cache_key=f"form4:{ticker}:{params['startdt']}:{params['enddt']}",
            ttl=self.SEARCH_CACHE_TTL,
            url=self.FULL_TEXT_SEARCH_URL,
            params=params,
        )

        hits = data.get("hits", {}).get("hits", [])
        results: list[InsiderFiling] = []
        for hit in hits[:limit]:
            source = hit.get("_source", {})
            ciks = source.get("ciks") or []
            cik = str(ciks[0]) if ciks else None
            accession = source.get("adsh")
            results.append(InsiderFiling(
                ticker=ticker,
                cik=cik,
                filer_names=list(source.get("display_names") or []),
                form=str(source.get("file_type") or "4"),
                filing_date=source.get("file_date"),
                accession_no=accession,
                filing_url=self._build_filing_url(cik, accession) if cik else None,
            ))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filing_url(cik: Optional[str], accession_no: Optional[str]) -> Optional[str]:
        if not cik or not accession_no:
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
