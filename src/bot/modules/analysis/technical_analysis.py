import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
import aiohttp

class TechnicalAnalysis:
    def __init__(self, logger=None):
        self.logger = logger
    
    def calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """RSI hesapla"""
        try:
            deltas = np.diff(prices)
            seed = deltas[:period+1]
            up = seed[seed >= 0].sum()/period
            down = -seed[seed < 0].sum()/period
            rs = up/down if down != 0 else 0
            rsi = np.zeros_like(prices)
            rsi[:period] = 100. - 100./(1.+rs)

            for i in range(period, len(prices)):
                delta = deltas[i-1]
                if delta > 0:
                    upval = delta
                    downval = 0.
                else:
                    upval = 0.
                    downval = -delta

                up = (up*(period-1) + upval)/period
                down = (down*(period-1) + downval)/period
                rs = up/down if down != 0 else 0
                rsi[i] = 100. - 100./(1.+rs)

            return rsi[-1]
        except Exception as e:
            if self.logger:
                self.logger.error(f"RSI hesaplama hatası: {e}")
            return 50.0  # Hata durumunda nötr değer

    def calculate_macd(self, prices: np.ndarray) -> tuple:
        """MACD hesapla"""
        try:
            # Numpy array'i pandas Series'e çevir
            prices_pd = pd.Series(prices)
            
            # MACD hesapla
            exp1 = prices_pd.ewm(span=12, adjust=False).mean()
            exp2 = prices_pd.ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            hist = macd - signal
            
            # Son değerleri al
            return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])
        except Exception as e:
            if self.logger:
                self.logger.error(f"MACD hesaplama hatası: {e}")
            return 0.0, 0.0, 0.0  # Hata durumunda nötr değerler

    def calculate_bollinger_bands(self, prices: np.ndarray, period: int = 20) -> tuple:
        """Bollinger Bands hesapla"""
        try:
            sma = np.mean(prices[-period:])
            std = np.std(prices[-period:])
            upper = sma + (std * 2)
            lower = sma - (std * 2)
            return upper, sma, lower
        except Exception as e:
            if self.logger:
                self.logger.error(f"Bollinger Bands hesaplama hatası: {e}")
            # Hata durumunda yaklaşık değerler
            avg = np.mean(prices) if len(prices) > 0 else 0
            return avg * 1.02, avg, avg * 0.98

    def calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """EMA hesapla"""
        try:
            # Numpy array'i pandas Series'e çevir
            prices_pd = pd.Series(prices)
            
            # EMA hesapla ve numpy array'e geri çevir
            ema = prices_pd.ewm(span=period, adjust=False).mean()
            return ema.to_numpy()
        except Exception as e:
            if self.logger:
                self.logger.error(f"EMA hesaplama hatası: {e}")
            return prices  # Hata durumunda orijinal fiyatları döndür

class MarketDataProvider:
    def __init__(self, logger=None):
        self.logger = logger
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
                
                if self.logger:
                    self.logger.debug(f"📡 API isteği: {url}?symbol={symbol}&interval={interval}&limit=100")
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            if self.logger:
                                self.logger.debug(f"✅ {symbol} için {len(data)} kline verisi alındı")
                            return data
                        else:
                            if self.logger:
                                self.logger.error(f"❌ {symbol} için veri bulunamadı")
                            return None
                    else:
                        response_text = await response.text()
                        if self.logger:
                            self.logger.error(f"❌ API Hatası: Status {response.status}, Response: {response_text}")
                        return None
                    
        except aiohttp.ClientError as e:
            if self.logger:
                self.logger.error(f"❌ Bağlantı hatası ({symbol}): {e}")
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"❌ Beklenmeyen hata ({symbol}): {e}")
            return None 