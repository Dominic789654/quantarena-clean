from datetime import datetime, timedelta
from typing import List, Dict, Optional
import akshare as ak
import pandas as pd
import re
import sqlite3
from requests.exceptions import RequestException
from loguru import logger
from deepear.src.utils.database_manager import DatabaseManager

class StockTools:
    """金融分析股票工具 - 结合高性能数据库缓存与增量更新"""
    
    def __init__(self, db: DatabaseManager, auto_update: bool = True):
        """
        初始化股票工具
        
        Args:
            db: 数据库管理器
            auto_update: 是否在列表为空时自动更新，默认 True
        """
        self.db = db
        if auto_update:
            self._check_and_update_stock_list()

    def _check_and_update_stock_list(self, force: bool = False):
        """检查并更新股票列表。仅在列表为空或 force=True 时从网络拉取。"""
        # 直接查询表中记录数
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stock_list")
        count = cursor.fetchone()[0]
        
        if count > 0 and not force:
            logger.info(f"ℹ️ Stock list already cached ({count} stocks)")
            return
        
        logger.info("📡 Updating A-share and HK-share stock list from akshare...")
        try:
            # A-share
            df_a = ak.stock_zh_a_spot_em()
            df_a = df_a[['代码', '名称']].copy()
            df_a.columns = ['code', 'name']
            
            # HK-share
            df_hk = ak.stock_hk_spot_em()
            df_hk = df_hk[['代码', '名称']].copy()
            df_hk.columns = ['code', 'name']
            
            # Combine
            df_combined = pd.concat([df_a, df_hk], ignore_index=True)
            
            self.db.save_stock_list(df_combined)
            logger.info(f"✅ Cached {len(df_combined)} stocks (A-share + HK) to database.")
        except Exception as e:
            logger.error(f"❌ Failed to sync stock list: {e}")


    def search_ticker(self, query: str, limit: int = 5) -> List[Dict]:
        """
        模糊搜索 A 股股票代码或名称，支持常见缩写。
        """
        # 清洗后缀 (如 CATL.SZ -> CATL, 000001.SZ -> 000001)
        clean_query = re.sub(r'\.(SZ|SH|HK|US)$', '', query, flags=re.IGNORECASE)
        
        # 常见缩写映射
        aliases = {
            "CATL": "宁德时代",
            "BYD": "比亚迪",
            "TSLA": "特斯拉",
            "Moutai": "贵州茅台",
            "Tencent": "腾讯",
            "Alibaba": "阿里巴巴",
            "Meituan": "美团",
        }
        
        search_query = aliases.get(clean_query.upper(), clean_query)
        
        # Robustness: if regex-like ticker code is embedded in query (e.g. "300364 中文在线"), try to extract it
        if not search_query.isdigit():
             # Extract explicit 5-6 digit codes
             match = re.search(r'\b(\d{5,6})\b', clean_query)
             if match:
                 search_query = match.group(1)

        return self.db.search_stock(search_query, limit)

    def get_stock_price(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_sync: bool = False,
    ) -> pd.DataFrame:
        """
        获取指定股票的历史价格数据。优先从本地缓存读取，智能增量补齐缺失数据。

        Args:
            ticker: 股票代码，如 "600519"（贵州茅台）或 "000001"（平安银行）。
            start_date: 开始日期，格式 "YYYY-MM-DD"。默认为 90 天前。
            end_date: 结束日期，格式 "YYYY-MM-DD"。默认为今天。
            force_sync: 强制从网络重新获取数据。

        Returns:
            包含 date, open, close, high, low, volume, change_pct 列的 DataFrame。
        """
        now = datetime.now()
        if not end_date:
            end_date = now.strftime('%Y-%m-%d')
        if not start_date:
            start_date = (now - timedelta(days=90)).strftime('%Y-%m-%d')

        # 清洗 ticker，确保只包含数字
        clean_ticker = "".join(filter(str.isdigit, ticker))
        if not clean_ticker:
            logger.warning(f"⚠️ Unsupported ticker format (A/H only): {ticker}")
            return pd.DataFrame()

        # Check cache coverage
        df_db = self.db.get_stock_prices(clean_ticker, start_date, end_date)

        if force_sync:
            # Force full refresh
            logger.info(f"🔄 Force sync requested for {clean_ticker}")
            self._fetch_and_cache_range(clean_ticker, start_date, end_date)
            return self.db.get_stock_prices(clean_ticker, start_date, end_date)

        # Smart incremental: find gaps in coverage
        if df_db.empty:
            # No cache, fetch full range
            logger.info(f"📡 No cache for {clean_ticker}, fetching {start_date} to {end_date}")
            self._fetch_and_cache_range(clean_ticker, start_date, end_date)
        else:
            # Find gaps
            gaps = self._find_date_gaps(df_db, start_date, end_date)

            if gaps:
                logger.info(f"📊 Cache partial for {clean_ticker}, fetching {len(gaps)} gap(s)")
                for gap_start, gap_end in gaps:
                    logger.info(f"  → Fetching gap: {gap_start} to {gap_end}")
                    self._fetch_and_cache_range(clean_ticker, gap_start, gap_end)
            else:
                # Check if data is fresh (within 2 days)
                db_latest = pd.to_datetime(df_db['date'].max())
                req_latest = pd.to_datetime(end_date)
                if (req_latest - db_latest).days > 2:
                    # Need to extend cache
                    extend_start = (db_latest + timedelta(days=1)).strftime('%Y-%m-%d')
                    logger.info(f"📈 Extending cache for {clean_ticker}: {extend_start} to {end_date}")
                    self._fetch_and_cache_range(clean_ticker, extend_start, end_date)
                else:
                    logger.info(f"✅ Cache hit for {clean_ticker} ({len(df_db)} rows)")

        # Return merged result from cache
        return self.db.get_stock_prices(clean_ticker, start_date, end_date)

    def _find_date_gaps(
        self,
        cached_df: pd.DataFrame,
        start_date: str,
        end_date: str
    ) -> List[tuple]:
        """
        Find date gaps between requested range and cached data.

        Returns list of (gap_start, gap_end) tuples.
        """
        gaps = []

        cached_dates = set(pd.to_datetime(cached_df['date']).dt.strftime('%Y-%m-%d'))

        # Generate expected trading days (simplified: exclude weekends)
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        expected_dates = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # Skip weekends
                expected_dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        if not expected_dates:
            return gaps

        # Find missing dates
        missing_dates = [d for d in expected_dates if d not in cached_dates]

        if not missing_dates:
            return gaps

        # Group consecutive missing dates into ranges
        gap_start = missing_dates[0]
        gap_end = missing_dates[0]

        for i in range(1, len(missing_dates)):
            curr = datetime.strptime(missing_dates[i], "%Y-%m-%d")
            prev = datetime.strptime(missing_dates[i-1], "%Y-%m-%d")

            if (curr - prev).days <= 3:  # Allow for weekends
                gap_end = missing_dates[i]
            else:
                gaps.append((gap_start, gap_end))
                gap_start = missing_dates[i]
                gap_end = missing_dates[i]

        # Don't forget the last gap
        gaps.append((gap_start, gap_end))

        return gaps

    def _fetch_and_cache_range(self, ticker: str, start_date: str, end_date: str) -> bool:
        """Fetch data for a specific date range and cache it."""
        try:
            s_fmt = start_date.replace("-", "")
            e_fmt = end_date.replace("-", "")

            df_remote = None

            # Determine if HK or A-share based on length
            if len(ticker) == 5:
                df_remote = ak.stock_hk_hist(
                    symbol=ticker, period="daily",
                    start_date=s_fmt, end_date=e_fmt,
                    adjust="qfq"
                )
            else:
                df_remote = ak.stock_zh_a_hist(
                    symbol=ticker, period="daily",
                    start_date=s_fmt, end_date=e_fmt,
                    adjust="qfq"
                )

            if df_remote is not None and not df_remote.empty:
                df_remote = df_remote.rename(columns={
                    '日期': 'date', '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low', '成交量': 'volume',
                    '涨跌幅': 'change_pct'
                })
                df_remote['date'] = pd.to_datetime(df_remote['date']).dt.strftime('%Y-%m-%d')

                self.db.save_stock_prices(ticker, df_remote)
                logger.info(f"✅ Cached {len(df_remote)} rows for {ticker} ({start_date} to {end_date})")
                return True
            else:
                logger.warning(f"⚠️ No data returned for {ticker} ({start_date} to {end_date})")
                return False

        except KeyError as e:
            logger.warning(f"⚠️ Akshare data missing for {ticker}: {e}")
        except (RequestException, ConnectionError) as e:
            logger.error(f"❌ Network error for {ticker}: {e}")
        except Exception as e:
            logger.error(f"❌ Error fetching {ticker}: {e}")

        return False


def get_stock_analysis(ticker: str, db: DatabaseManager) -> str:
    """
    生成指定股票的分析摘要报告。
    
    Args:
        ticker: 股票代码
        db: 数据库管理器实例
    
    Returns:
        Markdown 格式的分析报告，包含价格走势和关键指标。
    """
    tools = StockTools(db)
    df = tools.get_stock_price(ticker)
    
    if df.empty:
        return f"❌ 未能获取 {ticker} 的股价数据。"
    
    latest = df.iloc[-1]
    change = ((latest['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
    
    report = [
        f"## 📊 {ticker} 分析报告",
        f"- **查询时段**: {df.iloc[0]['date']} -> {latest['date']}",
        f"- **当前价**: ¥{latest['close']:.2f}",
        f"- **时段涨跌**: {change:+.2f}%",
        f"- **最高/最低**: ¥{df['high'].max():.2f} / ¥{df['low'].min():.2f}",
        "\n### 最近交易概览",
        "```",
        df.tail(5)[['date', 'close', 'change_pct', 'volume']].to_string(index=False),
        "```"
    ]
    return "\n".join(report)
