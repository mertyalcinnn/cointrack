import aiohttp
import logging

class BinanceClient:
    BASE_URL = 'https://api.binance.com/api/v3'
    
    def __init__(self):
        self.logger = logging.getLogger('BinanceClient')
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 100) -> list:
        try:
            async with aiohttp.ClientSession() as session:
                url = f'{BinanceClient.BASE_URL}/klines'
                params = {'symbol': symbol, 'interval': interval, 'limit': limit}
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
            return None
        except Exception as e:
            self.logger.error(f"get_klines error for {symbol}: {str(e)}")
            return None

    async def get_ticker(self, symbol: str = None) -> dict:
        try:
            async with aiohttp.ClientSession() as session:
                url = f'{BinanceClient.BASE_URL}/ticker/24hr'
                params = {'symbol': symbol} if symbol else {}
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
            return None
        except Exception as e:
            self.logger.error(f"get_ticker error: {str(e)}")
            return None
