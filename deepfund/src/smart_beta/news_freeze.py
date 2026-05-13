"""
News Freeze Mechanism

Implements trading freeze logic based on market stress and crisis news.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum


class FreezeReason(str, Enum):
    """Reason for trading freeze."""
    VOLATILITY = "volatility"  # Market volatility too high
    MARKET_DROP = "market_drop"  # Significant market drop
    CRISIS_NEWS = "crisis_news"  # Crisis-related news detected
    MANUAL = "manual"  # Manual intervention
    NONE = "none"  # No freeze


class FreezeStatus(str, Enum):
    """Freeze status."""
    ACTIVE = "active"  # Freeze currently active
    PENDING = "pending"  # Conditions met, pending activation
    EXPIRED = "expired"  # Freeze expired
    NONE = "none"  # No freeze


@dataclass
class FreezeDecision:
    """
    Trading freeze decision.

    Attributes:
        status: Current freeze status
        reason: Reason for freeze (if active)
        duration_days: Duration of freeze in trading days
        start_date: When freeze started
        end_date: When freeze ends
        confidence: Confidence in freeze decision (0-1)
        triggers: Specific triggers that activated freeze
    """

    status: FreezeStatus = FreezeStatus.NONE
    reason: FreezeReason = FreezeReason.NONE
    duration_days: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    confidence: float = 0.0
    triggers: Optional[List[str]] = None

    def __post_init__(self):
        """Initialize triggers list."""
        if self.triggers is None:
            self.triggers = []

    @property
    def is_active(self) -> bool:
        """Check if freeze is currently active."""
        return self.is_active_at(datetime.now())

    def is_active_at(self, current_date: datetime) -> bool:
        """Check if freeze is active for a specific backtest date."""
        if self.status != FreezeStatus.ACTIVE:
            return False

        if self.start_date is not None and current_date < self.start_date:
            return False

        if self.end_date is None:
            return True

        return current_date <= self.end_date

    def days_remaining(self) -> int:
        """Get days remaining in freeze."""
        return self.days_remaining_at(datetime.now())

    def days_remaining_at(self, current_date: datetime) -> int:
        """Get remaining freeze sessions using the same weekday-based calendar."""
        if not self.is_active_at(current_date) or self.end_date is None:
            return 0

        current = current_date
        remaining = 0
        while current < self.end_date:
            current += timedelta(days=1)
            if current.weekday() < 5:
                remaining += 1
        return remaining

    def to_dict(self, current_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Convert to dictionary, optionally using a specific backtest date."""
        reference_date = current_date or datetime.now()
        return {
            "status": self.status.value,
            "reason": self.reason.value,
            "duration_days": self.duration_days,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "confidence": self.confidence,
            "triggers": self.triggers,
            "is_active": self.is_active_at(reference_date),
            "days_remaining": self.days_remaining_at(reference_date)
        }


