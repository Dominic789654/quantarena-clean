"""
Backtest Engine
===============

Core orchestration for sequential backtesting simulation.
Integrates with existing DeepFund workflow.
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import pandas as pd
from loguru import logger

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
from shared.utils.run_id import generate_run_id
setup_paths()

from backtest.base_engine import BaseBacktestEngine
from backtest.behavior_metrics import compute_behavior_metrics
from backtest.execution import (
    convert_targets_to_trades,
    execute_buy_order,
    execute_sell_order,
    record_portfolio_snapshot,
)
from backtest.mandate_interface import allocate_with_mandate
from backtest.portfolio_tracker import Trade, PortfolioTracker
from backtest.metrics import PerformanceMetrics
from backtest.workflow_adapter import BacktestWorkflowAdapter, create_workflow_adapter

# Portfolio allocator for multi-stock allocation (B1 scheme)
try:
    from backtest.portfolio_allocator import PortfolioAllocator
    PORTFOLIO_ALLOCATOR_AVAILABLE = True
except ImportError:
    PortfolioAllocator = None
    PORTFOLIO_ALLOCATOR_AVAILABLE = False

# Import token tracker for LLM cost tracking
try:
    from llm.inference import reset_token_tracker, get_token_stats
    TOKEN_TRACKER_AVAILABLE = True
except ImportError:
    TOKEN_TRACKER_AVAILABLE = False

# Import deepear stats for API call tracking
try:
    from deepear.src.utils.stats import get_stats as get_deepear_stats
    DEEPEAR_STATS_AVAILABLE = True
except ImportError:
    DEEPEAR_STATS_AVAILABLE = False


@dataclass
class BacktestResult:
    """Container for backtest results."""
    run_id: str
    start_date: str
    end_date: str
    tickers: List[str]
    market: str
    initial_cash: float
    tracker: PortfolioTracker
    metrics: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    benchmark_curve: Optional[pd.Series] = None
    benchmark_source: str = "unavailable"
    errors: List[str] = field(default_factory=list)
    broker_audit_events: List[Dict[str, Any]] = field(default_factory=list)


class BacktestEngine(BaseBacktestEngine):
    """
    Core backtesting orchestration engine.

    Inherits from BaseBacktestEngine:
    - Data prefetching with caching
    - Trading day management
    - Portfolio tracking initialization
    - Report generation setup

    Adds:
    - Sequential daily simulation
    - LLM-based decision making
    - Portfolio mode and smart priority mode
    """
    EQUAL_WEIGHT_PERSONALITIES = {"equal_weight_index", "equal_weight", "ewi"}

    def _init_portfolio_allocator(self, personality: str):
        """Instantiate a portfolio allocator while remaining compatible with test stubs."""
        allocator_cls = PortfolioAllocator
        if allocator_cls is None:
            from backtest.portfolio_allocator import PortfolioAllocator as allocator_cls
        try:
            return allocator_cls(
                personality=personality,
                llm_provider=self.llm_provider,
                llm_model=self.llm_model,
            )
        except TypeError:
            return allocator_cls(personality=personality)

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
        personality: str = "balanced",
        portfolio_mode: bool = True,
        smart_priority_mode: bool = True,
        shared_analyst_cache_dir: Optional[str] = None,
        shared_phase1_cache_dir: Optional[str] = None,
    ):
        """
        Initialize backtest engine.

        Args:
            tickers: List of ticker symbols to trade
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            initial_cash: Starting capital
            market: Market type ("cn" for A-share, "us" for US stocks)
            config: Optional configuration dict for DeepFund workflow
            db_path: Path to SQLite database for caching
            use_llm: Whether to use LLM for intelligent trading decisions
            analysts: List of analysts to use (e.g., ["fundamental", "technical"])
            personality: Investment personality (conservative, aggressive, balanced)
            portfolio_mode: Whether to use multi-stock portfolio allocation (B1 scheme)
                True: Collect signals from all stocks first, then make unified allocation
                False: Process each stock independently (legacy mode)
            smart_priority_mode: Whether to use smart priority with parallel signal collection
                True: Parallel signal collection + smart priority order decision making
                False: Use portfolio_mode or legacy mode
        """
        # Call base class constructor for common initialization
        super().__init__(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            market=market,
            config=config,
            db_path=db_path,
            use_llm=use_llm,
            analysts=analysts,
            personality=personality
        )

        # BacktestEngine-specific settings
        self.portfolio_mode = portfolio_mode and use_llm
        self.smart_priority_mode = smart_priority_mode and use_llm
        benchmark_cfg = (self.config or {}).get("benchmark", {})
        self.benchmark_mode = str(benchmark_cfg.get("mode", "auto")).lower()
        self.benchmark_index_code = str(
            benchmark_cfg.get(
                "index_code",
                "000300.SH" if self.market == "cn" else ""
            )
        )

        # Initialize workflow adapter if using LLM
        self.workflow_adapter = None
        self.portfolio_allocator = None
        self.shared_analyst_cache_dir = shared_analyst_cache_dir
        self.shared_phase1_cache_dir = shared_phase1_cache_dir
        llm_cfg = dict((self.config or {}).get("llm", {}) or {})
        llm_provider = str(llm_cfg.get("provider", "")).strip() or None
        llm_model = str(llm_cfg.get("model", "")).strip() or None
        self.llm_provider = llm_provider or os.getenv("REASONING_MODEL_PROVIDER", "DeepSeek")
        self.llm_model = llm_model or os.getenv("REASONING_MODEL_ID", "deepseek-chat")
        if use_llm:
            try:
                self.workflow_adapter = create_workflow_adapter(
                    tickers=tickers,
                    initial_cash=initial_cash,
                    market=self.market,
                    use_llm=True,
                    analysts=self.analysts,
                    personality=self.personality,
                    db_path=self.db_path,
                    llm_provider=self.llm_provider,
                    llm_model=self.llm_model,
                    api_source_config=self.api_source_config,
                    shared_analyst_cache_dir=self.shared_analyst_cache_dir,
                    shared_phase1_cache_dir=self.shared_phase1_cache_dir,
                )
                logger.info(
                    f"LLM workflow enabled: analysts={self.analysts}, personality={self.personality}, "
                    f"portfolio_mode={self.portfolio_mode}, smart_priority_mode={self.smart_priority_mode}"
                )

                # Initialize portfolio allocator if in portfolio mode
                if self.portfolio_mode and PORTFOLIO_ALLOCATOR_AVAILABLE:
                    self.portfolio_allocator = self._init_portfolio_allocator(self.personality)
                    logger.info("Portfolio allocator initialized for multi-stock allocation")

            except Exception as e:
                logger.warning(f"Failed to initialize LLM workflow: {e}. Falling back to simple strategy.")
                self.use_llm = False
                self.portfolio_mode = False
                self.smart_priority_mode = False

        # Decision memory for portfolio allocator
        self.decision_memory = []

        # State
        self.current_portfolio = {
            "cashflow": initial_cash,
            "positions": {ticker: {"shares": 0, "value": 0} for ticker in tickers}
        }
        self.broker_audit_events: List[Dict[str, Any]] = []

    def run(
        self,
        prefetch: bool = True,
        generate_report: bool = True,
        run_id: Optional[str] = None
    ) -> BacktestResult:
        """
        Execute the backtest.

        Args:
            prefetch: Whether to prefetch data before running
            generate_report: Whether to generate report files
            run_id: Optional run ID for report organization

        Returns:
            BacktestResult with all results
        """
        run_id = run_id or generate_run_id()
        errors = []

        # Reset token tracker for this run
        if TOKEN_TRACKER_AVAILABLE:
            reset_token_tracker()

        # Reset deepear stats for this run
        if DEEPEAR_STATS_AVAILABLE:
            try:
                get_deepear_stats().reset()
            except Exception:
                pass

        logger.info(f"Starting backtest run: {run_id}")

        # Step 1: Prefetch data
        if prefetch:
            try:
                prefetch_stats = self.prefetch_data()
            except Exception as e:
                logger.error(f"Data prefetch failed: {e}")
                errors.append(f"Prefetch error: {str(e)}")
                prefetch_stats = {}

        # Step 2: Get trading days
        trading_days = self.get_trading_days()
        logger.info(f"Backtesting over {len(trading_days)} trading days")

        if not trading_days:
            errors.append("No trading days found in date range")

        # Step 3: Run sequential simulation
        for i, date in enumerate(trading_days):
            try:
                self._run_single_day(date, i + 1, len(trading_days))
            except Exception as e:
                logger.error(f"Error on {date}: {e}")
                errors.append(f"{date}: {str(e)}")
                continue

        return self.finalize_run(
            trading_days=trading_days,
            run_id=run_id,
            generate_report=generate_report,
            errors=errors,
        )

    def finalize_run(
        self,
        trading_days: List[str],
        run_id: Optional[str] = None,
        generate_report: bool = True,
        errors: Optional[List[str]] = None,
        token_stats_override: Optional[Dict[str, Any]] = None,
    ) -> BacktestResult:
        """Finalize metrics/report generation for an already-executed backtest."""
        run_id = run_id or generate_run_id()
        errors = list(errors or [])

        final_prices = self._get_final_prices(trading_days[-1] if trading_days else self.end_date)
        benchmark_curve, benchmark_source = self._calculate_benchmark_curve(trading_days)
        benchmark_returns = pd.Series(dtype=float)
        if not benchmark_curve.empty:
            benchmark_returns = benchmark_curve.pct_change().fillna(0.0) * 100

        metrics = PerformanceMetrics.calculate_all(
            self.tracker,
            final_prices,
            benchmark_returns=benchmark_returns,
        )
        metrics.update(compute_behavior_metrics(self.tracker, metrics))
        metrics["benchmark_source"] = benchmark_source
        if not benchmark_curve.empty and benchmark_curve.iloc[0] > 0:
            metrics["benchmark_total_return"] = round(
                (benchmark_curve.iloc[-1] - benchmark_curve.iloc[0]) / benchmark_curve.iloc[0] * 100,
                2,
            )
        else:
            metrics["benchmark_total_return"] = 0.0

        result = BacktestResult(
            run_id=run_id,
            start_date=self.start_date,
            end_date=self.end_date,
            tickers=self.tickers,
            market=self.market,
            initial_cash=self.initial_cash,
            tracker=self.tracker,
            metrics=metrics,
            config=dict(self.config or {}),
            benchmark_curve=benchmark_curve,
            benchmark_source=benchmark_source,
            errors=errors,
            broker_audit_events=list(self.broker_audit_events),
        )

        if generate_report:
            try:
                report_paths = self.reporter.generate_full_report(
                    result,
                    run_id,
                    token_stats_override=token_stats_override,
                )
                logger.info(f"Reports generated: {report_paths}")
            except Exception as e:
                logger.error(f"Report generation failed: {e}")
                errors.append(f"Report error: {str(e)}")

        logger.info(f"Backtest completed: {run_id}")
        logger.info(f"Total return: {metrics.get('total_return', 0):+.2f}%")

        token_stats = token_stats_override
        if token_stats is None and TOKEN_TRACKER_AVAILABLE and self.use_llm:
            token_stats = get_token_stats()
        if token_stats and self.use_llm:
            total_tokens = token_stats.get("total_input", 0) + token_stats.get("total_output", 0)
            calls = token_stats.get("calls", 0)
            cost = (token_stats.get("total_input", 0) / 1_000_000 * 1) + (token_stats.get("total_output", 0) / 1_000_000 * 2)
            logger.info(f"LLM Usage: {calls} calls, {total_tokens:,} tokens, ¥{cost:.4f} cost")

        return result

    def _calculate_benchmark_curve(self, trading_days: List[str]) -> tuple[pd.Series, str]:
        """
        Build benchmark curve aligned with trading days.

        Benchmark modes:
        - auto (default): CN market tries real index first, then falls back to equal-weight basket.
        - index: force real index benchmark (falls back to equal-weight if unavailable).
        - equal_weight: use same-ticker equal-weight buy-and-hold basket.
        - none: disable benchmark calculation.
        """
        if not trading_days or self.benchmark_mode == "none":
            return pd.Series(dtype=float), "none"

        if self.benchmark_mode in {"auto", "index"} and self.benchmark_index_code:
            if self.market == "cn":
                index_curve = self._build_cn_index_benchmark_curve(trading_days, self.benchmark_index_code)
            else:
                index_curve = self._build_us_index_benchmark_curve(trading_days, self.benchmark_index_code)
            if not index_curve.empty:
                return index_curve, f"index:{self.benchmark_index_code}"
            logger.warning(
                f"Benchmark index {self.benchmark_index_code} unavailable, falling back to equal-weight basket."
            )

        if self.benchmark_mode in {"auto", "index", "equal_weight"}:
            basket_curve = self._build_equal_weight_benchmark_curve(trading_days)
            if not basket_curve.empty:
                return basket_curve, "equal_weight_basket"

        return pd.Series(dtype=float), "unavailable"

    def _build_us_index_benchmark_curve(self, trading_days: List[str], index_code: str) -> pd.Series:
        """Build benchmark curve from US index or ETF daily close prices via yfinance."""
        try:
            import importlib
            yf = importlib.import_module("yfinance")

            start_dt = datetime.strptime(trading_days[0], "%Y-%m-%d")
            end_dt = datetime.strptime(trading_days[-1], "%Y-%m-%d")
            raw_df = yf.download(
                index_code,
                start=start_dt.strftime("%Y-%m-%d"),
                end=(end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=False,
            )
            if raw_df is None or raw_df.empty:
                return pd.Series(dtype=float)

            if isinstance(raw_df.columns, pd.MultiIndex) and "Adj Close" in raw_df.columns.get_level_values(0):
                close_frame = raw_df.xs("Adj Close", axis=1, level=0)
                close_series = close_frame.iloc[:, 0].copy() if isinstance(close_frame, pd.DataFrame) else close_frame.copy()
            elif isinstance(raw_df.columns, pd.MultiIndex) and "Close" in raw_df.columns.get_level_values(0):
                close_frame = raw_df.xs("Close", axis=1, level=0)
                close_series = close_frame.iloc[:, 0].copy() if isinstance(close_frame, pd.DataFrame) else close_frame.copy()
            elif isinstance(raw_df.columns, pd.MultiIndex) and "adj close" in raw_df.columns.get_level_values(0):
                close_frame = raw_df.xs("adj close", axis=1, level=0)
                close_series = close_frame.iloc[:, 0].copy() if isinstance(close_frame, pd.DataFrame) else close_frame.copy()
            elif isinstance(raw_df.columns, pd.MultiIndex) and "close" in raw_df.columns.get_level_values(0):
                close_frame = raw_df.xs("close", axis=1, level=0)
                close_series = close_frame.iloc[:, 0].copy() if isinstance(close_frame, pd.DataFrame) else close_frame.copy()
            elif "Adj Close" in raw_df.columns:
                close_series = raw_df["Adj Close"].copy()
            elif "Close" in raw_df.columns:
                close_series = raw_df["Close"].copy()
            elif "adj close" in raw_df.columns:
                close_series = raw_df["adj close"].copy()
            elif "close" in raw_df.columns:
                close_series = raw_df["close"].copy()
            else:
                return pd.Series(dtype=float)

            close_series.index = pd.to_datetime(close_series.index)
            close_series = close_series.sort_index()
            target_index = pd.to_datetime(trading_days)
            aligned_close = close_series.reindex(target_index).ffill()
            if aligned_close.isna().any():
                aligned_close = aligned_close.dropna()
            if len(aligned_close) != len(target_index):
                return pd.Series(dtype=float)
            if aligned_close.empty or aligned_close.iloc[0] <= 0:
                return pd.Series(dtype=float)

            benchmark_curve = self.initial_cash * (aligned_close / aligned_close.iloc[0])
            benchmark_curve.name = "benchmark_value"
            benchmark_curve.index.name = "date"
            return benchmark_curve
        except Exception as exc:
            logger.warning(f"Failed to build US index benchmark ({index_code}): {exc}")
            return pd.Series(dtype=float)

    def _build_cn_index_benchmark_curve(self, trading_days: List[str], index_code: str) -> pd.Series:
        """Build benchmark curve from CN index daily close prices."""
        try:
            from apis.tushare.api import TushareAPI

            api = TushareAPI()
            start_dt = datetime.strptime(trading_days[0], "%Y-%m-%d")
            end_dt = datetime.strptime(trading_days[-1], "%Y-%m-%d")
            index_df = api.get_index_daily(index_code=index_code, start_date=start_dt, end_date=end_dt)
            if index_df is None or index_df.empty or "close" not in index_df.columns:
                return pd.Series(dtype=float)

            close_series = index_df["close"].copy()
            if "date" in index_df.columns:
                close_series.index = pd.to_datetime(index_df["date"])
            close_series.index = pd.to_datetime(close_series.index)
            close_series = close_series.sort_index()

            target_index = pd.to_datetime(trading_days)
            aligned_close = close_series.reindex(target_index).ffill()
            if aligned_close.isna().any():
                aligned_close = aligned_close.dropna()
            if len(aligned_close) != len(target_index):
                return pd.Series(dtype=float)
            if aligned_close.empty or aligned_close.iloc[0] <= 0:
                return pd.Series(dtype=float)

            benchmark_curve = self.initial_cash * (aligned_close / aligned_close.iloc[0])
            benchmark_curve.name = "benchmark_value"
            benchmark_curve.index.name = "date"
            return benchmark_curve
        except Exception as exc:
            logger.warning(f"Failed to build CN index benchmark ({index_code}): {exc}")
            return pd.Series(dtype=float)

    def _build_equal_weight_benchmark_curve(self, trading_days: List[str]) -> pd.Series:
        """Build equal-weight buy-and-hold benchmark from the same ticker basket."""
        if not trading_days:
            return pd.Series(dtype=float)

        first_day = trading_days[0]
        first_prices: Dict[str, float] = {}
        for ticker in self.tickers:
            day_price = self.prefetcher.get_cached_prices(ticker, first_day)
            if day_price and day_price.get("close", 0) > 0:
                first_prices[ticker] = float(day_price["close"])

        if not first_prices:
            return pd.Series(dtype=float)

        allocation = self.initial_cash / len(first_prices)
        shares = {ticker: allocation / price for ticker, price in first_prices.items()}
        residual_cash = self.initial_cash - sum(shares[t] * first_prices[t] for t in first_prices)
        last_prices = dict(first_prices)

        values: List[float] = []
        for day in trading_days:
            for ticker in shares:
                day_price = self.prefetcher.get_cached_prices(ticker, day)
                if day_price and day_price.get("close", 0) > 0:
                    last_prices[ticker] = float(day_price["close"])

            total_value = residual_cash + sum(shares[t] * last_prices[t] for t in shares)
            values.append(total_value)

        benchmark_curve = pd.Series(values, index=pd.to_datetime(trading_days), name="benchmark_value")
        benchmark_curve.index.name = "date"
        return benchmark_curve

    def _run_single_day(self, date: str, day_num: int, total_days: int):
        """
        Execute one trading day simulation.

        Args:
            date: Trading date in YYYY-MM-DD format
            day_num: Current day number (for progress logging)
            total_days: Total number of trading days
        """
        logger.info(f"[{day_num}/{total_days}] Processing {date}...")

        # Get prices for all tickers
        prices = {}
        for ticker in self.tickers:
            price_data = self.prefetcher.get_cached_prices(ticker, date)
            if price_data:
                prices[ticker] = price_data['close']
            else:
                logger.warning(f"No price data for {ticker} on {date}")

        if not prices:
            logger.warning(f"No prices available for {date}, skipping")
            return

        # For MVP: Simple buy-and-hold or random strategy simulation
        # In production, this would call DeepFund AgentWorkflow
        decisions = self._generate_decisions(date, prices)

        self._execute_day_with_decisions(date, prices, decisions)

    def _execute_day_with_decisions(self, date: str, prices: Dict[str, float], decisions: Dict[str, Dict]) -> None:
        """Apply day decisions to the portfolio and record the closing snapshot."""
        for ticker, decision in decisions.items():
            if ticker not in prices:
                continue

            action = decision.get('action', 'HOLD')
            shares = decision.get('shares', 0)
            price = prices[ticker]
            justification = decision.get('justification', '')
            already_applied = decision.get('_applied', False)

            if already_applied:
                continue

            if action == 'BUY' and shares > 0:
                self._execute_buy(date, ticker, shares, price, justification)
            elif action == 'SELL' and shares > 0:
                self._execute_sell(date, ticker, shares, price, justification)

        self._record_snapshot(date, prices)

    def _generate_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        """
        Generate trading decisions for the day.

        If use_llm is enabled, uses DeepFund's AgentWorkflow for intelligent decisions.
        Otherwise, uses a simple buy-and-hold strategy.

        Args:
            date: Trading date
            prices: Dict of {ticker: current_price}

        Returns:
            Dict of {ticker: {"action": str, "shares": int, "justification": str}}
        """
        # Equal-weight index runs as deterministic rules, not day-by-day LLM decisions.
        if self._is_equal_weight_personality():
            return self._generate_equal_weight_index_decisions(date, prices)

        # If LLM is enabled and adapter is available, use intelligent decisions
        if self.use_llm and self.workflow_adapter:
            return self._generate_llm_decisions(date, prices)

        # Fallback: Simple buy-and-hold strategy
        return self._generate_simple_decisions(prices)

    def _is_equal_weight_personality(self) -> bool:
        """Check whether current personality should follow strict equal-weight rules."""
        return str(self.personality).lower() in self.EQUAL_WEIGHT_PERSONALITIES

    def _is_equal_weight_rebalance_day(self, date: str) -> bool:
        """
        Determine whether a date is in the semi-annual rebalance window.

        We treat the first trading week of June and December as rebalance window.
        """
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"Invalid date format for equal-weight rebalance check: {date}")
            return False
        return dt.month in {6, 12} and dt.day <= 7

    def _generate_equal_weight_index_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        """
        Generate strict equal-weight decisions with deterministic rebalancing.

        Rules:
        - Initial allocation: buy to equal weights when there is no position yet.
        - Rebalance only in June/December first trading week.
        - Outside rebalance window: HOLD all positions.
        """
        decisions: Dict[str, Dict] = {}
        tradable_tickers = [t for t in self.tickers if t in prices and prices[t] > 0]

        # Keep shape stable for missing-price tickers.
        for ticker in self.tickers:
            if ticker not in tradable_tickers:
                decisions[ticker] = {
                    "action": "HOLD",
                    "shares": 0,
                    "justification": "No valid price for strict equal-weight strategy",
                    "_applied": True,
                }

        if not tradable_tickers:
            return decisions

        has_position = any(
            self.current_portfolio["positions"].get(ticker, {}).get("shares", 0) > 0
            for ticker in tradable_tickers
        )
        rebalance_now = (not has_position) or self._is_equal_weight_rebalance_day(date)
        if not rebalance_now:
            for ticker in tradable_tickers:
                decisions[ticker] = {
                    "action": "HOLD",
                    "shares": 0,
                    "justification": "Strict equal-weight: outside rebalance window",
                    "_applied": True,
                }
            return decisions

        total_value = self.current_portfolio["cashflow"]
        for ticker in tradable_tickers:
            shares = self.current_portfolio["positions"].get(ticker, {}).get("shares", 0)
            total_value += shares * prices[ticker]

        target_ratio = 1.0 / len(tradable_tickers)
        target_shares = {
            ticker: int((total_value * target_ratio) / prices[ticker])
            for ticker in tradable_tickers
        }

        # Sell first to free cash before buys.
        for ticker in tradable_tickers:
            current_shares = self.current_portfolio["positions"].get(ticker, {}).get("shares", 0)
            shares_to_sell = max(current_shares - target_shares[ticker], 0)
            if shares_to_sell > 0:
                self._execute_sell(date, ticker, shares_to_sell, prices[ticker])
                decisions[ticker] = {
                    "action": "SELL",
                    "shares": shares_to_sell,
                    "justification": f"Strict equal-weight rebalance to {target_ratio:.2%}",
                    "_applied": True,
                }

        for ticker in tradable_tickers:
            current_shares = self.current_portfolio["positions"].get(ticker, {}).get("shares", 0)
            shares_to_buy = max(target_shares[ticker] - current_shares, 0)
            if shares_to_buy > 0:
                affordable = int(self.current_portfolio["cashflow"] / prices[ticker])
                actual_buy = min(shares_to_buy, affordable)
                if actual_buy > 0:
                    self._execute_buy(date, ticker, actual_buy, prices[ticker])
                    decisions[ticker] = {
                        "action": "BUY",
                        "shares": actual_buy,
                        "justification": f"Strict equal-weight rebalance to {target_ratio:.2%}",
                        "_applied": True,
                    }
                else:
                    decisions[ticker] = {
                        "action": "HOLD",
                        "shares": 0,
                        "justification": "Strict equal-weight: insufficient cash for rebalance",
                        "_applied": True,
                    }
            elif ticker not in decisions:
                decisions[ticker] = {
                    "action": "HOLD",
                    "shares": 0,
                    "justification": f"Strict equal-weight target {target_ratio:.2%} already met",
                    "_applied": True,
                }

        return decisions

    def _generate_llm_decisions_with_precollected_signals(
        self,
        date: str,
        prices: Dict[str, float],
        enhanced_signals: Dict[str, Any],
        priority_order: Optional[List[str]] = None,
    ) -> Dict[str, Dict]:
        """Generate smart-priority LLM decisions using shared pre-collected analyst signals."""
        decisions: Dict[str, Dict] = {}

        if not (self.smart_priority_mode and self.workflow_adapter):
            return self._generate_llm_decisions(date, prices)

        try:
            llm_decisions = self.workflow_adapter.run_single_day_with_precollected_signals(
                trading_date=date,
                prices=prices,
                enhanced_signals=enhanced_signals,
                priority_order=priority_order,
                prev_portfolio=self.current_portfolio,
            )

            for ticker, decision in llm_decisions.items():
                decisions[ticker] = {
                    "action": decision.action.upper(),
                    "shares": decision.shares,
                    "price": decision.price,
                    "justification": decision.justification,
                    "_applied": False,
                }

            logger.info(
                f"Shared smart-priority decisions for {date}: "
                f"{[(t, d['action'], d['shares']) for t, d in decisions.items()]}"
            )
        except Exception as e:
            logger.error(f"Shared smart-priority decision failed for {date}: {e}. Falling back to HOLD.")
            for ticker in self.tickers:
                if ticker in prices:
                    decisions[ticker] = {
                        "action": "HOLD",
                        "shares": 0,
                        "justification": f"LLM error: {str(e)}",
                        "_applied": False,
                    }

        return decisions

    def _generate_llm_decisions(self, date: str, prices: Dict[str, float]) -> Dict[str, Dict]:
        """
        Generate trading decisions using LLM-based AgentWorkflow.

        Two modes available:
        1. Portfolio mode (B1 scheme - default):
           - Collect signals from ALL stocks first
           - Make unified portfolio allocation decision
           - Better for multi-asset scenarios
        2. Legacy mode:
           - Process each stock independently

        Args:
            date: Trading date
            prices: Dict of {ticker: current_price}

        Returns:
            Dict of {ticker: {"action": str, "shares": int, "justification": str, "_applied": bool}}
            The "_applied" flag indicates if the decision was already applied to portfolio.
        """
        decisions = {}

        try:
            # ========== SMART PRIORITY MODE ==========
            if self.smart_priority_mode and self.workflow_adapter:
                logger.info(f"Smart priority mode: Parallel signal collection + priority order decision making")

                # Run with smart priority: parallel signals + priority order decisions
                llm_decisions = self.workflow_adapter.run_single_day_with_smart_priority(
                    trading_date=date,
                    prices=prices,
                    prev_portfolio=self.current_portfolio,
                    max_workers=5
                )

                # Convert BacktestDecision to dict format
                for ticker, decision in llm_decisions.items():
                    decisions[ticker] = {
                        "action": decision.action.upper(),
                        "shares": decision.shares,
                        "price": decision.price,
                        "justification": decision.justification,
                        "_applied": False,
                    }

                logger.info(f"Smart priority decisions for {date}: {[(t, d['action'], d['shares']) for t, d in decisions.items()]}")
                return decisions

            # ========== PORTFOLIO MODE (B1 SCHEME) ==========
            if self.portfolio_mode and self.portfolio_allocator and self.workflow_adapter:
                logger.info(f"Portfolio mode: Collecting signals for all {len(self.tickers)} stocks...")

                # Phase 1: Collect signals from all stocks
                all_signals = self.workflow_adapter.collect_signals_only(
                    trading_date=date,
                    prices=prices
                )

                if not all_signals:
                    logger.warning("No signals collected, falling back to HOLD")
                    for ticker in self.tickers:
                        if ticker in prices:
                            decisions[ticker] = {
                                "action": "HOLD",
                                "shares": 0,
                                "justification": "No signals collected",
                                "_applied": False
                            }
                    return decisions

                # Phase 2: Build simplified Portfolio structure for allocator
                from backtest.portfolio_allocator import Portfolio as AllocatorPortfolio
                alloc_portfolio = AllocatorPortfolio(
                    cashflow=self.current_portfolio["cashflow"],
                    positions={
                        ticker: int(pos.get("shares", 0))
                        for ticker, pos in self.current_portfolio["positions"].items()
                    }
                )

                # Phase 3: Unified portfolio allocation
                logger.info(f"Portfolio mode: Making unified allocation decision...")
                target_positions = allocate_with_mandate(
                    self.portfolio_allocator,
                    signals=all_signals,
                    current_portfolio=alloc_portfolio,
                    prices=prices,
                    trading_date=date,
                    decision_memory=self.decision_memory[-5:] if self.decision_memory else None,
                )

                # Phase 4: Convert target ratios to actionable trades
                decisions = self._convert_targets_to_trades(target_positions, prices, date)

                # Record decision to memory
                for ticker, dec in decisions.items():
                    self.decision_memory.append({
                        "trading_date": date,
                        "ticker": ticker,
                        "action": dec.get("action", "HOLD"),
                        "shares": dec.get("shares", 0),
                        "price": prices.get(ticker, 0)
                    })
                    dec["_applied"] = True  # Mark as already applied (in _convert_targets_to_trades)

                logger.info(f"Portfolio allocation decisions: {[(t, d['action'], d.get('shares', 0)) for t, d in decisions.items()]}")
                return decisions

            # ========== LEGACY MODE (PER-STOCK) ==========
            # Run workflow for the day (per-stock)
            llm_decisions = self.workflow_adapter.run_single_day(
                trading_date=date,
                prices=prices,
                prev_portfolio=self.current_portfolio
            )

            # Convert BacktestDecision to dict format
            for ticker, decision in llm_decisions.items():
                decisions[ticker] = {
                    "action": decision.action.upper(),
                    "shares": decision.shares,
                    "price": decision.price,
                    "justification": decision.justification,
                    "_applied": False,
                }

            logger.info(f"LLM decisions for {date}: {[(t, d['action'], d['shares']) for t, d in decisions.items()]}")

        except Exception as e:
            logger.error(f"LLM decision failed for {date}: {e}. Falling back to HOLD.")
            # Fallback to HOLD for all tickers
            for ticker in self.tickers:
                if ticker in prices:
                    decisions[ticker] = {
                        "action": "HOLD",
                        "shares": 0,
                        "justification": f"LLM error: {str(e)}",
                        "_applied": False
                    }

        return decisions

    def _convert_targets_to_trades(
        self,
        target_positions: Dict[str, float],
        prices: Dict[str, float],
        date: str
    ) -> Dict[str, Dict]:
        """
        Convert target position ratios to actionable BUY/SELL/HOLD trades.

        Args:
            target_positions: {ticker: target_ratio (0~1)}
            prices: {ticker: current_price}
            date: Trading date

        Returns:
            {ticker: {"action", "shares", "justification"}}
        """
        return convert_targets_to_trades(
            current_portfolio=self.current_portfolio,
            target_positions=target_positions,
            prices=prices,
            date=date,
            record_trade=self._record_target_trade,
            audit_events=self.broker_audit_events,
        )

    def _record_target_trade(
        self,
        date: str,
        ticker: str,
        action: str,
        shares: int,
        price: float,
        justification: str,
    ) -> None:
        """Record a trade produced by target-weight execution.

        Kept as a small adapter so subclasses can override target-weight trade
        recording without changing generic BUY/SELL execution helpers.
        """
        self.tracker.record_trade(
            date=date,
            ticker=ticker,
            action=action,
            shares=shares,
            price=price,
            justification=justification,
        )

    def _apply_decision_to_portfolio(self, date: str, ticker: str, decision, price: float):
        """Apply a trading decision to the current portfolio state."""
        action = decision.action.upper()
        shares = decision.shares

        if action == "BUY" and shares > 0:
            cost = shares * price
            if cost <= self.current_portfolio["cashflow"]:
                self.current_portfolio["cashflow"] -= cost
                current_shares = self.current_portfolio["positions"][ticker]["shares"]
                new_shares = current_shares + shares
                self.current_portfolio["positions"][ticker] = {
                    "shares": new_shares,
                    "value": round(new_shares * price, 2)
                }
                # Record trade in tracker
                self.tracker.record_trade(
                    date=date,
                    ticker=ticker,
                    action="BUY",
                    shares=shares,
                    price=price
                )
        elif action == "SELL" and shares > 0:
            current_shares = self.current_portfolio["positions"][ticker]["shares"]
            actual_shares = min(shares, current_shares)
            if actual_shares > 0:
                proceeds = actual_shares * price
                self.current_portfolio["cashflow"] += proceeds
                new_shares = current_shares - actual_shares
                self.current_portfolio["positions"][ticker] = {
                    "shares": new_shares,
                    "value": round(new_shares * price, 2)
                }
                # Record trade in tracker
                self.tracker.record_trade(
                    date=date,
                    ticker=ticker,
                    action="SELL",
                    shares=actual_shares,
                    price=price
                )

    def _generate_simple_decisions(self, prices: Dict[str, float]) -> Dict[str, Dict]:
        """
        Generate simple buy-and-hold decisions (fallback when LLM is disabled).

        Args:
            prices: Dict of {ticker: current_price}

        Returns:
            Dict of {ticker: {"action": str, "shares": int}}
        """
        decisions = {}

        # Simple Strategy: First-day allocation, then hold
        for ticker in self.tickers:
            if ticker not in prices:
                decisions[ticker] = {"action": "HOLD", "shares": 0}
                continue

            current_pos = self.current_portfolio["positions"].get(ticker, {})
            current_shares = current_pos.get("shares", 0)

            # If no position, allocate 10% of portfolio
            if current_shares == 0:
                allocation = self.initial_cash * 0.1 / len(self.tickers)
                shares = int(allocation / prices[ticker])
                if shares > 0:
                    decisions[ticker] = {
                        "action": "BUY",
                        "shares": shares,
                        "justification": "Simple strategy: initial allocation",
                        "_applied": False  # Not applied yet, needs _execute_buy
                    }
                else:
                    decisions[ticker] = {"action": "HOLD", "shares": 0, "_applied": False}
            else:
                # Hold existing position
                decisions[ticker] = {"action": "HOLD", "shares": 0, "_applied": False}

        return decisions

    def _execute_buy(self, date: str, ticker: str, shares: int, price: float, justification: str = ""):
        """Execute a buy order."""
        execute_buy_order(
            current_portfolio=self.current_portfolio,
            date=date,
            ticker=ticker,
            shares=shares,
            price=price,
            record_trade=self._record_order_trade,
            warn=logger.warning,
            audit_events=self.broker_audit_events,
            justification=justification,
        )

    def _execute_sell(self, date: str, ticker: str, shares: int, price: float, justification: str = ""):
        """Execute a sell order."""
        execute_sell_order(
            current_portfolio=self.current_portfolio,
            date=date,
            ticker=ticker,
            shares=shares,
            price=price,
            record_trade=self._record_order_trade,
            warn=logger.warning,
            audit_events=self.broker_audit_events,
            justification=justification,
        )

    def _record_order_trade(
        self,
        date: str,
        ticker: str,
        action: str,
        shares: int,
        price: float,
    ) -> None:
        """Record a generic order execution through the portfolio tracker."""
        self.tracker.record_trade(
            date=date,
            ticker=ticker,
            action=action,
            shares=shares,
            price=price,
        )

    def _record_snapshot(self, date: str, prices: Dict[str, float]):
        """Record daily portfolio snapshot."""
        record_portfolio_snapshot(
            current_portfolio=self.current_portfolio,
            date=date,
            prices=prices,
            record_snapshot=self.tracker.record_snapshot,
        )

    def close(self):
        """Clean up resources including workflow adapter."""
        # Close workflow adapter if initialized
        if self.workflow_adapter:
            self.workflow_adapter.close()
        # Call base class close for prefetcher cleanup
        super().close()


def run_backtest(
    tickers: List[str],
    start_date: str,
    end_date: str,
    initial_cash: float = 100000.0,
    market: str = "cn",
    prefetch_only: bool = False,
    config: Optional[Dict[str, Any]] = None,
    use_llm: bool = False,
    analysts: Optional[List[str]] = None,
    personality: str = "balanced",
    smart_priority_mode: bool = True
) -> Optional[BacktestResult]:
    """
    Convenience function to run a backtest.

    Args:
        tickers: List of ticker symbols
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        initial_cash: Starting capital
        market: Market type ("cn" or "us")
        prefetch_only: Only prefetch data without running backtest
        config: Optional configuration dict
        use_llm: Whether to use LLM for intelligent decisions
        analysts: List of analysts (e.g., ["fundamental", "technical"])
        personality: Investment personality (conservative, aggressive, balanced)
        smart_priority_mode: Whether to use smart priority with parallel signal collection

    Returns:
        BacktestResult or None if prefetch_only
    """
    engine = create_backtest_engine(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        market=market,
        config=config,
        use_llm=use_llm,
        analysts=analysts,
        personality=personality,
        smart_priority_mode=smart_priority_mode
    )

    try:
        if prefetch_only:
            engine.prefetch_data(force_sync=True)
            engine.close()
            return None

        result = engine.run(prefetch=True, generate_report=True)
        engine.close()
        return result

    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        engine.close()
        raise


def create_backtest_engine(
    tickers: List[str],
    start_date: str,
    end_date: str,
    initial_cash: float = 100000.0,
    market: str = "cn",
    config: Optional[Dict[str, Any]] = None,
    db_path: str = "data/signal_flux.db",
    use_llm: bool = False,
    analysts: Optional[List[str]] = None,
    personality: str = "balanced",
    portfolio_mode: bool = True,
    smart_priority_mode: bool = True,
    shared_analyst_cache_dir: Optional[str] = None,
    shared_phase1_cache_dir: Optional[str] = None,
) -> BacktestEngine:
    """Create the appropriate backtest engine for the requested personality."""
    engine_cls, routed_personality = _resolve_backtest_engine_route(personality)
    engine_kwargs = _build_engine_kwargs(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        market=market,
        config=config,
        db_path=db_path,
        use_llm=use_llm,
        analysts=analysts,
        personality=routed_personality,
        portfolio_mode=portfolio_mode,
        smart_priority_mode=smart_priority_mode,
        shared_analyst_cache_dir=shared_analyst_cache_dir,
        shared_phase1_cache_dir=shared_phase1_cache_dir,
    )
    return engine_cls(**engine_kwargs)


def _build_engine_kwargs(
    *,
    tickers: List[str],
    start_date: str,
    end_date: str,
    initial_cash: float,
    market: str,
    config: Optional[Dict[str, Any]],
    db_path: str,
    use_llm: bool,
    analysts: Optional[List[str]],
    personality: str,
    portfolio_mode: bool,
    smart_priority_mode: bool,
    shared_analyst_cache_dir: Optional[str],
    shared_phase1_cache_dir: Optional[str],
) -> Dict[str, Any]:
    """Build common constructor kwargs for backtest engines."""
    return {
        "tickers": tickers,
        "start_date": start_date,
        "end_date": end_date,
        "initial_cash": initial_cash,
        "market": market,
        "config": config,
        "db_path": db_path,
        "use_llm": use_llm,
        "analysts": analysts,
        "personality": personality,
        "portfolio_mode": portfolio_mode,
        "smart_priority_mode": smart_priority_mode,
        "shared_analyst_cache_dir": shared_analyst_cache_dir,
        "shared_phase1_cache_dir": shared_phase1_cache_dir,
    }


def _resolve_backtest_engine_route(personality: str):
    """Resolve raw personality/profile input to an engine class and constructor value."""
    normalized_personality = str(personality).strip().lower()
    if normalized_personality == "fof":
        from backtest.fof_engine import FOFBacktestEngine

        return FOFBacktestEngine, normalized_personality

    if normalized_personality in {"macro_tactical", "tactical_allocation"}:
        from backtest.macro_tactical_engine import MacroTacticalBacktestEngine

        return MacroTacticalBacktestEngine, "macro_tactical"

    if normalized_personality in {"fundamental_value", "value"}:
        from backtest.fundamental_value_engine import FundamentalValueBacktestEngine

        # Preserve legacy constructor values until engine internals fully migrate to canonical profiles.
        return FundamentalValueBacktestEngine, normalized_personality

    if normalized_personality in {"behavioral_momentum", "momentum"}:
        from backtest.behavioral_momentum_engine import BehavioralMomentumBacktestEngine

        return BehavioralMomentumBacktestEngine, normalized_personality

    if normalized_personality in {"smart_beta_passive", "smart_beta"}:
        from backtest.smart_beta_engine import SmartBetaBacktestEngine

        return SmartBetaBacktestEngine, normalized_personality

    return BacktestEngine, personality
