"""
Policy Analyst - Refactored to use BaseAnalyst

Analyzes fiscal and monetary policy news to provide trading signals.
"""

from typing import Dict, List
from graph.schema import FundState
from graph.constants import AgentKey
from llm.prompt import POLICY_PROMPT
from apis.router import Router
from .base import BaseAnalyst


class PolicyAnalyst(BaseAnalyst):
    """
    Policy specialist analyzing fiscal and monetary policy news.
    Uses policy announcements to determine market direction bias.
    """

    def __init__(self):
        super().__init__(AgentKey.POLICY, POLICY_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Dict[str, List[str]]:
        """
        Fetch fiscal and monetary policy news.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            Dict with fiscal_policy and monetary_policy news lists
        """
        trading_date = state["trading_date"]

        fiscal_policy = router.get_market_news(
            topic="economy_fiscal",
            trading_date=trading_date,
            news_count=self.thresholds["news_count"]
        )
        monetary_policy = router.get_market_news(
            topic="economy_monetary",
            trading_date=trading_date,
            news_count=self.thresholds["news_count"]
        )

        return {
            "fiscal_policy": [m.model_dump_json() for m in fiscal_policy],
            "monetary_policy": [m.model_dump_json() for m in monetary_policy]
        }

    def build_prompt(self, data: Dict[str, List[str]]) -> str:
        """
        Build prompt from policy news data.

        Args:
            data: Dict with fiscal_policy and monetary_policy lists

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(
            fiscal_policy=data["fiscal_policy"],
            monetary_policy=data["monetary_policy"]
        )


# Backward-compatible function interface
def policy_agent(state: FundState):
    """
    Policy analysis agent function (backward compatible).

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return PolicyAnalyst().analyze(state)
