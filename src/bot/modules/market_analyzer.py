import numpy as np
import pandas as pd
from datetime import datetime
from io import BytesIO
import matplotlib.pyplot as plt
import mplfinance as mpf
from typing import Dict, List, Optional, Tuple
from .analysis.technical_analysis import TechnicalAnalysis, MarketDataProvider
import asyncio
from scipy.signal import argrelextrema
import random
import logging
import aiohttp

class MarketAnalyzer:
    def __init__(self, logger):
        self.logger = logger
        self.ta = TechnicalAnalysis(logger)
        self.data_provider = MarketDataProvider(logger)
        self.excluded_coins = ['USDCUSDT', 'BUSDUSDT', 'USDTUSDT', 'TUSDUSDT', 'BUSDUSDC']
        self.min_volume = 1000000  # Minimum 24 saatlik hacim (1 milyon $)
        self.valid_symbols = []
        # _init_valid_symbols'ı başlatma sırasında çağırmıyoruz, bunun yerine
        # ilk kullanımda çağıracağız

    async def _init_valid_symbols(self):
        """Geçerli sembolleri başlat"""
        try:
            exchange_info = await self.data_provider.get_exchange_info()
            if exchange_info and 'symbols' in exchange_info:
                self.valid_symbols = [
                    s['symbol'] for s in exchange_info['symbols'] 
                    if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')
                ]
                self.logger.info(f"Geçerli semboller yüklendi: {len(self.valid_symbols)} USDT çifti")
            else:
                self.logger.warning("Exchange bilgisi alınamadı, geçerli semboller yüklenemedi")
        except Exception as e:
            self.logger.error(f"Geçerli sembolleri başlatma hatası: {e}")
            self.valid_symbols = []

    async def get_klines_data(self, symbol: str, interval: str) -> list:
        """Belirli bir zaman dilimi için kline verilerini getir"""
        return await self.data_provider.get_klines_data(symbol, interval)

    async def _analyze_market_condition(self) -> str:
        """Genel piyasa durumunu analiz et"""
        try:
            # BTC verilerini al
            btc_klines = await self.get_klines_data("BTCUSDT", "1d")
            if not btc_klines or len(btc_klines) < 20:
                return "NORMAL"
            
            # BTC fiyatlarını numpy dizisine dönüştür
            btc_closes = np.array([float(k[4]) for k in btc_klines])
            
            # 20 günlük hareketli ortalama
            btc_ma20 = np.mean(btc_closes[-20:])
            
            # Son fiyat
            btc_last_price = btc_closes[-1]
            
            # RSI hesapla
            btc_rsi = self.ta.calculate_rsi(btc_closes)
            
            # Piyasa durumunu belirle
            if btc_last_price > btc_ma20 * 1.05 and btc_rsi > 70:
                return "AŞIRI_ALIM"  # Aşırı alım - düzeltme olabilir
            elif btc_last_price < btc_ma20 * 0.95 and btc_rsi < 30:
                return "AŞIRI_SATIM"  # Aşırı satım - sıçrama olabilir
            elif btc_last_price > btc_ma20:
                return "YUKARI_TREND"  # Yukarı trend
            elif btc_last_price < btc_ma20:
                return "AŞAĞI_TREND"  # Aşağı trend
            else:
                return "NORMAL"  # Normal piyasa
            
        except Exception as e:
            self.logger.error(f"Piyasa durumu analiz hatası: {e}")
            return "NORMAL"

    async def scan_market(self, interval: str = "4h") -> List[Dict]:
        """Piyasayı tara ve fırsatları bul"""
        try:
            # Geçerli sembolleri başlat (eğer henüz başlatılmadıysa)
            if not self.valid_symbols:
                await self._init_valid_symbols()
            
            # Tüm sembolleri al
            tickers = await self.get_all_tickers()
            if not tickers:
                self.logger.error("Ticker verileri alınamadı")
                return []
            
            # Piyasa analizi yap
            opportunities = await self.analyze_market(tickers, interval)
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa tarama hatası: {e}")
            return []

    async def analyze_market(self, ticker_data: List[Dict], interval: str = "4h") -> List[Dict]:
        """Tüm piyasayı analiz et ve fırsatları bul"""
        try:
            # Geçerli sembolleri başlat (eğer henüz başlatılmadıysa)
            if not self.valid_symbols:
                await self._init_valid_symbols()
                
            opportunities = []
            long_opportunities = []
            short_opportunities = []
            total_coins = len(ticker_data)
            analyzed_count = 0
            valid_usdt_pairs = 0
            
            self.logger.info(f"🔍 Toplam {total_coins} coin taranıyor...")
            
            # Rastgele sıralama ekleyelim - farklı coinler bulmak için
            ticker_data = random.sample(ticker_data, len(ticker_data))
            
            # Daha önce önerilen coinleri takip etmek için
            # Bu değişken sınıf seviyesinde tanımlanmalı
            if not hasattr(self, 'recently_suggested'):
                self.recently_suggested = set()
            
            for ticker in ticker_data:
                symbol = ticker['symbol']
                
                # USDT çiftleri dışındakileri ve hariç tutulan coinleri atla
                if not symbol.endswith('USDT') or symbol in self.excluded_coins:
                    continue
                    
                # Son 24 saatte önerilen coinleri atla (farklı coinler önermek için)
                if symbol in self.recently_suggested and len(self.recently_suggested) > 20:
                    continue
                    
                valid_usdt_pairs += 1
                
                # Düşük fiyatlı coinleri atla (örn. $0.00001'den düşük)
                current_price = float(ticker['lastPrice'])
                if current_price < 0.00001:
                    continue
                
                # Düşük hacimli coinleri atla
                volume = float(ticker['quoteVolume'])
                if volume < self.min_volume:
                    continue
                    
                analyzed_count += 1
                
                # Fırsat analizi yap
                opportunity = await self.analyze_opportunity(symbol, current_price, volume, interval)
                
                if opportunity:
                    # Zaman dilimine göre farklı stratejiler uygula
                    if interval == "15m":
                        # 15 dakikalık işlemler için daha agresif ve kısa vadeli stratejiler
                        self._adjust_for_short_term(opportunity)
                    elif interval == "4h":
                        # 4 saatlik işlemler için orta vadeli stratejiler
                        self._adjust_for_medium_term(opportunity)
                    elif interval == "1d":
                        # Günlük işlemler için uzun vadeli stratejiler
                        self._adjust_for_long_term(opportunity)
                    
                    # Fırsat puanı yeterince yüksekse listeye ekle
                    if opportunity['opportunity_score'] >= 60:
                        # Sinyal türüne göre ayır
                        if "LONG" in opportunity['signal']:
                            long_opportunities.append(opportunity)
                        elif "SHORT" in opportunity['signal']:
                            short_opportunities.append(opportunity)
                        
                        # Önerilen coinleri kaydet
                        self.recently_suggested.add(symbol)
                        
                        # Son 50 öneriyi tut
                        if len(self.recently_suggested) > 50:
                            self.recently_suggested.pop()
                
                # Her 20 analizde bir ilerleme raporu
                if analyzed_count % 20 == 0:
                    self.logger.debug(f"İlerleme: {analyzed_count}/{valid_usdt_pairs} coin analiz edildi")
            
            # LONG ve SHORT fırsatlarını puanlarına göre sırala
            long_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            short_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            # Genel piyasa durumunu analiz et
            market_condition = await self._analyze_market_condition()
            self.logger.info(f"Piyasa durumu: {market_condition}")
            
            # Piyasa durumuna göre LONG/SHORT dağılımını ayarla
            if market_condition == "AŞIRI_ALIM":
                # Aşırı alım durumunda daha fazla SHORT sinyali
                long_count = min(3, len(long_opportunities))
                short_count = min(7, len(short_opportunities))
            elif market_condition == "AŞIRI_SATIM":
                # Aşırı satım durumunda daha fazla LONG sinyali
                long_count = min(7, len(long_opportunities))
                short_count = min(3, len(short_opportunities))
            elif market_condition == "YUKARI_TREND":
                # Yukarı trendde daha fazla LONG sinyali
                long_count = min(6, len(long_opportunities))
                short_count = min(4, len(short_opportunities))
            elif market_condition == "AŞAĞI_TREND":
                # Aşağı trendde daha fazla SHORT sinyali
                long_count = min(4, len(long_opportunities))
                short_count = min(6, len(short_opportunities))
            else:
                # Normal piyasada dengeli dağılım
                long_count = min(5, len(long_opportunities))
                short_count = min(5, len(short_opportunities))
            
            # En iyi LONG ve SHORT fırsatlarını birleştir
            opportunities = long_opportunities[:long_count] + short_opportunities[:short_count]
            
            # Fırsatları karıştır
            random.shuffle(opportunities)
            
            # En fazla 10 fırsat göster
            opportunities = opportunities[:10]
            
            # Fırsatlara piyasa durumunu ekle
            for opp in opportunities:
                opp['market_condition'] = market_condition
            
            # Analiz özeti
            self.logger.info(
                f"Analiz tamamlandı: {analyzed_count} coin analiz edildi, "
                f"{len(opportunities)} fırsat bulundu. "
                f"LONG: {len([o for o in opportunities if 'LONG' in o['signal']])}, "
                f"SHORT: {len([o for o in opportunities if 'SHORT' in o['signal']])}"
            )
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa analizi hatası: {e}")
            return []

    def _get_strategy_for_timeframe(self, interval: str) -> Dict:
        """Zaman dilimine göre strateji parametrelerini al"""
        if interval == "15m":
            return {
                'rsi_oversold': 35,  # RSI aşırı satım eşiği
                'rsi_overbought': 65,  # RSI aşırı alım eşiği
                'bb_lower_threshold': 30,  # BB alt bant eşiği
                'bb_upper_threshold': 70,  # BB üst bant eşiği
                'ema_fast': 9,  # Hızlı EMA periyodu
                'ema_slow': 21,  # Yavaş EMA periyodu
                'min_score': 55,  # Minimum fırsat puanı
                'long_ratio': 0.4,  # LONG fırsatları oranı
                'short_ratio': 0.6,  # SHORT fırsatları oranı
                'volatility_weight': 1.2,  # Volatilite ağırlığı
                'volume_weight': 1.5,  # Hacim ağırlığı
            }
        elif interval == "4h":
            return {
                'rsi_oversold': 30,
                'rsi_overbought': 70,
                'bb_lower_threshold': 20,
                'bb_upper_threshold': 80,
                'ema_fast': 20,
                'ema_slow': 50,
                'min_score': 60,
                'long_ratio': 0.5,
                'short_ratio': 0.5,
                'volatility_weight': 1.0,
                'volume_weight': 1.0,
            }
        elif interval == "1d":
            return {
                'rsi_oversold': 30,
                'rsi_overbought': 70,
                'bb_lower_threshold': 10,
                'bb_upper_threshold': 90,
                'ema_fast': 20,
                'ema_slow': 50,
                'min_score': 65,
                'long_ratio': 0.7,
                'short_ratio': 0.3,
                'volatility_weight': 0.8,
                'volume_weight': 1.2,
            }
        else:
            # Varsayılan strateji
            return {
                'rsi_oversold': 30,
                'rsi_overbought': 70,
                'bb_lower_threshold': 20,
                'bb_upper_threshold': 80,
                'ema_fast': 20,
                'ema_slow': 50,
                'min_score': 60,
                'long_ratio': 0.5,
                'short_ratio': 0.5,
                'volatility_weight': 1.0,
                'volume_weight': 1.0,
            }

    def _determine_trade_signal(self, rsi: float, macd: float, signal: float, bb_position: float, ema_trend: str) -> str:
        """Teknik göstergelere göre işlem sinyali belirle"""
        # RSI sinyali
        if rsi < 30:
            rsi_signal = "LONG"
        elif rsi > 70:
            rsi_signal = "SHORT"
        else:
            rsi_signal = "NÖTR"
        
        # MACD sinyali
        if macd > signal and macd > 0:
            macd_signal = "LONG"
        elif macd < signal and macd < 0:
            macd_signal = "SHORT"
        else:
            macd_signal = "NÖTR"
        
        # Bollinger Bands sinyali
        if bb_position < 20:
            bb_signal = "LONG"
        elif bb_position > 80:
            bb_signal = "SHORT"
        else:
            bb_signal = "NÖTR"
        
        # EMA trend sinyali
        if ema_trend == "YUKARI":
            ema_signal = "LONG"
        elif ema_trend == "AŞAĞI":
            ema_signal = "SHORT"
        else:
            ema_signal = "NÖTR"
        
        # Sinyalleri sayalım
        long_count = sum(1 for signal in [rsi_signal, macd_signal, bb_signal, ema_signal] if signal == "LONG")
        short_count = sum(1 for signal in [rsi_signal, macd_signal, bb_signal, ema_signal] if signal == "SHORT")
        
        # Karar ver
        if long_count > short_count and long_count >= 2:
            return "LONG"
        elif short_count > long_count and short_count >= 2:
            return "SHORT"
        else:
            return "NÖTR"

    async def analyze_opportunity(self, symbol: str, current_price: float, volume: float, interval: str = "4h") -> Optional[Dict]:
        """Fırsat analizi yap"""
        try:
            # OHLCV verilerini al
            klines = await self.get_klines_data(symbol, interval)
            if not klines or len(klines) < 50:
                self.logger.warning(f"Yetersiz kline verisi: {symbol}")
                return None
            
            # Numpy dizilerine dönüştür
            timestamps = np.array([float(k[0]) for k in klines])
            opens = np.array([float(k[1]) for k in klines])
            highs = np.array([float(k[2]) for k in klines])
            lows = np.array([float(k[3]) for k in klines])
            closes = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])
            
            # Teknik göstergeleri hesapla
            ema20_values = self.ta.calculate_ema(closes, 20)
            ema50_values = self.ta.calculate_ema(closes, 50)
            ema200_values = self.ta.calculate_ema(closes, 200)
            
            # Son değerleri al
            ema20 = ema20_values[-1] if isinstance(ema20_values, np.ndarray) else ema20_values
            ema50 = ema50_values[-1] if isinstance(ema50_values, np.ndarray) else ema50_values
            ema200 = ema200_values[-1] if isinstance(ema200_values, np.ndarray) else ema200_values
            
            # RSI hesapla
            rsi_values = self.ta.calculate_rsi(closes)
            rsi = rsi_values[-1] if isinstance(rsi_values, np.ndarray) else rsi_values
            
            # MACD hesapla
            macd_result = self.ta.calculate_macd(closes)
            
            # MACD sonuçlarını kontrol et
            if isinstance(macd_result, tuple) and len(macd_result) == 3:
                macd_line, signal_line, hist_line = macd_result
                
                # Dizileri kontrol et
                macd_val = macd_line[-1] if isinstance(macd_line, np.ndarray) else macd_line
                signal_val = signal_line[-1] if isinstance(signal_line, np.ndarray) else signal_line
                hist_val = hist_line[-1] if isinstance(hist_line, np.ndarray) else hist_line
            else:
                # MACD hesaplanamadıysa varsayılan değerler kullan
                macd_val = 0
                signal_val = 0
                hist_val = 0
            
            # Bollinger Bands hesapla
            bb_result = self.ta.calculate_bollinger_bands(closes)
            
            # BB sonuçlarını kontrol et
            if isinstance(bb_result, tuple) and len(bb_result) == 3:
                bb_upper, bb_middle, bb_lower = bb_result
                
                # Dizileri kontrol et
                bb_upper_val = bb_upper[-1] if isinstance(bb_upper, np.ndarray) else bb_upper
                bb_middle_val = bb_middle[-1] if isinstance(bb_middle, np.ndarray) else bb_middle
                bb_lower_val = bb_lower[-1] if isinstance(bb_lower, np.ndarray) else bb_lower
                
                # Bollinger Bands pozisyonu (0-100 arası)
                if bb_upper_val - bb_lower_val == 0:
                    bb_position = 50
                else:
                    bb_position = (closes[-1] - bb_lower_val) / (bb_upper_val - bb_lower_val) * 100
            else:
                # BB hesaplanamadıysa varsayılan değerler kullan
                bb_position = 50
            
            # EMA trend
            if ema20 > ema50:
                ema_trend = "YUKARI"
            else:
                ema_trend = "AŞAĞI"
            
            # İşlem sinyali belirle
            trade_signal = self._determine_trade_signal(rsi, macd_val, signal_val, bb_position, ema_trend)
            
            # Volatilite hesapla
            volatility = self._calculate_volatility(closes)
            
            # Hacim trendi analiz et
            volume_trend, volume_change = self._analyze_volume_trend(volumes, closes)
            
            # Stochastic hesapla
            stoch_k, stoch_d = self._calculate_stochastic(highs, lows, closes)
            
            # Pivot noktalarını hesapla
            pivot_points = self._calculate_pivot_points(highs, lows, closes)
            
            # LONG ve SHORT puanlarını hesapla
            long_score = 0
            short_score = 0
            
            # RSI'ya göre puanlama
            if rsi < 30:
                long_score += 20
            elif rsi > 70:
                short_score += 20
            
            # MACD'ye göre puanlama
            if macd_val > signal_val and hist_val > 0:
                long_score += 15
            elif macd_val < signal_val and hist_val < 0:
                short_score += 15
            
            # Bollinger Bands'e göre puanlama
            if bb_position < 20:
                long_score += 15
            elif bb_position > 80:
                short_score += 15
            
            # EMA trendine göre puanlama
            if ema_trend == "YUKARI":
                long_score += 10
                # 200 EMA üzerinde mi?
                if closes[-1] > ema200:
                    long_score += 10
            else:
                short_score += 10
                # 200 EMA altında mı?
                if closes[-1] < ema200:
                    short_score += 10
            
            # Volatiliteye göre puanlama
            if interval == "15m":
                # Kısa vadeli işlemler için yüksek volatilite ideal
                if volatility > 2.0:  # Yüksek volatilite
                    long_score += 10
                    short_score += 10
            elif interval == "4h":
                # Orta vadeli işlemler için orta volatilite ideal
                if 1.0 < volatility < 2.0:  # Orta volatilite
                    long_score += 10
                    short_score += 10
            elif interval == "1d":
                # Uzun vadeli işlemler için düşük volatilite tercih edilir
                if volatility < 1.0:  # Düşük volatilite
                    long_score += 10
                    short_score += 10
            
            # Hacim trendine göre puanlama
            if volume_trend == "ARTAN_HACIM_YUKARI":
                long_score += 15
            elif volume_trend == "ARTAN_HACIM_ASAGI":
                short_score += 15
            elif volume_trend == "AZALAN_HACIM_YUKARI":
                long_score += 5
            elif volume_trend == "AZALAN_HACIM_ASAGI":
                short_score += 5
            
            # Stochastic'e göre puanlama
            if stoch_k < 20 and stoch_k > stoch_d:  # Aşırı satım + yukarı çapraz
                long_score += 15
            elif stoch_k > 80 and stoch_k < stoch_d:  # Aşırı alım + aşağı çapraz
                short_score += 15
            elif stoch_k < 30:  # Aşırı satım
                long_score += 10
            elif stoch_k > 70:  # Aşırı alım
                short_score += 10
            
            # Zaman dilimine göre ek puanlama
            if interval == "15m":
                # 15 dakikalık işlemlerde SHORT'a biraz daha ağırlık ver
                short_score += 5
            elif interval == "1d":
                # Günlük işlemlerde LONG'a biraz daha ağırlık ver
                long_score += 5
            
            # Stop Loss ve Take Profit hesapla
            if long_score > short_score:
                # LONG için
                stop_price = min(lows[-5:]) * 0.99  # Son 5 mumun en düşüğünün %1 altı
                target_price = current_price + (current_price - stop_price) * 2  # 1:2 risk-ödül oranı
            else:
                # SHORT için
                stop_price = max(highs[-5:]) * 1.01  # Son 5 mumun en yükseğinin %1 üstü
                target_price = current_price - (stop_price - current_price) * 2  # 1:2 risk-ödül oranı
            
            # Risk-ödül oranı
            if long_score > short_score:
                risk = current_price - stop_price
                reward = target_price - current_price
            else:
                risk = stop_price - current_price
                reward = current_price - target_price
            
            risk_reward = reward / risk if risk > 0 else 0
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'volume': volume,
                'ema20': ema20,
                'ema50': ema50,
                'ema200': ema200,
                'rsi': rsi,
                'macd': macd_val,
                'signal': self._get_signal_text(long_score, short_score),
                'bb_position': bb_position,
                'stop_price': stop_price,
                'target_price': target_price,
                'risk_reward': risk_reward,
                'long_score': long_score,
                'short_score': short_score,
                'volatility': volatility,
                'volume_trend': volume_trend,
                'volume_change': volume_change,
                'stoch_k': stoch_k,
                'stoch_d': stoch_d,
                'pivot_points': pivot_points
            }
        except Exception as e:
            self.logger.error(f"Fırsat analizi hatası ({symbol}): {e}")
            return None

    def _adjust_for_short_term(self, opportunity):
        """15 dakikalık işlemler için ayarlamalar yap"""
        # RSI 50'nin üzerindeyse SHORT puanını artır
        if opportunity['rsi'] > 50:
            opportunity['short_score'] += 15
            
        # Fiyat BB orta bandının üzerindeyse SHORT puanını artır
        if opportunity['current_price'] > opportunity.get('bb_middle', 0):
            opportunity['short_score'] += 10
            
        # Fiyat EMA20'nin üzerindeyse SHORT puanını artır
        if opportunity['current_price'] > opportunity['ema20']:
            opportunity['short_score'] += 5
            
        # MACD histogramı negatifse SHORT puanını artır
        if opportunity.get('hist', 0) < 0:
            opportunity['short_score'] += 10
            
        # Sinyal yeniden belirle
        opportunity['signal'] = self._determine_trade_signal_clear(
            opportunity['long_score'], 
            opportunity['short_score']
        )
        
        # Opportunity score güncelle
        opportunity['opportunity_score'] = max(opportunity['long_score'], opportunity['short_score'])

    def _adjust_for_medium_term(self, opportunity):
        """4 saatlik işlemler için ayarlamalar yap"""
        # EMA20 ve EMA50 arasındaki fark büyükse trend güçlü
        ema_diff = abs(opportunity['ema20'] - opportunity['ema50']) / opportunity['ema50'] * 100
        
        if ema_diff > 2:
            # Trend yönüne göre puanı artır
            if opportunity['ema20'] > opportunity['ema50']:
                opportunity['long_score'] += 10
            else:
                opportunity['short_score'] += 10
        
        # RSI trendine göre puanı ayarla
        if opportunity['rsi'] < 40:
            opportunity['long_score'] += 10
        elif opportunity['rsi'] > 60:
            opportunity['short_score'] += 10
        
        # Sinyal yeniden belirle
        opportunity['signal'] = self._determine_trade_signal_clear(
            opportunity['long_score'], 
            opportunity['short_score']
        )
        
        # Opportunity score güncelle
        opportunity['opportunity_score'] = max(opportunity['long_score'], opportunity['short_score'])

    def _adjust_for_long_term(self, opportunity):
        """Günlük işlemler için ayarlamalar yap"""
        # EMA200 ile fiyat karşılaştırması - uzun vadeli trend
        if opportunity['current_price'] > opportunity['ema200']:
            opportunity['long_score'] += 15
        else:
            opportunity['short_score'] += 15
        
        # Hacim analizi - yüksek hacim daha önemli
        if opportunity['volume'] > self.min_volume * 5:
            # Mevcut trendi güçlendir
            if opportunity['long_score'] > opportunity['short_score']:
                opportunity['long_score'] += 10
            else:
                opportunity['short_score'] += 10
        
        # Sinyal yeniden belirle
        opportunity['signal'] = self._determine_trade_signal_clear(
            opportunity['long_score'], 
            opportunity['short_score']
        )
        
        # Opportunity score güncelle
        opportunity['opportunity_score'] = max(opportunity['long_score'], opportunity['short_score'])

    def _determine_trade_signal_clear(self, long_score: float, short_score: float) -> str:
        """Net işlem sinyali belirle"""
        # Debug için puanları logla
        self.logger.debug(f"LONG Score: {long_score}, SHORT Score: {short_score}")
        
        # Puanlar arasındaki fark
        score_diff = abs(long_score - short_score)
        
        # Puanlar birbirine çok yakınsa, bekle sinyali ver
        if score_diff < 15:
            return "BEKLEYİN - Belirsiz Piyasa"
        
        # LONG sinyali
        if long_score > short_score:
            if long_score >= 70:
                return "LONG GİR - Güçlü Sinyal"
            elif long_score >= 55:
                return "LONG GİR"
            else:
                return "LONG GİR - Zayıf Sinyal"
        # SHORT sinyali
        else:  # short_score >= long_score
            if short_score >= 70:
                return "SHORT GİR - Güçlü Sinyal"
            elif short_score >= 55:
                return "SHORT GİR"
            else:
                return "SHORT GİR - Zayıf Sinyal"

    def _calculate_target_stop(self, current_price: float, signal: str, resistance_levels: List[float], support_levels: List[float]) -> Tuple[float, float]:
        """Hedef ve stop fiyatlarını hesapla"""
        try:
            # Varsayılan değerler
            target_price = current_price
            stop_price = current_price
            
            # Direnç ve destek seviyelerini sırala
            resistance_levels = sorted([r for r in resistance_levels if r > current_price])
            support_levels = sorted([s for s in support_levels if s < current_price], reverse=True)
            
            # Sinyal türüne göre hedef ve stop belirle
            if "LONG" in signal or "ALIM" in signal:
                # LONG için hedef: en yakın direnç seviyesi
                if resistance_levels:
                    target_price = resistance_levels[0]
                else:
                    # Direnç yoksa fiyatın %3 üstü
                    target_price = current_price * 1.03
                    
                # LONG için stop: en yakın destek seviyesi
                if support_levels:
                    stop_price = support_levels[0]
                else:
                    # Destek yoksa fiyatın %2 altı
                    stop_price = current_price * 0.98
                    
            elif "SHORT" in signal or "SATIŞ" in signal:
                # SHORT için hedef: en yakın destek seviyesi
                if support_levels:
                    target_price = support_levels[0]
                else:
                    # Destek yoksa fiyatın %3 altı
                    target_price = current_price * 0.97
                    
                # SHORT için stop: en yakın direnç seviyesi
                if resistance_levels:
                    stop_price = resistance_levels[0]
                else:
                    # Direnç yoksa fiyatın %2 üstü
                    stop_price = current_price * 1.02
            
            # Minimum risk/ödül oranı kontrolü
            risk = abs(current_price - stop_price)
            reward = abs(current_price - target_price)
            
            # Risk/ödül oranı en az 1.5 olsun
            if reward / risk < 1.5:
                if "LONG" in signal or "ALIM" in signal:
                    target_price = current_price + (1.5 * risk)
                elif "SHORT" in signal or "SATIŞ" in signal:
                    target_price = current_price - (1.5 * risk)
            
            self.logger.debug(f"Hesaplanan hedef: {target_price}, stop: {stop_price}, sinyal: {signal}")
            return target_price, stop_price
            
        except Exception as e:
            self.logger.error(f"Hedef/stop hesaplama hatası: {e}")
            # Hata durumunda varsayılan değerler
            if "LONG" in signal or "ALIM" in signal:
                return current_price * 1.03, current_price * 0.98
            elif "SHORT" in signal or "SATIŞ" in signal:
                return current_price * 0.97, current_price * 1.02
            else:
                return current_price * 1.01, current_price * 0.99

    def _find_support_resistance(self, lows: np.ndarray, highs: np.ndarray, closes: np.ndarray, window: int = 10, threshold: float = 0.01) -> Tuple[List[float], List[float]]:
        """Destek ve direnç seviyelerini bul"""
        try:
            # Son fiyat
            last_price = closes[-1]
            
            # Yerel minimum ve maksimumları bul
            min_idx = argrelextrema(lows, np.less, order=window)[0]
            max_idx = argrelextrema(highs, np.greater, order=window)[0]
            
            # Destek seviyeleri (yerel minimumlar)
            support_levels = [lows[i] for i in min_idx if lows[i] < last_price]
            
            # Direnç seviyeleri (yerel maksimumlar)
            resistance_levels = [highs[i] for i in max_idx if highs[i] > last_price]
            
            # Pivot noktalarını hesapla
            pivot_points = self._calculate_pivot_points(highs, lows, closes)
            
            # Pivot destek seviyelerini ekle
            for key in ['S1', 'S2', 'S3']:
                if key in pivot_points and pivot_points[key] < last_price:
                    support_levels.append(pivot_points[key])
                    
            # Pivot direnç seviyelerini ekle
            for key in ['R1', 'R2', 'R3']:
                if key in pivot_points and pivot_points[key] > last_price:
                    resistance_levels.append(pivot_points[key])
                    
            # Seviyeleri konsolide et
            support_levels = self._consolidate_levels(support_levels, threshold)
            resistance_levels = self._consolidate_levels(resistance_levels, threshold)
            
            # Seviyeleri sırala
            support_levels.sort(reverse=True)  # Yüksekten düşüğe
            resistance_levels.sort()  # Düşükten yükseğe
            
            return support_levels, resistance_levels
            
        except Exception as e:
            self.logger.error(f"Destek/direnç bulma hatası: {e}")
            return [], []

    def _consolidate_levels(self, levels: List[float], threshold: float = 0.01) -> List[float]:
        """Yakın seviyeleri birleştir"""
        if not levels:
            return []
            
        # Seviyeleri sırala
        levels = sorted(levels)
        
        # Konsolide edilmiş seviyeler
        consolidated = [levels[0]]
        
        # Yakın seviyeleri birleştir
        for level in levels[1:]:
            if abs(level - consolidated[-1]) / consolidated[-1] > threshold:
                consolidated.append(level)
                
        return consolidated

    def _calculate_pivot_points(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Dict[str, float]:
        """Pivot noktalarını hesapla"""
        try:
            # Son günün değerlerini al
            high = highs[-1]
            low = lows[-1]
            close = closes[-1]
            
            # Pivot noktası
            pp = (high + low + close) / 3
            
            # Destek seviyeleri
            s1 = (2 * pp) - high
            s2 = pp - (high - low)
            s3 = low - 2 * (high - pp)
            
            # Direnç seviyeleri
            r1 = (2 * pp) - low
            r2 = pp + (high - low)
            r3 = high + 2 * (pp - low)
            
            return {
                'PP': float(pp),
                'S1': float(s1),
                'S2': float(s2),
                'S3': float(s3),
                'R1': float(r1),
                'R2': float(r2),
                'R3': float(r3)
            }
        except Exception as e:
            self.logger.error(f"Pivot noktaları hesaplama hatası: {e}")
            return {}

    async def generate_chart(self, symbol: str, interval: str = "4h") -> Optional[BytesIO]:
        """Teknik analiz grafiği oluştur"""
        try:
            # OHLCV verilerini al
            klines = await self.get_klines_data(symbol, interval)
            if not klines or len(klines) < 50:
                self.logger.warning(f"Yetersiz kline verisi: {symbol}")
                return None
                
            # Pandas DataFrame'e dönüştür
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
            
            # Veri tiplerini dönüştür
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            
            # DataFrame'i indeksle
            df.set_index('timestamp', inplace=True)
            
            # Teknik göstergeleri hesapla
            df['ema20'] = self.ta.calculate_ema(df['close'].values, 20)
            df['ema50'] = self.ta.calculate_ema(df['close'].values, 50)
            df['ema200'] = self.ta.calculate_ema(df['close'].values, 200)
            
            # RSI
            df['rsi'] = self.ta.calculate_rsi(df['close'].values)
            
            # MACD
            macd, signal, hist = self.ta.calculate_macd(df['close'].values)
            df['macd'] = macd
            df['signal'] = signal
            df['hist'] = hist
            
            # Bollinger Bands
            bb_upper, bb_middle, bb_lower = self.ta.calculate_bollinger_bands(df['close'].values)
            df['bb_upper'] = bb_upper
            df['bb_middle'] = bb_middle
            df['bb_lower'] = bb_lower
            
            # Son 100 mum göster
            df = df.iloc[-100:]
            
            # Grafik ayarları
            mc = mpf.make_marketcolors(up='green', down='red', edge='black', wick='black', volume='green')
            s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
            
            # Ek göstergeler
            apds = [
                mpf.make_addplot(df['ema20'], color='blue', width=1),
                mpf.make_addplot(df['ema50'], color='orange', width=1),
                mpf.make_addplot(df['ema200'], color='purple', width=1.5),
                mpf.make_addplot(df['bb_upper'], color='gray', width=1, linestyle='--'),
                mpf.make_addplot(df['bb_middle'], color='gray', width=1),
                mpf.make_addplot(df['bb_lower'], color='gray', width=1, linestyle='--'),
                mpf.make_addplot(df['rsi'], panel=1, color='red', width=1),
                mpf.make_addplot(df['macd'], panel=2, color='blue', width=1),
                mpf.make_addplot(df['signal'], panel=2, color='orange', width=1),
                mpf.make_addplot(df['hist'], panel=2, type='bar', color='gray')
            ]
            
            # Grafik başlığı
            title = f'{symbol} - {interval} Grafiği'
            
            # Grafik oluştur
            buf = BytesIO()
            fig, axes = mpf.plot(df, type='candle', style=s, addplot=apds, volume=True, 
                                panel_ratios=(6, 2, 2), figsize=(12, 10), title=title, 
                                returnfig=True)
            
            # RSI paneline 30 ve 70 çizgileri ekle
            axes[2].axhline(y=30, color='green', linestyle='--', alpha=0.5)
            axes[2].axhline(y=70, color='red', linestyle='--', alpha=0.5)
            
            # MACD paneline 0 çizgisi ekle
            axes[3].axhline(y=0, color='black', linestyle='-', alpha=0.5)
            
            # Grafiği kaydet
            fig.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            
            return buf
            
        except Exception as e:
            self.logger.error(f"Grafik oluşturma hatası ({symbol}): {e}")
            return None

    def get_bb_signal(self, bb_position: float) -> str:
        """Bollinger Bands sinyali belirle"""
        if bb_position <= 0:
            return "💚 GÜÇLÜ ALIM"
        elif bb_position <= 20:
            return "💛 ALIM"
        elif bb_position >= 100:
            return "🔴 GÜÇLÜ SATIŞ"
        elif bb_position >= 80:
            return "🟡 SATIŞ"
        elif bb_position >= 70:  # Ek kontrol - SHORT potansiyeli
            return "🟠 SATIŞ POTANSİYELİ"
        elif bb_position <= 30:  # Ek kontrol - LONG potansiyeli
            return "🟢 ALIM POTANSİYELİ"
        else:
            return "⚪ NÖTR"

    def format_opportunities(self, opportunities: list, interval: str) -> list:
        """Fırsatları formatla"""
        messages = []
        
        # Zaman dilimi metni
        if interval == "15m":
            time_frame = "15 DAKİKALIK"
        elif interval == "4h":
            time_frame = "4 SAATLİK"
        elif interval == "1d":
            time_frame = "GÜNLÜK"
        else:
            time_frame = interval.upper()
        
        for opp in opportunities:
            # Değerler 0 ise veya None ise, varsayılan değerler kullan
            current_price = opp.get('current_price', 0)
            
            # EMA Sinyalleri
            ema_signal = "YUKARI TREND" if opp.get('ema20', 0) > opp.get('ema50', 0) else "AŞAĞI TREND"
            ema_cross = abs(opp.get('ema20', 0) - opp.get('ema50', 0)) / opp.get('ema50', 1) * 100
            
            # Bollinger Bands Analizi
            bb_position = opp.get('bb_position', 50)
            
            # Stop Loss ve Take Profit bilgileri
            stop_loss = opp.get('stop_price', 0)
            take_profit = opp.get('target_price', 0)
            risk_reward = opp.get('risk_reward', 0)
            
            # Volatilite bilgisi
            volatility = opp.get('volatility', 0)
            volatility_text = "DÜŞÜK" if volatility < 1.0 else "ORTA" if volatility < 2.0 else "YÜKSEK"
            
            # Hacim trendi
            volume_trend = opp.get('volume_trend', 'NORMAL_HACIM')
            volume_change = opp.get('volume_change', 0)
            
            if volume_trend == "ARTAN_HACIM_YUKARI":
                volume_text = f"ARTAN HACİM (↑ %{abs(volume_change):.1f})"
            elif volume_trend == "ARTAN_HACIM_ASAGI":
                volume_text = f"ARTAN HACİM (↑ %{abs(volume_change):.1f})"
            elif volume_trend == "AZALAN_HACIM_YUKARI":
                volume_text = f"AZALAN HACİM (↓ %{abs(volume_change):.1f})"
            elif volume_trend == "AZALAN_HACIM_ASAGI":
                volume_text = f"AZALAN HACİM (↓ %{abs(volume_change):.1f})"
            else:
                volume_text = f"NORMAL HACİM (%{volume_change:.1f})"
            
            # Stochastic bilgisi
            stoch_k = opp.get('stoch_k', 50)
            stoch_d = opp.get('stoch_d', 50)
            
            if stoch_k < 20:
                stoch_text = f"AŞIRI SATIM ({stoch_k:.1f})"
            elif stoch_k > 80:
                stoch_text = f"AŞIRI ALIM ({stoch_k:.1f})"
            else:
                stoch_text = f"NÖTR ({stoch_k:.1f})"
            
            # İşlem gerekçesi
            reason = ""
            if "LONG" in opp.get('signal', ''):
                if opp.get('rsi', 50) < 30:
                    reason += "• RSI aşırı satım bölgesinde\n"
                if stoch_k < 20:
                    reason += "• Stochastic aşırı satım bölgesinde\n"
                if opp.get('bb_position', 50) < 20:
                    reason += "• Fiyat BB alt bandına yakın\n"
                if volume_trend == "ARTAN_HACIM_YUKARI":
                    reason += "• Artan hacimle yükseliş var\n"
                if opp.get('ema20', 0) > opp.get('ema50', 0):
                    reason += "• EMA20 > EMA50 (yukarı trend)\n"
            elif "SHORT" in opp.get('signal', ''):
                if opp.get('rsi', 50) > 70:
                    reason += "• RSI aşırı alım bölgesinde\n"
                if stoch_k > 80:
                    reason += "• Stochastic aşırı alım bölgesinde\n"
                if opp.get('bb_position', 50) > 80:
                    reason += "• Fiyat BB üst bandına yakın\n"
                if volume_trend == "ARTAN_HACIM_ASAGI":
                    reason += "• Artan hacimle düşüş var\n"
                if opp.get('ema20', 0) < opp.get('ema50', 0):
                    reason += "• EMA20 < EMA50 (aşağı trend)\n"
            
            if not reason:
                reason = "• Teknik göstergeler işlem sinyali veriyor\n"
            
            message = (
                f"💰 {opp['symbol']} - {time_frame} İŞLEM\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💵 Fiyat: ${current_price:.4f}\n"
                f"📊 RSI: {opp.get('rsi', 0):.1f}\n"
                f"📈 Trend: {ema_signal}\n"
                f"⚡ Hacim: ${opp.get('volume', 0):,.0f}\n"
                f"🌡️ Volatilite: {volatility_text}\n\n"
                f"📈 TEKNİK ANALİZ:\n"
                f"• EMA Trend: {ema_signal} ({ema_cross:.1f}%)\n"
                f"• BB Pozisyon: {bb_position:.1f}%\n"
                f"• MACD: {opp.get('macd', 0):.4f}\n"
                f"• RSI: {opp.get('rsi', 0):.1f}\n"
                f"• Stochastic: {stoch_text}\n\n"
                f"🎯 İŞLEM ÖNERİSİ: {opp.get('signal', 'BEKLEYİN')}\n"
                f"📝 GEREKÇE:\n{reason}\n"
                f"🛑 Stop Loss: ${stop_loss:.4f}\n"
                f"✨ Take Profit: ${take_profit:.4f}\n"
                f"⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                f"⭐ Fırsat Puanı: {opp.get('opportunity_score', 0):.1f}/100\n"
                f"━━━━━━━━━━━━━━━━"
            )
            messages.append(message)
        return messages

    def _calculate_volatility(self, closes: np.ndarray, window: int = 14) -> float:
        """Fiyat volatilitesini hesapla (ATR benzeri)"""
        try:
            # Günlük değişim yüzdesi
            pct_changes = np.diff(closes) / closes[:-1] * 100
            
            # Son N günün volatilitesi (standart sapma)
            volatility = np.std(pct_changes[-window:])
            
            return volatility
        except Exception as e:
            self.logger.error(f"Volatilite hesaplama hatası: {e}")
            return 0

    def _analyze_volume_trend(self, volumes: np.ndarray, closes: np.ndarray, window: int = 5) -> Tuple[str, float]:
        """Hacim trendini analiz et"""
        try:
            # Son N günün hacim ortalaması
            recent_volume_avg = np.mean(volumes[-window:])
            
            # Önceki N günün hacim ortalaması
            previous_volume_avg = np.mean(volumes[-2*window:-window])
            
            # Hacim değişim oranı
            volume_change = (recent_volume_avg / previous_volume_avg - 1) * 100
            
            # Fiyat değişimi
            price_change = (closes[-1] / closes[-window] - 1) * 100
            
            # Hacim ve fiyat trendini karşılaştır
            if volume_change > 20 and price_change > 0:
                return "ARTAN_HACIM_YUKARI", volume_change
            elif volume_change > 20 and price_change < 0:
                return "ARTAN_HACIM_ASAGI", volume_change
            elif volume_change < -20 and price_change > 0:
                return "AZALAN_HACIM_YUKARI", volume_change
            elif volume_change < -20 and price_change < 0:
                return "AZALAN_HACIM_ASAGI", volume_change
            else:
                return "NORMAL_HACIM", volume_change
            
        except Exception as e:
            self.logger.error(f"Hacim trendi analiz hatası: {e}")
            return "HATA", 0

    def _calculate_stochastic(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
        """Stochastic Oscillator hesapla"""
        try:
            # %K hesapla
            lowest_low = np.min(lows[-k_period:])
            highest_high = np.max(highs[-k_period:])
            
            if highest_high - lowest_low == 0:
                k = 50
            else:
                k = (closes[-1] - lowest_low) / (highest_high - lowest_low) * 100
            
            # %D hesapla (K'nın hareketli ortalaması)
            if len(closes) >= k_period + d_period:
                # Son d_period için K değerlerini hesapla
                k_values = []
                for i in range(d_period):
                    idx = -(i+1)
                    ll = np.min(lows[idx-k_period:idx])
                    hh = np.max(highs[idx-k_period:idx])
                    if hh - ll == 0:
                        k_values.append(50)
                    else:
                        k_values.append((closes[idx] - ll) / (hh - ll) * 100)
            
                d = np.mean(k_values)
            else:
                d = k
            
            return k, d
            
        except Exception as e:
            self.logger.error(f"Stochastic hesaplama hatası: {e}")
            return 50, 50

    async def get_all_tickers(self) -> List[Dict]:
        """Tüm sembollerin ticker verilerini al"""
        try:
            # Binance API'den tüm ticker verilerini al
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.binance.com/api/v3/ticker/24hr') as response:
                    if response.status == 200:
                        tickers = await response.json()
                        return tickers
                    else:
                        self.logger.error(f"Ticker verileri alınamadı: {response.status}")
                        return []
        except Exception as e:
            self.logger.error(f"Ticker verileri alma hatası: {e}")
            return []

    def _get_signal_text(self, long_score: float, short_score: float) -> str:
        """Puanlara göre işlem sinyali metni oluştur"""
        # Puanları karşılaştır
        if long_score >= 70 and long_score > short_score + 20:
            return "💚 GÜÇLÜ LONG"
        elif long_score >= 60 and long_score > short_score + 10:
            return "🟢 LONG"
        elif short_score >= 70 and short_score > long_score + 20:
            return "🔴 GÜÇLÜ SHORT"
        elif short_score >= 60 and short_score > long_score + 10:
            return "🟠 SHORT"
        elif long_score >= 50 and long_score > short_score:
            return "🟡 ZAYIF LONG"
        elif short_score >= 50 and short_score > long_score:
            return "🟡 ZAYIF SHORT"
        else:
            return "⚪ BEKLEYİN"