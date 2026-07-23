"""
Tushare API client implementation for Chinese A-share market.
Reference: https://tushare.pro/document/2
Free tier: 120 API requests per minute
"""

import os
import time
import pandas as pd
from datetime import datetime, timedelta
from apis.common_model import MediaNews
from .api_model import TushareInsiderTrade, TushareFundamentals, CNEconomicIndicators

# Import stats for cache tracking
try:
    from deepear.src.utils.stats import get_stats
    STATS_AVAILABLE = True
except ImportError:
    STATS_AVAILABLE = False


try:
    import tushare as ts
except ImportError:
    ts = None


class TushareAPI:
    """Tushare API Wrapper for Chinese A-share market data."""

    def __init__(self, db=None):
        """
        Initialize Tushare API client.

        Args:
            db: Optional DatabaseManager instance for caching
        """
        if ts is None:
            raise ImportError("tushare package is not installed. Run: pip install tushare")

        self.api_key = os.environ.get("TUSHARE_API_KEY")
        if not self.api_key:
            raise ValueError("TUSHARE_API_KEY not found in environment variables")

        # Initialize Tushare by directly using DataApi to bypass tk.csv issues
        # The tk.csv file can become corrupted and cause "No columns to parse" errors
        from tushare.pro import client
        self.pro = client.DataApi(token=self.api_key, timeout=30)

        # Database cache layer (optional)
        self.db = db
        if db:
            print("TushareAPI caching enabled")

    def _format_tushare_code(self, ticker) -> str:
        """
        Convert ticker format to Tushare format.
        - Shanghai: 6-digit -> XXXXXX.SH
        - Shenzhen: 6-digit -> XXXXXX.SZ
        """
        # Convert to string if integer
        ticker = str(ticker).strip()

        # If already has correct format, return as-is
        if len(ticker) == 9 and ticker[6] == '.' and ticker[7:].upper() in ('SH', 'SZ'):
            return ticker

        # Handle underscored format like 600519_SH
        if '_' in ticker:
            ticker = ticker.replace('_', '.')
            return ticker

        # Handle suffix-only format
        if ticker.startswith('.SH') or ticker.startswith('.SZ'):
            return ticker[1:]  # Remove leading dot

        # Clean up dots and underscores for pure numeric check
        clean_ticker = ticker.replace('.', '').replace('_', '')

        if len(clean_ticker) == 6:
            if clean_ticker.startswith('6') or clean_ticker.startswith('5'):
                return f"{clean_ticker}.SH"
            elif clean_ticker.startswith('0') or clean_ticker.startswith('3'):
                return f"{clean_ticker}.SZ"

        # Try to detect from existing suffix (after removing extra chars)
        upper_ticker = clean_ticker.upper()
        if 'SH' in upper_ticker or 'SS' in upper_ticker:
            return f"{clean_ticker[:6]}.SH"
        elif 'SZ' in upper_ticker:
            return f"{clean_ticker[:6]}.SZ"

        # Default: assume Shanghai
        return f"{clean_ticker[:6]}.SH"

    def _parse_date(self, trading_date: datetime) -> str:
        """Convert datetime to Tushare date format (YYYYMMDD)."""
        return trading_date.strftime("%Y%m%d")

    def get_daily_candles_df(self, ticker: str, trading_date: datetime) -> pd.DataFrame:
        """
        Get daily candles for a ticker as DataFrame.

        Args:
            ticker: Stock code (e.g., '600519' or '600519.SH')
            trading_date: Trading date to filter up to

        Returns:
            DataFrame with OHLCV data
        """
        ts_code = self._format_tushare_code(ticker)
        end_date = self._parse_date(trading_date)
        start_date = (trading_date - timedelta(days=365)).strftime("%Y%m%d")

        try:
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                return pd.DataFrame()

            # Map Tushare columns to standard names
            df = df[['trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']].copy()
            df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
            df.set_index('date', inplace=True)

            # Convert to numeric
            numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df.sort_index(inplace=True)
            return df

        except Exception as e:
            print(f"Error fetching daily candles for {ts_code}: {e}")
            return pd.DataFrame()

    def get_last_close_price(self, ticker: str, trading_date: datetime) -> float:
        """
        Get the last close price for a ticker.

        Args:
            ticker: Stock code
            trading_date: Trading date

        Returns:
            Last close price or None
        """
        df = self.get_daily_candles_df(ticker, trading_date)
        if not df.empty:
            return float(df['close'].iloc[-1])
        return None

    def get_insider_trades(self, ticker: str, trading_date: datetime, limit: int = None) -> list[TushareInsiderTrade]:
        """
        Get insider trades for a ticker.

        Args:
            ticker: Stock code
            trading_date: Filter trades up to this date
            limit: Maximum number of trades to return

        Returns:
            List of TushareInsiderTrade objects
        """
        ts_code = self._format_tushare_code(ticker)
        end_date = self._parse_date(trading_date)

        try:
            df = self.pro.stk_holder_trade(
                ts_code=ts_code,
                end_date=end_date,
                limit=limit or 100
            )

            if df.empty:
                return []

            trades = []
            for _, row in df.iterrows():
                trade = TushareInsiderTrade(
                    ts_code=row.get('ts_code', ts_code),
                    ann_date=str(row.get('ann_date', '')),
                    endDate=str(row.get('end_date', '')),
                    name=row.get('name', ''),
                    title=row.get('title', ''),
                    gender=row.get('gender', ''),
                    age=row.get('age'),
                    share_num=row.get('hold_share_num'),
                    hold_ratio=row.get('hold_ratio')
                )
                trades.append(trade)

            return trades

        except Exception as e:
            print(f"Error fetching insider trades for {ts_code}: {e}")
            return []

    def get_fundamentals(self, ticker: str) -> TushareFundamentals:
        """
        Get company fundamentals from Tushare.

        Note: This uses only free-tier APIs. Some fields may be None due to
        access restrictions on daily_basic and fina_indicator interfaces.

        Args:
            ticker: Stock code

        Returns:
            TushareFundamentals object or None
        """
        ts_code = self._format_tushare_code(ticker)

        try:
            # Get company info (free API)
            df_info = self.pro.stock_basic(
                ts_code=ts_code,
                fields='ts_code,name,industry,area,list_date'
            )

            if df_info.empty:
                return None

            info_data = df_info.iloc[0].to_dict()

            # Try to get daily basic (may require paid account)
            basic_data = {}
            try:
                df_basic = self.pro.daily_basic(
                    ts_code=ts_code,
                    fields='ts_code,trade_date,pe,pe_ttm,pb,ps,ps_ttm,total_share,float_share'
                )
                if not df_basic.empty:
                    basic_data = df_basic.iloc[0].to_dict()
            except Exception as e:
                print(f"Note: daily_basic requires paid account: {e}")

            # Try to get financial indicators (may require paid account)
            fin_data = {}
            try:
                df_fin = self.pro.fina_indicator(
                    ts_code=ts_code,
                    limit=1,
                    fields='ts_code,ann_date,roe,roe_waa,roa,npta,gitr_gp,gpr,npr'
                )
                if not df_fin.empty:
                    fin_data = df_fin.iloc[0].to_dict()
            except Exception as e:
                print(f"Note: fina_indicator requires paid account: {e}")

            fundamentals = TushareFundamentals(
                ts_code=ts_code,
                name=info_data.get('name', ''),
                industry=info_data.get('industry'),
                area=info_data.get('area'),
                pe=basic_data.get('pe'),
                pe_ttm=basic_data.get('pe_ttm'),
                pb=basic_data.get('pb'),
                ps=basic_data.get('ps'),
                ps_ttm=basic_data.get('ps_ttm'),
                total_share=basic_data.get('total_share'),
                float_share=basic_data.get('float_share'),
                roe=fin_data.get('roe'),
                roa=fin_data.get('roa'),
                gross_profit_margin=fin_data.get('gpr'),
                net_profit_margin=fin_data.get('npr')
            )

            return fundamentals

        except Exception as e:
            print(f"Error fetching fundamentals for {ts_code}: {e}")
            return None

    def get_news(self, ticker: str = None, topic: str = None, trading_date: datetime = None, limit: int = None) -> list[MediaNews]:
        """
        Get news from Tushare (using major news).

        Args:
            ticker: Stock ticker symbol (optional, for Tushare we use major news)
            topic: Topic for market news (optional)
            trading_date: Get news up to this date
            limit: Maximum number of news items to return

        Returns:
            List of MediaNews objects
        """
        end_date = datetime.now() if trading_date is None else trading_date
        start_date = (end_date - timedelta(days=7)).strftime("%Y%m%d")
        end_date_str = end_date.strftime("%Y%m%d")

        try:
            # Tushare major news (requires premium usually)
            # Fallback to empty list for free tier
            df = self.pro.major_news(
                start_date=start_date,
                end_date=end_date_str,
                limit=limit or 50
            )

            if df.empty:
                return []

            news_list = []
            for _, row in df.iterrows():
                news_list.append(MediaNews(
                    title=row.get('title', ''),
                    publish_time=str(row.get('datetime', '')),
                    publisher=row.get('source', 'Tushare'),
                    link=row.get('url'),
                    summary=row.get('content', '')[:200] if row.get('content') else None
                ))

            return news_list

        except Exception as e:
            # Tushare major news requires premium, return empty list
            print(f"Note: Tushare major news may require premium account: {e}")
            return []

    def get_economic_indicators(self) -> CNEconomicIndicators:
        """
        Get Chinese economic indicators from Tushare.

        Note: Many economic indicators require premium Tushare account.
        This method attempts to fetch available data and returns what's accessible.

        Returns:
            CNEconomicIndicators object with available data
        """
        indicators = {
            "gdp": {},
            "gdp_yoy": {},
            "cpi": {},
            "ppi": {},
            "m2": {},
            "m1": {},
            "loan_rate": {},
            "unemployment_rate": {},
            "export_growth": {},
            "import_growth": {}
        }

        # Try to fetch GDP data (cn_gdp may require premium)
        try:
            df = self.pro.cn_gdp(limit=1)
            if not df.empty:
                indicators["gdp"] = df.iloc[0].to_dict()
        except Exception as e:
            print(f"Note: cn_gdp requires premium account: {e}")

        # Try to fetch CPI data (cn_cpi may require premium)
        try:
            df = self.pro.cn_cpi(limit=1)
            if not df.empty:
                indicators["cpi"] = df.iloc[0].to_dict()
        except Exception as e:
            print(f"Note: cn_cpi requires premium account: {e}")

        # Try to fetch PPI data (cn_ppi may require premium)
        try:
            df = self.pro.cn_ppi(limit=1)
            if not df.empty:
                indicators["ppi"] = df.iloc[0].to_dict()
        except Exception as e:
            print(f"Note: cn_ppi requires premium account: {e}")

        # Try to fetch money supply (cn_m may require premium)
        try:
            df = self.pro.cn_m(limit=1)
            if not df.empty:
                row = df.iloc[0].to_dict()
                indicators["m2"] = {"m2": row.get("m2")}
                indicators["m1"] = {"m1": row.get("m1")}
        except Exception as e:
            print(f"Note: cn_m requires premium account: {e}")

        # Try to fetch loan rate (shibor may require premium)
        try:
            df = self.pro.shibor(limit=1)
            if not df.empty:
                indicators["loan_rate"] = df.iloc[0].to_dict()
        except Exception as e:
            print(f"Note: shibor requires premium account: {e}")

        return CNEconomicIndicators(**indicators)

    # =========================================================================
    # Index Data Methods (for Smart Beta)
    # =========================================================================

    def get_index_constituents(
        self,
        index_code: str,
        trade_date: datetime
    ) -> list[dict]:
        """
        Get index constituents for a specific date.

        Args:
            index_code: Index code (e.g., '000300.SH' for CSI 300)
            trade_date: Trading date

        Returns:
            List of dictionaries with 'ticker', 'weight', 'name' fields
        """
        # Normalize index code
        if len(index_code) == 6:
            if index_code.startswith('000'):
                index_code = f"{index_code}.SH"
            elif index_code.startswith('399'):
                index_code = f"{index_code}.SZ"

        date_str = self._parse_date(trade_date)
        date_iso = trade_date.strftime('%Y-%m-%d')

        # Check cache first (1-day TTL for constituents)
        if self.db:
            cached = self.db.get_index_constituents(index_code, date_iso, max_age_days=1)
            if cached is not None:
                # Record cache hit
                if STATS_AVAILABLE:
                    get_stats().record_api_call('tushare_cache_hit', success=True)
                print(f"Cache hit for {index_code} constituents on {date_iso}")
                return cached

        # Cache miss - call API
        start_time = time.time()
        try:
            # Get index weights (may require premium account)
            df = self.pro.index_weight(
                index_code=index_code,
                start_date=date_str,
                end_date=date_str
            )

            if df.empty:
                # Try without date constraint
                df = self.pro.index_weight(index_code=index_code)
                if not df.empty:
                    # Get most recent data
                    df = df[df['trade_date'] <= date_str].tail(1)
                    if df.empty:
                        return []

            constituents = []
            for _, row in df.iterrows():
                constituents.append({
                    'ticker': row.get('con_code', ''),
                    'weight': row.get('weight', 0) / 100.0,  # Convert to ratio
                    'name': ''
                })

            # Normalize weights
            total_weight = sum(c['weight'] for c in constituents)
            if total_weight > 0:
                for c in constituents:
                    c['weight'] = c['weight'] / total_weight

            # Record API call
            elapsed_ms = (time.time() - start_time) * 1000
            if STATS_AVAILABLE:
                get_stats().record_api_call('tushare', success=True, time_ms=elapsed_ms)

            # Save to cache
            if self.db and constituents:
                self.db.save_index_constituents(index_code, date_iso, constituents)
                print(f"Cached {len(constituents)} constituents for {index_code} on {date_iso}")

            return constituents

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            if STATS_AVAILABLE:
                get_stats().record_api_call('tushare', success=False, time_ms=elapsed_ms)
            print(f"Error fetching index constituents for {index_code}: {e}")
            return []

    def get_index_daily(
        self,
        index_code: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Get daily index data.

        Args:
            index_code: Index code (e.g., '000300.SH')
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with OHLCV data
        """
        # Normalize index code
        if len(index_code) == 6:
            if index_code.startswith('000'):
                index_code = f"{index_code}.SH"
            elif index_code.startswith('399'):
                index_code = f"{index_code}.SZ"

        start_iso = start_date.strftime('%Y-%m-%d')
        end_iso = end_date.strftime('%Y-%m-%d')

        # Check cache first (no TTL for historical price data)
        if self.db:
            cached_df = self.db.get_index_prices(index_code, start_iso, end_iso)
            if not cached_df.empty:
                # Record cache hit
                if STATS_AVAILABLE:
                    get_stats().record_api_call('tushare_cache_hit', success=True, time_ms=0)
                print(f"Cache hit for {index_code} prices: {len(cached_df)} rows")
                return cached_df

        # Cache miss - call API
        start_time = time.time()
        try:
            df = self.pro.index_daily(
                ts_code=index_code,
                start_date=self._parse_date(start_date),
                end_date=self._parse_date(end_date)
            )

            if df.empty:
                return pd.DataFrame()

            # Standardize columns
            df = df[['trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']].copy()
            df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
            df.set_index('date', inplace=True)

            # Convert to numeric
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df.sort_index(inplace=True)

            # Record API call
            elapsed_ms = (time.time() - start_time) * 1000
            if STATS_AVAILABLE:
                get_stats().record_api_call('tushare', success=True, time_ms=elapsed_ms)

            # Save to cache
            if self.db and not df.empty:
                self.db.save_index_prices(index_code, df)
                print(f"Cached {len(df)} price rows for {index_code}")

            return df

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            if STATS_AVAILABLE:
                get_stats().record_api_call('tushare', success=False, time_ms=elapsed_ms)
            print(f"Error fetching index daily data for {index_code}: {e}")
            return pd.DataFrame()

    def get_index_weights(
        self,
        index_code: str,
        trade_date: datetime
    ) -> dict[str, float]:
        """
        Get index constituent weights as a dictionary.

        Args:
            index_code: Index code
            trade_date: Trading date

        Returns:
            Dictionary mapping ticker to weight
        """
        constituents = self.get_index_constituents(index_code, trade_date)
        return {c['ticker']: c['weight'] for c in constituents}

    def get_extended_daily_candles(
        self,
        ticker: str,
        trading_date: datetime,
        lookback_days: int = 252
    ) -> pd.DataFrame:
        """
        Get extended daily candles for factor calculation.

        Args:
            ticker: Stock code
            trading_date: End date
            lookback_days: Number of trading days to look back (default: 252, ~1 year)

        Returns:
            DataFrame with OHLCV data
        """
        ts_code = self._format_tushare_code(ticker)
        end_date = self._parse_date(trading_date)

        # Calculate start date (add buffer for non-trading days)
        start_dt = trading_date - timedelta(days=int(lookback_days * 1.5))
        start_date = start_dt.strftime("%Y%m%d")
        start_iso = start_dt.strftime('%Y-%m-%d')
        end_iso = trading_date.strftime('%Y-%m-%d')

        # Check cache first (stock_prices table)
        if self.db:
            cached_df = self.db.get_stock_prices(ticker, start_iso, end_iso)
            if not cached_df.empty:
                # Ensure we have enough data
                if len(cached_df) >= lookback_days * 0.8:
                    # Record cache hit
                    if STATS_AVAILABLE:
                        get_stats().record_api_call('tushare_cache_hit', success=True, time_ms=0)
                    print(f"Cache hit for {ticker} candles: {len(cached_df)} rows")
                    # Limit to lookback_days
                    if len(cached_df) > lookback_days:
                        cached_df = cached_df.tail(lookback_days)
                    return cached_df
                else:
                    print(f"Partial cache for {ticker}: {len(cached_df)} rows, fetching from API")

        start_time = time.time()
        try:
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df.empty:
                return pd.DataFrame()

            # Map columns
            df = df[['trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']].copy()
            df.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
            df.set_index('date', inplace=True)

            # Convert to numeric
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df.sort_index(inplace=True)

            # Record API call
            elapsed_ms = (time.time() - start_time) * 1000
            if STATS_AVAILABLE:
                get_stats().record_api_call('tushare', success=True, time_ms=elapsed_ms)

            # Save to cache (need change_pct for stock_prices table)
            if self.db and not df.empty:
                df_to_save = df.reset_index()
                df_to_save['change_pct'] = df_to_save['close'].pct_change() * 100
                self.db.save_stock_prices(ticker, df_to_save)
                print(f"Cached {len(df_to_save)} candles for {ticker}")

            # Limit to lookback_days
            if len(df) > lookback_days:
                df = df.tail(lookback_days)

            return df

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            if STATS_AVAILABLE:
                get_stats().record_api_call('tushare', success=False, time_ms=elapsed_ms)
            print(f"Error fetching extended daily candles for {ts_code}: {e}")
            return pd.DataFrame()
