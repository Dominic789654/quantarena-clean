"""
Smart Beta Portfolio Optimizer

Implements quadratic programming optimization for Smart Beta strategies:
- Minimize tracking error relative to benchmark
- Subject to: full investment, weight constraints, factor exposure, downside risk
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .factor_engine import FactorData
import numpy as np

try:
    from scipy.optimize import minimize
    from scipy.linalg import sqrtm  # noqa: F401 — availability probe
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy not available. Optimizer will not function.")


@dataclass
class OptimizationResult:
    """
    Result of portfolio optimization.

    Attributes:
        weights: Optimized portfolio weights (ticker -> weight)
        tracking_error: Expected tracking error
        expected_return: Expected portfolio return
        factor_exposures: Factor exposures of the portfolio
        success: Whether optimization succeeded
        message: Status message
        turnover: Required turnover from current portfolio
    """

    weights: Dict[str, float]
    tracking_error: float
    expected_return: Optional[float] = None
    factor_exposures: Optional[Dict[str, float]] = None
    success: bool = False
    message: str = ""
    turnover: float = 0.0
    benchmark_vector: Optional[Dict[str, float]] = None
    covariance_matrix: Optional[List[List[float]]] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "weights": self.weights,
            "tracking_error": self.tracking_error,
            "expected_return": self.expected_return,
            "factor_exposures": self.factor_exposures,
            "success": self.success,
            "message": self.message,
            "turnover": self.turnover,
            "benchmark_vector": self.benchmark_vector,
            "covariance_matrix": self.covariance_matrix,
        }


class SmartBetaOptimizer:
    """
    Quadratic programming optimizer for Smart Beta portfolios.

    Objective: Minimize tracking error
        min (w - w_b)^T Σ (w - w_b)

    Subject to:
        - sum(w) = 1  (full investment)
        - w_i >= 0  (no short selling)
        - w_i <= w_max  (single stock weight limit)
        - |w_i - w_b,i| <= delta  (deviation from benchmark)
        - Σ w_i * factor_i <= target  (factor exposure constraint)
        - Σ w_i * β⁻_i <= β⁻_benchmark - γ  (downside risk constraint)
    """

    def __init__(self, config=None):
        """
        Initialize optimizer.

        Args:
            config: SmartBetaConfig instance (optional)
        """
        from .config import get_smart_beta_config
        self.config = config or get_smart_beta_config()

        if not SCIPY_AVAILABLE:
            raise ImportError("scipy is required for SmartBetaOptimizer")

    def optimize(
        self,
        tickers: List[str],
        benchmark_weights: Dict[str, float],
        factor_data: Dict[str, "FactorData"],
        returns_covariance: Optional[np.ndarray] = None,
        current_weights: Optional[Dict[str, float]] = None,
        factor_targets: Optional[Dict[str, float]] = None,
        excluded_tickers: Optional[List[str]] = None,
    ) -> OptimizationResult:
        """
        Optimize portfolio weights.

        Args:
            tickers: List of ticker symbols
            benchmark_weights: Benchmark index weights (ticker -> weight)
            factor_data: Factor data for each ticker
            returns_covariance: Covariance matrix of returns (optional, will estimate if not provided)
            current_weights: Current portfolio weights (for turnover constraint)
            factor_targets: Target factor exposures (optional)

        Returns:
            OptimizationResult with optimized weights
        """
        n = len(tickers)

        if n == 0:
            return OptimizationResult(
                weights={},
                tracking_error=0,
                success=False,
                message="No tickers provided"
            )

        excluded_set = set(excluded_tickers or [])

        # Build benchmark weight vector against the full benchmark universe.
        w_b = np.array([benchmark_weights.get(t, 0) for t in tickers], dtype=float)

        def benchmark_fallback_weights() -> Dict[str, float]:
            fallback = {
                t: (0.0 if t in excluded_set else float(w_b[i]))
                for i, t in enumerate(tickers)
            }
            total = sum(fallback.values())
            if total > 0:
                fallback = {ticker: weight / total for ticker, weight in fallback.items()}
            return fallback

        # Build covariance matrix if not provided
        if returns_covariance is None:
            # Use diagonal approximation based on factor volatilities
            returns_covariance = self._estimate_covariance_from_factors(
                tickers, factor_data
            )

        # Get current weights
        if current_weights is None:
            current_weights = {t: w_b[i] for i, t in enumerate(tickers)}

        w_current = np.array([current_weights.get(t, 0) for t in tickers])

        # Define objective function (tracking error squared)
        def objective(w):
            diff = w - w_b
            return diff @ returns_covariance @ diff

        # Define gradient of objective
        def gradient(w):
            diff = w - w_b
            return 2 * returns_covariance @ diff

        # Constraints
        constraints = []

        # Full investment constraint: sum(w) = 1
        constraints.append({
            "type": "eq",
            "fun": lambda w: np.sum(w) - 1.0,
            "jac": lambda w: np.ones(n)
        })

        # Hard tracking-error ceiling using annualized TE semantics to match
        # config/documentation (e.g. 0.03 = 3% annualized tracking error).
        annualization = float(self.config.market_days_per_year)
        te_limit_sq = float(self.config.tracking_error_limit) ** 2
        constraints.append({
            "type": "ineq",
            "fun": lambda w, limit=te_limit_sq, ann=annualization: limit - (objective(w) * ann),
            "jac": lambda w, ann=annualization: -(gradient(w) * ann),
        })

        # Downside beta constraint (if enabled)
        if self.config.require_downside_protection:
            downside_betas = []
            for t in tickers:
                fd = factor_data.get(t)
                if fd and fd.downside_beta is not None:
                    downside_betas.append(fd.downside_beta)
                else:
                    downside_betas.append(1.0)  # Default beta

            downside_betas = np.array(downside_betas)

            # Calculate benchmark downside beta
            benchmark_downside_beta = w_b @ downside_betas
            target_downside_beta = benchmark_downside_beta - self.config.downside_beta_gamma

            constraints.append({
                "type": "ineq",
                "fun": lambda w, db=downside_betas, tdb=target_downside_beta: tdb - w @ db,
                "jac": lambda w, db=downside_betas: -db
            })

        # Bounds for each weight
        # Ensure upper bound is at least as large as benchmark weight to allow feasibility
        min_upper = max(1.0 / n, self.config.max_stock_weight)  # At least equal weight
        bounds = []
        for i, ticker in enumerate(tickers):
            if ticker in excluded_set:
                bounds.append((0.0, 0.0))
                continue

            # w_i >= 0 (no short selling)
            # w_i <= max_stock_weight (but at least allow equal weight)
            # Allow 2% deviation from benchmark
            lower = 0.0
            upper = max(min_upper, w_b[i] + 0.02)  # Ensure feasibility
            bounds.append((lower, upper))

        # Initial guess: start with benchmark weights
        w0 = w_b.copy()

        # Optimize
        try:
            # First try SLSQP
            result = minimize(
                objective,
                w0,
                method="SLSQP",
                jac=gradient,
                bounds=bounds,
                constraints=constraints,
                options={
                    "maxiter": 1000,
                    "ftol": 1e-8,
                    "disp": False
                }
            )

            # Only short-circuit obviously unrecoverable SLSQP failures. For
            # generic numerical/convergence misses, still give trust-constr a
            # bounded chance to rescue the solve.
            should_try_trust_constr = False
            if not result.success:
                failure_message = str(getattr(result, "message", "")).lower()
                should_try_trust_constr = "fixed by bounds" not in failure_message

            # If SLSQP fails, try trust-constr (more robust)
            if should_try_trust_constr:
                result_tc = minimize(
                    objective,
                    w0,
                    method="trust-constr",
                    jac=gradient,
                    bounds=bounds,
                    constraints=constraints,
                    options={
                        "maxiter": 300,
                        "gtol": 1e-8,
                        "verbose": 0
                    }
                )
                if result_tc.success:
                    result = result_tc

            if result.success:
                # Extract optimized weights
                w_opt = result.x

                # Clean up very small weights
                w_opt[w_opt < self.config.min_weight] = 0
                weight_sum = w_opt.sum()
                if weight_sum <= 0:
                    return OptimizationResult(
                        weights=benchmark_fallback_weights(),
                        tracking_error=0,
                        success=False,
                        message="Optimization produced no investable weights after min_weight pruning",
                    )
                w_opt = w_opt / weight_sum  # Re-normalize

                # Create weight dictionary
                weights = {t: float(w_opt[i]) for i, t in enumerate(tickers)}

                # Recompute annualized tracking error from the shipped portfolio,
                # not the pre-pruning optimizer objective.
                diff = w_opt - w_b
                tracking_error = float(np.sqrt((diff @ returns_covariance @ diff) * self.config.market_days_per_year))
                if tracking_error > self.config.tracking_error_limit + 1e-12:
                    return OptimizationResult(
                        weights=benchmark_fallback_weights(),
                        tracking_error=0,
                        success=False,
                        message="Optimization exceeded tracking_error_limit after min_weight pruning",
                    )

                # Calculate turnover
                turnover = float(np.sum(np.abs(w_opt - w_current)) / 2)

                # Calculate factor exposures
                factor_exposures = self._calculate_factor_exposures(
                    tickers, w_opt, factor_data
                )

                return OptimizationResult(
                    weights=weights,
                    tracking_error=tracking_error,
                    factor_exposures=factor_exposures,
                    success=True,
                    message="Optimization successful",
                    turnover=turnover,
                    benchmark_vector={t: float(w_b[i]) for i, t in enumerate(tickers)},
                    covariance_matrix=returns_covariance.tolist(),
                )
            else:
                # Optimization failed, return benchmark weights
                return OptimizationResult(
                    weights=benchmark_fallback_weights(),
                    tracking_error=0,
                    success=False,
                    message=f"Optimization failed: {result.message}"
                )

        except Exception as e:
            # Fallback to benchmark weights
            return OptimizationResult(
                weights=benchmark_fallback_weights(),
                tracking_error=0,
                success=False,
                message=f"Optimization error: {str(e)}"
            )

    def _estimate_covariance_from_factors(
        self,
        tickers: List[str],
        factor_data: Dict[str, "FactorData"]
    ) -> np.ndarray:
        """
        Estimate covariance matrix from factor data.

        Uses a diagonal approximation based on factor volatilities.
        In production, this should be replaced with actual return covariance.

        Args:
            tickers: List of tickers
            factor_data: Factor data for each ticker

        Returns:
            Covariance matrix (n x n)
        """
        n = len(tickers)

        # Estimate individual volatilities from IVOL
        volatilities = []
        for t in tickers:
            fd = factor_data.get(t)
            if fd and fd.ivol is not None:
                vol = fd.ivol / np.sqrt(self.config.market_days_per_year)
            else:
                vol = 0.02  # Default daily volatility (2%)
            volatilities.append(vol)

        volatilities = np.array(volatilities)

        # Create diagonal covariance matrix with small regularization for numerical stability
        # In production, should use full covariance from historical returns
        reg = 1e-6  # Regularization for numerical stability
        cov = np.diag(volatilities ** 2 + reg)

        # Add some market correlation
        market_var = 0.0004  # ~2% daily market vol
        market_beta = 1.0  # Assume beta = 1 for simplicity

        # Adjust for market correlation: σ_ij = β_i * β_j * σ_m² + σ_idio,i * σ_idio,j * corr
        for i in range(n):
            for j in range(n):
                if i != j:
                    # Assume 0.3 idiosyncratic correlation
                    cov[i, j] = market_beta ** 2 * market_var + 0.3 * volatilities[i] * volatilities[j]

        # Ensure covariance matrix is positive semi-definite
        # Add small diagonal if needed
        min_eigenvalue = np.min(np.linalg.eigvalsh(cov))
        if min_eigenvalue < 0:
            cov += np.eye(n) * (-min_eigenvalue + 1e-6)

        return cov

    def _calculate_factor_exposures(
        self,
        tickers: List[str],
        weights: np.ndarray,
        factor_data: Dict[str, "FactorData"]
    ) -> Dict[str, float]:
        """
        Calculate portfolio factor exposures.

        Args:
            tickers: List of tickers
            weights: Portfolio weights
            factor_data: Factor data for each ticker

        Returns:
            Dictionary of factor exposures
        """
        exposures = {}

        for factor_name in ["dimson_beta", "downside_beta", "ivol", "amihud"]:
            exposure = 0
            weight_sum = 0

            for i, t in enumerate(tickers):
                fd = factor_data.get(t)
                if fd:
                    factor_value = getattr(fd, factor_name, None)
                    if factor_value is not None:
                        exposure += weights[i] * factor_value
                        weight_sum += weights[i]

            if weight_sum > 0:
                exposures[factor_name] = exposure

        return exposures

    CASH_BUCKET = "__cash__"

    def apply_turnover_constraint(
        self,
        target_weights: Dict[str, float],
        current_weights: Dict[str, float],
        turnover_limit: float
    ) -> Dict[str, float]:
        """
        Apply turnover constraint by limiting changes from current portfolio.

        Args:
            target_weights: Target optimized weights
            current_weights: Current portfolio weights
            turnover_limit: Maximum allowed turnover

        Returns:
            Adjusted weights that satisfy turnover constraint
        """
        # Model idle cash as an explicit weight bucket so turnover limits also
        # constrain transitions between invested assets and cash.
        current_with_cash = dict(current_weights)
        target_with_cash = dict(target_weights)
        current_with_cash[self.CASH_BUCKET] = max(0.0, 1.0 - sum(current_weights.values()))
        target_with_cash[self.CASH_BUCKET] = max(0.0, 1.0 - sum(target_weights.values()))

        all_tickers = set(target_with_cash.keys()) | set(current_with_cash.keys())

        # Calculate required turnover
        total_turnover = 0
        for t in all_tickers:
            total_turnover += abs(
                target_with_cash.get(t, 0) - current_with_cash.get(t, 0)
            )
        total_turnover /= 2

        if total_turnover <= turnover_limit:
            return target_weights

        # Scale down changes to meet turnover limit
        scale_factor = turnover_limit / total_turnover

        adjusted_weights = {}
        for t in all_tickers:
            current = current_with_cash.get(t, 0)
            target = target_with_cash.get(t, 0)
            adjusted = current + scale_factor * (target - current)
            if adjusted > 0:
                adjusted_weights[t] = adjusted

        # Linear interpolation between two 100% allocations should still sum to 1,
        # but re-normalize defensively across assets + cash before stripping cash.
        total = sum(adjusted_weights.values())
        if total > 0:
            adjusted_weights = {t: w / total for t, w in adjusted_weights.items()}

        adjusted_weights.pop(self.CASH_BUCKET, None)
        return adjusted_weights

    def negative_screening(
        self,
        tickers: List[str],
        factor_data: Dict[str, "FactorData"]
    ) -> List[str]:
        """
        Apply negative screening based on factor thresholds.

        Removes stocks with:
        - IVOL above threshold percentile
        - Amihud above threshold

        Args:
            tickers: List of tickers to screen
            factor_data: Factor data for each ticker

        Returns:
            List of tickers that pass screening
        """
        # Collect IVOL values
        ivol_values = []
        for t in tickers:
            fd = factor_data.get(t)
            if fd and fd.ivol is not None:
                ivol_values.append((t, fd.ivol))

        # Calculate IVOL threshold
        if ivol_values:
            ivol_threshold = np.percentile(
                [v for _, v in ivol_values],
                self.config.ivol_percentile * 100
            )
        else:
            ivol_threshold = float("inf")

        # Screen tickers
        passed_tickers = []
        for t in tickers:
            fd = factor_data.get(t)
            if not fd or not fd.is_valid:
                continue

            # Check IVOL
            if fd.ivol is not None and fd.ivol > ivol_threshold:
                continue

            # Check Amihud
            if fd.amihud is not None and fd.amihud > self.config.amihud_threshold:
                continue

            passed_tickers.append(t)

        return passed_tickers
