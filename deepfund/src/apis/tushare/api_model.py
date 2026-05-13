"""
Tushare API data models for Chinese A-share market.
Reference: https://tushare.pro/document/2
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class TushareNews(BaseModel):
    """Tushare news model for Chinese market news."""
    title: str = Field(..., description="News title")
    publish_time: str = Field(..., description="Publication time")
    publisher: str = Field(..., description="News source/publisher")
    link: Optional[str] = Field(None, description="News URL link")
    summary: Optional[str] = Field(None, description="News summary")


class TushareCandle(BaseModel):
    """Tushare candle/OHLCV data model for Chinese stocks."""
    trade_date: str = Field(..., description="Trading date (YYYYMMDD)")
    open: float = Field(..., description="Open price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Close price")
    vol: Optional[float] = Field(None, description="Volume (lots)")
    amount: Optional[float] = Field(None, description="Trading amount (thousand yuan)")


class TushareFundamentals(BaseModel):
    """Tushare fundamentals model for Chinese stocks."""
    # Basic Info
    ts_code: str = Field(..., description="TS code (e.g., 600519.SH)")
    name: str = Field(..., description="Stock name")
    industry: Optional[str] = Field(None, description="Industry")
    area: Optional[str] = Field(None, description="Area/region")

    # Valuation Metrics
    pe: Optional[float] = Field(None, description="P/E ratio")
    pe_ttm: Optional[float] = Field(None, description="P/E ratio (TTM)")
    pb: Optional[float] = Field(None, description="P/B ratio")
    ps: Optional[float] = Field(None, description="P/S ratio")
    ps_ttm: Optional[float] = Field(None, description="P/S ratio (TTM)")

    # Per-share Metrics
    total_share: Optional[float] = Field(None, description="Total shares (ten thousand)")
    float_share: Optional[float] = Field(None, description="Float shares (ten thousand)")
    total_assets: Optional[float] = Field(None, description="Total assets")
    liquid_assets: Optional[float] = Field(None, description="Liquid assets")

    # Profitability
    roe: Optional[float] = Field(None, description="ROE (%)")
    roa: Optional[float] = Field(None, description="ROA (%)")
    gross_profit_margin: Optional[float] = Field(None, description="Gross profit margin (%)")
    net_profit_margin: Optional[float] = Field(None, description="Net profit margin (%)")

    # Growth Metrics
    revenue_yoy: Optional[float] = Field(None, description="Revenue YoY growth (%)")
    profit_to_gr_yoy: Optional[float] = Field(None, description="Net profit YoY growth (%)")


class TushareInsiderTrade(BaseModel):
    """Tushare insider trade model for Chinese stocks."""
    ts_code: str = Field(..., description="TS code")
    ann_date: str = Field(..., description="Announcement date")
    endDate: str = Field(..., description="End date of reporting period")
    name: str = Field(..., description="Insider name")
    title: Optional[str] = Field(None, description="Insider title")
    gender: Optional[str] = Field(None, description="Gender")
    age: Optional[int] = Field(None, description="Age")
    share_num: Optional[float] = Field(None, description="Holding shares (ten thousand)")
    hold_ratio: Optional[float] = Field(None, description="Holding ratio (%)")


class CNEconomicIndicators(BaseModel):
    """Chinese economic indicators model from Tushare."""
    # GDP and Growth
    gdp: dict = Field(default_factory=dict, description="GDP data (quarterly)")
    gdp_yoy: dict = Field(default_factory=dict, description="GDP year-over-year growth")

    # Price Indices
    cpi: dict = Field(default_factory=dict, description="Consumer Price Index (monthly)")
    ppi: dict = Field(default_factory=dict, description="Producer Price Index (monthly)")

    # Monetary Policy
    m2: dict = Field(default_factory=dict, description="M2 money supply (monthly)")
    m1: dict = Field(default_factory=dict, description="M1 money supply (monthly)")
    loan_rate: dict = Field(default_factory=dict, description="Loan prime rate")

    # Employment
    unemployment_rate: dict = Field(default_factory=dict, description="Urban unemployment rate")

    # Trade
    export_growth: dict = Field(default_factory=dict, description="Export growth rate")
    import_growth: dict = Field(default_factory=dict, description="Import growth rate")
