"""
Technical Indicators Library

A collection of technical analysis indicator functions for financial data analysis.
All functions use pandas/numpy vectorized operations for efficiency.
"""

import math
from typing import Tuple, List, Optional
import pandas as pd
import numpy as np


def calculate_ema(prices: pd.Series, window: int) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).

    EMA gives more weight to recent prices, making it more responsive
    to new information compared to Simple Moving Average.

    Args:
        prices: Series of prices (typically closing prices)
        window: Number of periods for EMA calculation

    Returns:
        Series containing EMA values

    Example:
        >>> prices = pd.Series([100, 101, 102, 101, 100])
        >>> ema = calculate_ema(prices, window=3)
    """
    return prices.ewm(span=window, adjust=False).mean()


def calculate_sma(prices: pd.Series, window: int) -> pd.Series:
    """
    Calculate Simple Moving Average (SMA).

    SMA is the unweighted mean of the previous n data points.

    Args:
        prices: Series of prices (typically closing prices)
        window: Number of periods for SMA calculation

    Returns:
        Series containing SMA values

    Example:
        >>> prices = pd.Series([100, 101, 102, 101, 100])
        >>> sma = calculate_sma(prices, window=3)
    """
    return prices.rolling(window=window).mean()


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).

    RSI is a momentum oscillator that measures the speed and magnitude
    of recent price changes to evaluate overbought or oversold conditions.

    RSI values:
        - > 70: Overbought condition (potential sell signal)
        - < 30: Oversold condition (potential buy signal)
        - 30-70: Neutral zone

    Args:
        prices: Series of prices (typically closing prices)
        period: Number of periods for RSI calculation (default: 14)

    Returns:
        Series containing RSI values (0-100)

    Example:
        >>> prices = pd.Series([100, 101, 102, 101, 100, 99, 100, 101, 102, 103,
        ...                     104, 103, 102, 101, 100])
        >>> rsi = calculate_rsi(prices, period=14)
    """
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_bollinger_bands(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.

    Bollinger Bands consist of:
        - Middle Band: Simple Moving Average
        - Upper Band: SMA + (Standard Deviation * num_std)
        - Lower Band: SMA - (Standard Deviation * num_std)

    Used for identifying overbought/oversold conditions and volatility.

    Args:
        prices: Series of prices (typically closing prices)
        window: Number of periods for moving average (default: 20)
        num_std: Number of standard deviations for bands (default: 2.0)

    Returns:
        Tuple of (upper_band, middle_band, lower_band)

    Example:
        >>> prices = pd.Series([100, 101, 102, 101, 100, 99, 100, 101, 102, 103,
        ...                     104, 105, 106, 105, 104, 103, 102, 101, 100, 99])
        >>> upper, middle, lower = calculate_bollinger_bands(prices)
    """
    sma = prices.rolling(window=window).mean()
    std_dev = prices.rolling(window=window).std()

    upper_band = sma + (std_dev * num_std)
    lower_band = sma - (std_dev * num_std)

    return upper_band, sma, lower_band


def calculate_z_score(prices: pd.Series, window: int) -> pd.Series:
    """
    Calculate Z-Score for mean reversion analysis.

    Z-Score measures how many standard deviations the current price
    is from the moving average. Used for identifying extreme price movements.

    Interpretation:
        - Z > 2: Price is significantly above average (potential sell)
        - Z < -2: Price is significantly below average (potential buy)
        - -2 <= Z <= 2: Price is within normal range

    Args:
        prices: Series of prices (typically closing prices)
        window: Number of periods for rolling calculation

    Returns:
        Series containing Z-Score values

    Example:
        >>> prices = pd.Series([100, 101, 102, 103, 104, 105, 104, 103, 102, 101])
        >>> z_score = calculate_z_score(prices, window=5)
    """
    ma = prices.rolling(window=window).mean()
    std = prices.rolling(window=window).std()
    z_score = (prices - ma) / std

    return z_score


def calculate_historical_volatility(
    prices: pd.Series,
    window: int = 21,
    annualize: bool = True
) -> pd.Series:
    """
    Calculate Historical Volatility.

    Historical volatility measures the dispersion of returns over a
    specified time period. It's useful for risk assessment and
    option pricing.

    Args:
        prices: Series of prices (typically closing prices)
        window: Number of periods for rolling calculation (default: 21)
        annualize: Whether to annualize the volatility (default: True)

    Returns:
        Series containing historical volatility values

    Note:
        Annualization uses 252 trading days by default.

    Example:
        >>> prices = pd.Series([100, 101, 102, 101, 100, 99, 100, 101, 102, 103])
        >>> vol = calculate_historical_volatility(prices, window=5)
    """
    returns = prices.pct_change()
    hist_vol = returns.rolling(window=window).std()

    if annualize:
        hist_vol = hist_vol * math.sqrt(252)

    return hist_vol


def _is_pivot_level(
    prices: pd.Series,
    idx: int,
    level_type: str,
    pivot_window: int = 5
) -> bool:
    """
    Check if the price point is a support or resistance level.

    A pivot level is identified when:
        - For support: price is lower than surrounding prices
        - For resistance: price is higher than surrounding prices

    Args:
        prices: Series of prices
        idx: Index of the price point to check
        level_type: 'support' or 'resistance'
        pivot_window: Number of periods on each side to compare

    Returns:
        True if the point is a pivot level, False otherwise
    """
    start_idx = max(0, idx - pivot_window)
    end_idx = min(len(prices), idx + pivot_window + 1)
    window_prices = prices.iloc[start_idx:end_idx]
    current_price = prices.iloc[idx]

    left_prices = window_prices.iloc[:pivot_window]
    right_prices = window_prices.iloc[pivot_window + 1:]

    if level_type == 'support':
        return (len(left_prices[left_prices > current_price]) >= 2 and
                len(right_prices[right_prices > current_price]) >= 2)
    elif level_type == 'resistance':
        return (len(left_prices[left_prices < current_price]) >= 2 and
                len(right_prices[right_prices < current_price]) >= 2)

    return False


def _find_pivot_levels(
    prices: pd.Series,
    pivot_window: int = 5,
    lookback_period: int = 20
) -> List[Tuple[int, float, str]]:
    """
    Find all pivot levels in the price series.

    Args:
        prices: Series of prices
        pivot_window: Number of periods on each side to identify pivot
        lookback_period: Number of periods to look back from current price

    Returns:
        List of tuples (index, price, level_type)
    """
    levels = []
    start_idx = lookback_period

    for i in range(start_idx, len(prices)):
        if _is_pivot_level(prices, i, 'support', pivot_window):
            levels.append((i, prices.iloc[i], 'support'))
        elif _is_pivot_level(prices, i, 'resistance', pivot_window):
            levels.append((i, prices.iloc[i], 'resistance'))

    return levels


def find_support_resistance_levels(
    prices: pd.Series,
    pivot_window: int = 5,
    lookback_period: int = 20
) -> Tuple[Optional[float], Optional[float]]:
    """
    Find the nearest support and resistance levels.

    Support and resistance levels are price points where a stock tends
    to stop and reverse. These are identified by finding pivot points
    in the price history.

    Args:
        prices: Series of prices (typically closing prices)
        pivot_window: Number of periods on each side to identify pivot (default: 5)
        lookback_period: Number of periods to analyze (default: 20)

    Returns:
        Tuple of (support_level, resistance_level)
        Returns (None, None) if no levels are found

    Example:
        >>> prices = pd.Series([100, 95, 100, 105, 100, 95, 100, 105, 110, 105,
        ...                     100, 95, 100, 105, 100, 95, 100, 105, 100, 95])
        >>> support, resistance = find_support_resistance_levels(prices)
    """
    levels = _find_pivot_levels(prices, pivot_window, lookback_period)
    current_price = prices.iloc[-1]

    support_levels = [price for _, price, level_type in levels
                      if level_type == 'support' and price < current_price]
    resistance_levels = [price for _, price, level_type in levels
                         if level_type == 'resistance' and price > current_price]

    support = max(support_levels) if support_levels else None
    resistance = min(resistance_levels) if resistance_levels else None

    return support, resistance


def calculate_price_position_in_bands(
    price: float,
    upper_band: float,
    lower_band: float
) -> float:
    """
    Calculate the normalized position of price within Bollinger Bands.

    Args:
        price: Current price
        upper_band: Upper Bollinger Band value
        lower_band: Lower Bollinger Band value

    Returns:
        Position value between 0 and 1:
            - 0: Price at lower band
            - 1: Price at upper band
            - 0.5: Price at middle band
    """
    if upper_band == lower_band:
        return 0.5
    return (price - lower_band) / (upper_band - lower_band)


def calculate_all_indicators(
    prices: pd.Series,
    ema_windows: List[int] = [8, 21, 55],
    rsi_period: int = 14,
    bollinger_window: int = 20,
    volatility_window: int = 21
) -> dict:
    """
    Calculate all technical indicators at once.

    Args:
        prices: Series of prices (typically closing prices)
        ema_windows: List of windows for EMA calculation
        rsi_period: Period for RSI calculation
        bollinger_window: Window for Bollinger Bands
        volatility_window: Window for historical volatility

    Returns:
        Dictionary containing all calculated indicators
    """
    result = {}

    # EMAs
    for window in ema_windows:
        result[f'ema_{window}'] = calculate_ema(prices, window)

    # RSI
    result['rsi'] = calculate_rsi(prices, rsi_period)

    # Bollinger Bands
    upper, middle, lower = calculate_bollinger_bands(prices, bollinger_window)
    result['bb_upper'] = upper
    result['bb_middle'] = middle
    result['bb_lower'] = lower

    # Z-Score
    result['z_score'] = calculate_z_score(prices, bollinger_window)

    # Historical Volatility
    result['volatility'] = calculate_historical_volatility(prices, volatility_window)

    # Support/Resistance
    support, resistance = find_support_resistance_levels(prices)
    result['support'] = support
    result['resistance'] = resistance

    return result
