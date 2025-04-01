import numpy as np
import pandas as pd

class TechnicalAnalysis:
    @staticmethod
    def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
        """RSI hesapla"""
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

    @staticmethod
    def calculate_macd(prices: np.ndarray) -> tuple:
        """MACD hesapla"""
        prices_pd = pd.Series(prices)
        exp1 = prices_pd.ewm(span=12, adjust=False).mean()
        exp2 = prices_pd.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])

    @staticmethod
    def calculate_bollinger_bands(prices: np.ndarray, period: int = 20) -> tuple:
        """Bollinger Bands hesapla"""
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        return upper, sma, lower

    @staticmethod
    def calculate_ema(prices: np.ndarray, period: int) -> np.ndarray:
        """EMA hesapla"""
        prices_pd = pd.Series(prices)
        ema = prices_pd.ewm(span=period, adjust=False).mean()
        return ema.to_numpy() 