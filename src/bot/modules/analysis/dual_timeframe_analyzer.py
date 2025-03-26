import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
import asyncio
import ccxt.async_support as ccxt
import logging
from datetime import datetime
from functools import partial
import concurrent.futures
import sys
import os
import matplotlib.pyplot as plt
import mplfinance as mpf
from io import BytesIO

# Modül path'ini ekliyoruz
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../'))
if src_path not in sys.path:
    sys.path.append(src_path)

from src.analysis.candlestick_patterns import CandlestickPatternRecognizer, analyze_chart
from src.analysis.volatility_stops import VolatilityBasedStopCalculator, calculate_volatility_based_stops
from src.analysis.volume_profile import VolumeProfileAnalyzer, analyze_volume_distribution

class DualTimeframeAnalyzer:
    """
    15 dakikalık ve 1 saatlik grafikleri birlikte kullanarak
    kısa vadeli kaldıraçlı işlemler için sinyal üreten analiz sınıfı
    """
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        # self.exchange = ccxt.binance() # Ana exchange nesnesi kullanmıyoruz - Kaynak sızıntısını önlüyoruz
        
        # Minimum hacim ve fiyat filtreleri
        self.min_volume = 500000  # Scalping için biraz daha düşük
        self.min_price = 0.00001
        
        # Her iki zaman dilimi için RSI periyotları
        self.rsi_period_1h = 14
        self.rsi_period_15m = 9  # Daha hızlı tepki için kısa periyot
        
        # Bollinger Band parametreleri
        self.bb_period = 20
        self.bb_std = 2
        
        # EMA parametreleri
        self.ema_short = 20
        self.ema_long = 50
        
        # Fırsat değerlendirme puanları
        self.trend_weight = 0.4    # 1h trend ağırlığı
        self.signal_weight = 0.6   # 15m sinyal ağırlığı
        
        # Mum formasyonu tanıyıcısını başlat
        self.pattern_recognizer = CandlestickPatternRecognizer()
        
        # Volatilite ve hacim analizi için sınıflar
        self.volatility_calculator = VolatilityBasedStopCalculator()
        self.volume_analyzer = VolumeProfileAnalyzer()

    def _combine_analysis_for_worker(self, trend: Dict, signal: Dict) -> Dict:
        """1h trend ve 15m sinyal analizlerini birleştir (worker için)"""
        # Trend ve sinyal puanlarını ağırlıklandır
        trend_weight = 0.4
        signal_weight = 0.6
        weighted_score = (trend['score'] * trend_weight) + (signal['score'] * signal_weight)
        
        # Nedenler listesini birleştir
        reasons = trend['reasons'] + signal['reasons']
        
        # İki zaman dilimi birbiriyle uyumlu mu?
        is_aligned = False
        
        # Trend yukarı ve sinyal LONG ise veya trend aşağı ve sinyal SHORT ise uyumlu
        if (trend['trend'] == "YUKARI" and "LONG" in signal['signal']) or \
           (trend['trend'] == "AŞAĞI" and "SHORT" in signal['signal']):
            is_aligned = True
            weighted_score *= 1.3  # Ek bonus puan
            reasons.append("✅ 1h trend ve 15m sinyal uyumlu - güçlü alım/satım fırsatı")
        else:
            # Uyumsuzluk durumunda bir uyarı ekle
            if "LONG" in signal['signal'] and trend['trend'] == "AŞAĞI":
                reasons.append("⚠️ Dikkat: 15m LONG sinyali, 1h aşağı trendine karşı")
            elif "SHORT" in signal['signal'] and trend['trend'] == "YUKARI":
                reasons.append("⚠️ Dikkat: 15m SHORT sinyali, 1h yukarı trendine karşı")
        
        # Son pozisyon kararı
        if weighted_score >= 3:
            position = "STRONG_LONG" if is_aligned else "LONG"
        elif weighted_score >= 1:
            position = "LONG"
        elif weighted_score <= -3:
            position = "STRONG_SHORT" if is_aligned else "SHORT"
        elif weighted_score <= -1:
            position = "SHORT"
        else:
            position = "NEUTRAL"
        
        # Güven skoru (0-100)
        confidence = min(100, abs(weighted_score) * 15)
        
        # Fırsat puanı (0-100)
        opportunity_score = 50 + weighted_score * 7
        opportunity_score = max(0, min(100, opportunity_score))  # 0-100 arasına sınırla
        
        return {
            'position': position,
            'score': opportunity_score,
            'confidence': confidence,
            'weighted_score': weighted_score,
            'is_aligned': is_aligned,
            'reasons': reasons
        }
    
    def _calculate_risk_management_for_worker(self, df: pd.DataFrame, position: str, current_price: float) -> Dict:
        """Pozisyona uygun stop-loss ve take-profit seviyelerini hesapla (worker için)"""
        # ATR hesapla (volatiliteye göre stop-loss belirlemek için)
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean().iloc[-1]
        
        # Scalping için daha sıkı stop-loss ve take-profit
        if "LONG" in position:
            stop_loss = current_price - (atr * 1.2)  # %1-1.5 arası stop-loss
            take_profit = current_price + (atr * 2.4)  # %2-3 arası take-profit
        elif "SHORT" in position:
            stop_loss = current_price + (atr * 1.2)
            take_profit = current_price - (atr * 2.4)
        else:
            # Nötr pozisyon için varsayılan değerler
            stop_loss = current_price * 0.98
            take_profit = current_price * 1.02
        
        # Risk/Ödül hesapla
        if "LONG" in position:
            risk = current_price - stop_loss
            reward = take_profit - current_price
        else:  # "SHORT" veya "NEUTRAL"
            risk = stop_loss - current_price
            reward = current_price - take_profit
        
        risk_reward = abs(reward / risk) if risk != 0 else 0
        
        return {
            'stop_loss': float(stop_loss),
            'take_profit': float(take_profit),
            'risk': float(risk),
            'reward': float(reward),
            'risk_reward': float(risk_reward),
            'risk_reward_ratio': float(risk_reward),
            'atr': float(atr)
        }

    # scan_market fonksiyonunu analyze_market_parallel yöntemine yönlendiren uyumluluk fonksiyonu
    async def scan_market(self, symbols: List[str]) -> List[Dict]:
        """Belirtilen sembolleri tarayarak kısa vadeli fırsatları bul"""
        self.logger.info("scan_market çağrıldı, analyze_market_parallel'e yönlendiriliyor")
        return await self.analyze_market_parallel(symbols)

    async def analyze_market_parallel(self, symbols: List[str], worker_count=None) -> List[Dict]:
        """Multi-işlemci ile sembolleri paralel olarak analiz eder"""
        try:
            import time
            start_time = time.time()
            
            # Daha az sembol üzerinde çalış
            if len(symbols) > 20:
                self.logger.info(f"Sembol sayısı çok fazla, ilk 20 sembol ile çalışılacak (toplam: {len(symbols)})")
                symbols = symbols[:20]
            
            self.logger.info(f"==== 📊 TARAMA BAŞLATILIYOR ({len(symbols)} coin) ====")
            
            # Seri işleme (paralelleştirme yapmadan)
            opportunities = []
            
            # Exchange örneğini yalnızca bir kez oluştur
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            
            try:
                await exchange.load_markets()
                
                for symbol in symbols:
                    try:
                        # 1h verilerini al
                        ohlcv_1h = await exchange.fetch_ohlcv(symbol, '1h', limit=100)
                        await asyncio.sleep(0.3)  # Rate limit için bekle
                        
                        # 15m verilerini al
                        ohlcv_15m = await exchange.fetch_ohlcv(symbol, '15m', limit=100)
                        await asyncio.sleep(0.3)  # Rate limit için bekle
                        
                        if not ohlcv_1h or not ohlcv_15m or len(ohlcv_1h) < 50 or len(ohlcv_15m) < 50:
                            continue
                            
                        # Analiz işlemleri...
                        df_1h = self._prepare_dataframe_for_worker(ohlcv_1h)
                        df_15m = self._prepare_dataframe_for_worker(ohlcv_15m)
                        
                        trend_analysis = self._analyze_trend_for_worker(df_1h)
                        signal_analysis = self._analyze_signal_for_worker(df_15m)
                        combined_analysis = self._combine_analysis_for_worker(trend_analysis, signal_analysis)
                        
                        # Hacim kontrolü - Hacim kontrolünü devre dışı bırakıyoruz veya düşürüyoruz
                        # (belirli bir coin aranırken hacim filtresini atlayabiliriz)
                        current_volume = float(df_15m['volume'].iloc[-1])
                        avg_volume = float(df_15m['volume'].rolling(20).mean().iloc[-1])
                        
                        # Eğer özel olarak aranıyorsa hacim kontrolünü atla
                        if len(symbols) == 1:
                            # Belirli bir coin aranıyor, hacim kontrolünü atla
                            pass
                        elif current_volume < self.min_volume:
                            continue
                        
                        # Mum formasyonu analizi ekle
                        candlestick_1h = analyze_chart(df_1h, '1h')
                        candlestick_15m = analyze_chart(df_15m, '15m')
                        
                        # Risk yönetimi hesaplamaları
                        risk_management = self._calculate_risk_management_for_worker(
                            df_15m, 
                            combined_analysis['position'], 
                            float(df_15m['close'].iloc[-1])
                        )
                        self.logger.debug(f"Risk yönetimi sonuçları: {risk_management}")
                        
                        # Volatilite ve hacim analizlerini ekle
                        volatility_stops = calculate_volatility_based_stops(df_15m, 'medium')
                        volume_analysis = analyze_volume_distribution(df_15m)
                        
                        # Sonuç oluştur...
                        result = {
                            'symbol': symbol,
                            'current_price': float(df_15m['close'].iloc[-1]),
                            'position': combined_analysis['position'],
                            'confidence': combined_analysis['confidence'],
                            'opportunity_score': combined_analysis['score'],
                            '1h_trend': trend_analysis['trend'],
                            '15m_signal': signal_analysis['signal'],
                            'stop_loss': risk_management['stop_loss'],
                            'take_profit': risk_management['take_profit'],
                            'risk_reward': risk_management.get('risk_reward', risk_management.get('risk_reward_ratio', 0)),
                            'risk_reward_ratio': risk_management.get('risk_reward_ratio', risk_management.get('risk_reward', 0)),
                            'volume': current_volume,
                            'volume_ratio': current_volume / avg_volume if avg_volume > 0 else 0,
                            'reasons': combined_analysis['reasons'],
                            'timestamp': datetime.now().isoformat(),
                            'timeframe': 'dual_15m_1h',
                            # Yeni mum formasyonu analiz sonuçlarını ekle
                            'candlestick_1h': candlestick_1h,
                            'candlestick_15m': candlestick_15m,
                            # Yeni volatilite analizi sonuçlarını ekle
                            'v_stop_loss': volatility_stops['stop_loss'],
                            'v_take_profit1': volatility_stops['take_profit1'],
                            'v_take_profit2': volatility_stops['take_profit2'],
                            'v_trailing_stop': volatility_stops['trailing_stop'],
                            'v_risk_reward': volatility_stops.get('risk_reward', volatility_stops.get('risk_reward_ratio', 0)),
                            'v_risk_reward_ratio': volatility_stops.get('risk_reward_ratio', volatility_stops.get('risk_reward', 0)),
                            'volatility_pct': volatility_stops['volatility_pct'],
                            # Hacim profili analizini ekle
                            'poc': volume_analysis['poc'],
                            'value_area_high': volume_analysis['value_area_high'],
                            'value_area_low': volume_analysis['value_area_low'],
                            'high_liquidity': volume_analysis['high_liquidity'],
                            'low_liquidity': volume_analysis['low_liquidity'],
                            'bullish_blocks': volume_analysis['bullish_blocks'],
                            'bearish_blocks': volume_analysis['bearish_blocks']
                        }
                        
                        # Eğer mum formasyonu güçlü bir sinyal veriyorsa puana ek yap
                        if candlestick_15m['pattern_confidence'] > 50:
                            if candlestick_15m['pattern_signal'] == 'BULLISH' and 'LONG' in result['position']:
                                result['opportunity_score'] += 10
                                result['reasons'].append(f"✅ 15m: Güçlü alım mum formasyonu tespit edildi")
                            elif candlestick_15m['pattern_signal'] == 'BEARISH' and 'SHORT' in result['position']:
                                result['opportunity_score'] += 10
                                result['reasons'].append(f"✅ 15m: Güçlü satım mum formasyonu tespit edildi")
                        
                        # Belirli bir coin aranıyorsa veya minimum puan eşiğini geçiyorsa ekle
                        min_score_threshold = 50 if len(symbols) > 1 else 0  # Tek coin aranıyorsa puanı dikkate alma
                        
                        if len(symbols) == 1 or result['opportunity_score'] > min_score_threshold:
                            opportunities.append(result)
                            self.logger.info(f"{symbol} için fırsat bulundu! Puan: {result['opportunity_score']:.1f}/100")
                        
                    except Exception as e:
                        self.logger.error(f"{symbol} analiz hatası: {str(e)}")
                        self.logger.error(f"Hata detayları: {repr(e)}")  # Hatanın daha detaylı temsilini ekle
                        import traceback
                        self.logger.error(f"Hata stack trace: {traceback.format_exc()}")  # Stack trace ekle
                        continue
            
            finally:
                # ÖNEMLİ: Exchange'i her durumda kapat
                try:
                    await exchange.close()
                    self.logger.debug("Exchange düzgün şekilde kapatıldı")
                except Exception as e:
                    self.logger.error(f"Exchange kapatma hatası: {str(e)}")
            
            # Sonuçları sırala
            opportunities.sort(key=lambda x: x.get('opportunity_score', 0), reverse=True)
            
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            self.logger.info(f"🎯 Bulunan Fırsat Sayısı: {len(opportunities)}/{len(symbols)}")
            self.logger.info(f"⏱️ Toplam Süre: {elapsed_time:.2f} saniye")
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa analiz hatası: {str(e)}")
            return []

    def _prepare_dataframe_for_worker(self, ohlcv: List) -> pd.DataFrame:
        """OHLCV verilerini DataFrame'e dönüştür (worker için)"""
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # RSI hesapla
        close_diff = df['close'].diff()
        gain = close_diff.where(close_diff > 0, 0).rolling(window=9).mean()
        loss = -close_diff.where(close_diff < 0, 0).rolling(window=9).mean()
        rs = gain / loss.replace(0, 1e-9)  # Sıfıra bölme hatasını önle
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # EMA hesapla - daha fazla EMA periyodu eklendi
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()  # Eklendi: EMA 9
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()  # Eklendi: EMA 21
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()  # Eklendi: EMA 200
        
        # SMA hesapla
        df['sma9'] = df['close'].rolling(window=9).mean()  # Eklendi: SMA 9
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['sma50'] = df['close'].rolling(window=50).mean()  # Eklendi: SMA 50
        
        # MACD hesapla
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['signal']
        
        # Bollinger Bands hesapla
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
        
        # BB Pozisyonu (0-100%)
        df['bb_width'] = df['bb_upper'] - df['bb_lower']
        df['bb_position'] = (df['close'] - df['bb_lower']) / df['bb_width'] * 100
        df['bb_position'] = df['bb_position'].clip(0, 100)  # 0-100 arası sınırla
        
        # Bollinger Band Squeeze ölçümü (eklendi)
        df['bb_squeeze'] = df['bb_width'] / df['bb_middle'] * 100
        
        # Hacim analizleri (eklendi)
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # Stochastic RSI (eklendi)
        period = 14
        df['rsi_min'] = df['rsi'].rolling(window=period).min()
        df['rsi_max'] = df['rsi'].rolling(window=period).max()
        df['stoch_rsi'] = 100 * (df['rsi'] - df['rsi_min']) / ((df['rsi_max'] - df['rsi_min']) + 1e-9)
        df['stoch_rsi_k'] = df['stoch_rsi'].rolling(window=3).mean()
        df['stoch_rsi_d'] = df['stoch_rsi_k'].rolling(window=3).mean()
        
        # Fiyat kanallarını belirle (eklendi)
        df['high_20'] = df['high'].rolling(window=20).max()
        df['low_20'] = df['low'].rolling(window=20).min()
        df['channel_mid'] = (df['high_20'] + df['low_20']) / 2
        
        return df

    def _analyze_trend_for_worker(self, df: pd.DataFrame) -> Dict:
        """1 saatlik grafikte trend analizi yap (worker için)"""
        trend_points = 0
        reasons = []
        
        # Son değerleri al
        last_close = df['close'].iloc[-1]
        last_rsi = df['rsi'].iloc[-1]
        
        # Yeni eklenen EMA değerlerini kontrol et
        last_ema9 = df['ema9'].iloc[-1] if 'ema9' in df.columns else None
        last_ema20 = df['ema20'].iloc[-1]
        last_ema21 = df['ema21'].iloc[-1] if 'ema21' in df.columns else None
        last_ema50 = df['ema50'].iloc[-1]
        last_ema200 = df['ema200'].iloc[-1] if 'ema200' in df.columns else None
        
        # EMA trendi kontrol et - Çoklu EMA Kullanımı (geliştirildi)
        if last_ema9 is not None and last_ema21 is not None and last_ema200 is not None:
            if last_ema9 > last_ema21 and last_ema21 > last_ema50 and last_ema50 > last_ema200:
                trend = "GÜÇLÜ YUKARI"
                trend_strength = (last_ema21 - last_ema50) / last_ema50 * 100
                trend_points += 3  # Daha güçlü bir sinyal
                reasons.append("1h: Güçlü yukarı trend (EMA9 > EMA21 > EMA50 > EMA200)")
            elif last_ema21 > last_ema50:
                trend = "YUKARI"
                trend_strength = (last_ema21 - last_ema50) / last_ema50 * 100
                trend_points += 2
                
                # Trend gücüne göre ek puanlar
                if trend_strength > 1:
                    trend_points += 2
                    reasons.append("1h: Güçlü yukarı trend (EMA21 > EMA50)")
                else:
                    reasons.append("1h: Yukarı trend başlangıcı (EMA21 > EMA50)")
            elif last_ema9 < last_ema21 and last_ema21 < last_ema50 and last_ema50 < last_ema200:
                trend = "GÜÇLÜ AŞAĞI"
                trend_strength = (last_ema50 - last_ema21) / last_ema50 * 100
                trend_points -= 3  # Daha güçlü bir sinyal
                reasons.append("1h: Güçlü aşağı trend (EMA9 < EMA21 < EMA50 < EMA200)")
            else:
                trend = "AŞAĞI"
                trend_strength = (last_ema50 - last_ema20) / last_ema50 * 100
                trend_points -= 2
                
                # Trend gücüne göre ek puanlar
                if trend_strength > 1:
                    trend_points -= 2
                    reasons.append("1h: Güçlü aşağı trend (EMA20 < EMA50)")
                else:
                    reasons.append("1h: Aşağı trend başlangıcı (EMA20 < EMA50)")
        else:
            # Orjinal EMA trendi kontrol et
            if last_ema20 > last_ema50:
                trend = "YUKARI"
                trend_strength = (last_ema20 - last_ema50) / last_ema50 * 100
                trend_points += 2
                
                # Trend gücüne göre ek puanlar
                if trend_strength > 1:
                    trend_points += 2
                    reasons.append("1h: Güçlü yukarı trend (EMA20 > EMA50)")
                else:
                    reasons.append("1h: Yukarı trend başlangıcı (EMA20 > EMA50)")
            else:
                trend = "AŞAĞI"
                trend_strength = (last_ema50 - last_ema20) / last_ema50 * 100
                trend_points -= 2
                
                # Trend gücüne göre ek puanlar
                if trend_strength > 1:
                    trend_points -= 2
                    reasons.append("1h: Güçlü aşağı trend (EMA20 < EMA50)")
                else:
                    reasons.append("1h: Aşağı trend başlangıcı (EMA20 < EMA50)")
            
        # Hızlı ve yavaş EMA kesişimi kontrolü (eklendi)
        if 'ema9' in df.columns and 'ema21' in df.columns:
            if last_ema9 > last_ema21 and df['ema9'].iloc[-2] <= df['ema21'].iloc[-2]:
                trend_points += 3
                reasons.append("1h: Taze altın kesişim (EMA9 > EMA21)")
            elif last_ema9 < last_ema21 and df['ema9'].iloc[-2] >= df['ema21'].iloc[-2]:
                trend_points -= 3
                reasons.append("1h: Taze ölüm kesişimi (EMA9 < EMA21)")
        
        # RSI kontrolü
        if last_rsi < 30:
            trend_points += 2
            reasons.append("1h: RSI aşırı satım bölgesinde")
        elif last_rsi > 70:
            trend_points -= 2
            reasons.append("1h: RSI aşırı alım bölgesinde")
        elif last_rsi < 40:
            trend_points += 1
            reasons.append("1h: RSI düşük seviyede")
        elif last_rsi > 60:
            trend_points -= 1
            reasons.append("1h: RSI yüksek seviyede")
        
        # Fiyat kanallarına göre analiz (eklendi)
        if 'channel_mid' in df.columns:
            if last_close > df['channel_mid'].iloc[-1]:
                trend_points += 1
                reasons.append("1h: Fiyat kanal orta çizgisinin üzerinde")
            else:
                trend_points -= 1
                reasons.append("1h: Fiyat kanal orta çizgisinin altında")
        
        # Momentum kontrolü (son 5 mum yönü)
        price_direction = 1 if df['close'].iloc[-5:].diff().mean() > 0 else -1
        trend_points += price_direction
        
        if price_direction > 0:
            reasons.append("1h: Fiyat momentumu yukarı yönlü")
        else:
            reasons.append("1h: Fiyat momentumu aşağı yönlü")
        
        # Sonuç
        trend_confidence = min(5, abs(trend_points)) / 5 * 100  # 0-100 arası normalize et
        
        result = {
            'trend': trend,
            'strength': trend_strength,
            'score': trend_points,
            'confidence': trend_confidence,
            'rsi': last_rsi,
            'ema20': last_ema20,
            'ema50': last_ema50,
            'reasons': reasons
        }
        
        # Yeni eklenen değerleri sonuca ekle
        if last_ema9 is not None:
            result['ema9'] = last_ema9
        if last_ema21 is not None:
            result['ema21'] = last_ema21
        if last_ema200 is not None:
            result['ema200'] = last_ema200
        
        return result

    def _analyze_signal_for_worker(self, df: pd.DataFrame) -> Dict:
        """15 dakikalık grafikte sinyal analizi yap (worker için)"""
        signal_points = 0
        reasons = []
        
        # Son değerleri al
        last_close = df['close'].iloc[-1]
        last_rsi = df['rsi'].iloc[-1]
        last_macd = df['macd'].iloc[-1]
        last_signal = df['signal'].iloc[-1]
        last_hist = df['macd_hist'].iloc[-1]
        last_hist_prev = df['macd_hist'].iloc[-2]
        last_bb_position = df['bb_position'].iloc[-1]
        
        # Stochastic RSI analizi (eklendi)
        if 'stoch_rsi_k' in df.columns and 'stoch_rsi_d' in df.columns:
            last_k = df['stoch_rsi_k'].iloc[-1]
            last_d = df['stoch_rsi_d'].iloc[-1]
            prev_k = df['stoch_rsi_k'].iloc[-2]
            prev_d = df['stoch_rsi_d'].iloc[-2]
            
            # Stochastic RSI kesişimleri
            if last_k > last_d and prev_k <= prev_d and last_k < 20:
                signal_points += 3
                reasons.append("15m: Stoch RSI aşırı satım bölgesinden yukarı kesişim (güçlü LONG)")
            elif last_k < last_d and prev_k >= prev_d and last_k > 80:
                signal_points -= 3
                reasons.append("15m: Stoch RSI aşırı alım bölgesinden aşağı kesişim (güçlü SHORT)")
        
        # RSI sinyalleri
        if last_rsi < 30:
            signal_points += 3
            reasons.append("15m: RSI aşırı satım bölgesinde (LONG)")
        elif last_rsi > 70:
            signal_points -= 3
            reasons.append("15m: RSI aşırı alım bölgesinde (SHORT)")
        elif last_rsi < 40:
            signal_points += 1
            reasons.append("15m: RSI düşük seviyede (LONG)")
        elif last_rsi > 60:
            signal_points -= 1
            reasons.append("15m: RSI yüksek seviyede (SHORT)")
        
        # RSI uyumsuzluğu (divergence) kontrolü (eklendi)
        if len(df) > 10:
            # Son 10 mumda fiyat yeni düşük yaparken RSI yeni düşük yapmıyorsa
            price_low_index = df['low'].iloc[-10:].idxmin()
            rsi_low_index = df['rsi'].iloc[-10:].idxmin()
            
            if price_low_index > rsi_low_index and df['low'].iloc[price_low_index] < df['low'].iloc[rsi_low_index]:
                signal_points += 3
                reasons.append("15m: Bullish RSI uyumsuzluğu tespit edildi (LONG)")
                
            # Son 10 mumda fiyat yeni yüksek yaparken RSI yeni yüksek yapmıyorsa
            price_high_index = df['high'].iloc[-10:].idxmax()
            rsi_high_index = df['rsi'].iloc[-10:].idxmax()
            
            if price_high_index > rsi_high_index and df['high'].iloc[price_high_index] > df['high'].iloc[rsi_high_index]:
                signal_points -= 3
                reasons.append("15m: Bearish RSI uyumsuzluğu tespit edildi (SHORT)")
        
        # MACD sinyalleri
        if last_hist > 0 and last_hist_prev <= 0:
            # MACD çapraz yukarı (yeni sinyal)
            signal_points += 3
            reasons.append("15m: MACD yukarı kesişim (LONG)")
        elif last_hist < 0 and last_hist_prev >= 0:
            # MACD çapraz aşağı (yeni sinyal)
            signal_points -= 3
            reasons.append("15m: MACD aşağı kesişim (SHORT)")
        elif last_hist > 0:
            # Pozitif histogramda devam
            signal_points += 1
            reasons.append("15m: MACD pozitif bölgede (LONG)")
        elif last_hist < 0:
            # Negatif histogramda devam
            signal_points -= 1
            reasons.append("15m: MACD negatif bölgede (SHORT)")
        
        # Bollinger Band sinyalleri
        if last_bb_position < 10:
            signal_points += 3
            reasons.append("15m: Fiyat BB alt bandının altında (LONG)")
        elif last_bb_position > 90:
            signal_points -= 3
            reasons.append("15m: Fiyat BB üst bandının üstünde (SHORT)")
        elif last_bb_position < 20:
            signal_points += 2
            reasons.append("15m: Fiyat BB alt bandına yakın (LONG)")
        elif last_bb_position > 80:
            signal_points -= 2
            reasons.append("15m: Fiyat BB üst bandına yakın (SHORT)")
        
        # Bollinger Band Squeeze tespiti (eklendi)
        if 'bb_squeeze' in df.columns:
            current_squeeze = df['bb_squeeze'].iloc[-1]
            avg_squeeze = df['bb_squeeze'].iloc[-20:].mean()
            
            if current_squeeze < avg_squeeze * 0.7:  # Bantlar daraldığında
                # MACD yönü squeeze'den çıkış yönünü belirleyebilir
                if last_hist > 0 and last_hist > last_hist_prev:
                    signal_points += 3
                    reasons.append("15m: BB Squeeze sonrası yukarı momentum (LONG)")
                elif last_hist < 0 and last_hist < last_hist_prev:
                    signal_points -= 3
                    reasons.append("15m: BB Squeeze sonrası aşağı momentum (SHORT)")
                else:
                    reasons.append("15m: BB Squeeze tespit edildi, breakout bekleyin")
        
        # Hacim analizi (eklendi)
        if 'volume_ratio' in df.columns:
            vol_ratio = df['volume_ratio'].iloc[-1]
            if vol_ratio > 2.0:  # Hacim ortalamanın 2 katından fazla
                # Son mum yönüne göre sinyal
                if df['close'].iloc[-1] > df['open'].iloc[-1]:  # Yeşil mum
                    signal_points += 2
                    reasons.append("15m: Yüksek hacimli yukarı hareket (LONG)")
                else:  # Kırmızı mum
                    signal_points -= 2
                    reasons.append("15m: Yüksek hacimli aşağı hareket (SHORT)")
        
        # Sinyal belirleme
        if signal_points >= 4:
            signal = "STRONG_LONG"
        elif signal_points >= 2:
            signal = "LONG"
        elif signal_points <= -4:
            signal = "STRONG_SHORT"
        elif signal_points <= -2:
            signal = "SHORT"
        else:
            signal = "NEUTRAL"
        
        # Sinyal güveni (0-100)
        signal_confidence = min(6, abs(signal_points)) / 6 * 100
        
        return {
            'signal': signal,
            'score': signal_points,
            'confidence': signal_confidence,
            'rsi': last_rsi,
            'macd': last_hist,
            'bb_position': last_bb_position,
            'reasons': reasons
        }

    def _detect_candlestick_patterns(self, df: pd.DataFrame) -> List[str]:
        """Önemli mum formasyonlarını tespit et (yeni eklenen fonksiyon)"""
        patterns = []
        
        # Son 3 mum
        if len(df) < 3:
            return patterns
        
        last = df.iloc[-1]  # Son mum
        prev = df.iloc[-2]  # Önceki mum
        prev2 = df.iloc[-3]  # Öncekinin önceki mumu
        
        # 1. Pinbar/Hammer tespiti
        body_size = abs(last['close'] - last['open'])
        total_size = last['high'] - last['low']
        
        if total_size > 0 and body_size <= 0.3 * total_size:  # Gövde küçük olmalı
            # Bullish Pinbar: Alt fitil uzun, üst fitil kısa
            lower_wick = min(last['open'], last['close']) - last['low']
            upper_wick = last['high'] - max(last['open'], last['close'])
            
            if lower_wick > 2 * upper_wick and lower_wick > 2 * body_size:
                patterns.append("Bullish Pinbar")
                
            # Bearish Pinbar: Üst fitil uzun, alt fitil kısa
            elif upper_wick > 2 * lower_wick and upper_wick > 2 * body_size:
                patterns.append("Bearish Pinbar")
        
        # 2. Engulfing Pattern (Yutan)
        if last['open'] != last['close'] and prev['open'] != prev['close']:  # Doji değilse
            # Bullish Engulfing
            if (prev['close'] < prev['open'] and  # Önceki kırmızı mum
                last['close'] > last['open'] and  # Şimdiki yeşil mum
                last['open'] <= prev['close'] and  # Daha düşük açılış
                last['close'] >= prev['open']):    # Daha yüksek kapanış
                patterns.append("Bullish Engulfing")
                
            # Bearish Engulfing
            elif (prev['close'] > prev['open'] and  # Önceki yeşil mum
                  last['close'] < last['open'] and  # Şimdiki kırmızı mum
                  last['open'] >= prev['close'] and  # Daha yüksek açılış
                  last['close'] <= prev['open']):   # Daha düşük kapanış
                patterns.append("Bearish Engulfing")
        
        # 3. Doji tespiti
        if abs(last['open'] - last['close']) <= 0.05 * (last['high'] - last['low']):
            patterns.append("Doji")
            
            # Dragonfly Doji (Bullish)
            if last['high'] - max(last['open'], last['close']) < 0.1 * total_size and \
               min(last['open'], last['close']) - last['low'] > 0.6 * total_size:
                patterns.append("Dragonfly Doji (Bullish)")
                
            # Gravestone Doji (Bearish)
            elif last['high'] - max(last['open'], last['close']) > 0.6 * total_size and \
                 min(last['open'], last['close']) - last['low'] < 0.1 * total_size:
                patterns.append("Gravestone Doji (Bearish)")
        
        return patterns

    def _calculate_fibonacci_levels(self, df: pd.DataFrame) -> Dict:
        """Son 20 mumun yüksek/düşük noktalarından Fibonacci seviyeleri hesapla (yeni eklenen fonksiyon)"""
        # Son 20 mumda yüksek ve düşük noktaları bul
        recent_data = df.iloc[-20:]
        high = recent_data['high'].max()
        low = recent_data['low'].min()
        
        # Fiyat farkı
        diff = high - low
        
        # Fibonacci seviyeleri (retracement)
        return {
            'fib_0': float(high),
            'fib_0.236': float(high - 0.236 * diff),
            'fib_0.382': float(high - 0.382 * diff),
            'fib_0.5': float(high - 0.5 * diff),
            'fib_0.618': float(high - 0.618 * diff),
            'fib_0.786': float(high - 0.786 * diff),
            'fib_1': float(low)
        }

    async def initialize(self):
        """Başlangıç ayarlarını yap"""
        try:
            # Sadece test amaçlı geçici bir exchange kullanıp hemen kapatıyoruz
            exchange = ccxt.binance()
            await exchange.load_markets()
            await exchange.close()  # Önemli: exchange'i hemen kapat
            
            self.logger.info("Dual Timeframe Analyzer başlatıldı")
            return True
        except Exception as e:
            self.logger.error(f"Dual Timeframe Analyzer başlatma hatası: {e}")
            return False

    async def analyze_dual_timeframe(self, symbol: str) -> Optional[Dict]:
        """
        Verilen sembol için 15m ve 1h zaman dilimlerini birlikte analiz eder.
        1h grafiğinden trend yönünü, 15m grafiğinden giriş noktalarını belirler.
        """
        exchange = None
        try:
            # Yeni bir exchange nesnesi oluştur
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            
            await exchange.load_markets()
            
            # 1h verilerini al
            ohlcv_1h = await exchange.fetch_ohlcv(symbol, '1h', limit=100)
            if not ohlcv_1h or len(ohlcv_1h) < 50:
                self.logger.debug(f"{symbol} için yeterli 1h verisi bulunamadı")
                return None
            
            # İstekler arasında biraz bekle (rate limiting için)
            await asyncio.sleep(0.5)
            
            # 15m verilerini al
            ohlcv_15m = await exchange.fetch_ohlcv(symbol, '15m', limit=100)
            if not ohlcv_15m or len(ohlcv_15m) < 50:
                self.logger.debug(f"{symbol} için yeterli 15m verisi bulunamadı")
                return None
            
            # Veri analizi
            df_1h = self._prepare_dataframe_for_worker(ohlcv_1h)
            df_15m = self._prepare_dataframe_for_worker(ohlcv_15m)
            
            # Mum formasyonu analizi ekle
            candlestick_1h = analyze_chart(df_1h, '1h')
            candlestick_15m = analyze_chart(df_15m, '15m')
            
            # Trend analizi (1h)
            trend_analysis = self._analyze_trend_for_worker(df_1h)
            
            # Sinyal analizi (15m)
            signal_analysis = self._analyze_signal_for_worker(df_15m)
            
            # İki zaman dilimini birleştirerek son kararı ver
            combined_analysis = self._combine_analysis_for_worker(trend_analysis, signal_analysis)
            
            # Hacim kontrolü - Burada hacim kontrolünü kaldırıyoruz, özel olarak coin seçildiğinde
            # hacim filtresi uygulamıyoruz
            current_volume = float(df_15m['volume'].iloc[-1])
            avg_volume = float(df_15m['volume'].rolling(20).mean().iloc[-1])
            
            # Risk yönetimi hesaplamaları
            risk_management = self._calculate_risk_management_for_worker(
                df_15m, 
                combined_analysis['position'], 
                float(df_15m['close'].iloc[-1])
            )
            self.logger.debug(f"Risk yönetimi sonuçları: {risk_management}")
            
            # Volatilite ve hacim analizlerini ekle
            volatility_stops = calculate_volatility_based_stops(df_15m, 'medium')
            volume_analysis = analyze_volume_distribution(df_15m)
            
            # Sonuç oluştur
            result = {
                'symbol': symbol,
                'current_price': float(df_15m['close'].iloc[-1]),
                'position': combined_analysis['position'],
                'confidence': combined_analysis['confidence'],
                'opportunity_score': combined_analysis['score'],
                '1h_trend': trend_analysis['trend'],
                '15m_signal': signal_analysis['signal'],
                'stop_loss': risk_management['stop_loss'],
                'take_profit': risk_management['take_profit'],
                'risk_reward': risk_management.get('risk_reward', risk_management.get('risk_reward_ratio', 0)),
                'risk_reward_ratio': risk_management.get('risk_reward_ratio', risk_management.get('risk_reward', 0)),
                'volume': current_volume,
                'volume_ratio': current_volume / avg_volume if avg_volume > 0 else 0,
                'reasons': combined_analysis['reasons'],
                'timestamp': datetime.now().isoformat(),
                'timeframe': 'dual_15m_1h',
                # Yeni mum formasyonu analiz sonuçlarını ekle
                'candlestick_1h': candlestick_1h,
                'candlestick_15m': candlestick_15m,
                # Yeni volatilite analizi sonuçlarını ekle
                'v_stop_loss': volatility_stops['stop_loss'],
                'v_take_profit1': volatility_stops['take_profit1'],
                'v_take_profit2': volatility_stops['take_profit2'],
                'v_trailing_stop': volatility_stops['trailing_stop'],
                'v_risk_reward': volatility_stops.get('risk_reward', volatility_stops.get('risk_reward_ratio', 0)),
                'v_risk_reward_ratio': volatility_stops.get('risk_reward_ratio', volatility_stops.get('risk_reward', 0)),
                'volatility_pct': volatility_stops['volatility_pct'],
                # Hacim profili analizini ekle
                'poc': volume_analysis['poc'],
                'value_area_high': volume_analysis['value_area_high'],
                'value_area_low': volume_analysis['value_area_low'],
                'high_liquidity': volume_analysis['high_liquidity'],
                'low_liquidity': volume_analysis['low_liquidity'],
                'bullish_blocks': volume_analysis['bullish_blocks'],
                'bearish_blocks': volume_analysis['bearish_blocks']
            }
            
            # Eğer mum formasyonu güçlü bir sinyal veriyorsa puana ek yap
            if candlestick_15m['pattern_confidence'] > 50:
                if candlestick_15m['pattern_signal'] == 'BULLISH' and 'LONG' in result['position']:
                    result['opportunity_score'] += 10
                    result['reasons'].append(f"✅ 15m: Güçlü alım mum formasyonu tespit edildi")
                elif candlestick_15m['pattern_signal'] == 'BEARISH' and 'SHORT' in result['position']:
                    result['opportunity_score'] += 10
                    result['reasons'].append(f"✅ 15m: Güçlü satım mum formasyonu tespit edildi")
            
            # Hacim profili bilgilerine göre puan ayarla
            if volume_analysis['poc'] is not None and result['current_price'] < volume_analysis['poc']:
                if 'LONG' in result['position']:
                    result['opportunity_score'] += 5
                    result['reasons'].append(f"✅ Fiyat POC (${volume_analysis['poc']}) seviyesinin altında - potansiyel destek")
            elif volume_analysis['poc'] is not None and result['current_price'] > volume_analysis['poc']:
                if 'SHORT' in result['position']:
                    result['opportunity_score'] += 5
                    result['reasons'].append(f"✅ Fiyat POC (${volume_analysis['poc']}) seviyesinin üzerinde - potansiyel direnç")
            
            # Teknik göstergeleri ekle
            result.update({
                'rsi_1h': float(trend_analysis['rsi']),
                'rsi_15m': float(signal_analysis['rsi']),
                'macd_15m': float(signal_analysis['macd']),
                'bb_position_15m': float(signal_analysis['bb_position']),
                'ema20_1h': float(trend_analysis['ema20']),
                'ema50_1h': float(trend_analysis['ema50']),
            })
            
            return result
            
        except Exception as e:
            self.logger.error(f"Dual timeframe analiz hatası ({symbol}): {e}")
            return None
        finally:
            # Exchange'i kapat
            if exchange:
                try:
                    await exchange.close()
                except Exception as e:
                    self.logger.debug(f"Exchange kapatılırken hata: {e}")

    async def generate_enhanced_scalp_chart(self, symbol: str, analysis_result: Dict) -> Optional[BytesIO]:
        """
        Scalping için gelişmiş, tahmin ve analiz bilgilerini içeren teknik analiz grafiği oluşturur
        
        Args:
            symbol: Kripto para sembolü
            analysis_result: Analiz sonuçları
            
        Returns:
            BytesIO: PNG formatında grafik içeren buffer
        """
        try:
            # Exchange örneğini oluştur
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            
            try:
                await exchange.load_markets()
                
                # OHLCV verilerini al - 15m için
                ohlcv = await exchange.fetch_ohlcv(symbol, '15m', limit=120)
                if not ohlcv or len(ohlcv) < 50:
                    self.logger.warning(f"Yetersiz kline verisi: {symbol}")
                    return None
                    
                # Pandas DataFrame'e dönüştür
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                
                # Teknik göstergeleri hesapla
                df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
                df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                
                # RSI
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss.replace(0, 1e-9)  # Sıfıra bölme hatasını önle
                df['rsi'] = 100 - (100 / (1 + rs))
                
                # MACD
                ema12 = df['close'].ewm(span=12, adjust=False).mean()
                ema26 = df['close'].ewm(span=26, adjust=False).mean()
                df['macd'] = ema12 - ema26
                df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
                df['hist'] = df['macd'] - df['signal']
                
                # Bollinger Bands
                df['bb_middle'] = df['close'].rolling(window=20).mean()
                df['bb_std'] = df['close'].rolling(window=20).std()
                df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
                df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
                
                # Volume Weighted Average Price (VWAP) - oturumun başlangıcından itibaren
                df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
                
                # Fiyat öngörüsü için basit lineer regresyon
                # Son 30 mumu kullanarak gelecek 10 mum için tahmin oluştur
                x = np.arange(30)
                y = df['close'].values[-30:]
                
                # Lineer regresyon hesapla - polynomial curve fitting kullanarak (2. derece)
                z = np.polyfit(x, y, 2)
                p = np.poly1d(z)
                
                # Gelecek 10 mum için tahmin
                forecast_x = np.arange(30, 40)
                forecast_y = p(forecast_x)
                
                # Son 80 mumu göster
                df = df.iloc[-80:]
                
                # Grafik ayarları
                mc = mpf.make_marketcolors(up='green', down='red', edge='black', wick='black', volume='in')
                s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
                
                # Gelecek fiyat tahmini için renkli bölge - sadece DataFrame'de olması gereken verileri kullan
                last_idx = df.index[-1]
                future_idx = [last_idx + pd.Timedelta(minutes=15*i) for i in range(1, 11)]
                
                # Ek göstergeler
                apds = [
                    mpf.make_addplot(df['ema9'], color='blue', width=0.7, label='EMA9'),
                    mpf.make_addplot(df['ema20'], color='orange', width=1, label='EMA20'),
                    mpf.make_addplot(df['ema50'], color='purple', width=1.2, label='EMA50'),
                    mpf.make_addplot(df['bb_upper'], color='gray', width=0.7, linestyle='--'),
                    mpf.make_addplot(df['bb_middle'], color='gray', width=0.7),
                    mpf.make_addplot(df['bb_lower'], color='gray', width=0.7, linestyle='--'),
                    mpf.make_addplot(df['vwap'], color='teal', width=1, label='VWAP'),
                    mpf.make_addplot(df['rsi'], panel=1, color='red', width=1),
                    mpf.make_addplot(df['macd'], panel=2, color='blue', width=1),
                    mpf.make_addplot(df['signal'], panel=2, color='orange', width=1),
                    mpf.make_addplot(df['hist'], panel=2, type='bar', color='gray'),
                ]
                
                # Grafik başlığı
                title = f'{symbol} - 15m Scalp Sinyali: {analysis_result.get("position", "NEUTRAL")}'
                
                # Figür boyutu arttırıldı
                fig, axes = mpf.plot(df, type='candle', style=s, addplot=apds, volume=True, 
                                    panel_ratios=(6, 2, 2), figsize=(14, 10), title=title, 
                                    returnfig=True)
                
                # RSI paneline 30 ve 70 çizgileri ekle
                axes[2].axhline(y=30, color='green', linestyle='--', alpha=0.5)
                axes[2].axhline(y=70, color='red', linestyle='--', alpha=0.5)
                
                # MACD paneline 0 çizgisi ekle
                axes[3].axhline(y=0, color='black', linestyle='-', alpha=0.5)
                
                # Ana grafiğe stop-loss ve take-profit seviyelerini ekle
                if 'stop_loss' in analysis_result and 'take_profit' in analysis_result:
                    # Stop-loss çizgisi
                    stop_price = analysis_result['stop_loss']
                    axes[0].axhline(y=stop_price, color='red', linestyle='--', linewidth=2, alpha=0.7)
                    axes[0].text(0.01, stop_price, f'Stop: {stop_price:.4f}', transform=axes[0].get_yaxis_transform(), 
                                color='red', fontweight='bold', va='center')
                    
                    # Take-profit çizgisi
                    target_price = analysis_result['take_profit']
                    axes[0].axhline(y=target_price, color='green', linestyle='--', linewidth=2, alpha=0.7)
                    axes[0].text(0.01, target_price, f'Target: {target_price:.4f}', transform=axes[0].get_yaxis_transform(), 
                                color='green', fontweight='bold', va='center')
                
                # Gelecek tahminini çiz
                last_close = df['close'].iloc[-1]
                next_15m = last_idx + pd.Timedelta(minutes=15)
                
                # Fiyat öngörüsü çizgisi (kesikli)
                forecast_dates = pd.date_range(start=next_15m, periods=10, freq='15min')
                axes[0].plot(forecast_dates, forecast_y, 'b--', linewidth=1.5, alpha=0.7)
                
                # Öngörü eğilimini gösteren ok
                if forecast_y[-1] > last_close:
                    arrow_color = 'green'
                    arrow_text = '↗ Yükseliş Eğilimi'
                else:
                    arrow_color = 'red'
                    arrow_text = '↘ Düşüş Eğilimi'
                
                axes[0].annotate(arrow_text, 
                               xy=(forecast_dates[5], forecast_y[5]), 
                               xytext=(forecast_dates[5], forecast_y[5] * 1.02),
                               arrowprops=dict(facecolor=arrow_color, shrink=0.05),
                               color=arrow_color,
                               fontweight='bold')
                
                # Destek ve Direnç Seviyeleri
                if 'support_levels' in analysis_result and 'resistance_levels' in analysis_result:
                    # Destek çizgileri (en fazla 2 tane)
                    for i, level in enumerate(analysis_result.get('support_levels', [])[:2]):
                        if level < last_close:  # Sadece mevcut fiyatın altındaki destekleri göster
                            axes[0].axhline(y=level, color='green', linestyle='-.', linewidth=1, alpha=0.6)
                            axes[0].text(0.99, level, f'S{i+1}: {level:.4f}', transform=axes[0].get_yaxis_transform(), 
                                        color='green', ha='right', va='center')
                    
                    # Direnç çizgileri (en fazla 2 tane)
                    for i, level in enumerate(analysis_result.get('resistance_levels', [])[:2]):
                        if level > last_close:  # Sadece mevcut fiyatın üstündeki dirençleri göster
                            axes[0].axhline(y=level, color='red', linestyle='-.', linewidth=1, alpha=0.6)
                            axes[0].text(0.99, level, f'R{i+1}: {level:.4f}', transform=axes[0].get_yaxis_transform(), 
                                        color='red', ha='right', va='center')
                
                # Hacim Profili POC seviyesi
                if 'poc' in analysis_result and analysis_result['poc'] is not None:
                    poc_level = analysis_result['poc']
                    axes[0].axhline(y=poc_level, color='blue', linestyle='-.', linewidth=1.5, alpha=0.6)
                    axes[0].text(0.5, poc_level, f'POC: {poc_level:.4f}', transform=axes[0].get_yaxis_transform(), 
                                color='blue', ha='center', va='center', fontweight='bold')
                
                # Mum Formasyonlarını İşaretle
                if 'candlestick_15m' in analysis_result and 'patterns' in analysis_result['candlestick_15m']:
                    patterns = analysis_result['candlestick_15m']['patterns']
                    if patterns:
                        for pattern in patterns[:2]:  # En önemli 2 formasyonu göster
                            pattern_name = pattern.get('name', '')
                            idx = pattern.get('index', -1)
                            if idx >= 0 and idx < len(df):
                                pattern_idx = df.index[idx]
                                price = df['high'].iloc[idx] * 1.01  # Biraz üstte göster
                                axes[0].annotate(pattern_name, 
                                              xy=(pattern_idx, price),
                                              xytext=(pattern_idx, price * 1.03),
                                              arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=8),
                                              fontweight='bold',
                                              ha='center')
                
                # Sinyal Metni
                position = analysis_result.get('position', 'NEUTRAL')
                confidence = analysis_result.get('confidence', 0)
                signal_color = 'green' if 'LONG' in position else 'red' if 'SHORT' in position else 'gray'
                
                signal_text = f"{position} - Güven: %{confidence:.0f}"
                plt.figtext(0.5, 0.01, signal_text, ha='center', color=signal_color, 
                           fontsize=12, fontweight='bold', 
                           bbox=dict(facecolor='white', alpha=0.8, boxstyle='round,pad=0.5'))
                
                # Risk/Ödül bilgisi
                risk_reward = analysis_result.get('risk_reward_ratio', analysis_result.get('risk_reward', 0))
                if risk_reward:
                    rr_text = f"Risk/Ödül: {risk_reward:.2f}"
                    plt.figtext(0.5, 0.04, rr_text, ha='center', fontsize=10)
                
                # Lejant ekle
                axes[0].legend(loc='upper left')
                
                # Grafiği kaydet
                buf = BytesIO()
                plt.tight_layout()
                plt.savefig(buf, format='png', dpi=100)
                buf.seek(0)
                plt.close(fig)
                
                return buf
                
            finally:
                # Exchange'i kapat
                if exchange:
                    try:
                        await exchange.close()
                    except Exception as e:
                        self.logger.debug(f"Exchange kapatılırken hata: {e}")
            
        except Exception as e:
            self.logger.error(f"Gelişmiş grafik oluşturma hatası ({symbol}): {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    async def send_scan_results(self, chat_id, opportunities, scan_type):
        """
        Tarama sonuçlarını chat'e gönderir ve en iyi fırsatın gelişmiş grafiğini ekler
        
        Args:
            chat_id: Telegram chat ID
            opportunities: Fırsat listesi (puana göre sıralanmış)
            scan_type: Tarama tipi (örn. 'scalp', 'swing')
        """
        try:
            # En iyi fırsatın grafiğini gönder
            if opportunities:
                top_opportunity = opportunities[0]  # En yüksek puanlı fırsat
                self.logger.info(f"En yüksek puanlı fırsat için gelişmiş grafik oluşturuluyor: {top_opportunity['symbol']}")
                
                chart_buf = await self.generate_enhanced_scalp_chart(top_opportunity['symbol'], top_opportunity)
                if chart_buf:
                    await self.application.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_buf,
                        caption=f"📊 En Yüksek Puanlı Fırsat: {top_opportunity['symbol']} - {scan_type.upper()} Analizi"
                    )
                    self.logger.info(f"Gelişmiş grafik başarıyla gönderildi: {top_opportunity['symbol']}")
                else:
                    self.logger.warning(f"Gelişmiş grafik oluşturulamadı: {top_opportunity['symbol']}")
            else:
                self.logger.info("Gösterilecek fırsat bulunamadı, grafik gönderilmiyor")
            
        except Exception as e:
            self.logger.error(f"Grafik gönderme hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())