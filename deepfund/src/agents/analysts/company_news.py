"""
Company News Analyst - Refactored to use BaseAnalyst

Analyzes company news sentiment to provide trading signals.
"""

from typing import Any, List
from graph.schema import FundState
from graph.constants import AgentKey
from llm.prompt import COMPANY_NEWS_PROMPT
from apis.router import Router
from .base import BaseAnalyst


class CompanyNewsAnalyst(BaseAnalyst):
    """
    News specialist analyzing company news to provide trading signals.
    Uses sentiment analysis of recent company news to determine bullish/bearish bias.
    """

    def __init__(self):
        super().__init__(AgentKey.COMPANY_NEWS, COMPANY_NEWS_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Any:
        """
        Fetch company news for analysis.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            List of news items as JSON strings
        """
        ticker = state["ticker"]
        trading_date = state["trading_date"]
        market = state.get("market", "us")

        if market == "cn":
            company_news = router.get_cn_stock_news(
                ticker, trading_date, self.thresholds["news_count"]
            )
        else:
            company_news = router.get_us_stock_news(
                ticker, trading_date, self.thresholds["news_count"]
            )

        return [m.model_dump_json() for m in company_news]

    def build_prompt(self, data: List[str]) -> str:
        """
        Build prompt from news data.

        Args:
            data: List of news item JSON strings

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(news=data)


# Backward-compatible function interface
def company_news_agent(state: FundState):
    """
    Company news analysis agent function (backward compatible).

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return CompanyNewsAnalyst().analyze(state)
