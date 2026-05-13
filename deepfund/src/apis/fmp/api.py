"""Financial Modeling Prep (FMP) API client implementation.

Uses stable endpoints:
https://site.financialmodelingprep.com/developer/docs/stable
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from apis.alphavantage.api_model import Fundamentals, InsiderTrade, MacroEconomic
from apis.common_model import MediaNews, OHLCVCandle


class FMPAPI:
    """FMP API wrapper with stable endpoint support."""

    BASE_URL = "https://financialmodelingprep.com"

    def __init__(self):
        self.api_key = os.environ.get("FMP_API_KEY")
        if not self.api_key:
            raise ValueError("FMP_API_KEY is not set")

        self.session = requests.Session()
        self.timeout = 20

    def _request_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Perform GET request and parse JSON response."""
        query = dict(params or {})
        query["apikey"] = self.api_key

        response = self.session.get(
            url=f"{self.BASE_URL}{path}",
            params=query,
            timeout=self.timeout,
        )

        # FMP uses 402 for plan-restricted endpoints
        if response.status_code == 402:
            raise PermissionError(response.text.strip())

        response.raise_for_status()

        body = response.text.strip()
        if body.startswith("Restricted Endpoint"):
            raise PermissionError(body)

        try:
            parsed = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON from FMP endpoint {path}: {body[:200]}") from exc

        if isinstance(parsed, dict) and parsed.get("Error Message"):
            raise RuntimeError(parsed["Error Message"])

        return parsed

    @staticmethod
    def _to_str(value: Any, default: str = "N/A") -> str:
        if value is None:
            return default
        return str(value)

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse common FMP datetime formats."""
        if not date_str:
            return None

        clean = date_str.strip()
        candidates = [clean]
        if len(clean) >= 19:
            candidates.append(clean[:19])
        if len(clean) >= 10:
            candidates.append(clean[:10])

        for candidate in candidates:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(candidate, fmt)
                except ValueError:
                    continue

        try:
            return datetime.fromisoformat(clean.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    def _fetch_first(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch list endpoint and return first item dict."""
        try:
            data = self._request_json(path, params)
        except Exception:
            return {}

        if isinstance(data, list) and data:
            item = data[0]
            return item if isinstance(item, dict) else {}
        if isinstance(data, dict):
            return data
        return {}

    def _get_daily_candles(self, ticker: str, trading_date: datetime) -> List[OHLCVCandle]:
        """Get historical daily candles up to trading date."""
        from_date = (trading_date - timedelta(days=450)).strftime("%Y-%m-%d")
        to_date = trading_date.strftime("%Y-%m-%d")

        rows = self._request_json(
            "/stable/historical-price-eod/full",
            {
                "symbol": ticker,
                "from": from_date,
                "to": to_date,
            },
        )

        candles: List[OHLCVCandle] = []
        if not isinstance(rows, list):
            return candles

        for row in rows:
            if not isinstance(row, dict):
                continue

            date_raw = row.get("date")
            candle_date = self._parse_date(self._to_str(date_raw, ""))
            if not candle_date or candle_date > trading_date:
                continue

            candles.append(
                OHLCVCandle(
                    date=candle_date.strftime("%Y-%m-%d"),
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=int(float(row.get("volume", 0) or 0)),
                )
            )

        # Keep latest first, matching existing AlphaVantage behavior.
        candles.sort(key=lambda x: x.date, reverse=True)
        return candles

    def get_last_close_price(self, ticker: str, trading_date: datetime) -> Optional[float]:
        """Get last close price up to trading date."""
        candles = self._get_daily_candles(ticker, trading_date)
        return candles[0].close if candles else None

    def get_daily_candles_df(self, ticker: str, trading_date: datetime) -> pd.DataFrame:
        """Convert daily candles into DataFrame."""
        candles = self._get_daily_candles(ticker, trading_date)
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame([candle.model_dump() for candle in candles])
        df["Date"] = pd.to_datetime(df["date"])
        df.set_index("Date", inplace=True)
        df.drop("date", axis=1, inplace=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.sort_index(inplace=True)
        return df

    def get_insider_trades(
        self, ticker: str, trading_date: Optional[datetime], limit: Optional[int] = None
    ) -> List[InsiderTrade]:
        """Get insider trades by filtering latest feed pages by symbol."""
        target = ticker.upper()
        max_items = limit or 10
        trades: List[InsiderTrade] = []

        # Free tier supports latest feed; symbol search endpoint is plan-restricted.
        for page in range(10):
            try:
                rows = self._request_json(
                    "/stable/insider-trading/latest",
                    {"page": page, "limit": 100},
                )
            except PermissionError as exc:
                # Free tier can restrict paging to page=0 only.
                if page > 0 and "page" in str(exc).lower():
                    break
                raise

            if not isinstance(rows, list) or not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                if self._to_str(row.get("symbol"), "").upper() != target:
                    continue

                tx_date_str = self._to_str(row.get("transactionDate") or row.get("filingDate"), "")
                tx_date = self._parse_date(tx_date_str)
                if trading_date and tx_date and tx_date > trading_date:
                    continue

                trades.append(
                    InsiderTrade(
                        transaction_date=tx_date_str[:10],
                        ticker=self._to_str(row.get("symbol"), target),
                        executive=self._to_str(row.get("reportingName"), "Unknown"),
                        executive_title=self._to_str(row.get("typeOfOwner"), "Unknown"),
                        security_type=self._to_str(row.get("securityName"), "Unknown"),
                        acquisition_or_disposal=self._to_str(
                            row.get("acquisitionOrDisposition") or row.get("transactionType"),
                            "",
                        ),
                        shares=self._to_str(row.get("securitiesTransacted"), "0"),
                        share_price=self._to_str(row.get("price"), "0"),
                    )
                )

                if len(trades) >= max_items:
                    return trades[:max_items]

        return trades[:max_items]

    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """Get company fundamentals and map to existing AlphaVantage model."""
        profile = self._fetch_first("/stable/profile", {"symbol": ticker})
        key_metrics = self._fetch_first("/stable/key-metrics-ttm", {"symbol": ticker})
        ratios = self._fetch_first("/stable/ratios-ttm", {"symbol": ticker})
        growth = self._fetch_first("/stable/financial-growth", {"symbol": ticker, "limit": 1})
        income_stmt = self._fetch_first("/stable/income-statement", {"symbol": ticker, "limit": 1})
        cashflow_stmt = self._fetch_first("/stable/cash-flow-statement", {"symbol": ticker, "limit": 1})
        target = self._fetch_first("/stable/price-target-summary", {"symbol": ticker})

        fundamentals_data = {
            "LatestQuarter": self._to_str(growth.get("date")),
            "MarketCapitalization": self._to_str(profile.get("marketCap") or key_metrics.get("marketCap")),
            "EBITDA": self._to_str(income_stmt.get("ebitda"), "N/A"),
            "PERatio": self._to_str(ratios.get("priceToEarningsRatioTTM")),
            "PEGRatio": self._to_str(
                ratios.get("priceToEarningsGrowthRatioTTM")
                or ratios.get("forwardPriceToEarningsGrowthRatioTTM")
            ),
            "BookValue": self._to_str(ratios.get("bookValuePerShareTTM")),
            "DividendPerShare": self._to_str(ratios.get("dividendPerShareTTM") or profile.get("lastDividend")),
            "DividendYield": self._to_str(ratios.get("dividendYieldTTM")),
            "EPS": self._to_str(ratios.get("netIncomePerShareTTM")),
            "RevenuePerShareTTM": self._to_str(ratios.get("revenuePerShareTTM")),
            "ProfitMargin": self._to_str(ratios.get("netProfitMarginTTM")),
            "OperatingMarginTTM": self._to_str(ratios.get("operatingProfitMarginTTM")),
            "ReturnOnAssetsTTM": self._to_str(key_metrics.get("returnOnAssetsTTM")),
            "ReturnOnEquityTTM": self._to_str(key_metrics.get("returnOnEquityTTM")),
            "RevenueTTM": self._to_str(income_stmt.get("revenue"), "N/A"),
            "GrossProfitTTM": self._to_str(income_stmt.get("grossProfit"), "N/A"),
            "DilutedEPSTTM": self._to_str(income_stmt.get("epsDiluted") or ratios.get("netIncomePerShareTTM")),
            "QuarterlyEarningsGrowthYOY": self._to_str(growth.get("epsgrowth")),
            "QuarterlyRevenueGrowthYOY": self._to_str(growth.get("revenueGrowth")),
            "AnalystTargetPrice": self._to_str(
                target.get("lastQuarterAvgPriceTarget") or target.get("allTimeAvgPriceTarget")
            ),
            "AnalystRatingStrongBuy": "0",
            "AnalystRatingBuy": "0",
            "AnalystRatingHold": "0",
            "AnalystRatingSell": "0",
            "AnalystRatingStrongSell": "0",
            "TrailingPE": self._to_str(ratios.get("priceToEarningsRatioTTM")),
            "ForwardPE": "N/A",
            "PriceToSalesRatioTTM": self._to_str(ratios.get("priceToSalesRatioTTM")),
            "PriceToBookRatio": self._to_str(ratios.get("priceToBookRatioTTM")),
            "EVToRevenue": self._to_str(key_metrics.get("evToSalesTTM")),
            "EVToEBITDA": self._to_str(key_metrics.get("evToEBITDATTM")),
            "Beta": self._to_str(profile.get("beta")),
            "CurrentRatio": self._to_str(ratios.get("currentRatioTTM")),
            "OperatingCashFlow": self._to_str(
                cashflow_stmt.get("operatingCashFlow")
                or cashflow_stmt.get("netCashProvidedByOperatingActivities")
            ),
        }

        return Fundamentals(**fundamentals_data)

    def _article_matches_ticker(self, article: Dict[str, Any], ticker: str) -> bool:
        """Check whether article appears to be about ticker."""
        target = ticker.upper()

        raw_tickers = article.get("tickers")
        if isinstance(raw_tickers, list):
            if any(self._to_str(t, "").upper() == target for t in raw_tickers):
                return True
        elif isinstance(raw_tickers, str):
            if target in {t.strip().upper() for t in raw_tickers.split(",") if t.strip()}:
                return True

        text = f"{article.get('title', '')} {article.get('content', '')}".upper()
        return target in text

    def _article_matches_topic(self, article: Dict[str, Any], topic: str) -> bool:
        """Topic filter for policy analyst compatibility."""
        keywords = {
            "economy_fiscal": [
                "fiscal",
                "budget",
                "tax",
                "deficit",
                "government spending",
                "debt ceiling",
                "treasury",
            ],
            "economy_monetary": [
                "federal reserve",
                "fed",
                "fomc",
                "interest rate",
                "rate cut",
                "rate hike",
                "monetary",
                "inflation",
                "cpi",
                "pce",
            ],
        }

        words = keywords.get(topic, [topic])
        text = f"{article.get('title', '')} {article.get('content', '')}".lower()
        return any(word in text for word in words)

    def _within_trading_date(self, date_text: str, trading_date: Optional[datetime]) -> bool:
        """Check whether a news timestamp is not later than trading date."""
        if not trading_date:
            return True

        parsed = self._parse_date(date_text)
        if not parsed:
            return True

        return parsed.date() <= trading_date.date()

    def _to_media_news(self, item: Dict[str, Any]) -> MediaNews:
        """Convert FMP news article payload to unified news model."""
        publish_time = self._to_str(item.get("date") or item.get("publishedDate"), "")
        return MediaNews(
            title=self._to_str(item.get("title"), ""),
            publish_time=publish_time,
            publisher=self._to_str(item.get("site") or item.get("publisher") or item.get("author"), "FMP"),
            link=item.get("link") or item.get("url"),
            summary=item.get("content") or item.get("text"),
        )

    def _fetch_fmp_articles(self, pages: int = 2, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch generic FMP article feed pages."""
        articles: List[Dict[str, Any]] = []
        for page in range(pages):
            data = self._request_json(
                "/stable/fmp-articles",
                {
                    "page": page,
                    "limit": limit,
                },
            )
            if not isinstance(data, list) or not data:
                break
            articles.extend(item for item in data if isinstance(item, dict))
        return articles

    def _fetch_general_news(self, pages: int = 2, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch generic market news feed pages."""
        articles: List[Dict[str, Any]] = []
        for page in range(pages):
            data = self._request_json(
                "/stable/news/general-latest",
                {
                    "page": page,
                    "limit": limit,
                },
            )
            if not isinstance(data, list) or not data:
                break
            articles.extend(item for item in data if isinstance(item, dict))
        return articles

    def _collect_matching_news(
        self,
        rows: List[Dict[str, Any]],
        trading_date: Optional[datetime],
        limit: int,
        ticker: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> List[MediaNews]:
        """Filter raw rows and convert them into unified news items."""
        results: List[MediaNews] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            publish_time = self._to_str(row.get("date") or row.get("publishedDate"), "")
            if not self._within_trading_date(publish_time, trading_date):
                continue
            if ticker and not self._article_matches_ticker(row, ticker):
                continue
            if topic and not self._article_matches_topic(row, topic):
                continue

            results.append(self._to_media_news(row))
            if len(results) >= limit:
                break
        return results

    def get_news(
        self,
        ticker: Optional[str] = None,
        topic: Optional[str] = None,
        trading_date: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[MediaNews]:
        """Get company or market news.

        Priority order:
        - stock news
        - general news
        - FMP articles fallback
        """
        max_items = limit or 10

        if ticker and not topic:
            try:
                rows = self._request_json(
                    "/stable/news/stock",
                    {
                        "symbols": ticker,
                        "limit": max_items,
                    },
                )
                if isinstance(rows, list):
                    results = self._collect_matching_news(
                        rows,
                        trading_date=trading_date,
                        limit=max_items,
                    )
                    if results:
                        return results[:max_items]
            except PermissionError:
                pass

        general_rows = self._fetch_general_news(pages=3, limit=50)
        general_results = self._collect_matching_news(
            general_rows,
            trading_date=trading_date,
            limit=max_items,
            ticker=ticker,
            topic=topic,
        )
        if general_results:
            return general_results[:max_items]

        article_rows = self._fetch_fmp_articles(pages=3, limit=50)
        article_results = self._collect_matching_news(
            article_rows,
            trading_date=trading_date,
            limit=max_items,
            ticker=ticker,
            topic=topic,
        )
        return article_results[:max_items]

    def _fetch_economic_indicator(self, name: str) -> Dict[str, Any]:
        """Fetch latest value for a single economic indicator name."""
        rows = self._request_json("/stable/economic-indicators", {"name": name})
        if isinstance(rows, list) and rows:
            row = rows[0]
            return row if isinstance(row, dict) else {}
        return {}

    def _fetch_treasury_yield_10y(self) -> Dict[str, Any]:
        """Fetch latest 10-year treasury yield."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=400)

        rows = self._request_json(
            "/stable/treasury-rates",
            {
                "from": start_date.strftime("%Y-%m-%d"),
                "to": end_date.strftime("%Y-%m-%d"),
            },
        )

        if not isinstance(rows, list) or not rows:
            return {}

        latest = rows[0] if isinstance(rows[0], dict) else {}
        if not latest:
            return {}

        return {
            "name": "treasuryYield10Y",
            "date": latest.get("date"),
            "value": latest.get("year10"),
        }

    def get_economic_indicators(self) -> MacroEconomic:
        """Get macroeconomic indicators in structure used by existing analysts."""
        indicators = {
            "real_gdp": self._fetch_economic_indicator("realGDP"),
            "cpi": self._fetch_economic_indicator("CPI"),
            "treasury_yield": self._fetch_treasury_yield_10y(),
            "federal_funds_rate": self._fetch_economic_indicator("federalFunds"),
            "unemployment": self._fetch_economic_indicator("unemploymentRate"),
            "nonfarm_payrolls": self._fetch_economic_indicator("totalNonfarmPayroll"),
        }

        indicators = {k: v or {} for k, v in indicators.items()}
        return MacroEconomic(**indicators)
