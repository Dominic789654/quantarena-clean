"""
Performance Metrics for Backtesting
====================================

Calculates various performance metrics including returns, drawdown,
and risk-adjusted measures.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np


class PerformanceMetrics:
    """
    Performance calculation utilities for backtesting.

    Provides methods for:
    - Total and annualized returns
    - Maximum drawdown
    - Sharpe ratio
    - Win rate
    - Volatility
    """

    TRADING_DAYS_PER_YEAR = 252

    @staticmethod
    def total_return(equity_curve: pd.DataFrame) -> float:
        """
        Calculate total return from equity curve.

        Args:
            equity_curve: DataFrame with 'total_value' column

        Returns:
            Total return as percentage
        """
        if equity_curve.empty or len(equity_curve) < 1:
            return 0.0

        initial = equity_curve['total_value'].iloc[0]
        final = equity_curve['total_value'].iloc[-1]

        if initial <= 0:
            return 0.0

        return round((final - initial) / initial * 100, 2)

    @staticmethod
    def annualized_return(daily_returns: pd.Series, trading_days: int = 252) -> float:
        """
        Calculate annualized return from daily returns.

        Args:
            daily_returns: Series of daily return percentages
            trading_days: Trading days per year (default 252)

        Returns:
            Annualized return as percentage
        """
        if daily_returns.empty:
            return 0.0

        # Convert percentage returns to decimal
        returns_decimal = daily_returns / 100

        # Calculate compound return
        total_return = (1 + returns_decimal).prod() - 1

        # Annualize
        n_days = len(returns_decimal)
        if n_days == 0:
            return 0.0

        annual_factor = trading_days / n_days
        annualized = ((1 + total_return) ** annual_factor - 1) * 100

        return round(annualized, 2)

    @staticmethod
    def max_drawdown(equity_curve: pd.DataFrame) -> float:
        """
        Calculate maximum drawdown from equity curve.

        Args:
            equity_curve: DataFrame with 'total_value' column

        Returns:
            Maximum drawdown as positive percentage (e.g., 20.5 = 20.5% drawdown)
        """
        if equity_curve.empty or 'total_value' not in equity_curve.columns:
            return 0.0

        values = equity_curve['total_value']

        # Calculate running maximum
        running_max = values.cummax()

        # Calculate drawdown
        drawdown = (values - running_max) / running_max * 100

        # Return the maximum (most negative) drawdown as positive
        max_dd = drawdown.min()

        return round(abs(max_dd), 2)

    @staticmethod
    def max_drawdown_duration(equity_curve: pd.DataFrame) -> int:
        """
        Calculate maximum drawdown duration in days.

        Args:
            equity_curve: DataFrame with 'total_value' column

        Returns:
            Maximum drawdown duration in trading days
        """
        if equity_curve.empty or 'total_value' not in equity_curve.columns:
            return 0

        values = equity_curve['total_value']
        running_max = values.cummax()

        # Find periods where we're in drawdown
        in_drawdown = values < running_max

        # Calculate longest streak
        max_duration = 0
        current_duration = 0

        for is_dd in in_drawdown:
            if is_dd:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                current_duration = 0

        return max_duration

    @staticmethod
    def sharpe_ratio(
        daily_returns: pd.Series,
        risk_free_rate: float = 0.02,
        trading_days: int = 252
    ) -> Optional[float]:
        """
        Calculate Sharpe ratio from daily returns.

        Args:
            daily_returns: Series of daily return percentages
            risk_free_rate: Annual risk-free rate (default 2%)
            trading_days: Trading days per year (default 252)

        Returns:
            Sharpe ratio
        """
        if daily_returns.empty or len(daily_returns) < 2:
            return 0.0

        # Convert percentage to decimal
        returns_decimal = daily_returns / 100

        # Daily risk-free rate
        daily_rf = risk_free_rate / trading_days

        # Excess returns
        excess_returns = returns_decimal - daily_rf

        # Calculate Sharpe
        mean_excess = excess_returns.mean()
        std_returns = excess_returns.std()

        if std_returns == 0 or pd.isna(std_returns):
            return 0.0

        # Annualize
        sharpe = (mean_excess / std_returns) * np.sqrt(trading_days)

        return round(sharpe, 2)

    @staticmethod
    def sortino_ratio(
        daily_returns: pd.Series,
        risk_free_rate: float = 0.02,
        trading_days: int = 252
    ) -> Optional[float]:
        """
        Calculate Sortino ratio from daily returns.

        Uses downside deviation instead of total standard deviation.

        Args:
            daily_returns: Series of daily return percentages
            risk_free_rate: Annual risk-free rate (default 2%)
            trading_days: Trading days per year (default 252)

        Returns:
            Sortino ratio
        """
        if daily_returns.empty or len(daily_returns) < 2:
            return 0.0

        # Convert percentage to decimal
        returns_decimal = daily_returns / 100

        # Daily risk-free rate
        daily_rf = risk_free_rate / trading_days

        # Excess returns
        excess_returns = returns_decimal - daily_rf
        mean_excess = excess_returns.mean()

        # Downside deviation (only negative returns)
        negative_returns = excess_returns[excess_returns < 0]

        if len(negative_returns) == 0:
            return float('inf') if mean_excess > 0 else 0.0

        downside_std = negative_returns.std()

        if downside_std == 0 or pd.isna(downside_std):
            return 0.0

        # Annualize
        sortino = (mean_excess / downside_std) * np.sqrt(trading_days)

        return round(sortino, 2)

    @staticmethod
    def volatility(daily_returns: pd.Series, trading_days: int = 252) -> float:
        """
        Calculate annualized volatility from daily returns.

        Args:
            daily_returns: Series of daily return percentages
            trading_days: Trading days per year (default 252)

        Returns:
            Annualized volatility as percentage
        """
        if daily_returns.empty or len(daily_returns) < 2:
            return 0.0

        # Convert percentage to decimal
        returns_decimal = daily_returns / 100

        # Calculate daily std and annualize
        daily_std = returns_decimal.std()
        annual_vol = daily_std * np.sqrt(trading_days) * 100

        return round(annual_vol, 2)

    @staticmethod
    def calmar_ratio(daily_returns: pd.Series, equity_curve: pd.DataFrame) -> float:
        """Calculate Calmar ratio as annualized return divided by max drawdown."""
        if daily_returns.empty or equity_curve.empty:
            return 0.0

        annualized_return = PerformanceMetrics.annualized_return(daily_returns)
        max_drawdown = PerformanceMetrics.max_drawdown(equity_curve)
        if max_drawdown <= 0:
            return float('inf') if annualized_return > 0 else 0.0

        return round(annualized_return / max_drawdown, 2)

    @staticmethod
    def cvar(
        daily_returns: pd.Series,
        alpha: float = 0.05,
    ) -> float:
        """Calculate conditional value at risk from daily return percentages."""
        if daily_returns.empty:
            return 0.0

        returns = pd.Series(daily_returns, dtype=float).dropna()
        if returns.empty:
            return 0.0

        var_threshold = returns.quantile(alpha)
        tail_losses = returns[returns <= var_threshold]
        tail_losses = tail_losses[tail_losses < 0]
        if tail_losses.empty:
            return 0.0

        return round(abs(float(tail_losses.mean())), 2)

    @staticmethod
    def win_rate(
        trades: List,
        final_prices: Dict[str, float]
    ) -> float:
        """
        Calculate win rate from closed trades.

        A trade is considered a "win" if:
        - BUY trade: current price > buy price
        - SELL trade: sell price > average buy price for that ticker

        Args:
            trades: List of Trade objects
            final_prices: Dict of {ticker: final_price}

        Returns:
            Win rate as percentage
        """
        if not trades:
            return 0.0

        # Track cost basis per ticker
        cost_basis = {}  # {ticker: [(shares, price), ...]}
        wins = 0
        total_closed = 0

        for trade in trades:
            ticker = trade.ticker

            if trade.action == "BUY":
                if ticker not in cost_basis:
                    cost_basis[ticker] = []
                cost_basis[ticker].append((trade.shares, trade.price))

            elif trade.action == "SELL":
                if ticker in cost_basis and cost_basis[ticker]:
                    # Calculate average cost
                    total_shares = sum(s for s, _ in cost_basis[ticker])
                    if total_shares > 0:
                        avg_cost = sum(s * p for s, p in cost_basis[ticker]) / total_shares

                        # Check if profitable
                        if trade.price > avg_cost:
                            wins += 1
                        total_closed += 1

                        # Reduce cost basis
                        remaining = trade.shares
                        new_basis = []
                        for s, p in cost_basis[ticker]:
                            if remaining <= 0:
                                new_basis.append((s, p))
                            elif s <= remaining:
                                remaining -= s
                            else:
                                new_basis.append((s - remaining, p))
                                remaining = 0
                        cost_basis[ticker] = new_basis

        # Check open positions
        for ticker, lots in cost_basis.items():
            if lots and ticker in final_prices:
                total_shares = sum(s for s, _ in lots)
                if total_shares > 0:
                    avg_cost = sum(s * p for s, p in lots) / total_shares
                    final_price = final_prices[ticker]
                    if final_price > avg_cost:
                        wins += 1
                    total_closed += 1

        if total_closed == 0:
            return 0.0

        return round(wins / total_closed * 100, 2)

    @staticmethod
    def profit_factor(trades: List) -> float:
        """
        Calculate profit factor (gross profit / gross loss).

        Args:
            trades: List of Trade objects with justification containing P&L info

        Returns:
            Profit factor (>1 is profitable)
        """
        if not trades:
            return 0.0

        gross_profit = 0.0
        gross_loss = 0.0

        for trade in trades:
            pnl = None
            if isinstance(trade, dict):
                pnl = trade.get("pnl")
            else:
                pnl = getattr(trade, "pnl", None)

            if pnl is None:
                continue

            pnl = float(pnl)
            if pnl > 0:
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += abs(pnl)

        if gross_loss == 0:
            return round(gross_profit, 2) if gross_profit > 0 else 0.0

        return round(gross_profit / gross_loss, 2)

    # ---------------------------------------------------------------------
    # Backward-compatible metric helpers (kept for legacy tests/callers)
    # ---------------------------------------------------------------------

    @staticmethod
    def calculate_total_return(initial: float, final: float) -> float:
        """Legacy API: returns percentage gain/loss (e.g., 10.0 for +10%)."""
        if initial <= 0:
            return 0.0
        return round((final - initial) / initial * 100, 2)

    @staticmethod
    def calculate_annualized_return(total_return: float, trading_days: int = 252) -> float:
        """
        Legacy API: total_return uses decimal form (0.10 => +10%).
        Returns decimal annualized return.
        """
        if trading_days <= 0:
            return 0.0
        annual_factor = PerformanceMetrics.TRADING_DAYS_PER_YEAR / trading_days
        annualized = (1 + total_return) ** annual_factor - 1
        return round(float(annualized), 4)

    @staticmethod
    def calculate_sharpe_ratio(
        returns: List[float],
        risk_free_rate: float = 0.02,
        trading_days: int = 252,
    ) -> float:
        """Legacy API: returns list is decimal daily returns."""
        if not returns or len(returns) < 2:
            return 0.0
        series = pd.Series(returns, dtype=float)
        daily_rf = risk_free_rate / trading_days
        excess_returns = series - daily_rf
        std = excess_returns.std()
        if std == 0 or pd.isna(std):
            return 0.0
        return round(float((excess_returns.mean() / std) * np.sqrt(trading_days)), 2)

    @staticmethod
    def calculate_max_drawdown(values: List[float]) -> float:
        """Legacy API: returns negative decimal drawdown (e.g., -0.12)."""
        if not values or len(values) < 2:
            return 0.0

        series = pd.Series(values, dtype=float)
        running_max = series.cummax()
        drawdowns = (series - running_max) / running_max
        min_dd = drawdowns.min()
        if pd.isna(min_dd):
            return 0.0
        return round(float(min_dd), 4)

    @staticmethod
    def calculate_win_rate(trades: List[Dict[str, Any]]) -> float:
        """Legacy API: trades are dicts with a 'pnl' field."""
        if not trades:
            return 0.0
        wins = 0
        for trade in trades:
            pnl = float(trade.get("pnl", 0))
            if pnl >= 0:
                wins += 1
        return round(wins / len(trades) * 100, 2)

    @staticmethod
    def calculate_profit_factor(trades: List[Dict[str, Any]]) -> float:
        """Legacy API: trades are dicts with a 'pnl' field."""
        return PerformanceMetrics.profit_factor(trades)

    @staticmethod
    def calculate_all(
        tracker,
        final_prices: Optional[Dict[str, float]] = None,
        benchmark_returns: Optional[pd.Series] = None,
    ) -> Dict[str, float]:
        """
        Calculate all performance metrics from a PortfolioTracker.

        Args:
            tracker: PortfolioTracker instance
            final_prices: Optional dict of {ticker: final_price} for win rate
            benchmark_returns: Optional benchmark daily return percentages

        Returns:
            Dict with all calculated metrics
        """
        equity_curve = tracker.get_equity_curve()
        daily_returns = equity_curve['daily_return'] if not equity_curve.empty else pd.Series()
        # Align portfolio returns to trading dates when available, so benchmark
        # series indexed by date can be merged correctly.
        if not equity_curve.empty and "date" in equity_curve.columns:
            date_index = pd.to_datetime(equity_curve["date"], errors="coerce")
            if date_index.notna().all():
                daily_returns = daily_returns.copy()
                daily_returns.index = date_index
        trades = tracker.get_trades()

        metrics = {
            "total_return": PerformanceMetrics.total_return(equity_curve),
            "annualized_return": PerformanceMetrics.annualized_return(daily_returns),
            "max_drawdown": PerformanceMetrics.max_drawdown(equity_curve),
            "max_drawdown_duration": PerformanceMetrics.max_drawdown_duration(equity_curve),
            "sharpe_ratio": PerformanceMetrics.sharpe_ratio(daily_returns),
            "sortino_ratio": PerformanceMetrics.sortino_ratio(daily_returns),
            "calmar_ratio": PerformanceMetrics.calmar_ratio(daily_returns, equity_curve),
            "cvar_95": PerformanceMetrics.cvar(daily_returns, alpha=0.05),
            "volatility": PerformanceMetrics.volatility(daily_returns),
            "total_trades": len(trades),
            "trading_days": len(equity_curve),
            "avg_position_days": tracker.calculate_avg_position_days(),
        }
        metrics.update(PerformanceMetrics.turnover_stats(tracker))

        if final_prices:
            metrics["win_rate"] = PerformanceMetrics.win_rate(trades, final_prices)
        else:
            metrics["win_rate"] = 0.0

        # Add portfolio summary
        summary = tracker.get_summary()
        metrics["initial_cash"] = summary["initial_cash"]
        metrics["final_value"] = summary["final_value"]
        metrics["final_cash"] = summary["final_cash"]

        if benchmark_returns is not None and not benchmark_returns.empty:
            aligned = pd.DataFrame(
                {"portfolio": daily_returns, "benchmark": benchmark_returns}
            ).dropna()
            if len(aligned) >= 2:
                benchmark_total_return = (1 + aligned["benchmark"] / 100.0).prod() - 1
                metrics["benchmark_annualized_return"] = PerformanceMetrics.annualized_return(
                    aligned["benchmark"]
                )
                metrics["benchmark_total_return"] = round(benchmark_total_return * 100, 2)
                metrics["excess_return"] = PerformanceMetrics.excess_return(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["tracking_error"] = PerformanceMetrics.tracking_error(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["information_ratio"] = PerformanceMetrics.information_ratio(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["up_capture_ratio"] = PerformanceMetrics.up_capture_ratio(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["down_capture_ratio"] = PerformanceMetrics.down_capture_ratio(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["beta"] = PerformanceMetrics.beta(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["alpha"] = PerformanceMetrics.alpha(
                    aligned["portfolio"],
                    aligned["benchmark"],
                )
                metrics["break_even_transaction_cost"] = PerformanceMetrics.break_even_transaction_cost(
                    aligned["portfolio"],
                    aligned["benchmark"],
                    float(metrics.get("total_turnover_ratio", 0.0) or 0.0),
                )
            else:
                metrics["benchmark_annualized_return"] = 0.0
                metrics["benchmark_total_return"] = 0.0
                metrics["excess_return"] = 0.0
                metrics["tracking_error"] = 0.0
                metrics["information_ratio"] = 0.0
                metrics["up_capture_ratio"] = 0.0
                metrics["down_capture_ratio"] = 0.0
                metrics["beta"] = None
                metrics["alpha"] = None
                metrics["break_even_transaction_cost"] = 0.0

        return metrics

    # =========================================================================
    # Smart Beta Specific Metrics
    # =========================================================================

    @staticmethod
    def tracking_error(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        trading_days: int = 252
    ) -> float:
        """
        Calculate tracking error (annualized standard deviation of excess returns).

        Tracking error measures how closely a portfolio follows its benchmark.
        Lower tracking error = better tracking.

        Args:
            portfolio_returns: Series of daily portfolio return percentages
            benchmark_returns: Series of daily benchmark return percentages
            trading_days: Trading days per year (default 252)

        Returns:
            Annualized tracking error as percentage
        """
        if portfolio_returns.empty or benchmark_returns.empty:
            return None

        # Align series
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns
        }).dropna()

        if len(aligned) < 2:
            return 0.0

        # Calculate excess returns
        excess_returns = aligned['portfolio'] - aligned['benchmark']

        # Calculate daily std and annualize
        daily_std = excess_returns.std()
        annual_te = daily_std * np.sqrt(trading_days)

        return round(annual_te, 2)

    @staticmethod
    def information_ratio(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        trading_days: int = 252
    ) -> float:
        """
        Calculate information ratio (excess return / tracking error).

        Information ratio measures risk-adjusted excess returns over benchmark.
        Higher IR = better risk-adjusted performance.

        Interpretation:
            - IR > 0.5: Good
            - IR > 1.0: Excellent
            - IR < 0: Underperforming benchmark

        Args:
            portfolio_returns: Series of daily portfolio return percentages
            benchmark_returns: Series of daily benchmark return percentages
            trading_days: Trading days per year (default 252)

        Returns:
            Information ratio
        """
        if portfolio_returns.empty or benchmark_returns.empty:
            return 0.0

        # Align series
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns
        }).dropna()

        if len(aligned) < 2:
            return 0.0

        # Calculate excess returns
        excess_returns = aligned['portfolio'] - aligned['benchmark']

        # Calculate annualized excess return
        mean_excess = excess_returns.mean()
        annual_excess = mean_excess * trading_days

        # Calculate tracking error
        te = PerformanceMetrics.tracking_error(
            aligned['portfolio'],
            aligned['benchmark'],
            trading_days
        )

        if te == 0:
            return 0.0

        # Information ratio
        ir = (annual_excess / te)

        return round(ir, 2)

    @staticmethod
    def up_capture_ratio(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
    ) -> float:
        """Calculate up-capture ratio on days when the benchmark is positive."""
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns,
        }).dropna()

        if aligned.empty:
            return 0.0

        up_days = aligned[aligned['benchmark'] > 0]
        if up_days.empty:
            return 0.0

        portfolio_cum = (1 + up_days['portfolio'] / 100.0).prod() - 1
        benchmark_cum = (1 + up_days['benchmark'] / 100.0).prod() - 1
        if abs(float(benchmark_cum)) < 1e-12:
            return 0.0

        return round(float(portfolio_cum / benchmark_cum), 2)

    @staticmethod
    def down_capture_ratio(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
    ) -> float:
        """Calculate down-capture ratio on days when the benchmark is negative."""
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns,
        }).dropna()

        if aligned.empty:
            return 0.0

        down_days = aligned[aligned['benchmark'] < 0]
        if down_days.empty:
            return 0.0

        portfolio_cum = (1 + down_days['portfolio'] / 100.0).prod() - 1
        benchmark_cum = (1 + down_days['benchmark'] / 100.0).prod() - 1
        if abs(float(benchmark_cum)) < 1e-12:
            return 0.0

        return round(float(portfolio_cum / benchmark_cum), 2)

    @staticmethod
    def beta(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> float:
        """
        Calculate portfolio beta relative to benchmark.

        Beta measures systematic risk / market sensitivity.
        - Beta = 1: Moves with market
        - Beta > 1: More volatile than market
        - Beta < 1: Less volatile than market

        Args:
            portfolio_returns: Series of daily portfolio return percentages
            benchmark_returns: Series of daily benchmark return percentages

        Returns:
            Portfolio beta
        """
        if portfolio_returns.empty or benchmark_returns.empty:
            return None

        # Align series
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns
        }).dropna()

        if len(aligned) < 10:
            return None

        # Calculate covariance matrix
        cov_matrix = np.cov(aligned['portfolio'], aligned['benchmark'])

        # Extract variance of benchmark
        benchmark_variance = cov_matrix[1, 1]

        if benchmark_variance == 0 or pd.isna(benchmark_variance):
            return None

        # Beta = Cov(Rp, Rb) / Var(Rb)
        beta = cov_matrix[0, 1] / benchmark_variance

        return round(beta, 2)

    @staticmethod
    def alpha(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        risk_free_rate: float = 0.02,
        trading_days: int = 252
    ) -> float:
        """
        Calculate Jensen's Alpha.

        Alpha measures excess return not explained by beta.
        Positive alpha = outperformance after adjusting for risk.

        Formula: Alpha = Rp - [Rf + Beta * (Rb - Rf)]

        Args:
            portfolio_returns: Series of daily portfolio return percentages
            benchmark_returns: Series of daily benchmark return percentages
            risk_free_rate: Annual risk-free rate (default 2%)
            trading_days: Trading days per year (default 252)

        Returns:
            Annualized alpha as percentage
        """
        if portfolio_returns.empty or benchmark_returns.empty:
            return 0.0

        # Align series
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns
        }).dropna()

        if len(aligned) < 10:
            return None

        # Calculate annualized returns
        portfolio_annual = PerformanceMetrics.annualized_return(aligned['portfolio'], trading_days)
        benchmark_annual = PerformanceMetrics.annualized_return(aligned['benchmark'], trading_days)

        # Calculate beta
        port_beta = PerformanceMetrics.beta(aligned['portfolio'], aligned['benchmark'])
        if port_beta is None:
            return None

        # Calculate alpha
        # Alpha = Rp - [Rf + Beta * (Rb - Rf)]
        alpha = portfolio_annual - (risk_free_rate * 100 + port_beta * (benchmark_annual - risk_free_rate * 100))

        return round(alpha, 2)

    @staticmethod
    def excess_return(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        trading_days: int = 252
    ) -> float:
        """
        Calculate excess return over benchmark.

        Args:
            portfolio_returns: Series of daily portfolio return percentages
            benchmark_returns: Series of daily benchmark return percentages
            trading_days: Trading days per year (default 252)

        Returns:
            Annualized excess return as percentage
        """
        if portfolio_returns.empty or benchmark_returns.empty:
            return 0.0

        # Align series
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns
        }).dropna()

        if len(aligned) < 2:
            return 0.0

        # Calculate annualized returns
        portfolio_annual = PerformanceMetrics.annualized_return(aligned['portfolio'], trading_days)
        benchmark_annual = PerformanceMetrics.annualized_return(aligned['benchmark'], trading_days)

        excess = portfolio_annual - benchmark_annual

        return round(excess, 2)

    @staticmethod
    def _position_weights_from_snapshot(snapshot: Any) -> Dict[str, float]:
        """Convert a portfolio snapshot into ticker weights over total portfolio value."""
        total_value = float(getattr(snapshot, 'total_value', 0.0) or 0.0)
        if total_value <= 0:
            return {}

        positions = getattr(snapshot, 'positions', {}) or {}
        weights: Dict[str, float] = {}
        for ticker, position in positions.items():
            value = float((position or {}).get('value', 0.0) or 0.0)
            if value <= 0:
                continue
            weights[str(ticker)] = value / total_value
        return weights

    @staticmethod
    def turnover_stats(tracker, trading_days: int = 252) -> Dict[str, float]:
        """Calculate turnover from executed trades, not passive weight drift."""
        snapshots = list(getattr(tracker, 'snapshots', []) or [])
        trades = list(getattr(tracker, 'trades', []) or [])
        if not snapshots or not trades:
            return {
                'avg_turnover_ratio': 0.0,
                'peak_turnover_ratio': 0.0,
                'annualized_turnover_ratio': 0.0,
                'total_turnover_ratio': 0.0,
            }

        snapshot_df = pd.DataFrame([
            {
                'date': pd.to_datetime(getattr(snapshot, 'date', None), errors='coerce'),
                'total_value': float(getattr(snapshot, 'total_value', 0.0) or 0.0),
            }
            for snapshot in snapshots
        ]).dropna(subset=['date']).sort_values('date').reset_index(drop=True)
        if snapshot_df.empty:
            return {
                'avg_turnover_ratio': 0.0,
                'peak_turnover_ratio': 0.0,
                'annualized_turnover_ratio': 0.0,
                'total_turnover_ratio': 0.0,
            }

        trade_df = pd.DataFrame([
            {
                'date': pd.to_datetime(getattr(trade, 'date', None), errors='coerce'),
                'value': float(getattr(trade, 'value', 0.0) or 0.0),
            }
            for trade in trades
        ]).dropna(subset=['date'])
        if trade_df.empty:
            return {
                'avg_turnover_ratio': 0.0,
                'peak_turnover_ratio': 0.0,
                'annualized_turnover_ratio': 0.0,
                'total_turnover_ratio': 0.0,
            }

        traded_value_by_date = trade_df.groupby('date', as_index=True)['value'].sum()
        turnover_series: List[float] = []
        first_snapshot_date = snapshot_df.iloc[0]['date']
        first_denominator = float(getattr(tracker, 'initial_cash', 0.0) or 0.0)
        first_traded_value = float(traded_value_by_date.get(first_snapshot_date, 0.0) or 0.0)
        if first_denominator > 0:
            turnover_series.append(first_traded_value / (2.0 * first_denominator))

        for idx in range(1, len(snapshot_df)):
            snapshot_date = snapshot_df.iloc[idx]['date']
            previous_total_value = float(snapshot_df.iloc[idx - 1]['total_value'] or 0.0)
            if previous_total_value <= 0:
                turnover_series.append(0.0)
                continue
            traded_value = float(traded_value_by_date.get(snapshot_date, 0.0) or 0.0)
            one_way_turnover = traded_value / (2.0 * previous_total_value)
            turnover_series.append(float(one_way_turnover))

        if not turnover_series:
            return {
                'avg_turnover_ratio': 0.0,
                'peak_turnover_ratio': 0.0,
                'annualized_turnover_ratio': 0.0,
                'total_turnover_ratio': 0.0,
            }

        avg_turnover = sum(turnover_series) / len(turnover_series)
        peak_turnover = max(turnover_series)
        total_turnover = sum(turnover_series)

        return {
            'avg_turnover_ratio': round(avg_turnover, 4),
            'peak_turnover_ratio': round(peak_turnover, 4),
            'annualized_turnover_ratio': round(avg_turnover * trading_days, 4),
            'total_turnover_ratio': round(total_turnover, 4),
        }

    @staticmethod
    def break_even_transaction_cost(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        total_turnover_ratio: float,
    ) -> float:
        """Estimate non-negative one-way transaction cost needed to erase benchmark outperformance."""
        aligned = pd.DataFrame({
            'portfolio': portfolio_returns,
            'benchmark': benchmark_returns,
        }).dropna()
        if aligned.empty or total_turnover_ratio <= 0:
            return 0.0

        portfolio_total_return = (1 + aligned['portfolio'] / 100.0).prod() - 1
        benchmark_total_return = (1 + aligned['benchmark'] / 100.0).prod() - 1
        excess_total_return = max(float(portfolio_total_return - benchmark_total_return), 0.0)
        if excess_total_return <= 0:
            return 0.0

        traded_notional_ratio = 2.0 * float(total_turnover_ratio)
        if traded_notional_ratio <= 0:
            return 0.0
        return round(excess_total_return / traded_notional_ratio, 6)

    @staticmethod
    def calculate_smart_beta_metrics(
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        risk_free_rate: float = 0.02,
        trading_days: int = 252
    ) -> Dict[str, float]:
        """
        Calculate all Smart Beta specific metrics.

        Args:
            portfolio_returns: Series of daily portfolio return percentages
            benchmark_returns: Series of daily benchmark return percentages
            risk_free_rate: Annual risk-free rate (default 2%)
            trading_days: Trading days per year (default 252)

        Returns:
            Dict with Smart Beta metrics
        """
        return {
            "tracking_error": PerformanceMetrics.tracking_error(
                portfolio_returns, benchmark_returns, trading_days
            ),
            "information_ratio": PerformanceMetrics.information_ratio(
                portfolio_returns, benchmark_returns, trading_days
            ),
            "beta": PerformanceMetrics.beta(portfolio_returns, benchmark_returns),
            "alpha": PerformanceMetrics.alpha(
                portfolio_returns, benchmark_returns, risk_free_rate, trading_days
            ),
            "excess_return": PerformanceMetrics.excess_return(
                portfolio_returns, benchmark_returns, trading_days
            ),
        }
