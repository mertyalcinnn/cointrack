import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


class CandlestickPatternRecognizer:
    """Mum formasyonlarını tanıma ve analiz etme sınıfı"""
    
    def __init__(self):
        self.pattern_descriptions = {
            'hammer': 'Alt gölgesi uzun, üst gölgesi kısa, küçük gövdeli mum. Düşüş trendinin sonunu işaret edebilir.',
            'inverted_hammer': 'Üst gölgesi uzun, alt gölgesi kısa, küçük gövdeli mum. Düşüş trendinin sonunu işaret edebilir.',
            'shooting_star': 'Üst gölgesi uzun, alt gölgesi kısa, küçük gövdeli mum. Yükseliş trendinin sonunu işaret edebilir.',
            'hanging_man': 'Alt gölgesi uzun, üst gölgesi kısa, küçük gövdeli mum. Yükseliş trendinin sonunu işaret edebilir.',
            'bullish_engulfing': 'Önceki kırmızı mumu tamamen içine alan yeşil mum. Güçlü alış sinyali verebilir.',
            'bearish_engulfing': 'Önceki yeşil mumu tamamen içine alan kırmızı mum. Güçlü satış sinyali verebilir.',
            'doji': 'Açılış ve kapanışın neredeyse aynı olduğu, trend değişimini işaret edebilen mum.',
            'morning_star': 'Düşüş trendinden sonra gelen doji ve sonrasında güçlü yeşil mum. Güçlü alış sinyali.',
            'evening_star': 'Yükseliş trendinden sonra gelen doji ve sonrasında güçlü kırmızı mum. Güçlü satış sinyali.',
            'three_white_soldiers': 'Üst üste gelen üç uzun yeşil mum. Güçlü yükseliş trendi başlangıcı.',
            'three_black_crows': 'Üst üste gelen üç uzun kırmızı mum. Güçlü düşüş trendi başlangıcı.'
        }
    
    def recognize_patterns(self, df: pd.DataFrame) -> Dict[str, List[int]]:
        """
        Verilen veri çerçevesindeki mum formasyonlarını tanır
        
        Args:
            df: OHLCV verileri içeren DataFrame ('open', 'high', 'low', 'close', 'volume' sütunları gerekli)
            
        Returns:
            Dict[str, List[int]]: {formasyon_adı: [index_listesi]} formatında sonuçlar
        """
        if len(df) < 5:
            return {}
            
        # Gövde ve gölge hesaplamaları
        df = df.copy()
        df['body'] = abs(df['close'] - df['open'])
        df['body_pct'] = df['body'] / (df['high'] - df['low']) * 100
        df['upper_shadow'] = df.apply(lambda x: x['high'] - max(x['open'], x['close']), axis=1)
        df['lower_shadow'] = df.apply(lambda x: min(x['open'], x['close']) - x['low'], axis=1)
        df['is_bullish'] = df['close'] > df['open']
        
        patterns = {}
        
        # Doji tanıma
        patterns['doji'] = self._find_doji(df)
        
        # Hammer ve Inverted Hammer
        patterns['hammer'] = self._find_hammer(df)
        patterns['inverted_hammer'] = self._find_inverted_hammer(df)
        
        # Shooting Star ve Hanging Man
        patterns['shooting_star'] = self._find_shooting_star(df)
        patterns['hanging_man'] = self._find_hanging_man(df)
        
        # Engulfing formasyonları
        patterns['bullish_engulfing'] = self._find_bullish_engulfing(df)
        patterns['bearish_engulfing'] = self._find_bearish_engulfing(df)
        
        # Morning Star ve Evening Star
        patterns['morning_star'] = self._find_morning_star(df)
        patterns['evening_star'] = self._find_evening_star(df)
        
        # Three White Soldiers ve Three Black Crows
        patterns['three_white_soldiers'] = self._find_three_white_soldiers(df)
        patterns['three_black_crows'] = self._find_three_black_crows(df)
        
        return {k: v for k, v in patterns.items() if v}  # Boş listeleri kaldır
    
    def analyze_recent_patterns(self, df: pd.DataFrame, n_candles: int = 5) -> Dict:
        """
        Son n mum içindeki formasyonları analiz eder
        
        Args:
            df: OHLCV verileri içeren DataFrame
            n_candles: Analiz edilecek son mum sayısı
            
        Returns:
            Dict: Analize dair sonuçlar
        """
        if len(df) < n_candles:
            return {'patterns': [], 'signal': 'NEUTRAL', 'confidence': 0}
        
        # Son n mumu analiz et
        recent_df = df.iloc[-n_candles:]
        patterns = self.recognize_patterns(recent_df)
        
        # Boş dönüş kontrolü
        if not patterns:
            return {'patterns': [], 'signal': 'NEUTRAL', 'confidence': 0}
        
        # Sinyal ve güven puanı hesapla
        bullish_patterns = ['hammer', 'inverted_hammer', 'bullish_engulfing', 'morning_star', 'three_white_soldiers']
        bearish_patterns = ['shooting_star', 'hanging_man', 'bearish_engulfing', 'evening_star', 'three_black_crows']
        
        bullish_score = 0
        bearish_score = 0
        detected_patterns = []
        
        for pattern, indices in patterns.items():
            # Sadece son 3 mum içinde olan formasyonları değerlendir
            recent_indices = [i for i in indices if i >= len(recent_df) - 3]
            
            if not recent_indices:
                continue
                
            detected_patterns.append({
                'name': pattern,
                'description': self.pattern_descriptions.get(pattern, ''),
                'index': recent_indices[-1]  # En son oluşan formasyonu al
            })
            
            # Formasyona göre puan ekle
            if pattern in bullish_patterns:
                bullish_score += 1 if pattern not in ['morning_star', 'three_white_soldiers'] else 2
            elif pattern in bearish_patterns:
                bearish_score += 1 if pattern not in ['evening_star', 'three_black_crows'] else 2
        
        # Sinyal belirle
        signal = 'NEUTRAL'
        confidence = 0
        
        if bullish_score > bearish_score:
            signal = 'BULLISH'
            confidence = min(100, bullish_score * 25)
        elif bearish_score > bullish_score:
            signal = 'BEARISH'
            confidence = min(100, bearish_score * 25)
            
        return {
            'patterns': detected_patterns,
            'signal': signal,
            'confidence': confidence
        }
    
    def _find_doji(self, df: pd.DataFrame) -> List[int]:
        """Doji formasyonlarını bulur"""
        doji_indices = []
        for i in range(len(df)):
            if df['body_pct'].iloc[i] < 5:  # Gövde çok küçük
                if df['upper_shadow'].iloc[i] > 0 and df['lower_shadow'].iloc[i] > 0:
                    doji_indices.append(i)
        return doji_indices
    
    def _find_hammer(self, df: pd.DataFrame) -> List[int]:
        """Hammer formasyonlarını bulur"""
        hammer_indices = []
        for i in range(4, len(df)):
            # Öncesinde düşüş trendi olmalı
            if not self._is_downtrend(df, i, window=4):
                continue
                
            current = df.iloc[i]
            if (current['lower_shadow'] > 2 * current['body'] and  # Alt gölge gövdenin 2 katından uzun
                current['upper_shadow'] < 0.3 * current['body'] and  # Üst gölge çok kısa
                current['body_pct'] < 40):  # Gövde çok büyük değil
                hammer_indices.append(i)
        return hammer_indices
    
    def _find_inverted_hammer(self, df: pd.DataFrame) -> List[int]:
        """Inverted Hammer formasyonlarını bulur"""
        inv_hammer_indices = []
        for i in range(4, len(df)):
            # Öncesinde düşüş trendi olmalı
            if not self._is_downtrend(df, i, window=4):
                continue
                
            current = df.iloc[i]
            if (current['upper_shadow'] > 2 * current['body'] and  # Üst gölge gövdenin 2 katından uzun
                current['lower_shadow'] < 0.3 * current['body'] and  # Alt gölge çok kısa
                current['body_pct'] < 40):  # Gövde çok büyük değil
                inv_hammer_indices.append(i)
        return inv_hammer_indices
    
    def _find_shooting_star(self, df: pd.DataFrame) -> List[int]:
        """Shooting Star formasyonlarını bulur"""
        shooting_star_indices = []
        for i in range(4, len(df)):
            # Öncesinde yükseliş trendi olmalı
            if not self._is_uptrend(df, i, window=4):
                continue
                
            current = df.iloc[i]
            if (current['upper_shadow'] > 2 * current['body'] and  # Üst gölge gövdenin 2 katından uzun
                current['lower_shadow'] < 0.3 * current['body'] and  # Alt gölge çok kısa
                current['body_pct'] < 40):  # Gövde çok büyük değil
                shooting_star_indices.append(i)
        return shooting_star_indices
    
    def _find_hanging_man(self, df: pd.DataFrame) -> List[int]:
        """Hanging Man formasyonlarını bulur"""
        hanging_man_indices = []
        for i in range(4, len(df)):
            # Öncesinde yükseliş trendi olmalı
            if not self._is_uptrend(df, i, window=4):
                continue
                
            current = df.iloc[i]
            if (current['lower_shadow'] > 2 * current['body'] and  # Alt gölge gövdenin 2 katından uzun
                current['upper_shadow'] < 0.3 * current['body'] and  # Üst gölge çok kısa
                current['body_pct'] < 40):  # Gövde çok büyük değil
                hanging_man_indices.append(i)
        return hanging_man_indices
    
    def _find_bullish_engulfing(self, df: pd.DataFrame) -> List[int]:
        """Bullish Engulfing formasyonlarını bulur"""
        bullish_engulfing_indices = []
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            current = df.iloc[i]
            
            if (not prev['is_bullish'] and current['is_bullish'] and  # Önceki kırmızı, şimdiki yeşil
                current['open'] < prev['close'] and  # Şimdiki açılış önceki kapanışın altında
                current['close'] > prev['open']):  # Şimdiki kapanış önceki açılışın üstünde
                bullish_engulfing_indices.append(i)
        return bullish_engulfing_indices
    
    def _find_bearish_engulfing(self, df: pd.DataFrame) -> List[int]:
        """Bearish Engulfing formasyonlarını bulur"""
        bearish_engulfing_indices = []
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            current = df.iloc[i]
            
            if (prev['is_bullish'] and not current['is_bullish'] and  # Önceki yeşil, şimdiki kırmızı
                current['open'] > prev['close'] and  # Şimdiki açılış önceki kapanışın üstünde
                current['close'] < prev['open']):  # Şimdiki kapanış önceki açılışın altında
                bearish_engulfing_indices.append(i)
        return bearish_engulfing_indices
    
    def _find_morning_star(self, df: pd.DataFrame) -> List[int]:
        """Morning Star formasyonunu bulur"""
        morning_star_indices = []
        for i in range(4, len(df) - 2):
            # En az 3 mum gerekiyor
            if i + 2 >= len(df):
                continue
                
            # Öncesinde düşüş trendi olmalı
            if not self._is_downtrend(df, i, window=4):
                continue
                
            first = df.iloc[i]
            middle = df.iloc[i+1]
            last = df.iloc[i+2]
            
            if (not first['is_bullish'] and  # İlk mum kırmızı
                middle['body_pct'] < 10 and  # Orta mum küçük gövdeli (doji benzeri)
                last['is_bullish'] and  # Son mum yeşil
                last['close'] > (first['open'] + first['close']) / 2):  # Son mum ilk mumun ortasını geçiyor
                morning_star_indices.append(i)
        return morning_star_indices
    
    def _find_evening_star(self, df: pd.DataFrame) -> List[int]:
        """Evening Star formasyonunu bulur"""
        evening_star_indices = []
        for i in range(4, len(df) - 2):
            # En az 3 mum gerekiyor
            if i + 2 >= len(df):
                continue
                
            # Öncesinde yükseliş trendi olmalı
            if not self._is_uptrend(df, i, window=4):
                continue
                
            first = df.iloc[i]
            middle = df.iloc[i+1]
            last = df.iloc[i+2]
            
            if (first['is_bullish'] and  # İlk mum yeşil
                middle['body_pct'] < 10 and  # Orta mum küçük gövdeli (doji benzeri)
                not last['is_bullish'] and  # Son mum kırmızı
                last['close'] < (first['open'] + first['close']) / 2):  # Son mum ilk mumun ortasının altında
                evening_star_indices.append(i)
        return evening_star_indices
    
    def _find_three_white_soldiers(self, df: pd.DataFrame) -> List[int]:
        """Three White Soldiers formasyonunu bulur"""
        three_white_indices = []
        for i in range(len(df) - 3):
            # En az 3 mum gerekiyor
            if i + 2 >= len(df):
                continue
                
            first = df.iloc[i]
            second = df.iloc[i+1]
            third = df.iloc[i+2]
            
            if (first['is_bullish'] and second['is_bullish'] and third['is_bullish'] and  # Üç mum da yeşil
                second['close'] > first['close'] and third['close'] > second['close'] and  # Her mum bir öncekinden yüksek kapanıyor
                second['open'] > first['open'] and third['open'] > second['open']):  # Her mum bir öncekinden yüksek açılıyor
                three_white_indices.append(i)
        return three_white_indices
    
    def _find_three_black_crows(self, df: pd.DataFrame) -> List[int]:
        """Three Black Crows formasyonunu bulur"""
        three_black_indices = []
        for i in range(len(df) - 3):
            # En az 3 mum gerekiyor
            if i + 2 >= len(df):
                continue
                
            first = df.iloc[i]
            second = df.iloc[i+1]
            third = df.iloc[i+2]
            
            if (not first['is_bullish'] and not second['is_bullish'] and not third['is_bullish'] and  # Üç mum da kırmızı
                second['close'] < first['close'] and third['close'] < second['close'] and  # Her mum bir öncekinden düşük kapanıyor
                second['open'] < first['open'] and third['open'] < second['open']):  # Her mum bir öncekinden düşük açılıyor
                three_black_indices.append(i)
        return three_black_indices
    
    def _is_uptrend(self, df: pd.DataFrame, idx: int, window: int = 4) -> bool:
        """Belirli bir pozisyonda yükseliş trendi olup olmadığını kontrol eder"""
        if idx < window:
            return False
            
        # Son window kadar mumun kapanış fiyatlarını kontrol et
        closes = df['close'].iloc[idx-window:idx].values
        return closes[-1] > closes[0] and np.polyfit(range(len(closes)), closes, 1)[0] > 0
    
    def _is_downtrend(self, df: pd.DataFrame, idx: int, window: int = 4) -> bool:
        """Belirli bir pozisyonda düşüş trendi olup olmadığını kontrol eder"""
        if idx < window:
            return False
            
        # Son window kadar mumun kapanış fiyatlarını kontrol et
        closes = df['close'].iloc[idx-window:idx].values
        return closes[-1] < closes[0] and np.polyfit(range(len(closes)), closes, 1)[0] < 0


# Kullanım örneği
def analyze_chart(df, timeframe):
    pattern_recognizer = CandlestickPatternRecognizer()
    pattern_analysis = pattern_recognizer.analyze_recent_patterns(df)
    
    result = {
        'timeframe': timeframe,
        'candlestick_patterns': pattern_analysis['patterns'],
        'pattern_signal': pattern_analysis['signal'],
        'pattern_confidence': pattern_analysis['confidence']
    }
    
    return result 