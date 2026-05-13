"""
Macro State Analyzer

Analyzes macroeconomic conditions to determine market state and adjust Smart Beta parameters.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
from enum import Enum


class MacroState(str, Enum):
    """Macroeconomic state classifications."""
    EXPANSION = "expansion"  # Strong growth, low volatility
    SLOWDOWN = "slowdown"    # Growth slowing, increasing uncertainty
    RECESSION = "recession"  # Contraction, high volatility
    RECOVERY = "recovery"   # Emerging from recession, improving conditions
    UNCERTAIN = "uncertain"  # Insufficient data or conflicting signals


@dataclass
class MacroIndicator:
    """
    Individual macroeconomic indicator.

    Attributes:
        name: Indicator name (e.g., "gdp_growth", "cpi", "pmi")
        value: Current value
        change: Change from previous period
        threshold_bullish: Bullish threshold
        threshold_bearish: Bearish threshold
        direction: Whether higher is better ("higher" or "lower")
        weight: Weight in macro score calculation
    """

    name: str
    value: float
    change: float = 0.0
    threshold_bullish: float = 0.0
    threshold_bearish: float = 0.0
    direction: str = "higher"  # "higher" or "lower"
    weight: float = 1.0

    def is_bullish(self) -> bool:
        """Check if indicator is bullish."""
        if self.direction == "higher":
            return self.value > self.threshold_bullish
        else:
            return self.value < self.threshold_bullish

    def is_bearish(self) -> bool:
        """Check if indicator is bearish."""
        if self.direction == "higher":
            return self.value < self.threshold_bearish
        else:
            return self.value > self.threshold_bearish

    def score(self) -> float:
        """Calculate normalized score (-1 to 1)."""
        if self.direction == "higher":
            if self.threshold_bullish > self.threshold_bearish:
                # Positive is better
                if self.value >= self.threshold_bullish:
                    return 1.0
                elif self.value <= self.threshold_bearish:
                    return -1.0
                else:
                    # Linear interpolation
                    return (self.value - self.threshold_bearish) / (self.threshold_bullish - self.threshold_bearish) * 2 - 1
            else:
                # Higher is worse (e.g., unemployment)
                if self.value <= self.threshold_bullish:
                    return 1.0
                elif self.value >= self.threshold_bearish:
                    return -1.0
                else:
                    return (self.threshold_bearish - self.value) / (self.threshold_bearish - self.threshold_bullish) * 2 - 1

        else:  # lower is better
            if self.value <= self.threshold_bullish:
                return 1.0
            elif self.value >= self.threshold_bearish:
                return -1.0
            else:
                return (self.threshold_bearish - self.value) / (self.threshold_bearish - self.threshold_bullish) * 2 - 1


@dataclass
class MacroAnalysis:
    """
    Macroeconomic analysis result.

    Attributes:
        state: Macroeconomic state classification
        score: Composite macro score (-1 to 1)
        indicators: Dictionary of individual indicators
        beta_adjustment: Recommended beta adjustment factor
        confidence: Analysis confidence (0 to 1)
        timestamp: Analysis timestamp
    """

    state: MacroState
    score: float
    indicators: Dict[str, MacroIndicator]
    beta_adjustment: float
    confidence: float
    timestamp: datetime


class MacroStateAnalyzer:
    """
    Analyzes macroeconomic conditions to determine market state.

    Uses indicators such as:
        - GDP growth
        - CPI inflation
        - PMI manufacturing index
        - M2 money supply growth
        - Unemployment rate
        - Market volatility (VIX/CVX)
    """

    # Default indicator thresholds
    DEFAULT_THRESHOLDS = {
        "gdp_growth": {
            "threshold_bullish": 0.06,  # >6% growth is bullish
            "threshold_bearish": 0.02,  # <2% growth is bearish
            "direction": "higher",
            "weight": 1.5
        },
        "cpi_yoy": {
            "threshold_bullish": 0.02,  # 2% inflation is target (bullish)
            "threshold_bearish": 0.05,  # >5% inflation is bearish
            "direction": "lower",
            "weight": 1.2
        },
        "pmi": {
            "threshold_bullish": 50.0,  # >50 is expansion
            "threshold_bearish": 48.0,  # <48 is contraction
            "direction": "higher",
            "weight": 1.3
        },
        "m2_growth": {
            "threshold_bullish": 0.10,  # 10% M2 growth is stimulative
            "threshold_bearish": 0.05,  # <5% growth is restrictive
            "direction": "higher",
            "weight": 0.8
        },
        "unemployment_rate": {
            "threshold_bullish": 0.04,  # 4% unemployment is healthy
            "threshold_bearish": 0.06,  # >6% unemployment is concerning
            "direction": "lower",
            "weight": 1.0
        },
        "market_volatility": {
            "threshold_bullish": 15.0,  # VIX < 15 is low volatility
            "threshold_bearish": 25.0,  # VIX > 25 is high volatility
            "direction": "lower",
            "weight": 1.4
        }
    }

    def __init__(self, config=None):
        """
        Initialize macro analyzer.

        Args:
            config: SmartBetaConfig instance (optional)
        """
        from .config import get_smart_beta_config
        self.config = config or get_smart_beta_config()

    def analyze(
        self,
        indicators_data: Dict[str, float],
        trade_date: datetime,
        market_returns: Optional[List[float]] = None
    ) -> MacroAnalysis:
        """
        Analyze macroeconomic conditions.

        Args:
            indicators_data: Dictionary of indicator values
            trade_date: Trading date for analysis
            market_returns: Recent market returns for volatility calculation

        Returns:
            MacroAnalysis result
        """
        # Build macro indicators
        indicators = self._build_indicators(indicators_data)

        # Calculate market volatility if returns provided
        if market_returns is not None:
            vol_indicator = self._calculate_market_volatility(market_returns)
            indicators["market_volatility"] = vol_indicator

        # Calculate composite score
        score, confidence = self._calculate_macro_score(indicators)

        # Determine macro state
        state = self._determine_macro_state(score, indicators)

        # Calculate beta adjustment
        beta_adjustment = self._calculate_beta_adjustment(state, score)

        return MacroAnalysis(
            state=state,
            score=score,
            indicators=indicators,
            beta_adjustment=beta_adjustment,
            confidence=confidence,
            timestamp=trade_date
        )

    def _build_indicators(
        self,
        indicators_data: Dict[str, float]
    ) -> Dict[str, MacroIndicator]:
        """
        Build MacroIndicator objects from raw data.

        Args:
            indicators_data: Dictionary of indicator values

        Returns:
            Dictionary of MacroIndicator objects
        """
        indicators = {}

        for name, value in indicators_data.items():
            if name in self.DEFAULT_THRESHOLDS:
                thresholds = self.DEFAULT_THRESHOLDS[name]
                indicator = MacroIndicator(
                    name=name,
                    value=value,
                    threshold_bullish=thresholds["threshold_bullish"],
                    threshold_bearish=thresholds["threshold_bearish"],
                    direction=thresholds["direction"],
                    weight=thresholds["weight"]
                )
                indicators[name] = indicator

        return indicators

    def _calculate_market_volatility(
        self,
        market_returns: List[float]
    ) -> MacroIndicator:
        """
        Calculate market volatility indicator.

        Args:
            market_returns: Recent market returns

        Returns:
            Market volatility MacroIndicator
        """
        if len(market_returns) < 20:
            volatility = 20.0  # Default to moderate volatility
        else:
            # Calculate annualized volatility
            daily_vol = np.std(market_returns)
            volatility = daily_vol * np.sqrt(252)

        thresholds = self.DEFAULT_THRESHOLDS["market_volatility"]
        return MacroIndicator(
            name="market_volatility",
            value=volatility,
            threshold_bullish=thresholds["threshold_bullish"],
            threshold_bearish=thresholds["threshold_bearish"],
            direction=thresholds["direction"],
            weight=thresholds["weight"]
        )

    def _calculate_macro_score(
        self,
        indicators: Dict[str, MacroIndicator]
    ) -> Tuple[float, float]:
        """
        Calculate composite macro score.

        Args:
            indicators: Dictionary of MacroIndicator objects

        Returns:
            Tuple of (score, confidence)
        """
        if not indicators:
            return 0.0, 0.0

        weighted_scores = []
        total_weight = 0

        for indicator in indicators.values():
            score = indicator.score()
            weighted_scores.append(score * indicator.weight)
            total_weight += indicator.weight

        if total_weight == 0:
            return 0.0, 0.0

        composite_score = sum(weighted_scores) / total_weight

        # Calculate confidence based on number of indicators and consistency
        num_indicators = len(indicators)
        confidence = min(1.0, num_indicators / 4)  # At least 4 indicators for full confidence

        # Check consistency of signals
        bullish_count = sum(1 for i in indicators.values() if i.is_bullish())
        bearish_count = sum(1 for i in indicators.values() if i.is_bearish())

        consistency = 1.0 - abs(bullish_count - bearish_count) / num_indicators
        confidence *= consistency

        # Clamp to [0, 1]
        confidence = max(0.0, min(1.0, confidence))

        return composite_score, confidence

    def _determine_macro_state(
        self,
        score: float,
        indicators: Dict[str, MacroIndicator]
    ) -> MacroState:
        """
        Determine macro state based on score and indicators.

        Args:
            score: Composite macro score
            indicators: Dictionary of MacroIndicator objects

        Returns:
            MacroState classification
        """
        if not indicators:
            return MacroState.UNCERTAIN

        # Check for extreme conditions first
        market_vol = indicators.get("market_volatility")
        if market_vol and market_vol.value > 30.0:
            return MacroState.RECESSION

        # Determine based on score
        if score > 0.3:
            # Strongly positive indicators
            return MacroState.EXPANSION
        elif score > 0.1:
            # Moderately positive
            return MacroState.RECOVERY if score < 0.2 else MacroState.EXPANSION
        elif score < -0.3:
            # Strongly negative
            return MacroState.RECESSION
        elif score < -0.1:
            # Moderately negative
            return MacroState.SLOWDOWN
        else:
            # Neutral
            return MacroState.SLOWDOWN if score < 0 else MacroState.RECOVERY

    def _calculate_beta_adjustment(
        self,
        state: MacroState,
        score: float
    ) -> float:
        """
        Calculate beta adjustment based on macro state.

        Args:
            state: Macroeconomic state
            score: Composite macro score

        Returns:
            Beta adjustment factor (e.g., 0.1 for +10% beta)
        """
        # Get target beta from config
        target_beta = self.config.get_beta_target(state.value)

        # Calculate adjustment (target_beta - 1.0)
        base_adjustment = target_beta - 1.0

        # Scale by score intensity
        if abs(score) > 0.5:
            # Strong signal, full adjustment
            adjustment = base_adjustment
        elif abs(score) > 0.2:
            # Moderate signal, scale adjustment
            adjustment = base_adjustment * (abs(score) / 0.5)
        else:
            # Weak signal, minimal adjustment
            adjustment = base_adjustment * 0.1

        # Apply constraints from config
        min_adj, max_adj = self.config.macro_adjustment_range
        adjustment = max(min_adj, min(max_adj, adjustment))

        return adjustment

    def get_llm_prompt_context(self, analysis: MacroAnalysis) -> Dict:
        """
        Generate context for LLM-based macro analysis.

        Args:
            analysis: MacroAnalysis result

        Returns:
            Dictionary with prompt context
        """
        # Format indicators for LLM
        indicators_text = []
        for name, indicator in analysis.indicators.items():
            direction = "↑" if indicator.is_bullish() else "↓" if indicator.is_bearish() else "→"
            indicators_text.append(
                f"- {name}: {indicator.value:.3f} {direction} "
                f"(bullish > {indicator.threshold_bullish:.3f}, "
                f"bearish < {indicator.threshold_bearish:.3f})"
            )

        return {
            "macro_state": analysis.state.value,
            "macro_score": f"{analysis.score:.3f}",
            "beta_adjustment": f"{analysis.beta_adjustment:.3f}",
            "confidence": f"{analysis.confidence:.1%}",
            "indicators": "\n".join(indicators_text),
            "timestamp": analysis.timestamp.strftime("%Y-%m-%d")
        }
