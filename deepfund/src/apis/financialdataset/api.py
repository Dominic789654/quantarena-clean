"""
Financial Datasets API client implementation.
Link: https://docs.financialdatasets.ai/introduction
"""

import os
import requests
from .api_model import FinancialMetrics, InsiderTrade

class FinancialDatasetAPI:
    """Financial Datasets API Wrapper."""

    def __init__(self):
        self.api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
        self.base_url = "https://api.financialdatasets.ai"

    def get_financial_metrics(self, ticker: str) -> FinancialMetrics:
        """Get a real-time snapshot of key financial metrics and ratios for a ticker."""
        response = requests.get(
            url=f"{self.base_url}/financial-metrics/snapshot", 
            headers={"X-API-KEY": self.api_key}, 
            params={"ticker": ticker}
            )
        if response.status_code != 200:
            response.raise_for_status()
        
        # parse response into FinancialMetric object
        snapshot = response.json().get("snapshot")
        metrics = FinancialMetrics(**snapshot)
        
        return metrics


    def get_insider_trades(self, ticker: str, limit: int) -> list[InsiderTrade]:
        """
        Get insider trades like buys and sells for a ticker by a company insider.
        Trades are sorted by transaction date from the most recent date.

        Args:
            ticker (str): The ticker symbol of the company to get insider trades for.
            limit (int): The maximum number of insider trades to return.

        Returns:
            list[InsiderTrade]: A list of InsiderTrade objects.
        """
        response = requests.get(
            url=f"{self.base_url}/insider-trades", 
            headers={"X-API-KEY": self.api_key}, 
            params={"ticker": ticker, "limit": limit}
            )
        if response.status_code != 200:
            response.raise_for_status()

        insider_trades = response.json().get('insider_trades')
        trades = [InsiderTrade(**trade) for trade in insider_trades]

        return trades
