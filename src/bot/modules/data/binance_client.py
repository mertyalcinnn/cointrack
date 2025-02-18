import aiohttp

class BinanceClient:
    BASE_URL = 'https://api.binance.com/api/v3'
    
    @staticmethod
    async def get_klines(symbol: str, interval: str, limit: int = 100) -> list:
        async with aiohttp.ClientSession() as session:
            url = f'{BinanceClient.BASE_URL}/klines'
            params = {'symbol': symbol, 'interval': interval, 'limit': limit}
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
        return None

    @staticmethod
    async def get_ticker(symbol: str = None) -> dict:
        async with aiohttp.ClientSession() as session:
            url = f'{BinanceClient.BASE_URL}/ticker/24hr'
            params = {'symbol': symbol} if symbol else {}
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
        return None 