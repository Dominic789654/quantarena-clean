"""
Smart Beta Backtest Engine
===========================

Extends BacktestEngine to support Smart Beta index enhancement strategies.
Integrates factor calculation, optimization, and macro adjustment.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from loguru import logger
import pandas as pd

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()

from backtest.engine import BacktestEngine, BacktestResult
from backtest.metrics import PerformanceMetrics


class SmartBetaBacktestEngine(BacktestEngine):
    """
    Smart Beta index enhancement backtesting engine.

    Extends BacktestEngine with:
    - Factor-based portfolio construction
    - Tracking error minimization
    - Macro state adjustment
    - News freeze mechanism

    Inherits from BacktestEngine:
    - Data prefetching with caching
    - Trading day management
    - Portfolio tracking
    - Report generation
    """

    def __init__(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        index_code: Optional[str] = None,
        initial_cash: float = 100000.0,
        market: str = "cn",
        config: Optional[Dict[str, Any]] = None,
        db_path: str = "data/signal_flux.db",
        rebalance_frequency: str = "monthly",
        **kwargs
    ):
        """
        Initialize Smart Beta backtest engine.

        Args:
            tickers: List of ticker symbols (index constituents)
            start_date: Backtest start date (YYYY-MM-DD)
            end_date: Backtest end date (YYYY-MM-DD)
            index_code: Target index code (default: CSI 300)
            initial_cash: Initial capital
            market: Market type ("cn" or "us")
            config: Additional configuration
            db_path: Database path for caching
            rebalance_frequency: "monthly" or "quarterly"
            **kwargs: Additional arguments passed to BacktestEngine
        """
        # Remove conflicting parameters from kwargs that we handle explicitly
        kwargs.pop('use_llm', None)  # Smart Beta uses its own logic, not LLM
        kwargs.pop('personality', None)  # We hardcode this as smart_beta_passive
        
        # Set market-appropriate index_code if not provided
        if index_code is None:
            index_code = "^GSPC" if market == "us" else "000300.SH"
        
        effective_config = dict(config or {})
        benchmark_cfg = dict(effective_config.get("benchmark", {}) or {})
        benchmark_cfg.setdefault("mode", "index")
        benchmark_cfg.setdefault("index_code", index_code)
        effective_config["benchmark"] = benchmark_cfg

        # Initialize parent without LLM (Smart Beta uses its own logic)
        super().__init__(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            market=market,
            config=effective_config,
            db_path=db_path,
            use_llm=False,  # Smart Beta uses its own decision logic
            personality="smart_beta_passive",
            **kwargs
        )

        self.index_code = index_code
        self.rebalance_frequency = rebalance_frequency

        # Initialize Smart Beta components
        self._init_smart_beta_components()

        # Track last rebalance date
        self.last_rebalance_date: Optional[datetime] = None

        # Benchmark data for tracking error calculation
        self.benchmark_returns: List[float] = []
        self.portfolio_returns: List[float] = []

        logger.info(f"Smart Beta Engine initialized for {index_code} (market={market})")

    def _init_smart_beta_components(self):
        """Initialize Smart Beta allocator and related components."""
        try:
            from deepfund.src.smart_beta import (
                SmartBetaAllocator,
                SmartBetaConfig,
                IndexConstituentsProvider
            )

            # Load market-specific configuration
            from shared.utils.path_manager import get_deepfund_src
            market_config = f"smart_beta_{self.market}.yaml"
            config_path = Path(get_deepfund_src()) / "config" / market_config
            if not config_path.exists():
                config_path = Path(get_deepfund_src()) / "config" / "smart_beta.yaml"
            if config_path.exists():
                self.smart_beta_config = SmartBetaConfig.from_yaml(str(config_path))
            else:
                self.smart_beta_config = SmartBetaConfig(index_code=self.index_code)

            # Override with constructor params
            self.smart_beta_config.index_code = self.index_code
            self.smart_beta_config.rebalance_frequency = self.rebalance_frequency

            # Initialize allocator
            self.smart_beta_allocator = SmartBetaAllocator(self.smart_beta_config)

            # Initialize index provider
            self.index_provider = IndexConstituentsProvider()

            self.smart_beta_available = True
            logger.info("Smart Beta components initialized successfully")

        except ImportError as e:
            logger.warning(f"Smart Beta components not available: {e}")
            self.smart_beta_available = False
            self.smart_beta_config = None
            self.smart_beta_allocator = None

    def _generate_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        """
        Generate Smart Beta trading decisions.

        This method:
        1. Checks if rebalancing is needed
        2. If yes, runs Smart Beta allocation
        3. Otherwise, returns HOLD for all positions

        Args:
            date: Trading date
            prices: Dict of {ticker: current_price}

        Returns:
            Dict of {ticker: {"action": str, "shares": int, "justification": str}}
        """
        date_dt = datetime.strptime(date, "%Y-%m-%d")

        # Check if rebalancing is needed
        should_rebalance = self._should_rebalance(date_dt)

        if not should_rebalance:
            # No rebalancing needed, hold positions
            return self._generate_hold_decisions(prices)

        # Perform Smart Beta allocation
        if self.smart_beta_available:
            return self._generate_smart_beta_decisions(date_dt, prices)
        else:
            # Fallback to simple buy-and-hold
            return self._generate_simple_decisions(prices)

    def _should_rebalance(self, current_date: datetime) -> bool:
        """
        Check if portfolio should be rebalanced.

        Args:
            current_date: Current trading date

        Returns:
            True if rebalancing is needed
        """
        # First day always rebalance
        if self.last_rebalance_date is None:
            return True

        days_since_rebalance = (current_date - self.last_rebalance_date).days

        if self.rebalance_frequency == "monthly":
            return days_since_rebalance >= 21  # ~21 trading days
        elif self.rebalance_frequency == "quarterly":
            return days_since_rebalance >= 63  # ~63 trading days

        return False

    def _generate_smart_beta_decisions(
        self,
        date: datetime,
        prices: Dict[str, float]
    ) -> Dict[str, Dict]:
        """
        Generate decisions using Smart Beta allocation.

        Args:
            date: Trading date
            prices: Current prices

        Returns:
            Dict of trading decisions
        """
        decisions = {}

        try:
            # Prepare data for Smart Beta allocator
            stock_data = self._prepare_stock_data(date)
            market_data = self._prepare_market_data(date)

            # Get macro indicators (if available)
            macro_indicators = self._get_macro_indicators(date)

            # Get news items for freeze detection
            news_items = self._get_news_items(date)

            # Calculate market return for freeze detection
            market_return = self._calculate_market_return(market_data)

            # Pass the structured portfolio through so the allocator can see
            # both holdings and idle cash when computing current weights.
            current_portfolio = {
                "positions": {
                    ticker: {"shares": int(pos.get("shares", 0))}
                    for ticker, pos in self.current_portfolio.get("positions", {}).items()
                },
                "cashflow": float(self.current_portfolio.get("cashflow", 0.0) or 0.0),
            }

            # Run Smart Beta allocation
            allocation_result = self.smart_beta_allocator.allocate(
                trade_date=date,
                stock_data=stock_data,
                market_data=market_data,
                current_portfolio=current_portfolio,
                prices=prices,
                macro_indicators=macro_indicators,
                news_items=news_items,
                market_return_today=market_return
            )

            if allocation_result.success:
                # Calculate total portfolio value (positions + cash) for correct target sizing
                positions = self.current_portfolio.get("positions", {})
                positions_value = sum(
                    pos.get("shares", 0) * prices.get(ticker, 0)
                    for ticker, pos in positions.items()
                )
                cash = self.current_portfolio.get("cashflow", self.initial_cash)
                total_portfolio_value = positions_value + cash

                # Convert allocation to trading decisions
                trading_decisions = self.smart_beta_allocator.get_trading_decisions(
                    allocation=allocation_result,
                    current_portfolio=current_portfolio,
                    prices=prices,
                    total_capital=total_portfolio_value
                )

                # Convert to decision format
                for td in trading_decisions:
                    ticker = td["ticker"]
                    decisions[ticker] = {
                        "action": td["action"].upper(),
                        "shares": td["shares"],
                        "price": td["price"],
                        "justification": f"Smart Beta allocation. Target weight: {td['target_weight']:.2%}",
                        "_applied": False,
                    }

                # Add HOLD for tickers not in decisions
                for ticker in self.tickers:
                    if ticker not in decisions and ticker in prices:
                        decisions[ticker] = {
                            "action": "HOLD",
                            "shares": 0,
                            "justification": "No change from Smart Beta allocation",
                            "_applied": False,
                        }

                # Update last rebalance date
                self.last_rebalance_date = date

                logger.info(f"Smart Beta rebalance on {date.strftime('%Y-%m-%d')}: "
                           f"{len(trading_decisions)} trades, "
                           f"tracking error: {allocation_result.tracking_error:.4f}")

            else:
                logger.warning(f"Smart Beta allocation failed: {allocation_result.message}")
                decisions = self._generate_hold_decisions(prices)

        except Exception as e:
            logger.error(f"Error in Smart Beta allocation: {e}")
            decisions = self._generate_hold_decisions(prices)

        return decisions

    def _prepare_stock_data(self, date: datetime) -> Dict[str, Any]:
        """
        Prepare stock OHLCV data for factor calculation.

        Args:
            date: Current date

        Returns:
            Dict of {ticker: DataFrame with OHLCV data}
        """
        stock_data = {}

        # Calculate start date for lookback period (need ~1.5 years of calendar days for 252 trading days)
        # We need enough history for factor calculation (252 days lookback)
        start_date = (date - timedelta(days=550)).strftime("%Y-%m-%d")
        end_date = date.strftime("%Y-%m-%d")

        for ticker in self.tickers:
            # Get historical data from database cache
            try:
                df = self.prefetcher.db.get_stock_prices(ticker, start_date, end_date)
                if df is not None and not df.empty:
                    # Convert to expected format
                    df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
                    df['date'] = pd.to_datetime(df['date'])
                    df.set_index('date', inplace=True)
                    stock_data[ticker] = df
            except Exception as e:
                logger.warning(f"Could not get stock data for {ticker}: {e}")

        return stock_data

    def _prepare_market_data(self, date: datetime) -> Any:
        """
        Prepare market index data.

        Args:
            date: Current date

        Returns:
            DataFrame with market OHLCV data
        """
        start_date = date - timedelta(days=550)

        # Prefer true index data when the provider can supply it.
        try:
            market_data = self.index_provider.get_index_daily(
                index_code=self.index_code,
                start_date=start_date,
                end_date=date,
            )
            if market_data is not None and not market_data.empty:
                return market_data
        except Exception as e:
            logger.warning(f"Could not fetch benchmark data for {self.index_code}: {e}")

        # For US market, fall back to a synthetic equal-weight proxy built from the universe.
        if self.market == "us":
            try:
                start_str = start_date.strftime("%Y-%m-%d")
                end_str = date.strftime("%Y-%m-%d")
                close_series = []
                for ticker in self.tickers:
                    df = self.prefetcher.db.get_stock_prices(ticker, start_str, end_str)
                    if df is not None and not df.empty and "close" in df.columns:
                        df["date"] = pd.to_datetime(df["date"])
                        df = df.set_index("date")["close"]
                        close_series.append(df)
                if close_series:
                    avg_close = pd.concat(close_series, axis=1).mean(axis=1).dropna()
                    market_df = pd.DataFrame({
                        "open": avg_close, "high": avg_close,
                        "low": avg_close, "close": avg_close,
                        "volume": 1e9
                    })
                    market_df.index.name = "date"
                    return market_df
            except Exception as e:
                logger.warning(f"Could not build US market data from cache: {e}")
            return None

        # Try to get index data from Tushare (CN market)
        try:
            from apis.tushare.api import TushareAPI
            api = TushareAPI()

            start_date = date - timedelta(days=400)  # ~400 calendar days for 252 trading days
            market_data = api.get_index_daily(
                index_code=self.index_code,
                start_date=start_date,
                end_date=date
            )
            return market_data

        except Exception as e:
            logger.warning(f"Could not fetch market data: {e}")
            return None

    def _get_macro_indicators(self, date: datetime) -> Optional[Dict[str, float]]:
        """
        Get macroeconomic indicators for the date.

        Args:
            date: Current date

        Returns:
            Dict of indicator values
        """
        # Avoid applying fake macro tilts in backtests until a real historical
        # macro source is wired in. Returning None leaves the portfolio purely
        # factor/optimizer driven.
        return None

    def _get_news_items(self, date: datetime) -> Optional[List[Dict]]:
        """
        Get news items for freeze detection.

        Args:
            date: Current date

        Returns:
            List of news items
        """
        # Placeholder - in production, would fetch from news source
        return None

    def _calculate_market_return(self, market_data: Any) -> Optional[float]:
        """
        Calculate most recent market return.

        Args:
            market_data: Market OHLCV DataFrame

        Returns:
            Most recent daily return
        """
        if market_data is None or market_data.empty:
            return None

        if "close" not in market_data.columns:
            return None

        returns = market_data["close"].pct_change()
        if len(returns) > 0:
            return returns.iloc[-1]

        return None

    def _generate_hold_decisions(self, prices: Dict[str, float]) -> Dict[str, Dict]:
        """Generate HOLD decisions for all tickers."""
        decisions = {}
        for ticker in self.tickers:
            if ticker in prices:
                decisions[ticker] = {
                    "action": "HOLD",
                    "shares": 0,
                    "justification": "No rebalancing scheduled",
                    "_applied": False,
                }
        return decisions

    def _record_snapshot(self, date: str, prices: Dict[str, float]):
        """
        Record daily portfolio snapshot.

        Extends parent to track benchmark returns.

        Args:
            date: Trading date
            prices: Current prices
        """
        super()._record_snapshot(date, prices)

        # Track portfolio return
        if self.tracker.snapshots:
            portfolio_value = self.tracker.snapshots[-1].total_value
            if hasattr(self, '_prev_portfolio_value') and self._prev_portfolio_value > 0:
                portfolio_return = (portfolio_value - self._prev_portfolio_value) / self._prev_portfolio_value
                self.portfolio_returns.append(portfolio_return)
            self._prev_portfolio_value = portfolio_value

        # Track benchmark return (simplified - would need actual benchmark data)
        # For now, we'll calculate this separately in the report

    def get_smart_beta_metrics(self) -> Dict[str, Any]:
        """
        Calculate Smart Beta specific metrics.

        Returns:
            Dict with tracking error, information ratio, etc.
        """
        metrics = {}

        try:
            import pandas as pd

            # Get equity curve
            equity_curve = self.tracker.get_equity_curve()

            if equity_curve.empty or len(equity_curve) < 2:
                return metrics

            # Calculate portfolio daily returns
            portfolio_returns = equity_curve['daily_return'] if 'daily_return' in equity_curve.columns else pd.Series()

            # For benchmark, we would need actual index data
            # Placeholder: assume benchmark return is 0 (market neutral)
            # In production, fetch actual index returns

            if len(portfolio_returns) > 1 and len(self.benchmark_returns) > 1:
                # Align lengths
                min_len = min(len(portfolio_returns), len(self.benchmark_returns))

                metrics = PerformanceMetrics.calculate_smart_beta_metrics(
                    portfolio_returns=pd.Series(portfolio_returns.iloc[:min_len]),
                    benchmark_returns=pd.Series(self.benchmark_returns[:min_len])
                )

        except Exception as e:
            logger.warning(f"Could not calculate Smart Beta metrics: {e}")

        return metrics

    def run(
        self,
        prefetch: bool = True,
        generate_report: bool = True,
        run_id: Optional[str] = None,
    ) -> BacktestResult:
        """
        Run Smart Beta backtest.

        Extends parent run() to add Smart Beta specific metrics.

        Args:
            prefetch: Whether to prefetch data before running
            generate_report: Whether to generate report files
            run_id: Optional run ID for report organization

        Returns:
            BacktestResult with Smart Beta metrics
        """
        # Run standard backtest
        result = super().run(
            prefetch=prefetch,
            generate_report=generate_report,
            run_id=run_id,
        )

        # Preserve the date-aligned benchmark metrics already computed by the base backtest,
        # and only fill them from Smart Beta-specific helpers when they are missing.
        smart_beta_metrics = self.get_smart_beta_metrics()
        benchmark_metric_keys = {"tracking_error", "information_ratio", "beta", "alpha", "excess_return"}
        missing_benchmark_metrics = {key for key in benchmark_metric_keys if key not in result.metrics}
        for key, value in smart_beta_metrics.items():
            if key not in benchmark_metric_keys or key in missing_benchmark_metrics:
                result.metrics[key] = value

        # Add Smart Beta config info
        result.config["smart_beta"] = {
            "index_code": self.index_code,
            "rebalance_frequency": self.rebalance_frequency,
            "strategy_type": "smart_beta"
        }

        if generate_report:
            try:
                self.reporter.generate_full_report(result, result.run_id)
            except Exception as exc:
                logger.error(f"Smart Beta report refresh failed: {exc}")
                result.errors.append(f"Smart Beta report refresh failed: {exc}")

        logger.info(f"Smart Beta backtest completed. "
                   f"Return: {result.metrics.get('total_return', 0):.2f}%, "
                   f"Tracking Error: {smart_beta_metrics.get('tracking_error', 'N/A')}")

        return result


def create_smart_beta_engine(
    tickers: List[str],
    start_date: str,
    end_date: str,
    index_code: str = "000300.SH",
    initial_cash: float = 100000.0,
    rebalance_frequency: str = "monthly",
    **kwargs
) -> SmartBetaBacktestEngine:
    """
    Factory function to create Smart Beta backtest engine.

    Args:
        tickers: List of ticker symbols
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        index_code: Target index code
        initial_cash: Initial capital
        rebalance_frequency: "monthly" or "quarterly"
        **kwargs: Additional arguments

    Returns:
        Configured SmartBetaBacktestEngine instance
    """
    return SmartBetaBacktestEngine(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        index_code=index_code,
        initial_cash=initial_cash,
        rebalance_frequency=rebalance_frequency,
        **kwargs
    )
