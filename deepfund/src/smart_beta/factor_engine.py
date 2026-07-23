"""
Factor Calculation Engine for Smart Beta

Implements factor calculations for index enhancement strategies:
1. Dimson Beta - Corrects for non-synchronous trading
2. Downside Beta (β⁻) - Calculated using only down days
3. Idiosyncratic Volatility (IVOL) - Fama-French three-factor residual volatility
4. Amihud Illiquidity - Price impact per unit trading volume
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from datetime import datetime
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)


@dataclass
class FactorData:
    """
    Container for calculated factor values.

    Attributes:
        ticker: Stock ticker symbol
        trade_date: Date of calculation
        dimson_beta: Dimson-adjusted beta (corrects non-synchronous trading)
        downside_beta: Downside beta (β⁻, calculated on down days only)
        ivol: Idiosyncratic volatility (residual volatility from 3-factor model)
        amihud: Amihud illiquidity measure (price impact per unit volume)
        factor_score: Composite factor score (weighted average of normalized factors)
        is_valid: Whether factor calculation succeeded
    """

    ticker: str
    trade_date: datetime
    dimson_beta: Optional[float] = None
    downside_beta: Optional[float] = None
    ivol: Optional[float] = None
    amihud: Optional[float] = None
    factor_score: Optional[float] = None
    is_valid: bool = False

    def __str__(self) -> str:
        """String representation of factor data."""
        return (f"FactorData({self.ticker}, {self.trade_date.strftime('%Y-%m-%d')}, "
                f"score={self.factor_score:.4f}, valid={self.is_valid})")

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date.strftime("%Y-%m-%d"),
            "dimson_beta": self.dimson_beta,
            "downside_beta": self.downside_beta,
            "ivol": self.ivol,
            "amihud": self.amihud,
            "factor_score": self.factor_score,
            "is_valid": self.is_valid,
        }


class FactorEngine:
    """
    Engine for calculating Smart Beta factors.

    Methods:
        calculate_dimson_beta: Calculate Dimson-adjusted beta
        calculate_downside_beta: Calculate downside beta (β⁻)
        calculate_ivol: Calculate idiosyncratic volatility (Fama-French 3-factor)
        calculate_amihud: Calculate Amihud illiquidity measure
        calculate_all_factors: Calculate all factors for a ticker
        batch_calculate_factors: Calculate factors for multiple tickers
    """

    def __init__(self, config=None):
        """
        Initialize factor engine.

        Args:
            config: SmartBetaConfig instance (optional)
        """
        from .config import get_smart_beta_config
        self.config = config or get_smart_beta_config()

    def calculate_dimson_beta(
        self,
        stock_returns: pd.Series,
        market_returns: pd.Series,
        num_lags: int = 1,
        num_leads: int = 1
    ) -> float:
        """
        Calculate Dimson Beta (corrects for non-synchronous trading).

        The Dimson Beta corrects for bias when stock and market prices are
        not synchronized (e.g., illiquid stocks). It includes leads and lags
        of market returns in the regression.

        Formula: β_dimson = Σ(β_i) where i = [-lags, ..., 0, ..., +leads]

        Args:
            stock_returns: Series of stock returns
            market_returns: Series of market returns
            num_lags: Number of lagged market returns to include
            num_leads: Number of leading market returns to include

        Returns:
            Dimson-adjusted beta coefficient
        """
        if len(stock_returns) < max(num_lags, num_leads) + 10:
            return None

        try:
            # Create DataFrame with aligned returns
            df = pd.DataFrame({
                "stock": stock_returns,
                "market": market_returns
            }).dropna()

            if len(df) < 30:
                return None

            # Add lagged and leading market returns
            for lag in range(1, num_lags + 1):
                df[f"market_lag_{lag}"] = df["market"].shift(lag)

            for lead in range(1, num_leads + 1):
                df[f"market_lead_{lead}"] = df["market"].shift(-lead)

            # Drop rows with NaN from leads/lags
            df = df.dropna()

            if len(df) < 20:
                return None

            # Prepare regression matrix
            X_columns = ["market"] + \
                [f"market_lag_{i}" for i in range(1, num_lags + 1)] + \
                [f"market_lead_{i}" for i in range(1, num_leads + 1)]

            X = df[X_columns].values
            y = df["stock"].values

            # Simple OLS regression
            beta_coeffs = np.linalg.lstsq(
                np.c_[X, np.ones(len(X))],  # Add intercept
                y,
                rcond=None
            )[0][:-1]  # Exclude intercept

            # Sum coefficients for Dimson Beta
            dimson_beta = np.sum(beta_coeffs)

            return float(dimson_beta)

        except (ValueError, np.linalg.LinAlgError) as e:
            print(f"Error calculating Dimson Beta: {e}")
            return None

    def calculate_downside_beta(
        self,
        stock_returns: pd.Series,
        market_returns: pd.Series,
        threshold: float = 0.0
    ) -> float:
        """
        Calculate Downside Beta (β⁻) using only market down days.

        Downside Beta measures a stock's sensitivity to market declines.
        It's calculated using only days when market returns are below a threshold.

        Formula: β⁻ = Cov(R_stock, R_market | R_market < threshold) / Var(R_market | R_market < threshold)

        Args:
            stock_returns: Series of stock returns
            market_returns: Series of market returns
            threshold: Market return threshold for down days (default: 0)

        Returns:
            Downside beta coefficient
        """
        # Align returns
        aligned_data = pd.DataFrame({
            "stock": stock_returns,
            "market": market_returns
        }).dropna()

        if len(aligned_data) < 20:
            return None

        # Select down days (market returns below threshold)
        down_days = aligned_data[aligned_data["market"] < threshold]

        if len(down_days) < 10:
            # Not enough down days, return standard beta on all days
            down_days = aligned_data

        try:
            # Calculate covariance and variance
            cov_matrix = np.cov(down_days["stock"], down_days["market"])
            market_variance = cov_matrix[1, 1]

            if market_variance < 1e-10:
                return 1.0  # Default if no variance

            downside_beta = cov_matrix[0, 1] / market_variance
            return float(downside_beta)

        except Exception as e:
            print(f"Error calculating Downside Beta: {e}")
            return None

    def calculate_ivol(
        self,
        stock_returns: pd.Series,
        market_returns: pd.Series,
        size_factor: Optional[pd.Series] = None,
        value_factor: Optional[pd.Series] = None
    ) -> float:
        """
        Calculate Idiosyncratic Volatility (IVOL).

        IVOL is the residual volatility from a Fama-French 3-factor model:
            R_stock = α + β1*R_market + β2*SMB + β3*HML + ε

        If size and value factors are not provided, uses CAPM (market factor only).

        Args:
            stock_returns: Series of stock returns
            market_returns: Series of market returns
            size_factor: Series of SMB (Small Minus Big) returns (optional)
            value_factor: Series of HML (High Minus Low) returns (optional)

        Returns:
            Annualized idiosyncratic volatility (standard deviation of residuals)
        """
        # Align all series
        data_dict = {"stock": stock_returns, "market": market_returns}

        if size_factor is not None:
            data_dict["size"] = size_factor
        if value_factor is not None:
            data_dict["value"] = value_factor

        df = pd.DataFrame(data_dict).dropna()

        if len(df) < 30:
            return None

        try:
            # Prepare regression
            y = df["stock"].values
            X_columns = ["market"]

            if "size" in df.columns:
                X_columns.append("size")
            if "value" in df.columns:
                X_columns.append("value")

            X = df[X_columns].values

            # Add intercept
            X_with_intercept = np.c_[X, np.ones(len(X))]

            # OLS regression
            coefficients = np.linalg.lstsq(X_with_intercept, y, rcond=None)[0]

            # Calculate residuals
            y_pred = X_with_intercept @ coefficients
            residuals = y - y_pred

            # Calculate residual volatility and annualize
            residual_std = np.std(residuals)
            ivol_annualized = residual_std * np.sqrt(self.config.market_days_per_year)

            return float(ivol_annualized)

        except Exception as e:
            print(f"Error calculating IVOL: {e}")
            return None

    def calculate_amihud(
        self,
        returns: pd.Series,
        volume: pd.Series,
        dollar_volume: Optional[pd.Series] = None
    ) -> float:
        """
        Calculate Amihud Illiquidity measure.

        The Amihud ratio measures price impact per unit of trading volume.
        Higher values indicate lower liquidity.

        Formula: Amihud = average(|Return_t| / DollarVolume_t)

        Args:
            returns: Series of daily returns
            volume: Series of trading volume (shares)
            dollar_volume: Series of dollar trading volume (optional).
                          If not provided, calculated as Volume * Price.

        Returns:
            Amihud illiquidity ratio (average daily value)
        """
        # Align data
        aligned_data = pd.DataFrame({
            "return": returns.abs(),  # Absolute returns
            "volume": volume
        }).dropna()

        if len(aligned_data) < 20:
            return None

        # Calculate or use dollar volume
        if dollar_volume is not None:
            aligned_data["dollar_volume"] = dollar_volume
        else:
            # Estimate price from returns (approximate)
            # This is a simplification - in practice need actual price data
            aligned_data["dollar_volume"] = aligned_data["volume"] * 100  # Placeholder

        # Filter out zero or negative dollar volume
        valid_data = aligned_data[aligned_data["dollar_volume"] > 0]

        if len(valid_data) < 10:
            return None

        try:
            # Calculate daily Amihud ratio
            amihud_daily = valid_data["return"] / valid_data["dollar_volume"]

            # Average over the period
            amihud_avg = amihud_daily.mean()

            # Handle extreme values
            if amihud_avg > 1.0:  # Unrealistically high
                return 1.0

            return float(amihud_avg)

        except Exception as e:
            print(f"Error calculating Amihud ratio: {e}")
            return None

    def calculate_factor_score(
        self,
        factor_values: Dict[str, float],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Calculate composite factor score from normalized factor values.

        Args:
            factor_values: Dictionary of factor values
            weights: Dictionary of factor weights (optional)

        Returns:
            Composite factor score (weighted average)
        """
        if weights is None:
            weights = self.config.factor_weights

        # Filter out None values
        valid_factors = {k: v for k, v in factor_values.items() if v is not None}
        if not valid_factors:
            return None

        # Normalize factor values (lower is better for IVOL and Amihud)
        normalized_values = {}

        for factor_name, value in valid_factors.items():
            # For IVOL and Amihud, invert so higher score = better
            if factor_name in ["ivol", "amihud"]:
                # Simple inversion: 1 / (1 + value)
                normalized = 1.0 / (1.0 + abs(value))
            else:
                # For beta factors, use absolute value (closer to 1 is better)
                normalized = 1.0 / (1.0 + abs(value - 1.0))

            normalized_values[factor_name] = normalized

        # Calculate weighted average
        total_weight = 0
        weighted_sum = 0

        for factor_name, normalized_value in normalized_values.items():
            weight = weights.get(factor_name, 0)
            weighted_sum += normalized_value * weight
            total_weight += weight

        if total_weight == 0:
            return None

        return weighted_sum / total_weight

    def calculate_all_factors(
        self,
        ticker: str,
        stock_data: pd.DataFrame,
        market_data: pd.DataFrame,
        trade_date: datetime
    ) -> FactorData:
        """
        Calculate all factors for a single ticker.

        Args:
            ticker: Stock ticker symbol
            stock_data: DataFrame with stock OHLCV data (must include 'close', 'volume')
            market_data: DataFrame with market index data (must include 'close')
            trade_date: Date for factor calculation

        Returns:
            FactorData object with calculated factors
        """
        try:
            # Ensure we have enough data
            min_days = min(60, self.config.lookback_days // 2)
            if len(stock_data) < min_days or len(market_data) < min_days:
                return FactorData(ticker, trade_date, is_valid=False)

            # Calculate returns
            stock_returns = stock_data["close"].pct_change().dropna()
            market_returns = market_data["close"].pct_change().dropna()

            # Align dates
            common_dates = stock_returns.index.intersection(market_returns.index)
            if len(common_dates) < min_days:
                return FactorData(ticker, trade_date, is_valid=False)

            stock_returns_aligned = stock_returns.loc[common_dates]
            market_returns_aligned = market_returns.loc[common_dates]

            # Calculate factors
            dimson_beta = self.calculate_dimson_beta(
                stock_returns_aligned, market_returns_aligned
            )

            downside_beta = self.calculate_downside_beta(
                stock_returns_aligned, market_returns_aligned
            )

            # For IVOL, use CAPM (market factor only) if size/value factors not available
            ivol = self.calculate_ivol(
                stock_returns_aligned, market_returns_aligned
            )

            # Calculate Amihud (requires volume data)
            if "volume" in stock_data.columns:
                # Calculate returns for Amihud (need aligned returns with volume)
                returns_for_amihud = stock_data["close"].pct_change()
                aligned_with_volume = pd.DataFrame({
                    "return": returns_for_amihud,
                    "volume": stock_data["volume"]
                }).dropna()

                # Align with market returns timeframe
                aligned_with_volume = aligned_with_volume.loc[
                    aligned_with_volume.index.intersection(common_dates)
                ]

                if len(aligned_with_volume) >= 10:
                    amihud = self.calculate_amihud(
                        aligned_with_volume["return"],
                        aligned_with_volume["volume"]
                    )
                else:
                    amihud = None
            else:
                amihud = None

            # Calculate composite factor score
            factor_values = {
                "dimson_beta": dimson_beta,
                "downside_beta": downside_beta,
                "ivol": ivol,
                "amihud": amihud,
            }

            factor_score = self.calculate_factor_score(factor_values)

            # Check if calculation is valid
            valid_factors = [v for v in factor_values.values() if v is not None]
            is_valid = len(valid_factors) >= 2 and factor_score is not None

            return FactorData(
                ticker=ticker,
                trade_date=trade_date,
                dimson_beta=dimson_beta,
                downside_beta=downside_beta,
                ivol=ivol,
                amihud=amihud,
                factor_score=factor_score,
                is_valid=is_valid
            )

        except Exception as e:
            print(f"Error calculating factors for {ticker}: {e}")
            return FactorData(ticker, trade_date, is_valid=False)

    def batch_calculate_factors(
        self,
        tickers: List[str],
        stock_data_dict: Dict[str, pd.DataFrame],
        market_data: pd.DataFrame,
        trade_date: datetime
    ) -> Dict[str, FactorData]:
        """
        Calculate factors for multiple tickers.

        Args:
            tickers: List of stock tickers
            stock_data_dict: Dictionary mapping ticker to stock OHLCV data
            market_data: DataFrame with market index data
            trade_date: Date for factor calculation

        Returns:
            Dictionary mapping ticker to FactorData
        """
        factors = {}
        for ticker in tickers:
            if ticker in stock_data_dict:
                stock_data = stock_data_dict[ticker]
                factor_data = self.calculate_all_factors(
                    ticker, stock_data, market_data, trade_date
                )
                factors[ticker] = factor_data
            else:
                factors[ticker] = FactorData(ticker, trade_date, is_valid=False)

        return factors
