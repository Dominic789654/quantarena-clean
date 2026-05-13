"""Router for APIs"""

import functools
import os
import time
from typing import Any, Dict, Optional

from apis import YFinanceAPI, AlphaVantageAPI, FMPAPI, TavilyNewsAPI, AKShareNewsAPI
from apis.tushare import TushareAPI
from shared.config.provider_routing import default_us_data_provider, preferred_us_data_provider

# Import stats for API call tracking
try:
    from deepear.src.utils.stats import get_stats
    STATS_AVAILABLE = True
except ImportError:
    STATS_AVAILABLE = False


def track_api_call(category: Optional[str] = None):
    """
    Decorator to track API calls with timing and success/failure status.

    Args:
        category: API category name (e.g., 'tushare', 'alpha_vantage', 'yfinance').
            If None, use router instance category.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not STATS_AVAILABLE:
                return func(*args, **kwargs)

            start_time = time.time()
            api_category = category
            if api_category is None and args:
                api_category = getattr(args[0], "_api_category", "unknown")
            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.time() - start_time) * 1000
                get_stats().record_api_call(api_category, success=True, time_ms=elapsed_ms)
                return result
            except Exception:
                elapsed_ms = (time.time() - start_time) * 1000
                get_stats().record_api_call(api_category, success=False, time_ms=elapsed_ms)
                raise
        return wrapper
    return decorator


class APISource:
    YFINANCE = "yfinance"
    ALPHA_VANTAGE = "alpha_vantage"
    TUSHARE = "tushare"
    FMP = "fmp"

    _ALIASES = {
        "alpha": ALPHA_VANTAGE,
        "alphavantage": ALPHA_VANTAGE,
        "alpha_vantage": ALPHA_VANTAGE,
        "yfinance": YFINANCE,
        "yf": YFINANCE,
        "tushare": TUSHARE,
        "fmp": FMP,
        "financialmodelingprep": FMP,
    }

    @classmethod
    def from_string(cls, value: Optional[str]) -> str:
        key = (value or "").strip().lower()
        if key in cls._ALIASES:
            return cls._ALIASES[key]
        raise ValueError(f"Invalid API source: {value}")


def _fallback_us_api_source() -> str:
    """Return the default US provider, preferring FMP when configured."""
    return default_us_data_provider()


def build_api_source_config(
    market: str,
    api_source_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Merge config + env overrides into a normalized api_source mapping."""
    cfg = dict(api_source_config or {})
    market_key = (market or "us").strip().lower()

    cn_source = str(
        os.environ.get(
            "DEEPFUND_CN_API_SOURCE",
            cfg.get("cn_source") or cfg.get("default") or APISource.TUSHARE,
        )
    ).strip() or APISource.TUSHARE

    us_source = preferred_us_data_provider(
        configured=str(cfg.get("us_source") or cfg.get("default") or "").strip(),
        env_override=os.environ.get("DEEPFUND_US_API_SOURCE", ""),
    )

    default_source = cn_source if market_key == "cn" else us_source
    return {
        "default": default_source,
        "cn_source": cn_source,
        "us_source": us_source,
    }


def resolve_api_source(market: str, api_source_config: Optional[Dict[str, Any]] = None) -> str:
    """Resolve API source by market + config with backward-compatible fallbacks."""
    cfg = build_api_source_config(market, api_source_config)
    market_key = (market or "us").strip().lower()

    if market_key == "cn":
        preferred = cfg.get("cn_source") or cfg.get("default") or APISource.TUSHARE
        try:
            resolved = APISource.from_string(preferred)
        except ValueError:
            return APISource.TUSHARE
        return APISource.TUSHARE if resolved != APISource.TUSHARE else resolved

    preferred = cfg.get("us_source") or cfg.get("default") or _fallback_us_api_source()
    try:
        resolved = APISource.from_string(preferred)
    except ValueError:
        return _fallback_us_api_source()
    return resolved if resolved in {APISource.FMP, APISource.ALPHA_VANTAGE, APISource.YFINANCE} else _fallback_us_api_source()


