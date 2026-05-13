from pydantic import BaseModel, Field

class InsiderTrade(BaseModel):
    """insider trade model."""
    transaction_date: str
    ticker: str
    executive: str
    executive_title: str
    security_type: str
    acquisition_or_disposal: str
    shares: str
    share_price: str

class Fundamentals(BaseModel):
    """Company fundamentals model."""
    # Basic Info
    latest_quarter: str = Field(alias="LatestQuarter")
    market_capitalization: str = Field(alias="MarketCapitalization")
    ebitda: str = Field(alias="EBITDA")
    
    # Valuation Metrics
    pe_ratio: str = Field(alias="PERatio")
    peg_ratio: str = Field(alias="PEGRatio")
    book_value: str = Field(alias="BookValue")
    dividend_per_share: str = Field(alias="DividendPerShare")
    dividend_yield: str = Field(alias="DividendYield")
    eps: str = Field(alias="EPS")
    
    # TTM Metrics
    revenue_per_share_ttm: str = Field(alias="RevenuePerShareTTM")
    profit_margin: str = Field(alias="ProfitMargin")
    operating_margin_ttm: str = Field(alias="OperatingMarginTTM")
    return_on_assets_ttm: str = Field(alias="ReturnOnAssetsTTM")
    return_on_equity_ttm: str = Field(alias="ReturnOnEquityTTM")
    revenue_ttm: str = Field(alias="RevenueTTM")
    gross_profit_ttm: str = Field(alias="GrossProfitTTM")
    diluted_eps_ttm: str = Field(alias="DilutedEPSTTM")
    
    # Growth Metrics
    quarterly_earnings_growth_yoy: str = Field(alias="QuarterlyEarningsGrowthYOY")
    quarterly_revenue_growth_yoy: str = Field(alias="QuarterlyRevenueGrowthYOY")

    # Analyst Ratings
    target_price: str = Field(alias="AnalystTargetPrice")
    strong_buy: str = Field(alias="AnalystRatingStrongBuy")
    buy: str = Field(alias="AnalystRatingBuy")
    hold: str = Field(alias="AnalystRatingHold")
    sell: str = Field(alias="AnalystRatingSell")
    strong_sell: str = Field(alias="AnalystRatingStrongSell")
    
    # Valuation Metrics
    trailing_pe: str = Field(alias="TrailingPE")
    forward_pe: str = Field(alias="ForwardPE")
    price_to_sales_ratio_ttm: str = Field(alias="PriceToSalesRatioTTM")
    price_to_book_ratio: str = Field(alias="PriceToBookRatio")
    ev_to_revenue: str = Field(alias="EVToRevenue")
    ev_to_ebitda: str = Field(alias="EVToEBITDA")
    beta: str = Field(alias="Beta")
    current_ratio: str = Field(default="N/A", alias="CurrentRatio")
    operating_cash_flow: str = Field(default="N/A", alias="OperatingCashFlow")

class MacroEconomic(BaseModel):
    """Economic indicator model."""
    real_gdp: dict   #default annual,quarterly
    cpi: dict #monthly
    treasury_yield: dict #default monthly, 10years
    federal_funds_rate: dict #default monthly. Strings daily, weekly, and monthly are accepted.
    unemployment: dict #monthly
    nonfarm_payrolls: dict #monthly