class NewsFreezeMechanism:
    """
    Implements news and market freeze mechanism.

    Triggers freeze when:
    1. Market volatility exceeds threshold (VIX > 30)
    2. Market experiences significant single-day drop (>5%)
    3. Crisis-related news detected in headlines
    """

    def __init__(self, config=None):
        """
        Initialize freeze mechanism.

        Args:
            config: SmartBetaConfig instance (optional)
        """
        from .config import get_smart_beta_config
        self.config = config or get_smart_beta_config()

        # Active freezes
        self._active_freeze: Optional[FreezeDecision] = None

    def check(
        self,
        market_volatility: Optional[float] = None,
        market_return: Optional[float] = None,
        news_items: Optional[List[Dict]] = None,
        current_date: Optional[datetime] = None
    ) -> FreezeDecision:
        """
        Check if freeze should be activated.

        Args:
            market_volatility: Current market volatility (VIX/CVX)
            market_return: Today's market return
            news_items: List of news items with 'title' and 'content'
            current_date: Current date (defaults to now)

        Returns:
            FreezeDecision with status and reason
        """
        if current_date is None:
            current_date = datetime.now()

        # Check if freeze is already active
        if self._active_freeze and self._active_freeze.is_active_at(current_date):
            return self._active_freeze

        # Check triggers
        triggers = []
        confidence = 0.0
        reason = FreezeReason.NONE

        # 1. Market volatility check
        if market_volatility is not None:
            if market_volatility > self.config.vix_threshold:
                triggers.append(f"Volatility {market_volatility:.1f} > {self.config.vix_threshold}")
                confidence += 0.4
                reason = FreezeReason.VOLATILITY

        # 2. Market drop check
        if market_return is not None:
            if market_return < self.config.market_drop_threshold:
                triggers.append(f"Market drop {market_return:.1%} < {self.config.market_drop_threshold:.1%}")
                confidence += 0.5
                reason = FreezeReason.MARKET_DROP

        # 3. Crisis news check
        if news_items:
            crisis_detected = self._detect_crisis_news(news_items)
            if crisis_detected:
                triggers.append(f"Crisis news detected: {crisis_detected}")
                if reason == FreezeReason.NONE:
                    reason = FreezeReason.CRISIS_NEWS
                confidence += 0.3

        # Determine if freeze should be activated
        if triggers:
            # Multiple triggers increase confidence
            if len(triggers) > 1:
                confidence = min(1.0, confidence + 0.2 * (len(triggers) - 1))

            # Crisis headlines are themselves a freeze trigger even without a
            # supporting market-drop/volatility signal.
            should_activate = confidence >= 0.5 or reason == FreezeReason.CRISIS_NEWS
            if should_activate:
                confidence = max(confidence, 0.5 if reason == FreezeReason.CRISIS_NEWS else confidence)
                self._activate_freeze(
                    reason=reason,
                    duration_days=self.config.freeze_duration_days,
                    triggers=triggers,
                    confidence=confidence,
                    start_date=current_date
                )
                assert self._active_freeze is not None
                return self._active_freeze

        # No freeze
        return FreezeDecision(
            status=FreezeStatus.NONE,
            reason=reason,
            confidence=confidence,
            triggers=triggers
        )

    def _detect_crisis_news(self, news_items: List[Dict]) -> Optional[str]:
        """
        Detect crisis-related news in headlines and content.

        Args:
            news_items: List of news items with 'title' and 'content'

        Returns:
            Crisis keyword if detected, None otherwise
        """
        if not news_items:
            return None

        crisis_keywords = set(kw.lower() for kw in self.config.crisis_keywords)

        for news in news_items:
            title = news.get("title", "").lower()
            content = news.get("content", "").lower()

            # Check for crisis keywords
            for keyword in crisis_keywords:
                if keyword in title or keyword in content:
                    return keyword

        return None

    def _activate_freeze(
        self,
        reason: FreezeReason,
        duration_days: int,
        triggers: List[str],
        confidence: float,
        start_date: datetime
    ) -> None:
        """
        Activate trading freeze.

        Args:
            reason: Reason for freeze
            duration_days: Duration of freeze
            triggers: Trigger conditions
            confidence: Decision confidence
            start_date: Freeze start date
        """
        # Count the trigger session as day 1 of the freeze window.
        end_date = self._add_trading_days(start_date, max(duration_days - 1, 0))

        self._active_freeze = FreezeDecision(
            status=FreezeStatus.ACTIVE,
            reason=reason,
            duration_days=duration_days,
            start_date=start_date,
            end_date=end_date,
            confidence=confidence,
            triggers=triggers
        )

    def _add_trading_days(self, start_date: datetime, trading_days: int) -> datetime:
        """Advance by trading days using a weekday-only calendar."""
        current = start_date
        remaining = max(0, trading_days)
        while remaining > 0:
            current += timedelta(days=1)
            if current.weekday() < 5:
                remaining -= 1
        return current

    def clear_freeze(self) -> None:
        """Clear active freeze."""
        if self._active_freeze:
            self._active_freeze.status = FreezeStatus.EXPIRED
        self._active_freeze = None

    def get_active_freeze(self, current_date: Optional[datetime] = None) -> Optional[FreezeDecision]:
        """Get currently active freeze, if any, for a given reference date."""
        reference_date = current_date or datetime.now()
        if self._active_freeze and self._active_freeze.is_active_at(reference_date):
            return self._active_freeze
        return None

    def should_freeze_trading(self, current_date: Optional[datetime] = None) -> bool:
        """
        Check if trading should be frozen.

        Args:
            current_date: Current date (defaults to now)

        Returns:
            True if trading should be frozen
        """
        if current_date is None:
            current_date = datetime.now()

        if self._active_freeze is None:
            return False

        if self._active_freeze.status != FreezeStatus.ACTIVE:
            return False

        return self._active_freeze.is_active_at(current_date)

    def get_llm_prompt_context(self, current_date: Optional[datetime] = None) -> Dict:
        """
        Generate context for LLM-based freeze analysis.

        Returns:
            Dictionary with prompt context
        """
        reference_date = current_date or datetime.now()
        if self._active_freeze and self._active_freeze.is_active_at(reference_date):
            return {
                "freeze_active": True,
                "freeze_reason": self._active_freeze.reason.value,
                "freeze_duration_days": self._active_freeze.duration_days,
                "days_remaining": self._active_freeze.days_remaining_at(reference_date),
                "freeze_triggers": self._active_freeze.triggers,
                "freeze_confidence": self._active_freeze.confidence,
                "freeze_start_date": self._active_freeze.start_date.isoformat() if self._active_freeze.start_date else None,
                "freeze_end_date": self._active_freeze.end_date.isoformat() if self._active_freeze.end_date else None,
            }
        else:
            return {
                "freeze_active": False,
                "freeze_reason": "none",
                "freeze_duration_days": 0,
                "days_remaining": 0,
                "freeze_triggers": [],
                "freeze_confidence": 0.0,
                "freeze_start_date": None,
                "freeze_end_date": None,
            }

    def simulate_market_stress(
        self,
        vix_levels: List[float],
        market_returns: List[float],
        news_stream: List[List[Dict]],
        dates: List[datetime]
    ) -> List[FreezeDecision]:
        """
        Simulate freeze mechanism over historical period.

        Args:
            vix_levels: Daily VIX levels
            market_returns: Daily market returns
            news_stream: Daily news items
            dates: Corresponding dates

        Returns:
            List of freeze decisions for each day
        """
        decisions = []

        # Clear any existing freeze
        self.clear_freeze()

        for i, date in enumerate(dates):
            vix = vix_levels[i] if i < len(vix_levels) else None
            market_ret = market_returns[i] if i < len(market_returns) else None
            news = news_stream[i] if i < len(news_stream) else []

            decision = self.check(vix, market_ret, news, date)
            decisions.append(decision)

        return decisions
