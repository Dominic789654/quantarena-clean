"""
Technical Analyst - Refactored to use BaseAnalyst and technical_indicators utils.

Analyzes price trends, momentum, and market patterns.
"""

import math
from datetime import timedelta
from typing import Any, Dict
import pandas as pd
from graph.schema import FundState
from graph.constants import AgentKey, Signal
from llm.prompt import TECHNICAL_PROMPT
from apis.router import Router
from .base import BaseAnalyst
from util.technical_indicators import (
    calculate_ema,
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_z_score,
    find_support_resistance_levels,
    calculate_price_position_in_bands
)


class TechnicalAnalyst(BaseAnalyst):
    """
    Technical analysis specialist that excels at short to medium-term
    price movement predictions using trend, momentum, and pattern analysis.
    """

    def __init__(self):
        super().__init__(AgentKey.TECHNICAL, TECHNICAL_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Dict[str, Any]:
        """
        Fetch price data and calculate technical indicators.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            Dict with ticker, prices_df, and signal_results
        """
        ticker = state["ticker"]
        trading_date = state["trading_date"]
        market = state.get("market", "us")

        prices_df = self._load_backtest_prices(state)
        if prices_df is None:
            if market == "cn":
                prices_df = router.get_cn_stock_daily_candles_df(ticker=ticker, trading_date=trading_date)
            else:
                prices_df = router.get_us_stock_daily_candles_df(ticker=ticker, trading_date=trading_date)

        # Calculate all technical indicators using utility functions
        signal_results = {
            "trend": self._get_trend_signal(prices_df),
            "mean_reversion": self._get_mean_reversion_signal(prices_df),
            "rsi": self._get_rsi_signal(prices_df),
            "volatility": self._get_volatility_signal(prices_df),
            "volume": self._get_volume_analysis(prices_df),
            "price_levels": self._get_support_resistance(prices_df),
        }

        return {
            "ticker": ticker,
            "signal_results": signal_results
        }

    def _load_backtest_prices(self, state: FundState) -> pd.DataFrame | None:
        """Load historical prices from the backtest cache when available."""
        if not state.get("is_backtest"):
            return None

        db_path = str(state.get("db_path") or "").strip()
        if not db_path:
            return None

        from deepear.src.utils.database_manager import DatabaseManager

        trading_date = state["trading_date"]
        lookback_start = (trading_date - timedelta(days=400)).strftime("%Y-%m-%d")
        lookback_end = trading_date.strftime("%Y-%m-%d")

        db = DatabaseManager(db_path)
        try:
            cached = db.get_stock_prices(state["ticker"], lookback_start, lookback_end)
        finally:
            db.close()

        if cached.empty:
            return None

        prices_df = cached.copy()
        prices_df["Date"] = pd.to_datetime(prices_df["date"])
        prices_df.set_index("Date", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            prices_df[col] = pd.to_numeric(prices_df[col], errors="coerce")
        prices_df.sort_index(inplace=True)
        return prices_df[["open", "high", "low", "close", "volume"]]

    def build_prompt(self, data: Dict[str, Any]) -> str:
        """
        Build prompt from technical analysis results.

        Args:
            data: Dict with ticker and signal_results

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(
            ticker=data["ticker"],
            analysis=data["signal_results"]
        )

    def _get_trend_signal(self, prices_df: pd.DataFrame) -> Signal:
        """Advanced trend following strategy using multiple timeframes and indicators"""
        params = self.thresholds["trend"]

        # Calculate EMAs for multiple timeframes using utility function
        ema_short = calculate_ema(prices_df["close"], params["short"])
        ema_medium = calculate_ema(prices_df["close"], params["medium"])
        ema_long = calculate_ema(prices_df["close"], params["long"])

        # Determine trend direction and strength
        short_trend = ema_short > ema_medium
        medium_trend = ema_medium > ema_long

        if short_trend.iloc[-1] and medium_trend.iloc[-1]:
            return Signal.BULLISH
        elif not short_trend.iloc[-1] and not medium_trend.iloc[-1]:
            return Signal.BEARISH
        else:
            return Signal.NEUTRAL

    def _get_mean_reversion_signal(self, prices_df: pd.DataFrame) -> Signal:
        """Mean reversion strategy using statistical measures and Bollinger Bands"""
        params = self.thresholds["mean_reversion"]

        # Calculate Bollinger Bands using utility function
        bb_upper, _, bb_lower = calculate_bollinger_bands(
            prices_df["close"], window=params["bollinger_window"], num_std=2.0
        )

        # Calculate z-score using utility function
        z_score = calculate_z_score(prices_df["close"], window=params["rolling_window"])

        # Calculate normalized position within Bollinger Bands
        price_vs_bb = calculate_price_position_in_bands(
            prices_df["close"].iloc[-1],
            bb_upper.iloc[-1],
            bb_lower.iloc[-1]
        )

        # Use threshold values for signal conditions
        if z_score.iloc[-1] < params["z_score_extreme"] and price_vs_bb < params["bb_position_threshold"]:
            return Signal.BULLISH
        elif z_score.iloc[-1] > params["z_score_extreme"] and price_vs_bb > (1 - params["bb_position_threshold"]):
            return Signal.BEARISH
        else:
            return Signal.NEUTRAL

    def _get_rsi_signal(self, prices_df: pd.DataFrame) -> Signal:
        """RSI signal that indicate overbought/oversold conditions"""
        params = self.thresholds["rsi"]

        # Calculate RSI using utility function
        rsi = calculate_rsi(prices_df["close"], period=params["period"])

        if rsi.iloc[-1] > params["bearish"]:
            return Signal.BEARISH
        elif rsi.iloc[-1] < params["bullish"]:
            return Signal.BULLISH
        else:
            return Signal.NEUTRAL

    def _get_volatility_signal(self, prices_df: pd.DataFrame) -> Signal:
        """Volatility-based trading strategy"""
        params = self.thresholds["volatility"]

        # Calculate various volatility metrics
        returns = prices_df["close"].pct_change()

        # Historical volatility
        hist_vol = returns.rolling(21).std() * math.sqrt(252)

        # Volatility regime detection
        vol_ma = hist_vol.rolling(63).mean()
        vol_regime = hist_vol / vol_ma

        # Volatility mean reversion
        vol_z_score = (hist_vol - vol_ma) / hist_vol.rolling(63).std()

        # Generate signal based on volatility regime
        current_vol_regime = vol_regime.iloc[-1]
        vol_z = vol_z_score.iloc[-1]

        if current_vol_regime < params["bullish"] and vol_z < -1:
            return Signal.BULLISH
        elif current_vol_regime > params["bearish"] and vol_z > 1:
            return Signal.BEARISH
        else:
            return Signal.NEUTRAL

    def _get_volume_analysis(self, prices_df: pd.DataFrame) -> str:
        """Analyze volume characteristics"""
        params = self.thresholds["volume"]
        volume = prices_df['volume']
        price = prices_df['close']

        # Calculate volume moving average
        vol_ma = volume.rolling(window=params["trend"]).mean()

        # Calculate price-volume relationship
        price_volume_corr = price.rolling(window=params["correlation"]).corr(volume)

        # Calculate volume trend
        vol_trend = (volume > vol_ma.shift(1)).astype(int)

        result = f"- Volume trend: {Signal.BULLISH if vol_trend.iloc[-1] == 1 else Signal.BEARISH}\n"
        result += f"- Price-volume correlation: {price_volume_corr.iloc[-1]}\n"
        result += f"- Unusual volume: {volume.iloc[-1] > (vol_ma.iloc[-1] * params['unusual_volume'])}\n"
        return result

    def _get_support_resistance(self, prices_df: pd.DataFrame) -> str:
        """Calculate support and resistance levels"""
        params = self.thresholds["support_resistance"]

        # Find support and resistance levels using utility function
        support, resistance = find_support_resistance_levels(
            prices_df['close'],
            pivot_window=params["pivot_window"],
            lookback_period=params["lookback_period"]
        )

        current_price = prices_df['close'].iloc[-1]

        if support is None or resistance is None:
            return "Failed to analyze support and resistance levels"
        else:
            result = f"- Current price: {current_price}\n"
            result += f"- Nearest support: {support}\n"
            result += f"- Nearest resistance: {resistance}\n"
            result += f"- Price to support: {(current_price - support) / support}\n"
            result += f"- Price to resistance: {(resistance - current_price) / current_price}\n"
            return result


# Backward-compatible function interface
def technical_agent(state: FundState):
    """
    Technical analysis agent function (backward compatible).

    This function maintains the same interface as the original implementation,
    allowing seamless integration with existing code.

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return TechnicalAnalyst().analyze(state)
