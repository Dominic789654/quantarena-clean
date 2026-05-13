from apis.router import Router, APISource
from datetime import datetime
router = Router(APISource.ALPHA_VANTAGE)

trading_date = datetime.strptime("2025-04-01", "%Y-%m-%d")
news = router.get_us_stock_news(ticker="TSLA", trading_date=trading_date, news_count=10)
print(news)
