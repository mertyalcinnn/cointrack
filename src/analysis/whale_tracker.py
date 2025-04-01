from typing import Dict, List
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import ccxt

class WhaleTracker:
    def __init__(self):
        self.exchange = ccxt.binance()
        self.whale_threshold = 100000  # USDT cinsinden balina işlem eşiği
        self.volume_threshold = 1.5    # Normal hacmin x katı
        
    async def analyze_whale_activity(self, symbol: str) -> Dict:
        """Balina aktivitelerini analiz et"""
        try:
            # Son işlemleri al
            trades = self.exchange.fetch_trades(symbol, limit=1000)
            
            # İşlemleri DataFrame'e dönüştür
            df = pd.DataFrame(trades, columns=['timestamp', 'price', 'amount', 'side'])
            df['value'] = df['price'] * df['amount']
            
            # Büyük işlemleri filtrele
            whale_trades = df[df['value'] >= self.whale_threshold]
            
            # Son 24 saatteki balina işlemleri
            recent_whales = whale_trades[
                whale_trades['timestamp'] >= (datetime.now() - timedelta(hours=24)).timestamp() * 1000
            ]
            
            # Alış/Satış oranı
            buy_volume = recent_whales[recent_whales['side'] == 'buy']['value'].sum()
            sell_volume = recent_whales[recent_whales['side'] == 'sell']['value'].sum()
            
            # Hacim analizi
            volume_analysis = self._analyze_volume_patterns(df)
            
            # Baskı analizi
            pressure_analysis = self._analyze_price_pressure(recent_whales, df['price'].iloc[-1])
            
            # Akümülasyon/Distribüsyon analizi
            accumulation = self._analyze_accumulation(df)
            
            return {
                'whale_count': len(recent_whales),
                'total_whale_volume': buy_volume + sell_volume,
                'buy_sell_ratio': buy_volume / sell_volume if sell_volume > 0 else float('inf'),
                'volume_analysis': volume_analysis,
                'pressure': pressure_analysis,
                'accumulation': accumulation,
                'recent_moves': self._get_recent_whale_moves(recent_whales),
                'alert_level': self._calculate_alert_level(
                    pressure_analysis, 
                    accumulation,
                    buy_volume / (buy_volume + sell_volume) if (buy_volume + sell_volume) > 0 else 0
                )
            }
            
        except Exception as e:
            print(f"Balina analizi hatası: {str(e)}")
            return {'error': str(e)}

    def _analyze_volume_patterns(self, df: pd.DataFrame) -> Dict:
        """Hacim paternlerini analiz et"""
        try:
            # Ortalama hacim
            avg_volume = df['value'].mean()
            recent_volume = df['value'].iloc[-10:].mean()
            
            # Hacim artışlarını tespit et
            volume_spikes = df[df['value'] >= (avg_volume * self.volume_threshold)]
            
            return {
                'volume_trend': 'INCREASING' if recent_volume > avg_volume else 'DECREASING',
                'spike_count': len(volume_spikes),
                'avg_spike_size': volume_spikes['value'].mean() if len(volume_spikes) > 0 else 0,
                'unusual_activity': recent_volume >= (avg_volume * self.volume_threshold)
            }
        except Exception as e:
            return {'error': str(e)}

    def _analyze_price_pressure(self, whale_trades: pd.DataFrame, current_price: float) -> Dict:
        """Fiyat baskısını analiz et"""
        try:
            if len(whale_trades) == 0:
                return {'pressure': 'NEUTRAL', 'strength': 0}
            
            # Son işlemlerin yönünü analiz et
            recent_pressure = whale_trades.iloc[-5:]
            buy_pressure = recent_pressure[recent_pressure['side'] == 'buy']['value'].sum()
            sell_pressure = recent_pressure[recent_pressure['side'] == 'sell']['value'].sum()
            
            # Baskı gücü (-1 ile 1 arası)
            pressure_strength = (buy_pressure - sell_pressure) / (buy_pressure + sell_pressure)
            
            if pressure_strength > 0.3:
                pressure = 'BUYING'
            elif pressure_strength < -0.3:
                pressure = 'SELLING'
            else:
                pressure = 'NEUTRAL'
                
            return {
                'pressure': pressure,
                'strength': abs(pressure_strength),
                'price_impact': self._calculate_price_impact(whale_trades, current_price)
            }
        except Exception as e:
            return {'error': str(e)}

    def _analyze_accumulation(self, df: pd.DataFrame) -> Dict:
        """Akümülasyon/Distribüsyon analizi"""
        try:
            # Son 100 işlemi analiz et
            recent_df = df.iloc[-100:]
            
            # Money Flow Multiplier
            mfm = ((recent_df['price'] - recent_df['price'].shift(1)) / 
                  (recent_df['price'].max() - recent_df['price'].min()))
            
            # Money Flow Volume
            mfv = mfm * recent_df['value']
            
            # Akümülasyon/Distribüsyon Line
            adl = mfv.cumsum()
            
            # Trend analizi
            adl_trend = 'ACCUMULATION' if adl.iloc[-1] > adl.iloc[-20:].mean() else 'DISTRIBUTION'
            
            return {
                'trend': adl_trend,
                'strength': abs(adl.iloc[-1] - adl.iloc[-20:].mean()) / adl.iloc[-20:].mean(),
                'consistent': self._check_trend_consistency(adl)
            }
        except Exception as e:
            return {'error': str(e)}

    def _get_recent_whale_moves(self, whale_trades: pd.DataFrame) -> List[Dict]:
        """Son balina hareketlerini formatla"""
        try:
            recent_moves = []
            for _, trade in whale_trades.iloc[-5:].iterrows():
                recent_moves.append({
                    'side': trade['side'].upper(),
                    'value': trade['value'],
                    'price': trade['price'],
                    'time': datetime.fromtimestamp(trade['timestamp']/1000).strftime('%H:%M:%S')
                })
            return recent_moves
        except Exception as e:
            return []

    def _calculate_alert_level(self, pressure: Dict, accumulation: Dict, buy_ratio: float) -> Dict:
        """Alarm seviyesini hesapla"""
        try:
            alert_score = 0
            signals = []
            
            # Baskı analizi
            if pressure['pressure'] == 'BUYING' and pressure['strength'] > 0.7:
                alert_score += 3
                signals.append("Güçlü alım baskısı")
            elif pressure['pressure'] == 'SELLING' and pressure['strength'] > 0.7:
                alert_score += 3
                signals.append("Güçlü satış baskısı")
                
            # Akümülasyon analizi
            if accumulation['trend'] == 'ACCUMULATION' and accumulation['strength'] > 0.2:
                alert_score += 2
                signals.append("Aktif akümülasyon")
            elif accumulation['trend'] == 'DISTRIBUTION' and accumulation['strength'] > 0.2:
                alert_score += 2
                signals.append("Aktif distribüsyon")
                
            # Alım/Satım oranı
            if buy_ratio > 0.7:
                alert_score += 2
                signals.append("Yoğun alım aktivitesi")
            elif buy_ratio < 0.3:
                alert_score += 2
                signals.append("Yoğun satış aktivitesi")
                
            # Alert seviyesi belirleme
            if alert_score >= 6:
                level = "YÜKSEK"
            elif alert_score >= 4:
                level = "ORTA"
            else:
                level = "DÜŞÜK"
                
            return {
                'level': level,
                'score': alert_score,
                'signals': signals
            }
        except Exception as e:
            return {'error': str(e)}

    def _calculate_price_impact(self, whale_trades: pd.DataFrame, current_price: float) -> float:
        """Balina işlemlerinin fiyat etkisini hesapla"""
        try:
            if len(whale_trades) < 2:
                return 0
                
            price_before = whale_trades['price'].iloc[0]
            price_change = ((current_price - price_before) / price_before) * 100
            
            return price_change
        except Exception:
            return 0

    def _check_trend_consistency(self, adl: pd.Series) -> bool:
        """Trend tutarlılığını kontrol et"""
        try:
            # Son 20 değerin eğilimini kontrol et
            recent_trend = adl.iloc[-20:].diff()
            positive_moves = (recent_trend > 0).sum()
            negative_moves = (recent_trend < 0).sum()
            
            # %70 tutarlılık ara
            return (positive_moves / 20 >= 0.7) or (negative_moves / 20 >= 0.7)
        except Exception:
            return False 