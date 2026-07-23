"""
Smart Beta Allocator

Main integration component that orchestrates:
1. Index constituent data retrieval
2. Factor calculation
3. Negative screening
4. Portfolio optimization
5. Macro adjustment
6. News freeze mechanism
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from .config import SmartBetaConfig, get_smart_beta_config
from .factor_engine import FactorEngine, FactorData
from .optimizer import SmartBetaOptimizer, OptimizationResult
from .index_constituents import IndexConstituentsProvider
from .macro_analyzer import MacroStateAnalyzer
from .news_freeze import NewsFreezeMechanism, FreezeDecision


@dataclass
class AllocationResult:
    """
    Result of Smart Beta allocation.

    Attributes:
        weights: Final portfolio weights (ticker -> weight)
        benchmark_weights: Benchmark index weights
        factor_scores: Factor scores for each ticker
        optimization_result: Raw optimization result
        macro_adjustment: Macro-based adjustment factor
        freeze_decision: News freeze decision
        turnover: Required turnover from current portfolio
        tracking_error: Expected tracking error
        timestamp: Allocation timestamp
        success: Whether allocation succeeded
        message: Status message
    """

    weights: Dict[str, float] = field(default_factory=dict)
    benchmark_weights: Dict[str, float] = field(default_factory=dict)
    factor_scores: Dict[str, float] = field(default_factory=dict)
    optimization_result: Optional[OptimizationResult] = None
    macro_adjustment: float = 0.0
    freeze_decision: Optional[FreezeDecision] = None
    turnover: float = 0.0
    tracking_error: float = 0.0
    timestamp: Optional[datetime] = None
    success: bool = False
    message: str = ""

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        reference_date = self.timestamp or datetime.now()
        freeze_state = (
            self.freeze_decision.to_dict(reference_date)
            if self.freeze_decision
            else FreezeDecision().to_dict(reference_date)
        )
        return {
            "weights": self.weights,
            "benchmark_weights": self.benchmark_weights,
            "factor_scores": self.factor_scores,
            "macro_adjustment": self.macro_adjustment,
            "freeze_active": freeze_state["is_active"],
            "freeze_decision": freeze_state,
            "turnover": self.turnover,
            "tracking_error": self.tracking_error,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "success": self.success,
            "message": self.message,
        }


class SmartBetaAllocator:
    """
    Main Smart Beta allocation orchestrator.

    Implements the complete Smart Beta workflow:
    1. Get index constituents
    2. Calculate factors for all constituents
    3. Apply negative screening (high IVOL, low liquidity)
    4. Run quadratic optimization
    5. Apply macro-based adjustments
    6. Check news freeze mechanism
    7. Return final allocation
    """

    def __init__(self, config: Optional[SmartBetaConfig] = None):
        """
        Initialize Smart Beta allocator.

        Args:
            config: SmartBetaConfig instance (optional)
        """
        self.config = config or get_smart_beta_config()

        # Initialize components
        self.factor_engine = FactorEngine(self.config)
        self.optimizer = SmartBetaOptimizer(self.config)
        self.index_provider = IndexConstituentsProvider()
        self.macro_analyzer = MacroStateAnalyzer(self.config)
        self.news_freeze = NewsFreezeMechanism(self.config)

        # Cache
        self._last_allocation: Optional[AllocationResult] = None
        self._current_portfolio_weights: Dict[str, float] = {}

    def allocate(
        self,
        trade_date: datetime,
        stock_data: Dict[str, pd.DataFrame],
        market_data: pd.DataFrame,
        current_portfolio: Optional[Dict[str, int]] = None,
        prices: Optional[Dict[str, float]] = None,
        macro_indicators: Optional[Dict[str, float]] = None,
        news_items: Optional[List[Dict]] = None,
        market_return_today: Optional[float] = None
    ) -> AllocationResult:
        """
        Execute Smart Beta allocation.

        Args:
            trade_date: Trading date
            stock_data: Dictionary of ticker -> OHLCV DataFrame
            market_data: Market index OHLCV DataFrame
            current_portfolio: Current portfolio holdings (ticker -> shares)
            prices: Current prices (ticker -> price)
            macro_indicators: Macroeconomic indicators
            news_items: Recent news items for freeze detection
            market_return_today: Today's market return

        Returns:
            AllocationResult with final portfolio weights
        """
        try:
            # Step 1: Get index constituents
            constituents = self.index_provider.get_constituents(
                self.config.index_code, trade_date
            )

            if not constituents:
                return AllocationResult(
                    timestamp=trade_date,
                    success=False,
                    message="Failed to get index constituents"
                )

            tickers = [self._canonicalize_ticker(c.ticker) for c in constituents]
            benchmark_weights = self._normalize_weights({
                self._canonicalize_ticker(c.ticker): c.weight for c in constituents
            })
            stock_data = self._canonicalize_frame_dict(stock_data)
            prices = self._canonicalize_scalar_dict(prices)
            current_portfolio = self._canonicalize_portfolio(current_portfolio)

            # Step 2: Calculate factors for all constituents
            factor_data = self.factor_engine.batch_calculate_factors(
                tickers=tickers,
                stock_data_dict=stock_data,
                market_data=market_data,
                trade_date=trade_date
            )

            # Step 3: Negative screening
            passed_tickers = self.optimizer.negative_screening(tickers, factor_data)

            if len(passed_tickers) < 10:
                # Not enough stocks pass screening, relax constraints
                passed_tickers = [t for t in tickers if factor_data.get(t, FactorData(t, trade_date)).is_valid]

            if not passed_tickers:
                return AllocationResult(
                    timestamp=trade_date,
                    benchmark_weights=benchmark_weights,
                    success=False,
                    message="No stocks passed negative screening"
                )

            # Step 4: Run optimization
            current_weights_full = self._calculate_current_weights(
                current_portfolio, prices, tickers
            )
            excluded_tickers = [t for t in tickers if t not in passed_tickers]

            # Optimize against the true benchmark universe while forcing screened
            # names to zero weight.
            opt_result = self.optimizer.optimize(
                tickers=tickers,
                benchmark_weights=benchmark_weights,
                factor_data=factor_data,
                current_weights=current_weights_full,
                excluded_tickers=excluded_tickers,
            )

            if not opt_result.success:
                # Use the full benchmark as fallback so defensive paths do not
                # unintentionally liquidate screened-out benchmark names.
                opt_result = OptimizationResult(
                    weights=dict(benchmark_weights),
                    tracking_error=0,
                    success=True,
                    message="Using benchmark weights (optimization failed)"
                )

            # Apply turnover constraint against the full benchmark universe.
            final_weights = self.optimizer.apply_turnover_constraint(
                target_weights=opt_result.weights,
                current_weights=current_weights_full,
                turnover_limit=self.config.turnover_limit
            )

            # Step 5: Macro adjustment
            macro_adjustment = 0.0
            if macro_indicators and self.config.llm_adjustment_enabled:
                market_returns = None
                if not market_data.empty and "close" in market_data.columns:
                    market_returns = market_data["close"].pct_change().dropna().tolist()

                macro_analysis = self.macro_analyzer.analyze(
                    indicators_data=macro_indicators,
                    trade_date=trade_date,
                    market_returns=market_returns
                )

                macro_adjustment = macro_analysis.beta_adjustment

                # Apply macro adjustment to weights
                if abs(macro_adjustment) > 0.01:
                    final_weights = self._apply_macro_adjustment(
                        weights=final_weights,
                        benchmark_weights=benchmark_weights,
                        adjustment=macro_adjustment
                    )

            # Step 6: News freeze check
            freeze_decision = None
            market_volatility = None
            if not market_data.empty and "close" in market_data.columns:
                returns = market_data["close"].pct_change().dropna()
                if len(returns) > 20:
                    market_volatility = returns.std() * np.sqrt(252)

            should_evaluate_freeze = (
                news_items is not None
                or market_return_today is not None
                or market_volatility is not None
                or self.news_freeze.get_active_freeze(trade_date) is not None
            )
            if should_evaluate_freeze:
                freeze_decision = self.news_freeze.check(
                    market_volatility=market_volatility,
                    market_return=market_return_today,
                    news_items=news_items,
                    current_date=trade_date
                )

                # Evaluate freeze against the simulated trade date, not wall-clock time.
                if freeze_decision.is_active_at(trade_date):
                    final_weights = dict(benchmark_weights)

            # Calculate factor scores for reporting
            factor_scores = {
                t: fd.factor_score if fd.factor_score else 0.0
                for t, fd in factor_data.items()
                if fd.is_valid
            }

            # Calculate turnover using the same asset + cash bucket semantics
            # as the optimizer constraint.
            turnover = self._calculate_turnover_with_cash(
                target_weights=final_weights,
                current_weights=current_weights_full,
            )

            tracking_error = self._calculate_tracking_error(
                target_weights=final_weights,
                benchmark_weights=benchmark_weights,
                optimization_result=opt_result,
            )
            if freeze_decision and freeze_decision.is_active_at(trade_date):
                tracking_error = 0.0

            result = AllocationResult(
                weights=final_weights,
                benchmark_weights=benchmark_weights,
                factor_scores=factor_scores,
                optimization_result=opt_result,
                macro_adjustment=macro_adjustment,
                freeze_decision=freeze_decision,
                turnover=turnover,
                tracking_error=tracking_error,
                timestamp=trade_date,
                success=True,
                message="Smart Beta allocation completed"
            )

            # Cache result
            self._last_allocation = result
            self._current_portfolio_weights = final_weights

            return result

        except Exception as e:
            return AllocationResult(
                timestamp=trade_date,
                success=False,
                message=f"Allocation error: {str(e)}"
            )

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Normalize a weight map to sum to 1.0 while preserving zero-weight entries."""
        total = sum(weights.values())
        if total <= 0:
            return weights
        return {ticker: weight / total for ticker, weight in weights.items()}

    def _canonicalize_ticker(self, ticker: Optional[str]) -> str:
        """Normalize ticker keys so CN symbols with exchange suffixes match bare backtest tickers."""
        symbol = str(ticker or "").strip().upper()
        if "." in symbol:
            base, suffix = symbol.split(".", 1)
            if suffix in {"SH", "SZ", "BJ"}:
                return base
        return symbol

    def _canonicalize_scalar_dict(self, values: Optional[Dict[str, float]]) -> Dict[str, float]:
        """Canonicalize ticker-keyed scalar dictionaries."""
        canonical: Dict[str, float] = {}
        for ticker, value in (values or {}).items():
            canonical[self._canonicalize_ticker(ticker)] = value
        return canonical

    def _canonicalize_frame_dict(self, frames: Optional[Dict[str, pd.DataFrame]]) -> Dict[str, pd.DataFrame]:
        """Canonicalize ticker-keyed DataFrame dictionaries."""
        canonical: Dict[str, pd.DataFrame] = {}
        for ticker, frame in (frames or {}).items():
            canonical[self._canonicalize_ticker(ticker)] = frame
        return canonical

    def _canonicalize_portfolio(self, portfolio: Optional[Dict]) -> Dict:
        """Canonicalize ticker keys in structured or flat portfolio payloads."""
        if not portfolio:
            return {}

        if isinstance(portfolio, dict) and "positions" in portfolio:
            positions = {
                self._canonicalize_ticker(ticker): position
                for ticker, position in (portfolio.get("positions", {}) or {}).items()
            }
            return {
                **portfolio,
                "positions": positions,
            }

        if isinstance(portfolio, dict):
            return {
                self._canonicalize_ticker(ticker): position
                for ticker, position in portfolio.items()
            }

        return portfolio

    def _calculate_tracking_error(
        self,
        target_weights: Dict[str, float],
        benchmark_weights: Dict[str, float],
        optimization_result: Optional[OptimizationResult] = None,
    ) -> float:
        """Compute annualized tracking error from the final shipped weights."""
        all_keys = sorted(set(target_weights.keys()) | set(benchmark_weights.keys()))
        if not all_keys:
            return 0.0

        diff = np.array([
            target_weights.get(key, 0.0) - benchmark_weights.get(key, 0.0)
            for key in all_keys
        ], dtype=float)

        covariance = None
        if (
            optimization_result
            and getattr(optimization_result, "covariance_matrix", None)
            and getattr(optimization_result, "benchmark_vector", None)
        ):
            benchmark_vector = optimization_result.benchmark_vector or {}
            covariance_lookup = np.array(optimization_result.covariance_matrix, dtype=float)
            optimizer_keys = list(benchmark_vector.keys())
            index_map = {key: idx for idx, key in enumerate(optimizer_keys)}
            covariance = np.zeros((len(all_keys), len(all_keys)), dtype=float)
            for i, key_i in enumerate(all_keys):
                for j, key_j in enumerate(all_keys):
                    idx_i = index_map.get(key_i)
                    idx_j = index_map.get(key_j)
                    if idx_i is not None and idx_j is not None:
                        covariance[i, j] = covariance_lookup[idx_i, idx_j]

        if covariance is None:
            # Fallback approximation when no optimizer covariance is available.
            covariance = np.eye(len(all_keys)) * 1e-6

        return float(np.sqrt((diff @ covariance @ diff) * self.config.market_days_per_year))

    def _calculate_turnover_with_cash(
        self,
        target_weights: Dict[str, float],
        current_weights: Dict[str, float],
    ) -> float:
        """Calculate turnover using the same explicit cash bucket semantics as the optimizer."""
        cash_bucket = getattr(self.optimizer, "CASH_BUCKET", "__cash__")
        current_with_cash = dict(current_weights)
        target_with_cash = dict(target_weights)
        current_with_cash[cash_bucket] = max(0.0, 1.0 - sum(current_weights.values()))
        target_with_cash[cash_bucket] = max(0.0, 1.0 - sum(target_weights.values()))

        all_keys = set(current_with_cash.keys()) | set(target_with_cash.keys())
        return sum(
            abs(target_with_cash.get(key, 0.0) - current_with_cash.get(key, 0.0))
            for key in all_keys
        ) / 2

    def _calculate_current_weights(
        self,
        current_portfolio: Optional[Dict[str, int]],
        prices: Optional[Dict[str, float]],
        tickers: List[str]
    ) -> Dict[str, float]:
        """
        Calculate current portfolio weights.

        Args:
            current_portfolio: Current holdings (ticker -> shares)
            prices: Current prices (ticker -> price)
            tickers: List of relevant tickers (for output keys)

        Returns:
            Dictionary of ticker -> weight (based on full portfolio value)
        """
        if not current_portfolio or not prices:
            return {t: 0.0 for t in tickers}

        holdings = current_portfolio
        cash_value = 0.0
        if isinstance(current_portfolio, dict) and "positions" in current_portfolio:
            holdings = current_portfolio.get("positions", {})
            cash_value = float(current_portfolio.get("cashflow", 0.0) or 0.0)

        holdings_dict = holdings if isinstance(holdings, dict) else {}

        # Calculate FULL portfolio value including idle cash.
        full_portfolio_value = cash_value + sum(
            (position.get("shares", 0) if isinstance(position, dict) else position) * prices.get(t, 0)
            for t, position in holdings_dict.items()
        )

        if full_portfolio_value <= 0:
            return {t: 0.0 for t in tickers}

        # Calculate weights for requested tickers
        weights = {}
        for t in tickers:
            position = holdings_dict.get(t, 0)
            shares = position.get("shares", 0) if isinstance(position, dict) else position
            price = prices.get(t, 0)
            weights[t] = (shares * price) / full_portfolio_value

        return weights

    def _apply_macro_adjustment(
        self,
        weights: Dict[str, float],
        benchmark_weights: Dict[str, float],
        adjustment: float
    ) -> Dict[str, float]:
        """
        Apply macro-based adjustment to portfolio weights.

        Positive adjustment = more aggressive (tilt towards high beta)
        Negative adjustment = more defensive (tilt towards low beta)

        Args:
            weights: Current portfolio weights
            benchmark_weights: Benchmark weights
            adjustment: Adjustment factor (-0.3 to 0.3)

        Returns:
            Adjusted weights
        """
        if abs(adjustment) < 0.01:
            return weights

        # Calculate deviation from benchmark
        adjusted_weights = {}
        for t in weights:
            current = weights[t]
            benchmark = benchmark_weights.get(t, 0)

            # If adjustment is positive, move away from benchmark (more aggressive)
            # If adjustment is negative, move towards benchmark (more defensive)
            if adjustment > 0:
                # Increase positions that are above benchmark
                deviation = current - benchmark
                adjusted = current + adjustment * deviation * 2
            else:
                # Move towards benchmark
                adjusted = current + abs(adjustment) * (benchmark - current)

            # Apply LLM weight cap
            max_deviation = self.config.llm_weight_cap
            adjusted = max(benchmark - max_deviation, min(benchmark + max_deviation, adjusted))

            adjusted_weights[t] = max(0, adjusted)

        # Normalize
        total = sum(adjusted_weights.values())
        if total > 0:
            adjusted_weights = {t: w / total for t, w in adjusted_weights.items()}

        return adjusted_weights

    def get_trading_decisions(
        self,
        allocation: AllocationResult,
        current_portfolio: Dict[str, int],
        prices: Dict[str, float],
        total_capital: float
    ) -> List[Dict]:
        """
        Convert allocation to trading decisions.

        Args:
            allocation: AllocationResult from allocate()
            current_portfolio: Current holdings (ticker -> shares)
            prices: Current prices (ticker -> price)
            total_capital: Total available capital

        Returns:
            List of trading decisions with action, ticker, shares, price
        """
        decisions = []
        holdings = current_portfolio
        if isinstance(current_portfolio, dict) and "positions" in current_portfolio:
            holdings = current_portfolio.get("positions", {})
        holdings_dict = holdings if isinstance(holdings, dict) else {}

        # Process tickers in target allocation
        for ticker, target_weight in allocation.weights.items():
            if target_weight < 0.001:
                continue

            price = prices.get(ticker)
            if not price or price <= 0:
                continue

            # Calculate target shares
            target_value = target_weight * total_capital
            target_shares = int(target_value / price)

            # Current shares
            position = holdings_dict.get(ticker, 0)
            current_shares = position.get("shares", 0) if isinstance(position, dict) else position

            # Trade size
            trade_shares = target_shares - current_shares

            if abs(trade_shares) == 0:
                continue

            action = "Buy" if trade_shares > 0 else "Sell"

            decisions.append({
                "action": action,
                "ticker": ticker,
                "shares": abs(trade_shares),
                "price": price,
                "current_shares": current_shares,
                "target_shares": target_shares,
                "target_weight": target_weight
            })

        # Process tickers held but not in new allocation (should be sold)
        for ticker, position in holdings_dict.items():
            current_shares = position.get("shares", 0) if isinstance(position, dict) else position
            if current_shares == 0:
                continue
            
            # Skip if already in decisions (already processed above)
            if any(d["ticker"] == ticker for d in decisions):
                continue
            
            # This ticker should be fully liquidated
            price = prices.get(ticker)
            if not price or price <= 0:
                continue
            
            decisions.append({
                "action": "Sell",
                "ticker": ticker,
                "shares": current_shares,
                "price": price,
                "current_shares": current_shares,
                "target_shares": 0,
                "target_weight": 0.0
            })

        # Deterministic sell-before-buy ordering avoids cash-dependent partial
        # failures during same-day rotations.
        decisions.sort(key=lambda d: (0 if d["action"] == "Sell" else 1, d["ticker"]))
        return decisions

    def should_rebalance(
        self,
        last_rebalance_date: Optional[datetime],
        current_date: datetime
    ) -> bool:
        """
        Check if portfolio should be rebalanced based on frequency.

        Args:
            last_rebalance_date: Date of last rebalance
            current_date: Current date

        Returns:
            True if rebalance is due
        """
        if last_rebalance_date is None:
            return True

        days_since_rebalance = (current_date - last_rebalance_date).days

        if self.config.rebalance_frequency == "monthly":
            return days_since_rebalance >= 21  # ~21 trading days per month
        elif self.config.rebalance_frequency == "quarterly":
            return days_since_rebalance >= 63  # ~63 trading days per quarter

        return False

    def get_llm_prompt_context(self, allocation: AllocationResult) -> Dict:
        """
        Generate context for LLM-based decision making.

        Args:
            allocation: AllocationResult

        Returns:
            Dictionary with prompt context
        """
        # Top holdings
        sorted_weights = sorted(
            allocation.weights.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        top_holdings = [
            f"{ticker}: {weight:.2%}"
            for ticker, weight in sorted_weights
        ]

        # Factor summary
        factor_summary = []
        for ticker, score in sorted(allocation.factor_scores.items(), key=lambda x: x[1], reverse=True)[:5]:
            factor_summary.append(f"{ticker}: {score:.4f}")

        # Freeze context should come from the immutable allocation snapshot,
        # not the allocator's current mutable freeze state.
        freeze_payload = (
            allocation.freeze_decision.to_dict(allocation.timestamp)
            if allocation.freeze_decision
            else FreezeDecision().to_dict(allocation.timestamp)
        )
        freeze_context = {
            "freeze_active": freeze_payload["is_active"],
            "freeze_reason": freeze_payload["reason"],
            "freeze_duration_days": freeze_payload["duration_days"],
            "days_remaining": freeze_payload["days_remaining"],
            "freeze_triggers": freeze_payload["triggers"],
            "freeze_confidence": freeze_payload["confidence"],
            "freeze_start_date": freeze_payload["start_date"],
            "freeze_end_date": freeze_payload["end_date"],
        }

        return {
            "index_code": self.config.index_code,
            "rebalance_frequency": self.config.rebalance_frequency,
            "tracking_error": f"{allocation.tracking_error:.2%}",
            "turnover": f"{allocation.turnover:.2%}",
            "macro_adjustment": f"{allocation.macro_adjustment:.2%}",
            "top_holdings": top_holdings,
            "factor_summary": factor_summary,
            "freeze_status": freeze_context,
            "success": allocation.success,
            "message": allocation.message,
            "timestamp": allocation.timestamp.isoformat() if allocation.timestamp else None
        }
