import aiohttp
import numpy as np
from .technical_analysis import TechnicalAnalysis

class MarketAnalyzer:
    def __init__(self, logger):
        self.logger = logger
        self.ta = TechnicalAnalysis()
        self.excluded_coins = ['USDCUSDT', 'BUSDUSDT']

    async def get_klines_data(self, symbol: str, interval: str) -> list:
        """Belirli bir zaman dilimi için kline verilerini getir"""
        try:
            async with aiohttp.ClientSession() as session:
                url = 'https://api.binance.com/api/v3/klines'
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'limit': 100
                }
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
            return None
        except Exception as e:
            self.logger.error(f"Kline veri hatası ({symbol}): {e}")
            return None

    async def analyze_opportunity(self, symbol: str, current_price: float, volume: float, interval: str = "4h") -> dict:
        """Fırsat analizi yap"""
        try:
            klines = await self.get_klines_data(symbol, interval)
            if not klines or len(klines) < 100:
                return None

            closes = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])
            highs = np.array([float(k[2]) for k in klines])
            lows = np.array([float(k[3]) for k in klines])

            rsi = self.ta.calculate_rsi(closes)
            macd_line, signal_line, hist = self.ta.calculate_macd(closes)
            upper, middle, lower = self.ta.calculate_bollinger_bands(closes)
            
            # ... diğer hesaplamalar ve skor mantığı ...
            
            return {
                'symbol': symbol,
                'price': current_price,
                'rsi': float(rsi),
                'macd': float(hist),
                'trend': trend,
                'opportunity_score': float(score),
                'signal': "🟢 AL" if score > 85 else "🟡 İZLE" if score > 75 else "🔴 BEKLE"
            }

        except Exception as e:
            self.logger.error(f"Analiz hatası ({symbol}): {e}")
            return None 