"""
Insider Trading Analyst - Refactored to use BaseAnalyst

Analyzes insider trading patterns to provide trading signals.
"""

from typing import Any, List
from graph.schema import FundState
from graph.constants import AgentKey
from llm.prompt import INSIDER_PROMPT
from apis.router import Router
from .base import BaseAnalyst


class InsiderAnalyst(BaseAnalyst):
    """
    Insider trading specialist analyzing insider activity patterns.
    Uses insider buy/sell data to detect informed trading signals.
    """

    def __init__(self):
        super().__init__(AgentKey.INSIDER, INSIDER_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Any:
        """
        Fetch insider trading data.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            List of insider trade JSON strings
        """
        ticker = state["ticker"]
        trading_date = state["trading_date"]
        market = state.get("market", "us")

        if market == "cn":
            insider_trades = router.get_cn_stock_insider_trades(
                ticker=ticker,
                trading_date=trading_date,
                limit=self.thresholds["num_trades"],
            )
        else:
            insider_trades = router.get_us_stock_insider_trades(
                ticker=ticker,
                trading_date=trading_date,
                limit=self.thresholds["num_trades"],
            )

        return [m.model_dump_json() for m in insider_trades]

    def build_prompt(self, data: List[str]) -> str:
        """
        Build prompt from insider trading data.

        Args:
            data: List of insider trade JSON strings

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(
            num_trades=self.thresholds["num_trades"],
            trades=data
        )


# Backward-compatible function interface
def insider_agent(state: FundState):
    """
    Insider trading analysis agent function (backward compatible).

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return InsiderAnalyst().analyze(state)
