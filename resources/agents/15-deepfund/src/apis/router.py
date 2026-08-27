"""Router for APIs"""

from apis import YFinanceAPI, AlphaVantageAPI

class APISource:
    YFINANCE = "yfinance"
    ALPHA_VANTAGE = "alpha_vantage"

class Router():
    """Router for APIs"""
    
    def __init__(self, source: APISource):
        if source == APISource.YFINANCE:
            self.api = YFinanceAPI()
        elif source == APISource.ALPHA_VANTAGE:
            self.api = AlphaVantageAPI()
        else:
            raise ValueError(f"Invalid API source: {source}")
    
    def get_us_stock_news(self, ticker, trading_date, news_count):
        """Get news for a ticker"""
        if isinstance(self.api, AlphaVantageAPI):
            return self.api.get_news(ticker=ticker, trading_date=trading_date, limit=news_count)
        else:  # YFinanceAPI
            return self.api.get_news(query=ticker, news_count=news_count)
    
    def get_market_news(self, topic, trading_date, news_count):
        """Get market news for a topic."""
        if isinstance(self.api, AlphaVantageAPI):
            return self.api.get_news(topic=topic, trading_date=trading_date, limit=news_count)
        else:  # YFinanceAPI
            return self.api.get_news(query=topic, news_count=news_count)

    def get_us_stock_insider_trades(self, ticker, trading_date, limit):
        return self.api.get_insider_trades(ticker, trading_date, limit)
    
    def get_us_stock_daily_candles_df(self, ticker, trading_date):
        return self.api.get_daily_candles_df(ticker, trading_date)
    
    def get_us_stock_last_close_price(self, ticker, trading_date):
        """Get the last close price for a ticker"""
        return self.api.get_last_close_price(ticker, trading_date)

    def get_us_stock_fundamentals(self, ticker):
        """Get fundamentals for a ticker"""
        return self.api.get_fundamentals(ticker)
    
    def get_us_economic_indicators(self):
        """Get economic indicators."""
        return self.api.get_economic_indicators()

