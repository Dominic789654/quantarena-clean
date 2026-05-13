"""
Fundamental Analyst - Refactored to use BaseAnalyst

Analyzes company financial health and valuation.
"""

from __future__ import annotations

from typing import Any, Protocol
from graph.schema import FundState
from graph.constants import AgentKey
from llm.prompt import FUNDAMENTAL_PROMPT
from apis.router import Router
from .base import BaseAnalyst


class FundamentalsProvider(Protocol):
    """Provider interface for optional fundamentals replay/injection."""

    name: str

    def get_fundamentals(self, ticker: str, market: str) -> Any:
        """Return fundamentals for ``ticker`` in ``market``."""


class FundamentalAnalyst(BaseAnalyst):
    """
    Fundamental analysis specialist focusing on company profitability,
    growth, cashflow and financial health.
    """

    def __init__(self, fundamentals_provider: FundamentalsProvider | None = None):
        super().__init__(AgentKey.FUNDAMENTAL, FUNDAMENTAL_PROMPT)
        self.fundamentals_provider = fundamentals_provider

    def fetch_data(self, state: FundState, router: Router) -> Any:
        """
        Fetch fundamental data for the ticker.

        Args:
            state: Current FundState
            router: Router instance for API calls

        Returns:
            Fundamentals object from router
        """
        ticker = state["ticker"]
        market = state.get("market", "us")

        if self.fundamentals_provider is not None:
            return self.fundamentals_provider.get_fundamentals(ticker, market)

        if market == "cn":
            return router.get_cn_stock_fundamentals(ticker=ticker)
        else:
            return router.get_us_stock_fundamentals(ticker=ticker)

    def build_prompt(self, data: Any) -> str:
        """
        Build prompt from fundamental data.

        Args:
            data: Fundamentals object

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(fundamentals=data.model_dump_json())


# Backward-compatible function interface
def fundamental_agent(state: FundState):
    """
    Fundamental analysis agent function (backward compatible).

    This function maintains the same interface as the original implementation,
    allowing seamless integration with existing code.

    Args:
        state: Current FundState

    Returns:
        Dict with analyst_signals
    """
    return FundamentalAnalyst().analyze(state)
