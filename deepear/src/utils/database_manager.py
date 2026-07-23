import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
import pandas as pd
from loguru import logger

from shared.db import configure_sqlite_connection, ensure_parent_dir


class DatabaseManager:
    """
    AlphaEar 数据库管理器 - 负责存储热点数据、搜索缓存和股价数据
    使用 SQLite 进行持久化存储
    
    支持上下文管理器，确保连接正确关闭：
    
    Example:
        # 方式1: 使用上下文管理器（推荐）
        with DatabaseManager() as db:
            db.save_signal(data)
        # 连接自动关闭
        
        # 方式2: 显式关闭
        db = DatabaseManager()
        db.save_signal(data)
        db.close()
    """
    
    def __init__(self, db_path: str = "data/signal_flux.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        self._connect()
    
    def _connect(self):
        """建立数据库连接（延迟初始化）"""
        if self._conn is not None:
            return
            
        ensure_parent_dir(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        configure_sqlite_connection(self._conn)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        logger.info(f"💾 Database connected: {self.db_path}")
    
    @property
    def conn(self) -> sqlite3.Connection:
        """获取数据库连接（自动连接）"""
        if self._closed:
            raise RuntimeError("Database connection is closed")
        if self._conn is None:
            self._connect()
        return self._conn

    def _init_db(self):
        """初始化表结构"""
        cursor = self.conn.cursor()
        
        # 1. 每日热点新闻表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_news (
                id TEXT PRIMARY KEY,
                source TEXT,
                rank INTEGER,
                title TEXT,
                url TEXT,
                content TEXT,
                publish_time TEXT,
                crawl_time TEXT,
                sentiment_score REAL,
                analysis TEXT,
                meta_data TEXT
            )
        """)
        
        # 尝试添加 analysis 列（如果表已存在但没有该列）
        try:
            cursor.execute("ALTER TABLE daily_news ADD COLUMN analysis TEXT")
        except Exception:
            pass  # 列已存在

        
        # 2. 搜索缓存表 (原有 JSON 缓存)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                query_hash TEXT PRIMARY KEY,
                query TEXT,
                engine TEXT,
                results TEXT,
                timestamp TEXT
            )
        """)

        # 2.5 搜索详情表 (展开的搜索结果)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_detail (
                id TEXT,
                query_hash TEXT,
                rank INTEGER,
                title TEXT,
                url TEXT,
                content TEXT,
                publish_time TEXT,
                crawl_time TEXT,
                sentiment_score REAL,
                source TEXT,
                meta_data TEXT,
                PRIMARY KEY (query_hash, id)
            )
        """)
        
        # 3. 股价数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_prices (
                ticker TEXT,
                date TEXT,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume REAL,
                change_pct REAL,
                PRIMARY KEY (ticker, date)
            )
        """)
        
        # 4. 股票列表表 (用于检索)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_list (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        
        # 5. 投资信号表 (ISQ Framework)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                title TEXT,
                summary TEXT,
                transmission_chain TEXT,
                sentiment_score REAL,
                confidence REAL,
                intensity INTEGER,
                expected_horizon TEXT,
                price_in_status TEXT,
                impact_tickers TEXT,
                industry_tags TEXT,
                sources TEXT,
                user_id TEXT,
                created_at TEXT
            )
        """)
        
        # 5.1 用户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT
            )
        """)

        # 5.2 邀请码表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invitation_codes (
                code TEXT PRIMARY KEY,
                is_used BOOLEAN DEFAULT 0,
                used_by INTEGER,
                created_at TEXT,
                FOREIGN KEY (used_by) REFERENCES users(id)
            )
        """)
        
        # 6. 创建索引以优化查询性能
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_crawl_time ON daily_news(crawl_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_source ON daily_news(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_cache_timestamp ON search_cache(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_prices_ticker_date ON stock_prices(ticker, date)")
        # 尝试添加 user_id 列到 signals 表
        try:
            cursor.execute("ALTER TABLE signals ADD COLUMN user_id TEXT")
        except Exception:
            pass
            
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_user_id ON signals(user_id)")

        # 7. 指数成分股缓存表 (for Smart Beta)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS index_constituents (
                index_code TEXT,
                trade_date TEXT,
                ticker TEXT,
                weight REAL,
                name TEXT,
                cached_at TEXT,
                PRIMARY KEY (index_code, trade_date, ticker)
            )
        """)

        # 8. 指数价格数据缓存表 (for Smart Beta)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS index_prices (
                index_code TEXT,
                date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                cached_at TEXT,
                PRIMARY KEY (index_code, date)
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_index_constituents_lookup ON index_constituents(index_code, trade_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_index_prices_lookup ON index_prices(index_code, date)")

        self.conn.commit()
        
        # 初始化邀请码
        self._ensure_invitation_code()

    # --- 新闻数据操作 ---
    
    def save_daily_news(self, news_list: List[Dict]) -> int:
        """保存热点新闻，包含发布时间与抓取时间"""
        cursor = self.conn.cursor()
        count = 0
        crawl_time = datetime.now().isoformat()
        
        for news in news_list:
            try:
                # 兼容不同来源的 ID 生成逻辑
                news_id = news.get('id') or f"{news.get('source')}_{news.get('rank')}_{crawl_time[:10]}"
                cursor.execute("""
                    INSERT OR REPLACE INTO daily_news 
                    (id, source, rank, title, url, content, publish_time, crawl_time, sentiment_score, meta_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    news_id,
                    news.get('source'),
                    news.get('rank'),
                    news.get('title'),
                    news.get('url'),
                    news.get('content', ''),
                    news.get('publish_time'), # 新增支持发布时间
                    crawl_time,
                    news.get('sentiment_score'),
                    json.dumps(news.get('meta_data', {}))
                ))
                count += 1
            except sqlite3.Error as e:
                logger.error(f"Database error saving news item {news.get('title')}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error saving news item {news.get('title')}: {e}")
        
        self.conn.commit()
        return count

    def get_daily_news(self, source: Optional[str] = None, limit: int = 100, days: int = 1) -> List[Dict]:
        """获取最近 N 天的热点新闻"""
        cursor = self.conn.cursor()
        # 使用 crawl_time 过滤，保证结果的新鲜度
        time_threshold = (datetime.now().timestamp() - days * 86400)
        time_threshold_str = datetime.fromtimestamp(time_threshold).isoformat()
        
        query = "SELECT * FROM daily_news WHERE crawl_time >= ?"
        params = [time_threshold_str]
        
        if source:
            query += " AND source = ?"
            params.append(source)
            
        query += " ORDER BY crawl_time DESC, rank LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def lookup_reference_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Best-effort lookup of a source item by URL.

        This is used to render a stable bibliography from DB-backed metadata.
        It searches both `daily_news` and `search_detail`.
        """
        url = (url or "").strip()
        if not url:
            return None

        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                SELECT title, source, publish_time, crawl_time, url
                FROM daily_news
                WHERE url = ?
                ORDER BY crawl_time DESC
                LIMIT 1
                """,
                (url,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        except Exception:
            pass

        try:
            cursor.execute(
                """
                SELECT title, source, publish_time, crawl_time, url
                FROM search_detail
                WHERE url = ?
                ORDER BY crawl_time DESC
                LIMIT 1
                """,
                (url,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        except Exception:
            pass

        return None

    def delete_news(self, news_id: str) -> bool:
        """删除特定新闻"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM daily_news WHERE id = ?", (news_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def update_news_content(self, news_id: str, content: str = None, analysis: str = None) -> bool:
        """更新新闻的内容或分析结果"""
        cursor = self.conn.cursor()
        updates = []
        params = []
        
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if analysis is not None:
            updates.append("analysis = ?")
            params.append(analysis)
            
        if not updates:
            return False
            
        params.append(news_id)
        query = f"UPDATE daily_news SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        self.conn.commit()
        return cursor.rowcount > 0

    # --- 搜索缓存辅助 ---
    
    def get_search_cache(self, query_hash: str, ttl_seconds: Optional[int] = None) -> Optional[Dict]:
        """获取搜索缓存 (优先查 search_detail)"""
        cursor = self.conn.cursor()
        
        # 1. 尝试从 search_detail 获取展开的结构化数据
        cursor.execute("""
            SELECT * FROM search_detail 
            WHERE query_hash = ? 
            ORDER BY rank
        """, (query_hash,))
        details = [dict(row) for row in cursor.fetchall()]
        
        if details:
            # 检查 TTL (取第一条的时间)
            first_time = datetime.fromisoformat(details[0]['crawl_time'])
            if ttl_seconds and (datetime.now() - first_time).total_seconds() > ttl_seconds:
                logger.info(f"⌛ Detailed cache expired for hash {query_hash}")
                pass # Expired, fall through or return None? If Detail expired, Cache likely expired too.
                # But let's check basic cache just in case metadata differs? 
                # Actually if details exist, we prefer them. If expired, we return None.
                return None
            
            logger.info(f"✅ Hit detailed search cache for {query_hash} ({len(details)} items)")
            # Reconstruct the expected 'results' list format for SearchTools
            # SearchTools expects a list of dicts. 
            # We return a dict wrapper to match get_search_cache signature returning Dict usually containing 'results' string.
            # But SearchTools logic: 
            # cache = db.get_search_cache(...)
            # cached_data = json.loads(cache['results'])
            
            # To minimize SearchTools changes, we can return a dict mimicking the old structure
            # OR Change SearchTools to handle list return.
            # Let's return a special dict that SearchTools can recognize or just format it as before.
            return {"results": json.dumps(details), "timestamp": details[0]['crawl_time']}

        # 2. Fallback to old table
        cursor.execute("SELECT * FROM search_cache WHERE query_hash = ?", (query_hash,))
        row = cursor.fetchone()
        
        if not row:
            return None
            
        row_dict = dict(row)
        if ttl_seconds:
            cache_time = datetime.fromisoformat(row_dict['timestamp'])
            if (datetime.now() - cache_time).total_seconds() > ttl_seconds:
                logger.info(f"⌛ Cache expired for hash {query_hash}")
                return None
                
        return row_dict

    def save_search_cache(self, query_hash: str, query: str, engine: str, results: Union[str, List[Dict]]):
        """保存搜索结果 (同时保存到 search_cache 和 search_detail)"""
        cursor = self.conn.cursor()
        current_time = datetime.now().isoformat()
        
        results_str = results if isinstance(results, str) else json.dumps(results)
        
        # 1. Save summary to search_cache
        cursor.execute("""
            INSERT OR REPLACE INTO search_cache (query_hash, query, engine, results, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (query_hash, query, engine, results_str, current_time))
        
        # 2. Save details to search_detail if results is a list
        if isinstance(results, list):
            for item in results:
                try:
                    item_id = item.get('id') or f"{hash(item.get('url', ''))}"
                    cursor.execute("""
                        INSERT OR REPLACE INTO search_detail
                        (id, query_hash, rank, title, url, content, publish_time, crawl_time, sentiment_score, source, meta_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(item_id),
                        query_hash,
                        item.get('rank', 0),
                        item.get('title'),
                        item.get('url'),
                        item.get('content', ''),
                        item.get('publish_time'),
                        item.get('crawl_time') or current_time,
                        item.get('sentiment_score'),
                        item.get('source'),
                        json.dumps(item.get('meta_data', {}))
                    ))
                except sqlite3.Error as e:
                    logger.error(f"Database error saving search detail {item.get('title')}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error saving search detail {item.get('title')}: {e}")
                    
        self.conn.commit()

    def find_similar_queries(self, query: str, limit: int = 5) -> List[Dict]:
        """模糊搜索相似的已缓存查询"""
        cursor = self.conn.cursor()
        
        # Simple fuzzy match: query in cached OR cached in query
        q_wild = f"%{query}%"
        cursor.execute("""
            SELECT query, query_hash, timestamp, results 
            FROM search_cache 
            WHERE query LIKE ? OR ? LIKE ('%' || query || '%')
            ORDER BY timestamp DESC
            LIMIT ?
        """, (q_wild, query, limit))
        
        return [dict(row) for row in cursor.fetchall()]

    def search_local_news(self, query: str, limit: int = 5) -> List[Dict]:
        """从本地 daily_news 搜索相关新闻"""
        cursor = self.conn.cursor()
        q_wild = f"%{query}%"
        # Search title and content
        cursor.execute("""
            SELECT * FROM daily_news
            WHERE title LIKE ? OR content LIKE ?
            ORDER BY crawl_time DESC
            LIMIT ?
        """, (q_wild, q_wild, limit))
        return [dict(row) for row in cursor.fetchall()]

    # --- 股票数据操作 ---

    def save_stock_list(self, df: pd.DataFrame):
        """保存股票列表到 stock_list 表"""
        cursor = self.conn.cursor()
        try:
            # 清空旧表
            cursor.execute("DELETE FROM stock_list")
            
            # 批量插入
            data = df[['code', 'name']].to_dict('records')
            cursor.executemany(
                "INSERT INTO stock_list (code, name) VALUES (:code, :name)",
                data
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error saving stock list: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving stock list: {e}")

    def search_stock(self, query: str, limit: int = 5) -> List[Dict]:
        """模糊搜索股票代码或名称"""
        cursor = self.conn.cursor()
        wild = f"%{query}%"
        cursor.execute("""
            SELECT code, name FROM stock_list 
            WHERE code LIKE ? OR name LIKE ? 
            LIMIT ?
        """, (wild, wild, limit))
        return [dict(row) for row in cursor.fetchall()]

    def get_stock_by_code(self, code: str) -> Optional[Dict[str, str]]:
        """精确按代码获取股票信息。

        Args:
            code: 股票代码（A股6位 / 港股5位），必须为纯数字字符串。

        Returns:
            dict: {"code": str, "name": str} 或 None。
        """
        if not code:
            return None
        clean = "".join([c for c in str(code).strip() if c.isdigit()])
        if not clean:
            return None

        cursor = self.conn.cursor()
        cursor.execute("SELECT code, name FROM stock_list WHERE code = ? LIMIT 1", (clean,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_stock_prices(self, ticker: str, df: pd.DataFrame):
        """保存股价历史数据"""
        if df.empty:
            return
            
        cursor = self.conn.cursor()
        
        # 确保 DataFrame 有必要的列
        required_cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'change_pct']
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"Missing column {col} in stock data for {ticker}")
                return

        try:
            for _, row in df.iterrows():
                cursor.execute("""
                    INSERT OR REPLACE INTO stock_prices 
                    (ticker, date, open, close, high, low, volume, change_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker,
                    row['date'],
                    row['open'],
                    row['close'],
                    row['high'],
                    row['low'],
                    row['volume'],
                    row['change_pct']
                ))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error saving stock prices for {ticker}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving stock prices for {ticker}: {e}")

    def get_stock_prices(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取指定日期范围的股价数据"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT * FROM stock_prices 
            WHERE ticker = ? AND date >= ? AND date <= ?
            ORDER BY date
        """, (ticker, start_date, end_date))
        
        rows = cursor.fetchall()
        if not rows:
            return pd.DataFrame()
            
        columns = ['ticker', 'date', 'open', 'close', 'high', 'low', 'volume', 'change_pct']
        return pd.DataFrame([dict(row) for row in rows], columns=columns)

    def execute_query(self, query: str, params: tuple = ()) -> List[Any]:
        """执行自定义 SQL 查询"""
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            if query.strip().upper().startswith("SELECT"):
                return cursor.fetchall()
            else:
                self.conn.commit()
                return []
        except sqlite3.Error as e:
            logger.error(f"SQL execution failed (Database error): {e}")
            return []
        except Exception as e:
            logger.error(f"SQL execution failed (Unexpected error): {e}")
            return []

    # --- 投资信号操作 (ISQ Framework) ---

    def save_signal(self, signal: Dict[str, Any]):
        """保存投资信号"""
        cursor = self.conn.cursor()
        created_at = datetime.now().isoformat()
        
        cursor.execute("""
            INSERT OR REPLACE INTO signals 
            (signal_id, title, summary, transmission_chain, sentiment_score, 
             confidence, intensity, expected_horizon, price_in_status, 
             impact_tickers, industry_tags, sources, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.get('signal_id'),
            signal.get('title'),
            signal.get('summary'),
            json.dumps(signal.get('transmission_chain', [])),
            signal.get('sentiment_score', 0.0),
            signal.get('confidence', 0.0),
            signal.get('intensity', 1),
            signal.get('expected_horizon', 'T+0'),
            signal.get('price_in_status', '未知'),
            json.dumps(signal.get('impact_tickers', [])),
            json.dumps(signal.get('industry_tags', [])),
            json.dumps(signal.get('sources', [])),
            signal.get('user_id'),
            created_at
        ))
        self.conn.commit()

    def get_recent_signals(self, limit: int = 20, user_id: Optional[str] = None) -> List[Dict]:
        """获取最近的投资信号"""
        cursor = self.conn.cursor()
        if user_id:
            cursor.execute("SELECT * FROM signals WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
        else:
            cursor.execute("SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        
        signals = []
        for row in rows:
            d = dict(row)
            # 解析 JSON 字段
            for field in ['transmission_chain', 'impact_tickers', 'industry_tags', 'sources']:
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except Exception:
                        pass
            signals.append(d)
        return signals

    # --- 用户管理 ---

    def _ensure_invitation_code(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM invitation_codes WHERE is_used = 0")
        code_count = cursor.fetchone()[0]
        
        if user_count == 0 and code_count == 0:
            initial_code = "DEEP-EAR-ADMIN"
            cursor.execute("INSERT OR IGNORE INTO invitation_codes (code, created_at) VALUES (?, ?)", 
                          (initial_code, datetime.now().isoformat()))
            self.conn.commit()
            logger.info(f"🔑 Generate Initial Invitation Code: {initial_code}")

    def create_invitation_code(self, code: str) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO invitation_codes (code, created_at) VALUES (?, ?)", 
                          (code, datetime.now().isoformat()))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def verify_invitation_code(self, code: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM invitation_codes WHERE code = ? AND is_used = 0", (code,))
        return cursor.fetchone() is not None

    def create_user(self, username: str, password_hash: str, invitation_code: str) -> bool:
        cursor = self.conn.cursor()
        
        # Verify invitation code
        cursor.execute("SELECT code FROM invitation_codes WHERE code = ? AND is_used = 0", (invitation_code,))
        if not cursor.fetchone():
            return False
            
        try:
            # Create user
            cursor.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                          (username, password_hash, datetime.now().isoformat()))
            user_id = cursor.lastrowid
            
            # Mark code as used
            cursor.execute("UPDATE invitation_codes SET is_used = 1, used_by = ? WHERE code = ?",
                          (user_id, invitation_code))
            
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # --- 指数数据缓存 (for Smart Beta) ---

    def get_index_constituents(self, index_code: str, trade_date: str, max_age_days: int = 1) -> Optional[List[Dict]]:
        """
        获取指数成分股缓存

        Args:
            index_code: 指数代码 (e.g., '000300.SH')
            trade_date: 交易日期 (YYYY-MM-DD)
            max_age_days: 缓存最大年龄（天），默认1天

        Returns:
            List of dicts with 'ticker', 'weight', 'name' or None if cache miss or expired
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT ticker, weight, name, cached_at FROM index_constituents
                WHERE index_code = ? AND trade_date = ?
            """, (index_code, trade_date))

            rows = cursor.fetchall()
            if not rows:
                return None

            # Check cache age
            cached_at = datetime.fromisoformat(rows[0]['cached_at'])
            age = datetime.now() - cached_at
            if age.days >= max_age_days:
                logger.debug(f"Cache expired for {index_code} on {trade_date} (age: {age.days} days)")
                return None

            constituents = []
            for row in rows:
                constituents.append({
                    'ticker': row['ticker'],
                    'weight': row['weight'],
                    'name': row['name']
                })

            logger.debug(f"Cache hit for {index_code} constituents on {trade_date}: {len(constituents)} stocks")
            return constituents

        except Exception as e:
            logger.warning(f"Error reading index constituents cache: {e}")
            return None

    def save_index_constituents(self, index_code: str, trade_date: str, constituents: List[Dict]):
        """
        保存指数成分股到缓存

        Args:
            index_code: 指数代码
            trade_date: 交易日期 (YYYY-MM-DD)
            constituents: List of dicts with 'ticker', 'weight', 'name'
        """
        try:
            cursor = self.conn.cursor()
            cached_at = datetime.now().isoformat()

            # Delete old entries for this index/date
            cursor.execute("""
                DELETE FROM index_constituents WHERE index_code = ? AND trade_date = ?
            """, (index_code, trade_date))

            # Insert new entries
            for c in constituents:
                cursor.execute("""
                    INSERT INTO index_constituents (index_code, trade_date, ticker, weight, name, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    index_code,
                    trade_date,
                    c.get('ticker', ''),
                    c.get('weight', 0),
                    c.get('name', ''),
                    cached_at
                ))

            self.conn.commit()
            logger.debug(f"Saved {len(constituents)} constituents for {index_code} on {trade_date}")

        except Exception as e:
            logger.error(f"Error saving index constituents cache: {e}")
            self.conn.rollback()

    def get_index_prices(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取指数价格数据缓存

        Args:
            index_code: 指数代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)

        Returns:
            DataFrame with OHLCV data (empty if cache miss)
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT date, open, high, low, close, volume, amount
                FROM index_prices
                WHERE index_code = ? AND date >= ? AND date <= ?
                ORDER BY date
            """, (index_code, start_date, end_date))

            rows = cursor.fetchall()
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame([dict(row) for row in rows])
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)

            logger.debug(f"Cache hit for {index_code} prices: {len(df)} rows")
            return df

        except Exception as e:
            logger.warning(f"Error reading index prices cache: {e}")
            return pd.DataFrame()

    def save_index_prices(self, index_code: str, df: pd.DataFrame):
        """
        保存指数价格数据到缓存

        Args:
            index_code: 指数代码
            df: DataFrame with columns ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
        """
        if df.empty:
            return

        try:
            cursor = self.conn.cursor()
            cached_at = datetime.now().isoformat()

            # Ensure date column exists
            if 'date' not in df.columns:
                df = df.reset_index()

            for _, row in df.iterrows():
                date_str = row['date']
                if isinstance(date_str, pd.Timestamp):
                    date_str = date_str.strftime('%Y-%m-%d')

                cursor.execute("""
                    INSERT OR REPLACE INTO index_prices
                    (index_code, date, open, high, low, close, volume, amount, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    index_code,
                    date_str,
                    float(row.get('open', 0)),
                    float(row.get('high', 0)),
                    float(row.get('low', 0)),
                    float(row.get('close', 0)),
                    float(row.get('volume', 0)),
                    float(row.get('amount', 0)),
                    cached_at
                ))

            self.conn.commit()
            logger.debug(f"Saved {len(df)} price rows for {index_code}")

        except Exception as e:
            logger.error(f"Error saving index prices cache: {e}")
            self.conn.rollback()

    def close(self):
        """
        关闭数据库连接。
        
        安全地关闭连接，可以多次调用不会报错。
        """
        if self._conn is not None:
            try:
                self._conn.close()
                logger.info(f"💾 Database closed: {self.db_path}")
            except Exception as e:
                logger.warning(f"Error closing database: {e}")
            finally:
                self._conn = None
                self._closed = True
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口 - 确保连接关闭"""
        self.close()
        return False  # 不吞掉异常
    
    def __del__(self):
        """析构函数 - 确保连接被清理"""
        if hasattr(self, '_conn') and self._conn is not None:
            self.close()

