import numpy as np
import pandas as pd

class Indicators:
    @staticmethod
    def rsi(prices: np.ndarray, period: int = 14) -> float:
        deltas = np.diff(prices)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum()/period
        down = -seed[seed < 0].sum()/period
        rs = up/down if down != 0 else 0
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(prices: np.ndarray) -> tuple:
        prices_pd = pd.Series(prices)
        exp1 = prices_pd.ewm(span=12, adjust=False).mean()
        exp2 = prices_pd.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        return float(macd.iloc[-1]), float(signal.iloc[-1])

    @staticmethod
    def ema(prices: np.ndarray, period: int) -> float:
        return float(pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]) 