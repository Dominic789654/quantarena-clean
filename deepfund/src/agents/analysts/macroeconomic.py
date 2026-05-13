"""
Macroeconomic Analyst - Refactored to use BaseAnalyst

Analyzes macroeconomic indicators to provide trading signals.
"""

from typing import Any
from graph.schema import FundState
from graph.constants import AgentKey
from llm.prompt import MACROECONOMIC_PROMPT
from apis.router import Router
from .base import BaseAnalyst


class MacroeconomicAnalyst(BaseAnalyst):
    """
    Macroeconomic analysis specialist focusing on economic indicators.
    Analyzes macro data like GDP, inflation, interest rates, etc.
    """

    def __init__(self):
        super().__init__(AgentKey.MACROECONOMIC, MACROECONOMIC_PROMPT)

    def fetch_data(self, state: FundState, router: Router) -> Any:
        """
        Fetch macroeconomic indicators.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            Economic indicators data
        """
        market = state.get("market", "us")

        if market == "cn":
            return router.get_cn_economic_indicators()
        else:
            return router.get_us_economic_indicators()

    def build_prompt(self, data: Any) -> str:
        """
        Build prompt from economic indicators.

        Args:
            data: Economic indicators data

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(economic_indicators=data)


# Backward-compatible function interface
def macroeconomic_agent(state: FundState):
    """
    Macroeconomic analysis agent function (backward compatible).

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return MacroeconomicAnalyst().analyze(state)
