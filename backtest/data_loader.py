"""
Data Prefetcher for Backtesting
================================

Handles batch data fetching with caching for efficient backtesting.
Uses provider-aware routing:
- CN market defaults to Tushare
- US market resolves to Alpha Vantage or FMP
"""

import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from shared.utils.path_manager import setup_paths

setup_paths()

from apis.router import APISource, Router, build_api_source_config, resolve_api_source
from backtest.providers import DailyCandleProvider, NewsProvider, ProviderFailure


class DataPrefetcher:
    """Data prefetcher for backtesting with cache-backed market data access."""

    def __init__(
        self,
        db_path: str = "data/signal_flux.db",
        market: str = "cn",
        api_source_config: Optional[Dict[str, str]] = None,
        daily_candle_provider: Optional[DailyCandleProvider] = None,
        news_provider: Optional[NewsProvider] = None,
    ):
        """
        Initialize data prefetcher.

        Args:
            db_path: Path to SQLite database for caching
            market: Market type ("cn" for A-share, "us" for US stocks)
            api_source_config: Optional API source config override
            daily_candle_provider: Optional provider override for offline replay tests
            news_provider: Optional news provider override for offline replay tests
        """
        self.market = (market or "cn").lower()
        self.db_path = db_path
        self.daily_candle_provider = daily_candle_provider
        self.news_provider = news_provider
        self.api_source_config = build_api_source_config(self.market, api_source_config)
        self.api_source = (
            daily_candle_provider.name
            if daily_candle_provider is not None
            else resolve_api_source(self.market, self.api_source_config)
        )
        self._last_prefetched_tickers: List[str] = []
        self._provider_failures: List[ProviderFailure] = []

        from deepear.src.utils.database_manager import DatabaseManager

        self.db = DatabaseManager(db_path)
        self.router: Optional[Router] = None
        self.tushare_api = None

        if self.daily_candle_provider is not None:
            logger.info(
                f"DataPrefetcher initialized for {self.market} market (source={self.api_source})"
            )
            return

        try:
            self.router = Router(self.api_source)
            if self.market == "cn" and self.api_source == APISource.TUSHARE:
                self.tushare_api = self.router.api
            logger.info(
                f"DataPrefetcher initialized for {self.market} market (source={self.api_source})"
            )
        except (ValueError, ImportError) as exc:
            logger.warning(f"Failed to initialize market data router: {exc}")


    def prefetch_klines(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        force_sync: bool = False,
    ) -> Dict[str, int]:
        """Download and cache daily candle data for all tickers."""
        self._last_prefetched_tickers = list(tickers or [])
        if self.market == "us":
            return self._prefetch_us_klines(tickers, start_date, end_date, force_sync)
        return self._prefetch_cn_klines(tickers, start_date, end_date, force_sync)

    def _prefetch_cn_klines(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        force_sync: bool,
    ) -> Dict[str, int]:
        if not self.tushare_api and self.daily_candle_provider is None:
            logger.error("Tushare API not available")
            return {ticker: 0 for ticker in tickers}

        results: Dict[str, int] = {}
        total = len(tickers)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        for i, ticker in enumerate(tickers, 1):
            logger.info(f"[{i}/{total}] Fetching K-line data for {ticker}...")

            cached_df = self._get_sufficient_cached_frame(ticker, start_date, end_date, force_sync)
            if cached_df is not None:
                results[ticker] = len(cached_df)
                continue

            try:
                df = self._fetch_daily_candles(ticker, end_dt)
                normalized = self._normalize_candles_df(df)
                if normalized.empty:
                    logger.warning(f"No K-line data available for {ticker}")
                    results[ticker] = 0
                    continue

                self.db.save_stock_prices(ticker, normalized)
                results[ticker] = self._count_rows_in_range(normalized, start_date, end_date)
                logger.info(
                    f"Cached {len(normalized)} rows for {ticker}, {results[ticker]} in range (source={self.api_source})"
                )
                time.sleep(self._request_interval_seconds())
            except Exception as exc:
                failure = self._record_provider_failure(
                    operation="daily_candles",
                    exc=exc,
                    ticker=ticker,
                    date=end_date,
                )
                logger.error(f"Failed to fetch K-line: {failure.summary()}")
                results[ticker] = 0

        return results

    def _prefetch_us_klines(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        force_sync: bool,
    ) -> Dict[str, int]:
        if not self.router and self.daily_candle_provider is None:
            logger.error("US market data router not available")
            return {ticker: 0 for ticker in tickers}

        results: Dict[str, int] = {}
        total = len(tickers)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        for i, ticker in enumerate(tickers, 1):
            logger.info(f"[{i}/{total}] Fetching US K-line data for {ticker}...")

            cached_df = self._get_sufficient_cached_frame(ticker, start_date, end_date, force_sync)
            if cached_df is not None:
                results[ticker] = len(cached_df)
                continue

            try:
                df = self._fetch_daily_candles(ticker, end_dt)
                normalized = self._normalize_candles_df(df)
                if normalized.empty:
                    logger.warning(f"No US K-line data available for {ticker}")
                    results[ticker] = 0
                    continue

                self.db.save_stock_prices(ticker, normalized)
                results[ticker] = self._count_rows_in_range(normalized, start_date, end_date)
                logger.info(
                    f"Cached {len(normalized)} rows for {ticker}, {results[ticker]} in range (source={self.api_source})"
                )
                time.sleep(self._request_interval_seconds())
            except Exception as exc:
                failure = self._record_provider_failure(
                    operation="daily_candles",
                    exc=exc,
                    ticker=ticker,
                    date=end_date,
                )
                logger.error(f"Failed to fetch US K-line: {failure.summary()}")
                results[ticker] = 0

        return results

    def _get_sufficient_cached_frame(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        force_sync: bool,
    ) -> Optional[pd.DataFrame]:
        if force_sync:
            return None

        cached_df = self.db.get_stock_prices(ticker, start_date, end_date)
        if cached_df.empty:
            return None

        expected_days = self._estimate_trading_days(start_date, end_date)
        if len(cached_df) >= expected_days * 0.8:
            logger.info(f"Cache hit for {ticker} ({len(cached_df)} rows)")
            return cached_df

        logger.info(f"Partial cache for {ticker}, fetching from source={self.api_source}...")
        return None

    def _normalize_candles_df(self, df: Optional[pd.DataFrame]) -> pd.DataFrame:
        """Normalize provider candles into database-ready schema."""
        required_cols = ["date", "open", "close", "high", "low", "volume", "change_pct"]
        if df is None or df.empty:
            return pd.DataFrame(columns=required_cols)

        normalized = df.reset_index().copy()
        if "Date" in normalized.columns and "date" not in normalized.columns:
            normalized = normalized.rename(columns={"Date": "date"})
        if "index" in normalized.columns and "date" not in normalized.columns:
            normalized = normalized.rename(columns={"index": "date"})
        if "date" not in normalized.columns:
            logger.warning(f"Candle frame missing date column: {list(normalized.columns)}")
            return pd.DataFrame(columns=required_cols)

        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        normalized = normalized.dropna(subset=["date"])

        for col in ["open", "close", "high", "low", "volume"]:
            if col not in normalized.columns:
                logger.warning(f"Candle frame missing column {col}")
                return pd.DataFrame(columns=required_cols)
            normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

        normalized = normalized.dropna(subset=["open", "close", "high", "low", "volume"])
        normalized = normalized.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        normalized["change_pct"] = normalized["close"].pct_change().fillna(0.0) * 100

        return normalized[required_cols].reset_index(drop=True)

    def _count_rows_in_range(self, df: pd.DataFrame, start_date: str, end_date: str) -> int:
        if df.empty:
            return 0
        in_range = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
        return len(in_range)

    def _request_interval_seconds(self) -> float:
        if self.daily_candle_provider is not None:
            return 0.0
        if self.market == "cn":
            return 0.6
        if self.api_source == APISource.FMP:
            return 0.2
        return 0.5

    def _estimate_trading_days(self, start_date: str, end_date: str) -> int:
        """Estimate number of trading days in range."""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (end - start).days + 1
        return int(total_days * 0.7)

    def prefetch_news(self, tickers: List[str], start_date: str, end_date: str) -> int:
        """Download and cache news data for all tickers."""
        if not self.router and self.news_provider is None:
            logger.warning("Router not available, skipping news prefetch")
            return 0

        total_news = 0
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        for ticker in tickers:
            try:
                news = self._fetch_news(ticker, end_dt, limit=50)

                if news:
                    news_items = self._convert_news_to_dicts(news, ticker)
                    saved = self.db.save_daily_news(news_items)
                    total_news += saved

                time.sleep(self._news_request_interval_seconds())
            except Exception as exc:
                failure = self._record_provider_failure(
                    operation="news",
                    exc=exc,
                    ticker=ticker,
                    date=end_date,
                    provider=self.news_provider,
                )
                logger.warning(f"Failed to fetch news: {failure.summary()}")

        logger.info(f"Total news items cached: {total_news}")
        return total_news

    def _fetch_news(self, ticker: str, end_dt: datetime, *, limit: int) -> List[Any]:
        if self.news_provider is not None:
            return self.news_provider.get_news(ticker, end_dt, limit, self.market)
        if self.market == "cn":
            return self.router.get_cn_stock_news(
                ticker=ticker,
                trading_date=end_dt,
                news_count=limit,
            )
        return self.router.get_us_stock_news(
            ticker=ticker,
            trading_date=end_dt,
            news_count=limit,
        )

    def _news_request_interval_seconds(self) -> float:
        if self.news_provider is not None:
            return 0.0
        return self._request_interval_seconds()

    def _convert_news_to_dicts(self, news_list: List[Any], ticker: str) -> List[Dict[str, Any]]:
        """Convert news objects to dictionaries for database storage."""
        items: List[Dict[str, Any]] = []
        for news in news_list:
            payload = news if isinstance(news, dict) else {
                "title": getattr(news, "title", ""),
                "url": getattr(news, "link", ""),
                "summary": getattr(news, "summary", ""),
                "content": getattr(news, "summary", ""),
                "publish_time": getattr(news, "publish_time", ""),
                "published": getattr(news, "publish_time", ""),
                "source": getattr(news, "publisher", "unknown"),
            }
            title = payload.get("title", "")
            items.append(
                {
                    "id": f"{ticker}_{hash(str(title))}",
                    "source": payload.get("source", "unknown"),
                    "rank": 0,
                    "title": title,
                    "url": payload.get("url", payload.get("link", "")),
                    "content": payload.get("summary", payload.get("content", "")),
                    "publish_time": payload.get("publish_time", payload.get("published", "")),
                    "meta_data": {"ticker": ticker},
                }
            )
        return items

    def check_coverage(self, tickers: List[str], start_date: str, end_date: str) -> Dict[str, float]:
        """Check cache coverage percentage per ticker."""
        expected_trading_days = self._estimate_trading_days(start_date, end_date)
        coverage = {}
        for ticker in tickers:
            df = self.db.get_stock_prices(ticker, start_date, end_date)
            coverage[ticker] = round(len(df) / expected_trading_days * 100, 1) if expected_trading_days > 0 else 0.0
        return coverage

    def get_trading_days(
        self,
        start_date: str,
        end_date: str,
        ticker: Optional[str] = None,
    ) -> List[str]:
        """Get list of trading days within the date range."""
        reference_tickers = []
        if ticker:
            reference_tickers.append(ticker)
        reference_tickers.extend(self._last_prefetched_tickers)
        default_reference = "600519" if self.market == "cn" else "AAPL"
        if default_reference not in reference_tickers:
            reference_tickers.append(default_reference)

        for ref_ticker in reference_tickers:
            df = self.db.get_stock_prices(ref_ticker, start_date, end_date)
            if not df.empty:
                return sorted(df["date"].tolist())

        fetched_df = self._fetch_reference_trading_days(reference_tickers[-1], end_date)
        if not fetched_df.empty:
            filtered = fetched_df[
                (fetched_df["date"] >= start_date) & (fetched_df["date"] <= end_date)
            ]
            if not filtered.empty:
                return sorted(filtered["date"].tolist())

        logger.warning("No trading days found, generating calendar days")
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        days = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                days.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return days

    def _fetch_reference_trading_days(self, ticker: str, end_date: str) -> pd.DataFrame:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        try:
            df = self._fetch_daily_candles(ticker, end_dt)
            normalized = self._normalize_candles_df(df)
            if not normalized.empty:
                self.db.save_stock_prices(ticker, normalized)
            return normalized
        except Exception as exc:
            failure = self._record_provider_failure(
                operation="reference_trading_days",
                exc=exc,
                ticker=ticker,
                date=end_date,
            )
            logger.warning(f"Failed to fetch reference trading days: {failure.summary()}")
            return pd.DataFrame()

    def _fetch_daily_candles(self, ticker: str, end_dt: datetime) -> pd.DataFrame:
        if self.daily_candle_provider is not None:
            return self.daily_candle_provider.get_daily_candles(ticker, end_dt)
        if self.market == "cn" and self.tushare_api:
            return self.tushare_api.get_daily_candles_df(ticker, end_dt)
        if self.market == "us" and self.router:
            return self.router.get_us_stock_daily_candles_df(ticker, end_dt)
        return pd.DataFrame()

    def get_cached_prices(self, ticker: str, date: str) -> Optional[Dict[str, float]]:
        """Get cached price data for a ticker on a specific date."""
        df = self.db.get_stock_prices(ticker, date, date)
        if df.empty:
            return None

        row = df.iloc[0]
        return {
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "volume": float(row["volume"]),
            "change_pct": float(row["change_pct"]) if pd.notna(row.get("change_pct", 0)) else 0.0,
        }

    def close(self):
        """Close database connection."""
        if self.db:
            self.db.close()

    @property
    def provider_failures(self) -> tuple[ProviderFailure, ...]:
        """Provider failures captured during this prefetcher run."""
        return tuple(self._provider_failures)

    def _record_provider_failure(
        self,
        *,
        operation: str,
        exc: Exception,
        ticker: Optional[str] = None,
        date: Optional[str] = None,
        provider: Optional[Any] = None,
    ) -> ProviderFailure:
        failure = ProviderFailure.from_exception(
            provider=self._provider_failure_name(provider),
            operation=operation,
            exc=exc,
            ticker=ticker,
            market=self.market,
            date=date,
        )
        self._provider_failures.append(failure)
        return failure

    def _provider_failure_name(self, provider: Optional[Any] = None) -> str:
        if provider is not None:
            return str(getattr(provider, "name", provider))
        return str(self.api_source)
