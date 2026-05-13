"""
Index Constituents Provider

Provides index composition data from Tushare API.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from datetime import datetime
import importlib
import pandas as pd


@dataclass
class IndexConstituent:
    """
    Single index constituent stock.

    Attributes:
        ticker: Stock ticker symbol
        weight: Weight in the index (0.0 to 1.0)
        name: Company name
        industry: Industry classification
    """

    ticker: str
    weight: float
    name: Optional[str] = None
    industry: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "ticker": self.ticker,
            "weight": self.weight,
            "name": self.name,
            "industry": self.industry,
        }


class IndexConstituentsProvider:
    """
    Provider for index constituent data.

    Supports:
        - CSI 300 (000300.SH)
        - CSI 500 (000905.SH)
        - SSE 50 (000016.SH)
    """

    # Known index codes
    INDEX_CODES = {
        "csi300": "000300.SH",
        "csi500": "000905.SH",
        "sse50": "000016.SH",
        "csi1000": "000852.SH",
        # US indices
        "sp500": "^GSPC",
        "nasdaq100": "^NDX",
    }

    def __init__(self, tushare_api=None):
        """
        Initialize index constituents provider.

        Args:
            tushare_api: TushareAPI instance (optional, will be created if needed)
        """
        self._tushare_api = tushare_api
        self._cache: Dict[str, List[IndexConstituent]] = {}  # Cache by date+index

    @property
    def tushare_api(self):
        """Lazy load TushareAPI."""
        if self._tushare_api is None:
            from apis.tushare.api import TushareAPI
            self._tushare_api = TushareAPI()
        return self._tushare_api

    def normalize_index_code(self, index_code: str) -> str:
        """
        Normalize index code to Tushare format.

        Args:
            index_code: Index code (e.g., "000300", "000300.SH", "csi300", "^GSPC")

        Returns:
            Normalized index code in Tushare format or US index format
        """
        index_code = index_code.upper().strip()

        # Check if it's a named index
        if index_code.lower() in self.INDEX_CODES:
            return self.INDEX_CODES[index_code.lower()]

        # Add suffix if needed (China market)
        if len(index_code) == 6:
            if index_code.startswith("000"):
                return f"{index_code}.SH"
            elif index_code.startswith("399"):
                return f"{index_code}.SZ"

        # Keep US indices as-is (^GSPC, ^NDX, etc.)
        if index_code.startswith("^"):
            return index_code

        return index_code

    def get_constituents(
        self,
        index_code: str,
        trade_date: Union[str, datetime]
    ) -> List[IndexConstituent]:
        """
        Get index constituents for a specific date.

        Args:
            index_code: Index code (e.g., "000300.SH")
            trade_date: Trading date (datetime or YYYY-MM-DD string)

        Returns:
            List of IndexConstituent objects
        """
        # Convert string to datetime if needed
        if isinstance(trade_date, str):
            try:
                trade_date = datetime.strptime(trade_date, "%Y-%m-%d")
            except ValueError:
                # Try alternative format
                try:
                    trade_date = datetime.strptime(trade_date, "%Y%m%d")
                except ValueError as e:
                    raise ValueError(f"Invalid date format: {trade_date}. Use YYYY-MM-DD or YYYYMMDD") from e

        index_code = self.normalize_index_code(index_code)
        cache_key = f"{index_code}_{trade_date.strftime('%Y%m%d')}"

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # Get constituents from Tushare
            constituents = self._fetch_constituents_from_tushare(
                index_code, trade_date
            )

            # Cache result
            self._cache[cache_key] = constituents

            return constituents

        except Exception as e:
            print(f"Error fetching index constituents: {e}")
            # Return empty list on error
            return []

    def _fetch_constituents_from_tushare(
        self,
        index_code: str,
        trade_date: datetime
    ) -> List[IndexConstituent]:
        """
        Fetch index constituents from Tushare API.

        Note: The index_weight interface may require premium Tushare account.

        Args:
            index_code: Index code in Tushare format
            trade_date: Trading date

        Returns:
            List of IndexConstituent objects
        """
        try:
            pro = self.tushare_api.pro
            date_str = trade_date.strftime("%Y%m%d")

            # Try to get index weights (requires premium)
            df = pro.index_weight(
                index_code=index_code,
                start_date=date_str,
                end_date=date_str
            )

            if df.empty:
                # Fallback: try to get constituents without weights
                return self._fetch_constituents_fallback(index_code, trade_date)

            constituents = []
            for _, row in df.iterrows():
                constituent = IndexConstituent(
                    ticker=row.get("con_code", ""),
                    weight=row.get("weight", 0.0) / 100.0,  # Convert percentage to ratio
                )
                if constituent.ticker:
                    constituents.append(constituent)

            return self._normalize_constituents(constituents)

        except Exception as e:
            print(f"Tushare API error for index constituents: {e}")
            return self._fetch_constituents_fallback(index_code, trade_date)

    def _fetch_constituents_fallback(
        self,
        index_code: str,
        trade_date: datetime
    ) -> List[IndexConstituent]:
        """
        Fallback method to get index constituents when API fails.

        Uses hardcoded data for major indices or returns empty list.

        Args:
            index_code: Index code
            trade_date: Trading date

        Returns:
            List of IndexConstituent objects (may be partial or empty)
        """
        # For CSI 300, use actual weights from public data (as of 2024-2025)
        # Source: Public index data from financial news
        print(f"Warning: Using fallback for index constituents of {index_code}")

        # Major CSI 300 constituents with actual weights
        if index_code == "000300.SH":
            return self._normalize_constituents([
                IndexConstituent(ticker="600519.SH", weight=0.042),  # 贵州茅台 4.2%
                IndexConstituent(ticker="300750.SZ", weight=0.033),  # 宁德时代 3.3%
                IndexConstituent(ticker="601318.SH", weight=0.028),  # 中国平安 2.8%
                IndexConstituent(ticker="600036.SH", weight=0.027),  # 招商银行 2.7%
                IndexConstituent(ticker="000858.SZ", weight=0.020),  # 五粮液 2.0%
                IndexConstituent(ticker="601166.SH", weight=0.019),  # 兴业银行 1.9%
                IndexConstituent(ticker="600900.SH", weight=0.0175), # 长江电力 1.75%
                IndexConstituent(ticker="000333.SZ", weight=0.017),  # 美的集团 1.7%
                IndexConstituent(ticker="601899.SH", weight=0.015),  # 紫金矿业 1.5%
                IndexConstituent(ticker="002594.SZ", weight=0.014),  # 比亚迪 1.4%
                IndexConstituent(ticker="300059.SZ", weight=0.014),  # 东方财富 1.4%
                IndexConstituent(ticker="002415.SZ", weight=0.012),  # 海康威视 1.2%
                IndexConstituent(ticker="601398.SH", weight=0.011),  # 工商银行 1.1%
                IndexConstituent(ticker="600030.SH", weight=0.010),  # 中信证券 1.0%
                IndexConstituent(ticker="000651.SZ", weight=0.008),  # 格力电器 0.8%
            ])

        # US S&P 500 constituents (equal weight fallback for demonstration)
        # In production, this would be fetched from yfinance or similar
        if index_code == "^GSPC":
            us_constituents = [
                "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
                "META", "TSLA", "JPM", "XOM", "UNH"
            ]
            # Use equal weights for fallback
            weight = 1.0 / len(us_constituents)
            return self._normalize_constituents([
                IndexConstituent(ticker=ticker, weight=weight)
                for ticker in us_constituents
            ])

        # Return empty list for other indices
        return []

    def _normalize_constituents(
        self,
        constituents: List[IndexConstituent]
    ) -> List[IndexConstituent]:
        """Normalize constituent weights to sum to 1.0."""
        total_weight = sum(c.weight for c in constituents)
        if total_weight > 0:
            for c in constituents:
                c.weight = c.weight / total_weight
        return constituents

    def get_index_daily(
        self,
        index_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Get daily index data.

        Args:
            index_code: Index code
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with daily index OHLCV data
        """
        index_code = self.normalize_index_code(index_code)

        if index_code.startswith("^"):
            return self._fetch_us_index_daily(index_code, start_date, end_date)

        try:
            pro = self.tushare_api.pro

            df = pro.index_daily(
                ts_code=index_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d")
            )

            if df.empty:
                return pd.DataFrame()

            # Standardize column names
            df = df[["trade_date", "open", "high", "low", "close", "vol", "amount"]].copy()
            df.columns = ["date", "open", "high", "low", "close", "volume", "amount"]
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            df.set_index("date", inplace=True)
            df.sort_index(inplace=True)

            return df

        except Exception as e:
            print(f"Error fetching index daily data: {e}")
            return pd.DataFrame()

    def _fetch_us_index_daily(
        self,
        index_code: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Fetch US index OHLCV from yfinance when available."""
        try:
            yf = importlib.import_module("yfinance")
        except Exception as e:
            print(f"Error importing yfinance for {index_code}: {e}")
            return pd.DataFrame()

        download = getattr(yf, "download", None)
        if download is None:
            print(f"yfinance.download unavailable for {index_code}")
            return pd.DataFrame()

        try:
            df = download(
                index_code,
                start=start_date.strftime("%Y-%m-%d"),
                end=(end_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=False,
            )
        except Exception as e:
            print(f"Error fetching US index daily data for {index_code}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        column_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        available = [c for c in column_map if c in df.columns]
        if not available:
            return pd.DataFrame()

        result = df[available].rename(columns=column_map).copy()
        for col in ["open", "high", "low", "close"]:
            if col not in result.columns:
                result[col] = result.get("close")
        if "volume" not in result.columns:
            result["volume"] = 0.0

        result.index = pd.to_datetime(result.index)
        result.index.name = "date"
        result.sort_index(inplace=True)
        return result[["open", "high", "low", "close", "volume"]]

    def get_constituent_weights(
        self,
        index_code: str,
        trade_date: datetime
    ) -> Dict[str, float]:
        """
        Get constituent weights as a dictionary.

        Args:
            index_code: Index code
            trade_date: Trading date

        Returns:
            Dictionary mapping ticker to weight
        """
        constituents = self.get_constituents(index_code, trade_date)
        return {c.ticker: c.weight for c in constituents}
