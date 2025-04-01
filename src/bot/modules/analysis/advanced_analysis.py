import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

class SignalStrength(Enum):
    CRITICAL = "KRİTİK"
    MEDIUM = "ORTA"
    LOW = "DÜŞÜK"

@dataclass
class SignalHistory:
    timestamp: datetime
    signal_type: str
    entry_price: float
    exit_price: float = 0
    success: bool = False
    profit_loss: float = 0

class AdvancedAnalyzer:
    def __init__(self):
        self.signal_history = {}  # {symbol: List[SignalHistory]}
        self.success_rates = {}   # {symbol: {'buy': float, 'sell': float}}
        
    def calculate_fibonacci_levels(self, high: float, low: float) -> Dict[str, float]:
        """Fibonacci seviyeleri hesapla"""
        diff = high - low
        return {
            'Extension 1.618': high + (diff * 0.618),
            'Extension 1.0': high,
            'Retracement 0.786': high - (diff * 0.786),
            'Retracement 0.618': high - (diff * 0.618),
            'Retracement 0.5': high - (diff * 0.5),
            'Retracement 0.382': high - (diff * 0.382),
            'Retracement 0.236': high - (diff * 0.236),
            'Extension 0.0': low
        }

    def find_support_resistance(self, prices: np.ndarray, window: int = 20) -> Tuple[List[float], List[float]]:
        """Destek ve direnç seviyelerini bul"""
        supports = []
        resistances = []
        
        # Yerel minimum ve maksimumları bul
        for i in range(window, len(prices) - window):
            if self._is_support(prices, i, window):
                supports.append(prices[i])
            elif self._is_resistance(prices, i, window):
                resistances.append(prices[i])
        
        # Yakın seviyeleri birleştir
        supports = self._consolidate_levels(supports)
        resistances = self._consolidate_levels(resistances)
        
        return supports, resistances

    def validate_signal(self, indicators: Dict) -> Tuple[bool, str, SignalStrength]:
        """Sinyal doğrulama"""
        confirmations = 0
        reasons = []
        
        # RSI Kontrolü
        if indicators['rsi'] < 30:
            confirmations += 1
            reasons.append("RSI aşırı satım")
        elif indicators['rsi'] > 70:
            confirmations -= 1
            reasons.append("RSI aşırı alım")
            
        # MACD Kontrolü
        if indicators['macd'] > 0 and indicators['macd_hist'] > 0:
            confirmations += 1
            reasons.append("MACD pozitif")
        elif indicators['macd'] < 0 and indicators['macd_hist'] < 0:
            confirmations -= 1
            reasons.append("MACD negatif")
            
        # Bollinger Kontrolü
        bb_position = (indicators['price'] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower'])
        if bb_position < 0.2:
            confirmations += 1
            reasons.append("BB alt bandına yakın")
        elif bb_position > 0.8:
            confirmations -= 1
            reasons.append("BB üst bandına yakın")
            
        # EMA Trend Kontrolü
        if indicators['ema20'] > indicators['ema50']:
            confirmations += 1
            reasons.append("EMA trend yukarı")
        else:
            confirmations -= 1
            reasons.append("EMA trend aşağı")

        # Sinyal gücünü belirle
        strength = SignalStrength.LOW
        if abs(confirmations) >= 3:
            strength = SignalStrength.CRITICAL
        elif abs(confirmations) >= 2:
            strength = SignalStrength.MEDIUM

        is_valid = confirmations >= 2
        reason_text = ", ".join(reasons)
        
        return is_valid, reason_text, strength

    def calculate_position_size(self, 
                              capital: float,
                              risk_percentage: float,
                              entry_price: float,
                              stop_loss: float) -> Dict:
        """Pozisyon büyüklüğü hesapla"""
        risk_amount = capital * (risk_percentage / 100)
        price_diff = abs(entry_price - stop_loss)
        position_size = risk_amount / price_diff
        
        return {
            'position_size': position_size,
            'risk_amount': risk_amount,
            'max_loss': risk_amount,
            'recommended_capital': capital * 0.1  # Maksimum %10 kullan
        }

    def calculate_exit_points(self, 
                            entry_price: float,
                            atr: float,
                            fibonacci_levels: Dict[str, float]) -> Dict:
        """Stop-loss ve take-profit seviyeleri hesapla"""
        # ATR bazlı stop-loss
        stop_loss = entry_price - (atr * 2)
        
        # Fibonacci bazlı take-profit seviyeleri
        take_profit_1 = fibonacci_levels['Retracement 0.382']
        take_profit_2 = fibonacci_levels['Retracement 0.618']
        take_profit_3 = fibonacci_levels['Extension 1.618']
        
        return {
            'stop_loss': stop_loss,
            'take_profit_1': take_profit_1,
            'take_profit_2': take_profit_2,
            'take_profit_3': take_profit_3,
            'risk_reward_1': (take_profit_1 - entry_price) / (entry_price - stop_loss),
            'risk_reward_2': (take_profit_2 - entry_price) / (entry_price - stop_loss),
            'risk_reward_3': (take_profit_3 - entry_price) / (entry_price - stop_loss)
        }

    def _is_support(self, prices: np.ndarray, index: int, window: int) -> bool:
        """Destek seviyesi kontrolü"""
        return all(prices[index] <= prices[i] for i in range(index - window, index + window + 1))

    def _is_resistance(self, prices: np.ndarray, index: int, window: int) -> bool:
        """Direnç seviyesi kontrolü"""
        return all(prices[index] >= prices[i] for i in range(index - window, index + window + 1))

    def _consolidate_levels(self, levels: List[float], threshold: float = 0.02) -> List[float]:
        """Yakın seviyeleri birleştir"""
        if not levels:
            return []
            
        levels = sorted(levels)
        consolidated = [levels[0]]
        
        for level in levels[1:]:
            if abs(level - consolidated[-1]) / consolidated[-1] > threshold:
                consolidated.append(level)
                
        return consolidated

    def update_signal_history(self, symbol: str, signal: SignalHistory):
        """Sinyal geçmişini güncelle"""
        if symbol not in self.signal_history:
            self.signal_history[symbol] = []
        self.signal_history[symbol].append(signal)
        self._update_success_rate(symbol)

    def _update_success_rate(self, symbol: str):
        """Başarı oranını güncelle"""
        if symbol not in self.signal_history:
            return
            
        signals = self.signal_history[symbol]
        buy_signals = [s for s in signals if s.signal_type == 'BUY' and s.success is not None]
        sell_signals = [s for s in signals if s.signal_type == 'SELL' and s.success is not None]
        
        self.success_rates[symbol] = {
            'buy': sum(1 for s in buy_signals if s.success) / len(buy_signals) if buy_signals else 0,
            'sell': sum(1 for s in sell_signals if s.success) / len(sell_signals) if sell_signals else 0
        } 