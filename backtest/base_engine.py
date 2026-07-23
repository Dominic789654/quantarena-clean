"""
Base Backtest Engine
====================

Abstract base class for all backtest engines.
Provides common functionality for data loading, trading day management, and result collection.
"""

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from loguru import logger

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()

from backtest.data_loader import DataPrefetcher
from backtest.portfolio_tracker import PortfolioTracker
from backtest.report import ReportGenerator


class BaseBacktestEngine(ABC):
    """
    Abstract base class for backtest engines.

    Provides common functionality:
    - Data prefetching with caching
    - Trading day management
    - Portfolio tracking initialization
    - Report generation setup

    Subclasses must implement:
    - run(): Execute the backtest simulation
    """

    def __init__(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        initial_cash: float = 100000.0,
        market: str = "cn",
        config: Optional[Dict[str, Any]] = None,
        db_path: str = "data/signal_flux.db",
        use_llm: bool = False,
        analysts: Optional[List[str]] = None,
        personality: str = "balanced"
    ):
        """
        Initialize base backtest engine.

        Args:
            tickers: List of ticker symbols to trade
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            initial_cash: Starting capital
            market: Market type ("cn" for A-share, "us" for US stocks)
            config: Optional configuration dict
            db_path: Path to SQLite database for caching
            use_llm: Whether to use LLM for intelligent trading decisions
            analysts: List of analysts to use (e.g., ["fundamental", "technical"])
            personality: Investment personality (conservative, aggressive, balanced)
        """
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash
        self.market = market.lower()
        self.config = config or {}
        self.db_path = db_path
        self.api_source_config = dict(self.config.get("api_source", {}) or {})
        self.use_llm = use_llm
        self.analysts = analysts or ["fundamental", "technical", "company_news"]
        self.personality = personality

        # Initialize common components
        self.prefetcher = DataPrefetcher(
            db_path=db_path,
            market=market,
            api_source_config=self.api_source_config,
        )
        self.tracker = PortfolioTracker(initial_cash=initial_cash)
        self.reporter = ReportGenerator()

        logger.info(
            f"{self.__class__.__name__} initialized: {len(tickers)} tickers, "
            f"${initial_cash:,.0f} capital, {start_date} to {end_date}, "
            f"market={market}, LLM={'enabled' if use_llm else 'disabled'}"
        )

    def prefetch_data(self, force_sync: bool = False) -> Dict[str, Any]:
        """
        Prefetch all required data for backtesting.

        Args:
            force_sync: Force re-download even if cached

        Returns:
            Dict with prefetch statistics
        """
        logger.info("Starting data prefetch...")

        # Prefetch K-line data
        kline_results = self.prefetcher.prefetch_klines(
            tickers=self.tickers,
            start_date=self.start_date,
            end_date=self.end_date,
            force_sync=force_sync
        )

        # Check coverage
        coverage = self.prefetcher.check_coverage(
            tickers=self.tickers,
            start_date=self.start_date,
            end_date=self.end_date
        )

        # Log coverage summary
        for ticker, pct in coverage.items():
            if pct < 50:
                logger.warning(f"Low data coverage for {ticker}: {pct}%")
            else:
                logger.info(f"Data coverage for {ticker}: {pct}%")

        return {
            "klines": kline_results,
            "coverage": coverage
        }

    def get_trading_days(self) -> List[str]:
        """
        Get list of trading days for the backtest period.

        Returns:
            List of trading day strings in YYYY-MM-DD format
        """
        return self.prefetcher.get_trading_days(
            start_date=self.start_date,
            end_date=self.end_date
        )

    def _get_final_prices(self, last_date: str) -> Dict[str, float]:
        """
        Get final prices for all tickers on the last trading day.

        Args:
            last_date: Last trading date in YYYY-MM-DD format

        Returns:
            Dict of {ticker: final_price}
        """
        prices = {}
        for ticker in self.tickers:
            price_data = self.prefetcher.get_cached_prices(ticker, last_date)
            if price_data:
                prices[ticker] = price_data['close']
            else:
                logger.warning(f"No final price data for {ticker} on {last_date}")
        return prices

    def close(self):
        """Clean up resources."""
        if self.prefetcher:
            self.prefetcher.close()

    @abstractmethod
    def run(
        self,
        prefetch: bool = True,
        generate_report: bool = True,
        run_id: Optional[str] = None
    ):
        """
        Execute the backtest simulation.

        Must be implemented by subclasses.

        Args:
            prefetch: Whether to prefetch data before running
            generate_report: Whether to generate report files
            run_id: Optional run ID for report organization

        Returns:
            Backtest result (type depends on subclass)
        """
        pass
