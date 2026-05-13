"""Financial Dataset API models."""

from pydantic import BaseModel
from typing import Optional

class FinancialMetrics(BaseModel):
    """Financial metrics model."""
    ticker: str
    # Profitability metrics
    return_on_equity: Optional[float] = None
    net_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    # Cash flow metrics
    cash_ratio: Optional[float] = None
    free_cash_flow_yield: Optional[float] = None
    free_cash_flow_growth: Optional[float] = None
    # Growth metrics
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    book_value_growth: Optional[float] = None
    # Financial health metrics
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    earnings_per_share: Optional[float] = None
    free_cash_flow_per_share: Optional[float] = None

class InsiderTrade(BaseModel):
    """Insider trade model. """
    ticker: str
    transaction_date: Optional[str] = None
    transaction_shares: Optional[float] = None
    shares_owned_before_transaction: Optional[float] = None
    shares_owned_after_transaction: Optional[float] = None
    security_title: Optional[str] = None
    