import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional


class VolatilityBasedStopCalculator:
    """Volatilite bazlı stop-loss ve take-profit hesaplama sınıfı"""
    
    def __init__(self):
        self.atr_periods = 14
        self.fast_atr_periods = 5
        self.rsi_periods = 14
        self.volatility_multipliers = {
            'low': 1.5,
            'medium': 2.0,
            'high': 2.5,
            'extreme': 3.0
        }
    
    def calculate_atr(self, df: pd.DataFrame, periods: int = 14) -> pd.Series:
        """
        Average True Range (ATR) hesaplar
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            periods: ATR periyodu
            
        Returns:
            pd.Series: ATR değerleri
        """
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        
        # True Range hesapla
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        
        true_range = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        
        # ATR hesapla
        atr = true_range.rolling(window=periods).mean()
        return atr
    
    def calculate_volatility_stops(self, df: pd.DataFrame, risk_level: str = 'medium') -> Dict:
        """
        Volatilite bazlı stop-loss ve take-profit seviyelerini hesaplar
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            risk_level: Risk seviyesi ('low', 'medium', 'high', 'extreme')
            
        Returns:
            Dict: Stop-loss ve take-profit seviyeleri
        """
        if len(df) < self.atr_periods:
            return {
                'stop_loss': None,
                'take_profit1': None,
                'take_profit2': None,
                'risk_reward_ratio': None,
                'atr': None,
                'volatility_pct': None
            }
            
        # ATR hesapla
        atr = self.calculate_atr(df, self.atr_periods)
        
        # Hızlı ATR (daha yakın dönem volatilite)
        fast_atr = self.calculate_atr(df, self.fast_atr_periods)
        
        # Son değerleri al
        current_price = df['close'].iloc[-1]
        current_atr = atr.iloc[-1]
        current_fast_atr = fast_atr.iloc[-1]
        
        # Volatilite yüzdesi
        volatility_pct = (current_atr / current_price) * 100
        
        # RSI Hesapla (volatiliteyi ayarlamak için)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_periods).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_periods).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        # Trend yönünü belirle
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema21 = df['close'].ewm(span=21, adjust=False).mean()
        
        if ema9.iloc[-1] > ema21.iloc[-1]:
            trend = 'LONG'
        else:
            trend = 'SHORT'
        
        # Volatilite çarpanını seç
        multiplier = self.volatility_multipliers.get(risk_level, 2.0)
        
        # RSI bazlı volatilite ayarı
        # RSI aşırı seviyelerdeyse, volatilite çarpanını arttır
        if current_rsi > 70 or current_rsi < 30:
            multiplier *= 1.2
        
        # Kısa dönem volatilite uzun dönemden yüksekse, çarpanı arttır
        if current_fast_atr > current_atr * 1.5:
            multiplier *= 1.1
        
        # Stop-loss ve take-profit hesapla
        if trend == 'LONG':
            stop_loss = current_price - (current_atr * multiplier)
            take_profit1 = current_price + (current_atr * multiplier)
            take_profit2 = current_price + (current_atr * multiplier * 2)
        else:
            stop_loss = current_price + (current_atr * multiplier)
            take_profit1 = current_price - (current_atr * multiplier)
            take_profit2 = current_price - (current_atr * multiplier * 2)
        
        # Risk-ödül oranı
        if trend == 'LONG':
            risk = current_price - stop_loss
            reward = take_profit1 - current_price
        else:
            risk = stop_loss - current_price
            reward = current_price - take_profit1
            
        risk_reward_ratio = abs(reward / risk) if risk != 0 else 0
        
        return {
            'trend': trend,
            'stop_loss': round(stop_loss, 8),
            'take_profit1': round(take_profit1, 8),
            'take_profit2': round(take_profit2, 8),
            'risk_reward_ratio': round(risk_reward_ratio, 2),
            'atr': round(current_atr, 8),
            'fast_atr': round(current_fast_atr, 8),
            'volatility_pct': round(volatility_pct, 2)
        }
    
    def calculate_trailing_stop(self, df: pd.DataFrame, risk_level: str = 'medium') -> Dict:
        """
        Hareketli (trailing) stop-loss seviyelerini hesaplar
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            risk_level: Risk seviyesi ('low', 'medium', 'high', 'extreme')
            
        Returns:
            Dict: Trailing stop ve ilgili bilgiler
        """
        if len(df) < self.atr_periods:
            return {'trailing_stop': None}
            
        # Stop hesapla
        stops = self.calculate_volatility_stops(df, risk_level)
        
        # Trend yönü
        trend = stops.get('trend', 'LONG')
        
        # Hareketli stop için ek hesaplamalar
        highs = df['high'].rolling(window=5).max()
        lows = df['low'].rolling(window=5).min()
        
        current_price = df['close'].iloc[-1]
        current_high = highs.iloc[-1]
        current_low = lows.iloc[-1]
        current_atr = stops.get('atr', 0)
        
        # Volatilite çarpanını seç
        multiplier = self.volatility_multipliers.get(risk_level, 2.0)
        
        # Trailing stop hesapla
        if trend == 'LONG':
            # Long pozisyonda, en yüksek seviyenin altında bir trailing stop
            trailing_stop = current_high - (current_atr * multiplier * 0.8)
            
            # Mevcut stop-loss ile karşılaştır ve yüksek olanı al
            trailing_stop = max(trailing_stop, stops.get('stop_loss', 0))
            
            # Aktif edilme koşulu
            activation_pct = ((current_price - stops.get('stop_loss', 0)) / 
                             (stops.get('take_profit1', current_price) - stops.get('stop_loss', 0))) * 100
        else:
            # Short pozisyonda, en düşük seviyenin üstünde bir trailing stop
            trailing_stop = current_low + (current_atr * multiplier * 0.8)
            
            # Mevcut stop-loss ile karşılaştır ve düşük olanı al
            trailing_stop = min(trailing_stop, stops.get('stop_loss', 0))
            
            # Aktif edilme koşulu
            activation_pct = ((stops.get('stop_loss', 0) - current_price) / 
                             (stops.get('stop_loss', 0) - stops.get('take_profit1', current_price))) * 100
        
        # Aktivasyon durumu
        is_active = activation_pct >= 30  # Kar %30'a ulaştığında aktif et
        
        return {
            'trailing_stop': round(trailing_stop, 8),
            'activation_pct': round(activation_pct, 2),
            'is_active': is_active,
            'trend': trend
        }
    
    def suggest_position_size(self, 
                            account_balance: float,
                            current_price: float,
                            stop_price: float,
                            risk_percentage: float = 1.0) -> Dict:
        """
        Risk yönetimi için uygun pozisyon büyüklüğü önerir
        
        Args:
            account_balance: Toplam hesap bakiyesi
            current_price: Mevcut fiyat
            stop_price: Stop-loss fiyatı
            risk_percentage: Riske edilecek hesap yüzdesi
            
        Returns:
            Dict: Önerilen pozisyon bilgileri
        """
        # Riske edilecek miktar
        risk_amount = account_balance * (risk_percentage / 100)
        
        # Stop-loss mesafesi
        stop_distance = abs(current_price - stop_price)
        stop_distance_pct = (stop_distance / current_price) * 100
        
        # Pozisyon büyüklüğü hesapla
        position_size = risk_amount / stop_distance
        position_value = position_size * current_price
        
        # Kaldıraç önerisi
        leverage_suggestion = 1
        
        if stop_distance_pct < 0.5:
            leverage_suggestion = 5
        elif stop_distance_pct < 1:
            leverage_suggestion = 3
        elif stop_distance_pct < 2:
            leverage_suggestion = 2
        
        # Kaldıraçlı pozisyon hesapla
        leverage_position_value = position_value * leverage_suggestion
        
        return {
            'risk_amount': round(risk_amount, 2),
            'stop_distance_pct': round(stop_distance_pct, 2),
            'position_size': round(position_size, 8),
            'position_value': round(position_value, 2),
            'leverage_suggestion': leverage_suggestion,
            'leveraged_position_value': round(leverage_position_value, 2)
        }


# Kullanım örneği
def calculate_volatility_based_stops(df, risk_level='medium'):
    calculator = VolatilityBasedStopCalculator()
    stops = calculator.calculate_volatility_stops(df, risk_level)
    trailing = calculator.calculate_trailing_stop(df, risk_level)
    
    result = {
        'stop_loss': stops['stop_loss'],
        'take_profit1': stops['take_profit1'],
        'take_profit2': stops['take_profit2'],
        'trailing_stop': trailing['trailing_stop'],
        'risk_reward_ratio': stops['risk_reward_ratio'],
        'volatility_pct': stops['volatility_pct'],
        'trend': stops['trend']
    }
    
    return result 