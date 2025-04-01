import ccxt
import logging
from typing import Dict, List, Optional

class BinanceClient:
    def __init__(self):
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        self.logger = logging.getLogger('BinanceClient')
        
    def get_exchange_info(self) -> Dict:
        """Get exchange information (not async)"""
        try:
            return self.exchange.load_markets()
        except Exception as e:
            self.logger.error(f"Exchange info alma hatası: {str(e)}")
            return {}
            
    def get_klines(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> List:
        """Get kline/candlestick data (not async)"""
        try:
            return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            self.logger.error(f"Kline verisi alma hatası: {str(e)}")
            return []
            
    def get_ticker(self, symbol: str = None) -> Dict:
        """Get ticker information (not async)"""
        try:
            if symbol:
                return self.exchange.fetch_ticker(symbol)
            else:
                # Fetch all tickers
                return self.exchange.fetch_tickers()
        except Exception as e:
            self.logger.error(f"Ticker verisi alma hatası: {str(e)}")
            return {} 