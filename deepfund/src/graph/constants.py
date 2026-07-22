from enum import Enum

class AgentKey:
    # analyst keys
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    INSIDER = "insider"
    COMPANY_NEWS = "company_news"
    SOCIAL_SENTIMENT = "social_sentiment"
    MACROECONOMIC = "macroeconomic"
    POLICY = "policy"
    DEEPEAR_INTELLIGENCE = "deepear_intelligence"
    # workflow keys
    PORTFOLIO = "portfolio manager"
    PLANNER = "analyst planner" 

class Signal(str, Enum):
    """Signal type"""
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"

    def __str__(self) -> str:
        return self.value

class Action(str, Enum):
    """Action type"""
    BUY = "Buy"
    SELL = "Sell"
    HOLD = "Hold"

    def __str__(self) -> str:
        return self.value 