class Router():
    """Router for APIs"""

    def __init__(self, source: str, news_provider: str | None = None):
        self._source = source
        self._tavily_news_api = None
        self._akshare_news_api = None
        self._news_provider = (news_provider or os.getenv("COMPANY_NEWS_PROVIDER", "default")).strip().lower()

        if source == APISource.YFINANCE:
            self.api = YFinanceAPI()
            self._api_category = "yfinance"
        elif source == APISource.ALPHA_VANTAGE:
            self.api = AlphaVantageAPI()
            self._api_category = "alpha_vantage"
        elif source == APISource.FMP:
            self.api = FMPAPI()
            self._api_category = "fmp"
        elif source == APISource.TUSHARE:
            self.api = TushareAPI()
            self._api_category = "tushare"
        else:
            raise ValueError(f"Invalid API source: {source}")

    def _should_use_tavily_news(self) -> bool:
        if self._news_provider in {"tavily", "tavily_strict"}:
            return True
        if self._news_provider == "auto":
            return bool(os.getenv("TAVILY_API_KEY", "").strip())
        return False

    def _should_use_akshare_news(self) -> bool:
        if self._news_provider in {"akshare", "akshare_strict"}:
            return True
        if self._news_provider == "auto":
            return not bool(os.getenv("TAVILY_API_KEY", "").strip())
        return False

    def _is_tavily_strict(self) -> bool:
        return self._news_provider == "tavily_strict"

    def _is_akshare_strict(self) -> bool:
        return self._news_provider == "akshare_strict"

    def _get_tavily_api(self) -> TavilyNewsAPI:
        if self._tavily_news_api is None:
            self._tavily_news_api = TavilyNewsAPI()
        return self._tavily_news_api

    def _get_akshare_api(self) -> AKShareNewsAPI:
        if self._akshare_news_api is None:
            self._akshare_news_api = AKShareNewsAPI()
        return self._akshare_news_api

    def _call_with_stats(self, category: str, func, *args, **kwargs):
        if not STATS_AVAILABLE:
            return func(*args, **kwargs)

        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed_ms = (time.time() - start_time) * 1000
            get_stats().record_api_call(category, success=True, time_ms=elapsed_ms)
            return result
        except Exception:
            elapsed_ms = (time.time() - start_time) * 1000
            get_stats().record_api_call(category, success=False, time_ms=elapsed_ms)
            raise

    @staticmethod
    def _log_news_fetch(
        provider: str,
        market: str,
        ticker: str,
        trading_date,
        item_count: int | None = None,
        error: Exception | None = None,
        strict: bool = False,
    ) -> None:
        date_str = trading_date.strftime("%Y-%m-%d") if hasattr(trading_date, "strftime") else str(trading_date)
        base = f"[company_news] provider={provider} market={market} ticker={ticker} date={date_str}"
        if error is not None:
            strict_tag = " strict=1" if strict else ""
            print(f"{base} status=error error={type(error).__name__}{strict_tag}")
            return
        print(f"{base} status=ok items={item_count if item_count is not None else 0}")

    def get_us_stock_news(self, ticker, trading_date, news_count):
        if self._should_use_tavily_news():
            try:
                tavily_api = self._get_tavily_api()
                news = self._call_with_stats(
                    "tavily_news",
                    tavily_api.get_news,
                    ticker=ticker,
                    trading_date=trading_date,
                    limit=news_count,
                    market="us",
                )
                is_cache_hit = bool(getattr(tavily_api, "last_cache_hit", False))
                provider = "tavily_cache" if is_cache_hit else "tavily"
                if is_cache_hit:
                    cache_source = str(getattr(tavily_api, "last_source", "")).strip().lower()
                    if cache_source.startswith("snapshot:"):
                        snapshot_source = cache_source.split(":", 1)[1] or "unknown"
                        provider = f"snapshot_{snapshot_source}"
                if is_cache_hit and STATS_AVAILABLE:
                    get_stats().record_api_call("tavily_news_cache_hit", success=True, time_ms=0.0)
                self._log_news_fetch(provider, "us", ticker, trading_date, item_count=len(news))
                if news or self._is_tavily_strict():
                    return news
            except Exception as e:
                self._log_news_fetch("tavily", "us", ticker, trading_date, error=e, strict=self._is_tavily_strict())
                if self._is_tavily_strict():
                    raise

        if isinstance(self.api, YFinanceAPI):
            news = self._call_with_stats(
                "yfinance_news",
                self.api.get_news,
                query=ticker,
                news_count=news_count,
            )
            self._log_news_fetch("yfinance", "us", ticker, trading_date, item_count=len(news))
            return news

        category = "fmp_news" if isinstance(self.api, FMPAPI) else "alpha_vantage_news"
        provider = "fmp" if isinstance(self.api, FMPAPI) else "alpha_vantage"
        news = self._call_with_stats(
            category,
            self.api.get_news,
            ticker=ticker,
            trading_date=trading_date,
            limit=news_count,
        )
        self._log_news_fetch(provider, "us", ticker, trading_date, item_count=len(news))
        return news

    @track_api_call()
    def get_market_news(self, topic, trading_date, news_count):
        if isinstance(self.api, YFinanceAPI):
            return self.api.get_news(query=topic, news_count=news_count)
        return self.api.get_news(topic=topic, trading_date=trading_date, limit=news_count)

    @track_api_call()
    def get_us_stock_insider_trades(self, ticker, trading_date, limit):
        return self.api.get_insider_trades(ticker, trading_date, limit)

    @track_api_call()
    def get_us_stock_daily_candles_df(self, ticker, trading_date):
        return self.api.get_daily_candles_df(ticker, trading_date)

    @track_api_call()
    def get_us_stock_last_close_price(self, ticker, trading_date):
        return self.api.get_last_close_price(ticker, trading_date)

    @track_api_call()
    def get_us_stock_fundamentals(self, ticker):
        return self.api.get_fundamentals(ticker)

    @track_api_call()
    def get_us_economic_indicators(self):
        return self.api.get_economic_indicators()

    def get_cn_stock_news(self, ticker, trading_date, news_count):
        if self._should_use_tavily_news():
            try:
                tavily_api = self._get_tavily_api()
                news = self._call_with_stats(
                    "tavily_news",
                    tavily_api.get_news,
                    ticker=ticker,
                    trading_date=trading_date,
                    limit=news_count,
                    market="cn",
                )
                is_cache_hit = bool(getattr(tavily_api, "last_cache_hit", False))
                provider = "tavily_cache" if is_cache_hit else "tavily"
                if is_cache_hit:
                    cache_source = str(getattr(tavily_api, "last_source", "")).strip().lower()
                    if cache_source.startswith("snapshot:"):
                        snapshot_source = cache_source.split(":", 1)[1] or "unknown"
                        provider = f"snapshot_{snapshot_source}"
                if is_cache_hit and STATS_AVAILABLE:
                    get_stats().record_api_call("tavily_news_cache_hit", success=True, time_ms=0.0)
                self._log_news_fetch(provider, "cn", ticker, trading_date, item_count=len(news))
                if news or self._is_tavily_strict():
                    return news
            except Exception as e:
                self._log_news_fetch("tavily", "cn", ticker, trading_date, error=e, strict=self._is_tavily_strict())
                if self._is_tavily_strict():
                    raise

        if self._should_use_akshare_news():
            try:
                akshare_api = self._get_akshare_api()
                news = self._call_with_stats(
                    "akshare_news",
                    akshare_api.get_news,
                    ticker=ticker,
                    trading_date=trading_date,
                    limit=news_count,
                    market="cn",
                )
                is_cache_hit = bool(getattr(akshare_api, "last_cache_hit", False))
                source = str(getattr(akshare_api, "last_source", "")).strip().lower()
                provider = "akshare_cache" if is_cache_hit else "akshare"
                if source.startswith("snapshot:"):
                    snapshot_source = source.split(":", 1)[1] or "unknown"
                    if snapshot_source.startswith("network:"):
                        snapshot_source = snapshot_source.split(":", 1)[1] or "unknown"
                    provider = f"snapshot_{snapshot_source}"
                if source.startswith("network:"):
                    source_name = source.split(":", 1)[1] or "akshare"
                    provider = f"{source_name}_cache" if is_cache_hit else source_name
                self._log_news_fetch(provider, "cn", ticker, trading_date, item_count=len(news))
                return news
            except Exception as e:
                self._log_news_fetch("akshare", "cn", ticker, trading_date, error=e, strict=self._is_akshare_strict())
                if self._is_akshare_strict():
                    raise
                return []

        if isinstance(self.api, TushareAPI):
            news = self._call_with_stats(
                "tushare_news",
                self.api.get_news,
                ticker=ticker,
                trading_date=trading_date,
                limit=news_count,
            )
            self._log_news_fetch("tushare", "cn", ticker, trading_date, item_count=len(news))
            return news
        raise NotImplementedError(f"Chinese stock news not supported for {type(self.api).__name__}")

    @track_api_call("tushare")
    def get_cn_stock_daily_candles_df(self, ticker, trading_date):
        if isinstance(self.api, TushareAPI):
            return self.api.get_daily_candles_df(ticker, trading_date)
        raise NotImplementedError(f"Chinese stock candles not supported for {type(self.api).__name__}")

    @track_api_call("tushare")
    def get_cn_stock_last_close_price(self, ticker, trading_date):
        if isinstance(self.api, TushareAPI):
            return self.api.get_last_close_price(ticker, trading_date)
        raise NotImplementedError(f"Chinese stock price not supported for {type(self.api).__name__}")

    @track_api_call("tushare")
    def get_cn_stock_fundamentals(self, ticker):
        if isinstance(self.api, TushareAPI):
            return self.api.get_fundamentals(ticker)
        raise NotImplementedError(f"Chinese stock fundamentals not supported for {type(self.api).__name__}")

    @track_api_call("tushare")
    def get_cn_stock_insider_trades(self, ticker, trading_date, limit):
        if isinstance(self.api, TushareAPI):
            return self.api.get_insider_trades(ticker, trading_date, limit)
        raise NotImplementedError(f"Chinese stock insider trades not supported for {type(self.api).__name__}")

    @track_api_call("tushare")
    def get_cn_economic_indicators(self):
        if isinstance(self.api, TushareAPI):
            return self.api.get_economic_indicators()
        raise NotImplementedError(f"Chinese economic indicators not supported for {type(self.api).__name__}")
