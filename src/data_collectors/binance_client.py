import os
from binance.client import Client
from dotenv import load_dotenv

class BinanceDataCollector:
    def __init__(self):
        load_dotenv()
        self.client = Client(
            os.getenv('BINANCE_API_KEY'),
            os.getenv('BINANCE_API_SECRET')
        )

    def get_klines(self, symbol: str, interval: str, limit: int = 100):
        """
        Belirli bir sembol için kline/candlestick verilerini çeker
        
        Args:
            symbol: "BTCUSDT" gibi sembol çifti
            interval: "1m", "5m", "15m", "1h", "4h", "1d" gibi zaman aralığı
            limit: Kaç veri noktası çekileceği
        """
        try:
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            return self._format_klines(klines)
        except Exception as e:
            print(f"Hata: {e}")
            return None

    def _format_klines(self, klines):
        """Kline verilerini formatlı şekilde döndürür"""
        formatted_klines = []
        for k in klines:
            formatted_klines.append({
                'timestamp': k[0],
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'close_time': k[6],
                'quote_asset_volume': float(k[7]),
                'number_of_trades': int(k[8]),
                'taker_buy_base_asset_volume': float(k[9]),
                'taker_buy_quote_asset_volume': float(k[10])
            })
        return formatted_klines

    def get_ticker_price(self, symbol: str):
        """Anlık fiyat bilgisini çeker"""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            print(f"Hata: {e}")
            return None