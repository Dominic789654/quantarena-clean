"""
Alpha Vantage API client implementation.
Link: https://www.alphavantage.co/documentation/
Free tier: 25 API requests per day
Premium tier: 75 API requests per minute
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from apis.common_model import OHLCVCandle, MediaNews
from .api_model import InsiderTrade, Fundamentals, MacroEconomic

class AlphaVantageAPI:
    """Alpha Vantage API Wrapper."""

    def __init__(self):
        self.api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
        self.entitlement = os.environ.get("ALPHA_VANTAGE_ENTITLEMENT", None) # Premium feature only
        self.base_url = f"https://www.alphavantage.co/query?apikey={self.api_key}"
        if self.entitlement:
            self.base_url += f"&entitlement={self.entitlement}"

    def _get_daily_candles(self, ticker: str, trading_date: datetime) -> list[OHLCVCandle]: 
        """Get daily candles for a ticker. Filter candles by trading_date."""
        response = requests.get(
            url=self.base_url,
            params={
                "function": "TIME_SERIES_DAILY", 
                "symbol": ticker
            }
        )

        if response.status_code != 200:
            response.raise_for_status()
        
        # parse response into OHLCVCandle objects
        candle_series = response.json()["Time Series (Daily)"]
        daily_candles = []
        
        for date, data in candle_series.items():
            candle_date = datetime.strptime(date, "%Y-%m-%d")
            # Filter by trading_date
            if candle_date > trading_date:
                continue
                
            candle = OHLCVCandle(
                date=date,
                open=float(data["1. open"]),
                high=float(data["2. high"]),
                low=float(data["3. low"]),
                close=float(data["4. close"]),
                volume=int(data["5. volume"])
            )
            daily_candles.append(candle)

        return daily_candles
    
    def get_last_close_price(self, ticker: str, trading_date: datetime) -> float:
        """Get the last close price for a ticker."""
        daily_candles = self._get_daily_candles(ticker, trading_date)
        if daily_candles:
            return daily_candles[0].close

        return None

    def get_daily_candles_df(self, ticker: str, trading_date: datetime) -> pd.DataFrame:
        """Convert daily candles into a DataFrame Object with datetime index and numeric columns."""
        daily_candles = self._get_daily_candles(ticker, trading_date)
        
        # Convert list of OHLCVCandle objects to DataFrame
        df = pd.DataFrame([candle.model_dump() for candle in daily_candles])
        
        # Convert date column to datetime and set as index
        df["Date"] = pd.to_datetime(df["date"])
        df.set_index("Date", inplace=True)
        df.drop("date", axis=1, inplace=True)  # Remove original date column
        
        # Convert price and volume columns to numeric
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        # Sort by date index
        df.sort_index(inplace=True)
        
        return df


    def get_insider_trades(self, ticker: str, trading_date: datetime, limit: int=None) -> list[InsiderTrade]:
        """
        Get insider trades for a ticker.
        This API returns the latest and historical insider transactions made by key stakeholders.
        
        Args:
            ticker (str): The ticker symbol
            limit (int): Maximum number of trades to return
            trading_date (datetime): Filter trades up to this date
            
        Returns:
            list[InsiderTrade]: List of insider trades sorted by transaction date
        """
        response = requests.get(
            url=self.base_url,
            params={
                "function": "INSIDER_TRANSACTIONS", 
                "symbol": ticker
            }
        )
        
        if response.status_code != 200:
            response.raise_for_status()

        trades = response.json()["data"]

        # Filter trades by trading_date if provided
        if trading_date:
            filtered_trades = []
            for trade in trades:
                transaction_date = datetime.strptime(trade["transaction_date"], "%Y-%m-%d")
                if transaction_date < trading_date:
                    filtered_trades.append(trade)
            trades = filtered_trades
            

        trades = trades[:limit]
        
        return [InsiderTrade(**trade) for trade in trades]

    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """Get company fundamentals from Alpha Vantage."""
        response = requests.get(
            url=self.base_url,
            params={
                "function": "OVERVIEW", 
                "symbol": ticker
            }
        )
        if response.status_code != 200:
            response.raise_for_status()

        data = response.json()
        
        # The field names in data match our model's aliases automatically
        try:
            fundamentals = Fundamentals(**data)  # Automatic field mapping happens here
            return fundamentals
        except Exception as e:
            print(f"Error parsing response: {e}")
            return None

    def get_news(self, ticker: str = None, topic: str = None, trading_date: datetime = None, limit: int = None) -> list[MediaNews]:
        """
        Get news from Alpha Vantage.
        
        Args:
            ticker (str, optional): Stock ticker symbol for company-specific news
            topic (str, optional): Topic for market news (e.g., 'blockchain', 'economy_fiscal')
            trading_date (datetime, optional): Get news up to this date in the past week (used with ticker)
            limit (int, optional): Maximum number of news items to return
            
        Returns:
            list[MediaNews]: List of news articles
        """
        params = {"function": "NEWS_SENTIMENT"}
        
        if ticker:
            params["tickers"] = ticker
        if topic:
            params["topics"] = topic
        if trading_date:
            params["time_to"] = trading_date.strftime("%Y%m%dT%H%M")
            time_from = trading_date - timedelta(days=7)
            params["time_from"] = time_from.strftime("%Y%m%dT%H%M")

        response = requests.get(
            url=self.base_url,
            params=params
        )
        
        if response.status_code != 200:
            response.raise_for_status()

        news_list = []
        for news in response.json()["feed"]:
            news_list.append(MediaNews(
                title=news["title"],
                publish_time=news["time_published"],
                summary=news["summary"],
                publisher=news["source"]
            ))
        return news_list[:limit]
    

    def get_economic_indicators(self):
        """
        Get all economic indicators in one call
        """
        indicators = {
            "real_gdp": self._fetch_indicator("REAL_GDP"),  # default annual
            "cpi": self._fetch_indicator("CPI"),
            "treasury_yield": self._fetch_indicator("TREASURY_YIELD"),
            "federal_funds_rate": self._fetch_indicator("FEDERAL_FUNDS_RATE"),
            "unemployment": self._fetch_indicator("UNEMPLOYMENT"),
            "nonfarm_payrolls": self._fetch_indicator("NONFARM_PAYROLL"),
        }
        indicators = {k: v or {} for k, v in indicators.items()}
        
        return MacroEconomic(**indicators)

    def _fetch_indicator(self, function: str) -> dict:
        """Unified indicator fetcher matching pattern"""
        try:
            response = requests.get(
                url=self.base_url,
                params={
                    "function": function
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [{}])[0]  # test，use first data point，better to use 3 data points
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {function}: {str(e)}")
            return None

