from ..data.binance_client import BinanceClient
from .indicators import Indicators
import numpy as np
import ccxt.async_support as ccxt
import pandas as pd
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import asyncio
import concurrent.futures
import multiprocessing
from functools import partial
from .advanced_analysis import AdvancedAnalyzer, SignalStrength
import matplotlib.pyplot as plt
import mplfinance as mpf
from io import BytesIO
import ta
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
import logging

class MarketAnalyzer:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('MarketAnalyzer')
        self.client = BinanceClient()
        self.indicators = Indicators()
        self.exchange = ccxt.binance()
        self.min_volume = 50000  # Minimum 50k USDT hacim (daha küçük coinleri de tarayabilmek için)
        self.min_price = 0.00001
        self.timeframe = '1h'  # 1 saatlik mum
        self.limit = 200  # Son 200 mum
        self.advanced_analyzer = AdvancedAnalyzer()
        
        # Debug için sayaçlar
        self.analysis_stats = {
            'total_coins': 0,
            'valid_pairs': 0,
            'price_filtered': 0,
            'volume_filtered': 0,
            'analysis_failed': 0,
            'analysis_success': 0
        }
        
        # Geçerli sembolleri başlangıçta boş bırak
        self.valid_symbols = set()
        
        # Kaldıraç limitleri
        self.max_leverage = 20  # Maksimum kaldıraç
        self.risk_levels = {
            'LOW': {'leverage': 2, 'min_score': 40},
            'MEDIUM': {'leverage': 5, 'min_score': 60},
            'HIGH': {'leverage': 10, 'min_score': 80},
            'EXTREME': {'leverage': 20, 'min_score': 90}
        }

        # Trading sinyalleri için eşikler
        self.signal_thresholds = {
            'STRONG_LONG': {'score': 80, 'rsi': 30, 'trend': 'YUKARI'},
            'LONG': {'score': 60, 'rsi': 40, 'trend': 'YUKARI'},
            'STRONG_SHORT': {'score': 80, 'rsi': 70, 'trend': 'AŞAĞI'},
            'SHORT': {'score': 60, 'rsi': 60, 'trend': 'AŞAĞI'},
            'NEUTRAL': {'score': 40, 'rsi': 45}
        }

        # Sinyal seviyeleri
        self.signal_levels = {
            'STRONG_BUY': {'min_score': 80, 'emoji': '🟢'},
            'BUY': {'min_score': 65, 'emoji': '🟡'},
            'NEUTRAL': {'min_score': 45, 'emoji': '⚪'},
            'SELL': {'min_score': 35, 'emoji': '🔴'},
            'STRONG_SELL': {'min_score': 0, 'emoji': '⛔'}
        }

    async def initialize(self):
        """
        Asenkron başlatma işlemleri için metod
        """
        await self._init_valid_symbols()
        
    async def _init_valid_symbols(self):
        """
        Geçerli sembolleri asenkron olarak yükle
        """
        try:
            exchange_info = await self.client.get_exchange_info()
            self.valid_symbols = [
                symbol['symbol'] for symbol in exchange_info['symbols']
                if symbol['status'] == 'TRADING' and symbol['quoteAsset'] == 'USDT'
            ]
            logging.info(f"Loaded {len(self.valid_symbols)} valid trading symbols")
        except Exception as e:
            logging.error(f"Error initializing valid symbols: {e}")
            self.valid_symbols = []

    async def analyze_market(self, ticker_data: list, interval: str = '4h') -> list:
        """Tüm market analizi"""
        try:
            opportunities = []
            
            # Sayaçları sıfırla
            self.analysis_stats = {key: 0 for key in self.analysis_stats}
            self.analysis_stats['total_coins'] = len(ticker_data)
            
            self.logger.info(f"🔍 Toplam {len(ticker_data)} coin taranıyor...")
            
            # Ticker verilerini al
            try:
                if not ticker_data:
                    # Eğer ticker_data boşsa, exchange'den al
                    ticker_data = await self.exchange.fetch_tickers()
                    ticker_data = [
                        {'symbol': symbol, 'lastPrice': ticker['last'], 'quoteVolume': ticker['quoteVolume']}
                        for symbol, ticker in ticker_data.items()
                    ]
            except Exception as e:
                self.logger.error(f"Ticker verisi alma hatası: {str(e)}")
                return []

            for ticker in ticker_data:
                try:
                    symbol = ticker['symbol']
                    
                    # Blacklist kontrolü
                    # Sadece USDT çiftlerini analiz et
                    if not symbol.endswith('USDT'):
                        continue
                        
                    # Blacklist karşılaştırma
                    blacklist = [
                        "EURUSDT", "GBPUSDT", "TRYUSDT", "USDTBRL", "USDTRUB", "AUDUSDT", "CADUSDT",
                        "JPYUSDT", "CNHUSDT", "CHFUSDT", "AUDUSDT", "NZDSUSDT", "RUBUSDT", "BUSDUSDT",
                        "TUSDUSDT", "USDCUSDT", "DAIUSDT", "FDUSDUSDT", "PYUSDUSDT", "BRLBIDR", "BRLRUB",
                        "USDTBKRW", "EURUSDC", "IDRTUSDT", "UAHUSDT", "VAIUSDT", "NGNUSDT", "BIDRUSDT", "BVNDUSDT", "BKRWUSDT"
                    ]
                    
                    # Kaldıraçlı tokenlar için pattern'ler
                    blacklist_patterns = ["UP", "DOWN", "BULL", "BEAR"]
                    
                    # Blacklist ve pattern kontrolleri
                    if symbol in blacklist:
                        self.logger.debug(f"🚫 {symbol} blacklist'te olduğu için atlandı")
                        continue
                        
                    if any(pattern in symbol for pattern in blacklist_patterns):
                        self.logger.debug(f"🚫 {symbol} kaldıraçlı token olduğu için atlandı ({[p for p in blacklist_patterns if p in symbol]})")
                        continue
                        
                    self.analysis_stats['valid_pairs'] += 1
                    
                    # Minimum fiyat kontrolü
                    current_price = float(ticker['lastPrice'])
                    if current_price < self.min_price:
                        self.analysis_stats['price_filtered'] += 1
                        self.logger.debug(f"💰 {symbol} düşük fiyat nedeniyle atlandı: {current_price}")
                        continue
                        
                    # Minimum hacim kontrolü - daha düşük hacim eşiği kullan
                    current_volume = float(ticker['quoteVolume'])
                    if current_volume < self.min_volume:  # 50k USDT'ye düşürüldü
                        self.analysis_stats['volume_filtered'] += 1
                        self.logger.debug(f"📊 {symbol} düşük hacim nedeniyle atlandı: {current_volume:.2f} USDT < {self.min_volume} USDT")
                        continue

                    # OHLCV verilerini al
                    try:
                        ohlcv = await self.exchange.fetch_ohlcv(symbol, interval, limit=100)
                        if not ohlcv or len(ohlcv) < 100:
                            self.analysis_stats['analysis_failed'] += 1
                            self.logger.debug(f"📈 {symbol} yetersiz OHLCV verisi")
                            continue
                            
                        self.logger.debug(f"✅ {symbol} analiz ediliyor...")
                        
                        # Verileri numpy dizilerine dönüştür
                        closes = np.array([float(candle[4]) for candle in ohlcv])
                        volumes = np.array([float(candle[5]) for candle in ohlcv])
                        
                        # Teknik indikatörleri hesapla
                        rsi = self._calculate_rsi(closes)
                        macd, signal, hist = self._calculate_macd(closes)
                        bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(closes)
                        ema20 = self._calculate_ema(closes, 20)
                        ema50 = self._calculate_ema(closes, 50)
                        
                        # Hacim analizi
                        avg_volume = np.mean(volumes[-20:])
                        volume_surge = current_volume > (avg_volume * 1.2)  # Hacim artış eşiğini düşürdük
                        
                        # Trend analizi
                        trend = "YUKARI" if ema20[-1] > ema50[-1] else "AŞAĞI"
                        
                        # Fırsat puanı hesapla
                        opportunity_score = self._calculate_opportunity_score(
                            rsi[-1],
                            hist[-1],
                            volume_surge,
                            trend,
                            current_volume,
                            avg_volume
                        )
                        
                        # Fırsat eşiğini düşürdük
                        if opportunity_score >= 40:  # 50'den 40'a düşürdük
                            position_rec = self._analyze_position_recommendation(
                                rsi[-1], hist[-1], ema20[-1], ema50[-1],
                                bb_upper, bb_lower, current_price, opportunity_score, volume_surge
                            )
                            
                            # Sinyal belirle
                            signal = self._determine_signal(opportunity_score, rsi[-1], trend)
                            
                            opportunity = {
                                'symbol': symbol,
                                'price': current_price,
                                'volume': current_volume,
                                'rsi': float(rsi[-1]),
                                'macd': float(hist[-1]),
                                'trend': trend,
                                'volume_surge': volume_surge,
                                'opportunity_score': float(opportunity_score),
                                'signal': signal,
                                'position_recommendation': position_rec['position'],
                                'position_confidence': position_rec['confidence'],
                                'recommended_leverage': position_rec['leverage'],
                                'risk_level': position_rec['risk_level'],
                                'analysis_reasons': position_rec['reasons'],
                                'score': position_rec['score'],
                                'ema20': float(ema20[-1]),
                                'ema50': float(ema50[-1]),
                                'bb_upper': float(bb_upper),
                                'bb_middle': float(bb_middle),
                                'bb_lower': float(bb_lower)
                            }
                            
                            opportunities.append(opportunity)
                            self.analysis_stats['analysis_success'] += 1
                            self.logger.debug(f"💎 {symbol} fırsat bulundu! Skor: {opportunity_score:.1f}")
                        
                    except Exception as e:
                        self.analysis_stats['analysis_failed'] += 1
                        self.logger.debug(f"❌ {symbol} analiz hatası: {str(e)}")
                        continue

                except Exception as e:
                    self.analysis_stats['analysis_failed'] += 1
                    self.logger.debug(f"❌ {symbol} işleme hatası: {str(e)}")
                    continue
            
            # Analiz istatistiklerini logla
            self.logger.info("\n📊 TARAMA İSTATİSTİKLERİ:")
            self.logger.info(f"📌 Toplam Coin: {self.analysis_stats['total_coins']}")
            self.logger.info(f"✅ Geçerli USDT Çiftleri: {self.analysis_stats['valid_pairs']}")
            self.logger.info(f"💰 Fiyat Filtresi: {self.analysis_stats['price_filtered']}")
            self.logger.info(f"📊 Hacim Filtresi: {self.analysis_stats['volume_filtered']}")
            self.logger.info(f"✨ Başarılı Analiz: {self.analysis_stats['analysis_success']}")
            self.logger.info(f"❌ Başarısız Analiz: {self.analysis_stats['analysis_failed']}")
            
            # Fırsatları puana göre sırala
            opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            if opportunities:
                self.logger.info(f"🎯 Bulunan Fırsat Sayısı: {len(opportunities)}")
            else:
                self.logger.info("❌ Fırsat bulunamadı")
            
            return opportunities[:10]  # En iyi 10 fırsatı döndür
            
        except Exception as e:
            self.logger.error(f"Market analysis error: {str(e)}")
            return []
        finally:
            try:
                await self.exchange.close()
            except:
                pass

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> np.ndarray:
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

        return rsi

    def _calculate_macd(self, prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """MACD hesapla"""
        exp1 = pd.Series(prices).ewm(span=12, adjust=False).mean()
        exp2 = pd.Series(prices).ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return macd.values, signal.values, hist.values

    def _calculate_bollinger_bands(self, prices: np.ndarray, period: int = 20) -> Tuple[float, float, float]:
        """Bollinger Bands hesapla"""
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        return upper, sma, lower

    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """EMA hesapla"""
        return pd.Series(prices).ewm(span=period, adjust=False).mean().values

    def _calculate_opportunity_score(self, rsi: float, macd: float, 
                                   volume_surge: bool, trend: str,
                                   current_volume: float, avg_volume: float) -> float:
        """Fırsat puanı hesapla (0-100)"""
        score = 0
        
        # RSI bazlı puan (0-30)
        if rsi < 30:  # Aşırı satım
            score += 30
        elif rsi > 70:  # Aşırı alım
            score += 10
        else:
            score += 20
            
        # MACD bazlı puan (0-20)
        if macd > 0:
            score += 20
        elif macd < 0:
            score += 5
        
        # Hacim bazlı puan (0-30)
        if volume_surge:
            score += 30
        else:
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            score += min(30, volume_ratio * 15)
            
        # Trend bazlı puan (0-20)
        if trend == "YUKARI":
            score += 20
        else:
            score += 10  # Düşüş trendinde de puan ver
            
        return min(100, score)

    def _format_position_signal(self, position_type: str) -> str:
        """Pozisyon sinyalini formatla"""
        signals = {
            'STRONG_LONG': "💚 GÜÇLÜ LONG",
            'LONG': "💚 LONG",
            'STRONG_SHORT': "❤️ GÜÇLÜ SHORT",
            'SHORT': "❤️ SHORT",
            'NEUTRAL': "⚪ NÖTR"
        }
        return signals.get(position_type, "⚪ NÖTR")

    def _determine_signal(self, score: float, rsi: float, trend: str) -> str:
        """Sinyal belirle"""
        # RSI bazlı ek kontroller
        rsi_extreme = False
        if rsi <= 30 or rsi >= 70:
            rsi_extreme = True

        # Trend bazlı ek kontroller
        trend_strong = trend in ["YUKARI", "AŞAĞI"]

        # Sinyal seviyesini belirle
        if score >= self.signal_levels['STRONG_BUY']['min_score'] and (rsi_extreme or trend_strong):
            return f"{self.signal_levels['STRONG_BUY']['emoji']} GÜÇLÜ AL"
        elif score >= self.signal_levels['BUY']['min_score']:
            return f"{self.signal_levels['BUY']['emoji']} AL"
        elif score >= self.signal_levels['NEUTRAL']['min_score']:
            return f"{self.signal_levels['NEUTRAL']['emoji']} NÖTR"
        elif score >= self.signal_levels['SELL']['min_score']:
            return f"{self.signal_levels['SELL']['emoji']} SAT"
        else:
            return f"{self.signal_levels['STRONG_SELL']['emoji']} GÜÇLÜ SAT"

    async def analyze_single_coin(self, symbol: str) -> Optional[Dict]:
        """Tek bir coin için analiz yap"""
        try:
            # API çağrısını kaldır veya devre dışı bırak
            if not self.valid_symbols:
                await self._init_valid_symbols()

            if symbol not in self.valid_symbols:
                self.logger.error(f"Invalid symbol: {symbol}")
                return None

            self.logger.debug(f"Analyzing {symbol}...")
            
            # OHLCV verilerini al - timeframe yerine interval kullan
            ohlcv = await self.exchange.fetch_ohlcv(symbol, interval='1h', limit=100)
            if not ohlcv or len(ohlcv) < 100:
                self.logger.error(f"Insufficient OHLCV data for {symbol}")
                return None
                
            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(candle[4]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Teknik indikatörleri hesapla
            rsi = self._calculate_rsi(closes)
            macd, signal, hist = self._calculate_macd(closes)
            bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(closes)
            
            # Hacim analizi
            avg_volume = np.mean(volumes[-20:])
            current_volume = float(ohlcv[-1][5]) if len(ohlcv) > 0 else 0
            volume_surge = current_volume > (avg_volume * 1.5)
            
            # Trend analizi
            ema20 = self._calculate_ema(closes, 20)
            ema50 = self._calculate_ema(closes, 50)
            trend = "YUKARI" if ema20[-1] > ema50[-1] else "AŞAĞI"
            
            # Fırsat puanı hesapla
            opportunity_score = self._calculate_opportunity_score(
                rsi[-1],
                hist[-1],
                volume_surge,
                trend,
                current_volume,
                avg_volume
            )
            
            # Pozisyon önerisi al
            position_rec = self._analyze_position_recommendation(
                rsi[-1], hist[-1], ema20[-1], ema50[-1],
                bb_upper, bb_lower, closes[-1], opportunity_score, volume_surge
            )
            
            # Sinyal belirle
            signal = self._determine_signal(opportunity_score, rsi[-1], trend)
            
            # Pozisyon yönü analizi ekle
            position_analysis = self.analyze_position_direction(pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']))
            
            return {
                'symbol': symbol,
                'price': closes[-1],
                'volume': current_volume,
                'rsi': float(rsi[-1]),
                'macd': float(hist[-1]),
                'trend': trend,
                'volume_surge': volume_surge,
                'opportunity_score': float(opportunity_score),
                'signal': signal,
                'position_recommendation': position_rec['position'],
                'position_confidence': position_rec['confidence'],
                'recommended_leverage': position_rec['leverage'],
                'risk_level': position_rec['risk_level'],
                'analysis_reasons': position_rec['reasons'],
                'score': position_rec['score'],
                'ema20': float(ema20[-1]),
                'ema50': float(ema50[-1]),
                'bb_upper': float(bb_upper),
                'bb_middle': float(bb_middle),
                'bb_lower': float(bb_lower),
                'position': position_analysis['direction'],
                'confidence': position_analysis['confidence'],
                'current_price': position_analysis['current_price'],
                'long_position': position_analysis['long_position'],
                'short_position': position_analysis['short_position'],
                'signals': position_analysis['signals']
            }
            
        except Exception as e:
            self.logger.error(f"Single coin analysis error ({symbol}): {str(e)}")
            return None
        finally:
            try:
                await self.exchange.close()
            except:
                pass

    def _calculate_atr(self, prices: np.ndarray, period: int = 14) -> float:
        """ATR (Average True Range) hesapla"""
        high = prices
        low = prices
        close = prices
        
        tr1 = np.abs(high[1:] - low[1:])
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = np.mean(tr[-period:])
        
        return float(atr)

    def _analyze_position_recommendation(self, 
                                  rsi: float, 
                                  macd: float, 
                                  ema20: float,
                                  ema50: float,
                                  bb_upper: float,
                                  bb_lower: float,
                                  current_price: float,
                                  opportunity_score: float,
                                  volume_surge: bool) -> dict:
        """Pozisyon önerisi analizi - Geliştirilmiş versiyon"""
        long_points = 0
        short_points = 0
        reasons = []
        
        # RSI Analizi - Daha net ayırım
        if rsi < 30:
            long_points += 4  # Arttırıldı
            reasons.append("💚 RSI aşırı satım bölgesinde (LONG)")
        elif rsi > 70:
            short_points += 4  # Arttırıldı
            reasons.append("❤️ RSI aşırı alım bölgesinde (SHORT)")
        elif rsi < 40:
            long_points += 2  # Daha yüksek aralık
            reasons.append("💚 RSI satım bölgesine yakın (LONG)")
        elif rsi > 60:
            short_points += 2  # Daha yüksek aralık
            reasons.append("❤️ RSI alım bölgesine yakın (SHORT)")
        # 40-60 aralığında hiçbir puan verme
            
        # MACD Analizi - Daha güçlü etki
        if macd > 0 and macd > abs(macd) * 0.05:  # Eşik arttırıldı
            long_points += 3  # Arttırıldı
            reasons.append("💚 MACD güçlü pozitif sinyal (LONG)")
        elif macd < 0 and abs(macd) > abs(macd) * 0.05:  # Eşik arttırıldı
            short_points += 3
            reasons.append("❤️ MACD güçlü negatif sinyal (SHORT)")
            
        # EMA Trend Analizi - Daha net trend ayrımı
        ema_diff_percent = (ema20 - ema50) / ema50 * 100
        
        if ema_diff_percent > 1:  # %1'den fazla fark
            long_points += 4  # Arttırıldı
            reasons.append("💚 Güçlü yükseliş trendi - EMA20 > EMA50 (LONG)")
        elif ema_diff_percent > 0.2:  # %0.2'den fazla fark
            long_points += 2  # Arttırıldı
            reasons.append("💚 Yükseliş trendi başlangıcı (LONG)")
        elif ema_diff_percent < -1:  # %1'den fazla fark
            short_points += 4  # Arttırıldı
            reasons.append("❤️ Güçlü düşüş trendi - EMA20 < EMA50 (SHORT)")
        elif ema_diff_percent < -0.2:  # %0.2'den fazla fark
            short_points += 2  # Arttırıldı
            reasons.append("❤️ Düşüş trendi başlangıcı (SHORT)")
        
        # Bollinger Bands Analizi - Net bir ayırım için
        if current_price > 0 and bb_upper > bb_lower:  # Sıfır kontrolü
            bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
            if bb_position < 10:  # Daha kesin sınırlar
                long_points += 5  # Arttırıldı
                reasons.append("💚 Fiyat BB alt bandının altında (GÜÇLÜ LONG)")
            elif bb_position < 20:
                long_points += 3
                reasons.append("💚 Fiyat BB alt bandına yakın (LONG)")
            elif bb_position > 90:  # Daha kesin sınırlar
                short_points += 5  # Arttırıldı
                reasons.append("❤️ Fiyat BB üst bandının üstünde (GÜÇLÜ SHORT)")
            elif bb_position > 80:
                short_points += 3
                reasons.append("❤️ Fiyat BB üst bandına yakın (SHORT)")
        
        # Hacim analizi - Daha net yorumla
        if volume_surge:
            if long_points > short_points * 1.5:  # Büyük fark varsa hacim sinyali güçlendir
                long_points += 3  # Arttırıldı
                reasons.append("💚 Yüksek hacimle yükseliş (LONG)")
            elif short_points > long_points * 1.5:  # Büyük fark varsa hacim sinyali güçlendir
                short_points += 3  # Arttırıldı
                reasons.append("❤️ Yüksek hacimle düşüş (SHORT)")
        
        # Eklenen emniyet kontrolü - minimum puan farkı
        if abs(long_points - short_points) < 2:
            # Puanlar çok yakınsa, EMA trendine göre karar ver
            if ema20 > ema50:
                long_points += 1
            else:
                short_points += 1
        
        # Pozisyon türünü ve gücünü belirle - daha net ayırım
        if long_points > short_points + 2:  # Minimum fark şartı
            if long_points >= 8:  # Yükseltildi
                position_type = "STRONG_LONG"
                confidence = 3
            else:
                position_type = "LONG"
                confidence = 2
        elif short_points > long_points + 2:  # Minimum fark şartı
            if short_points >= 8:  # Yükseltildi
                position_type = "STRONG_SHORT"
                confidence = 3
            else:
                position_type = "SHORT"
                confidence = 2
        else:
            position_type = "NEUTRAL"
            confidence = 1
        
        # Kaldıraç önerisi
        leverage = self._recommend_leverage(opportunity_score, position_type, confidence)
        
        # Debug için ekstra bilgi ekle
        debug_info = {
            'long_points': long_points,
            'short_points': short_points,
            'ema_diff_percent': ema_diff_percent
        }
        
        return {
            'position': position_type,
            'confidence': confidence,
            'leverage': leverage,
            'reasons': reasons,
            'risk_level': self._get_risk_level(leverage),
            'score': opportunity_score,
            'debug': debug_info  # Analiz için debug bilgisi
        }

    def _recommend_leverage(self, opportunity_score: float, position_type: str, confidence: int) -> int:
        """Kaldıraç önerisi hesapla"""
        # Base kaldıraç puanını hesapla
        if opportunity_score >= 90:
            base_leverage = self.risk_levels['EXTREME']['leverage']
        elif opportunity_score >= 80:
            base_leverage = self.risk_levels['HIGH']['leverage']
        elif opportunity_score >= 60:
            base_leverage = self.risk_levels['MEDIUM']['leverage']
        else:
            base_leverage = self.risk_levels['LOW']['leverage']
        
        # Pozisyon türüne göre ayarla
        if position_type.startswith('STRONG'):
            leverage = base_leverage
        elif position_type == 'NEUTRAL':
            leverage = max(2, base_leverage - 4)
        else:
            leverage = max(2, base_leverage - 2)
        
        # Güven skoruna göre ayarla
        leverage = leverage * confidence // 3
        
        return min(leverage, self.max_leverage)

    def _get_risk_level(self, leverage: int) -> str:
        """Kaldıraç seviyesine göre risk seviyesini belirle"""
        if leverage >= 15:
            return "⚠️ AŞIRI RİSKLİ"
        elif leverage >= 10:
            return "🔴 YÜKSEK RİSK"
        elif leverage >= 5:
            return "🟡 ORTA RİSK"
        else:
            return "🟢 DÜŞÜK RİSK"

    def _format_position_message(self, analysis: dict) -> str:
        """Pozisyon önerisi mesajını formatla"""
        position = analysis['position_recommendation']
        leverage = analysis['recommended_leverage']
        risk_level = analysis['risk_level']
        
        message = (
            f"📊 POZİSYON ÖNERİSİ:\n"
            f"{'🟢 LONG' if position == 'LONG' else '🔴 SHORT'} x{leverage}\n"
            f"Risk Seviyesi: {risk_level}\n\n"
            f"📝 Analiz Nedenleri:\n"
        )
        
        for reason in analysis['analysis_reasons']:
            message += f"• {reason}\n"
            
        return message 

    def analyze_volume_profile(self, df: pd.DataFrame) -> Dict:
        """Hacim profili analizi"""
        try:
            recent_volume = df['volume'].tail(20).mean()
            volume_sma = df['volume'].rolling(window=20).mean()
            
            volume_strength = 'WEAK'
            if recent_volume > volume_sma.mean() * 2:
                volume_strength = 'VERY_STRONG'
            elif recent_volume > volume_sma.mean() * 1.5:
                volume_strength = 'STRONG'
            elif recent_volume > volume_sma.mean() * 1.2:
                volume_strength = 'MODERATE'
                
            return {
                'strength': volume_strength,
                'recent_volume': float(recent_volume),
                'average_volume': float(volume_sma.mean())
            }
        except Exception as e:
            self.logger.error(f"Hacim profili analiz hatası: {e}")
            return {'strength': 'WEAK', 'recent_volume': 0, 'average_volume': 0}

    def analyze_trend_strength(self, df: pd.DataFrame) -> float:
        """Trend gücü analizi"""
        try:
            # EMA hesapla
            ema20 = df['close'].ewm(span=20, adjust=False).mean()
            ema50 = df['close'].ewm(span=50, adjust=False).mean()
            ema200 = df['close'].ewm(span=200, adjust=False).mean()
            
            # Trend yönü ve gücü
            trend_score = 0.0
            
            # Kısa vadeli trend
            if ema20.iloc[-1] > ema50.iloc[-1]:
                trend_score += 0.4
            
            # Orta vadeli trend
            if ema50.iloc[-1] > ema200.iloc[-1]:
                trend_score += 0.3
            
            # Momentum
            roc = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20] * 100
            if roc > 0:
                trend_score += 0.3
                
            return float(trend_score)
            
        except Exception as e:
            self.logger.error(f"Trend gücü analiz hatası: {e}")
            return 0.0

    def analyze_momentum(self, df: pd.DataFrame) -> Dict:
        """Momentum analizi"""
        try:
            # RSI
            rsi = self.calculate_rsi(df)
            
            # MACD
            macd = self.calculate_macd(df['close'].to_numpy())
            
            # Momentum gücü
            momentum_strength = 'WEAK'
            if rsi > 70 and macd[0][-1] > 0:
                momentum_strength = 'VERY_STRONG'
            elif rsi > 60 and macd[0][-1] > 0:
                momentum_strength = 'STRONG'
            elif rsi > 50 and macd[0][-1] > 0:
                momentum_strength = 'MODERATE'
                
            return {
                'strength': momentum_strength,
                'rsi': float(rsi),
                'macd': float(macd[0][-1])
            }
        except Exception as e:
            self.logger.error(f"Momentum analiz hatası: {e}")
            return {'strength': 'WEAK', 'rsi': 50, 'macd': 0}

    def analyze_liquidity(self, df: pd.DataFrame) -> Dict:
        """Likidite analizi"""
        try:
            # Hacim bazlı likidite skoru
            volume_mean = df['volume'].mean()
            recent_volume = df['volume'].tail(20).mean()
            liquidity_score = min(1.0, recent_volume / volume_mean)
            
            return {
                'score': float(liquidity_score),
                'average_volume': float(volume_mean),
                'recent_volume': float(recent_volume)
            }
        except Exception as e:
            self.logger.error(f"Likidite analiz hatası: {e}")
            return {'score': 0.0, 'average_volume': 0, 'recent_volume': 0}

    def calculate_volatility(self, df: pd.DataFrame) -> float:
        """Volatilite hesaplama"""
        try:
            returns = df['close'].pct_change()
            return float(returns.std())
        except Exception as e:
            self.logger.error(f"Volatilite hesaplama hatası: {e}")
            return 0.0

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """ATR (Average True Range) hesaplama"""
        try:
            high = df['high']
            low = df['low']
            close = df['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            
            return float(atr.iloc[-1])
        except Exception as e:
            self.logger.error(f"ATR hesaplama hatası: {e}")
            return 0.0

    async def validate_advanced_signal(self, symbol: str, timeframe: str) -> Dict:
        """Gelişmiş sinyal doğrulama"""
        try:
            # OHLCV verilerini al
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=self.limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            score = 0
            required_score = {'15m': 12, '4h': 10}
            
            # Teknik analiz skoru
            analysis = await self.analyze_single_coin(symbol)
            if analysis and analysis.get('opportunity_score', 0) > 80:
                score += 3
            elif analysis and analysis.get('opportunity_score', 0) > 70:
                score += 2
            
            # Hacim analizi
            volume_profile = self.analyze_volume_profile(df)
            if volume_profile['strength'] == 'VERY_STRONG':
                score += 3
            elif volume_profile['strength'] == 'STRONG':
                score += 2
            
            # Trend gücü
            trend_strength = self.analyze_trend_strength(df)
            if trend_strength > 0.8:
                score += 3
            elif trend_strength > 0.6:
                score += 2
            
            # Momentum
            momentum = self.analyze_momentum(df)
            if momentum['strength'] == 'VERY_STRONG':
                score += 3
            elif momentum['strength'] == 'STRONG':
                score += 2
            
            # Likidite
            liquidity = self.analyze_liquidity(df)
            if liquidity['score'] > 0.8:
                score += 2
            elif liquidity['score'] > 0.6:
                score += 1
            
            return {
                'score': score,
                'required_score': required_score.get(timeframe, 10),
                'is_valid': score >= required_score.get(timeframe, 10),
                'confidence': score / 15 * 100
            }
            
        except Exception as e:
            self.logger.error(f"Gelişmiş sinyal doğrulama hatası: {e}")
            return {'is_valid': False, 'confidence': 0}

    def calculate_advanced_risk_management(self, df: pd.DataFrame, entry_price: float, timeframe: str) -> Optional[Dict]:
        """Gelişmiş risk yönetimi"""
        try:
            volatility = self.calculate_volatility(df)
            atr = self.calculate_atr(df)
            
            risk_factors = {
                '15m': {
                    'sl_mult': 1.5 + (volatility * 0.5),
                    'tp_mult': 3.0 + (volatility * 1.0),
                    'trailing_start': 1.5,
                    'partial_exit': [
                        {'percentage': 30, 'at_profit': 1.0},
                        {'percentage': 40, 'at_profit': 2.0},
                        {'percentage': 30, 'at_profit': 3.0}
                    ]
                },
                '4h': {
                    'sl_mult': 2.0 + (volatility * 0.7),
                    'tp_mult': 4.0 + (volatility * 1.5),
                    'trailing_start': 2.0,
                    'partial_exit': [
                        {'percentage': 20, 'at_profit': 1.5},
                        {'percentage': 30, 'at_profit': 3.0},
                        {'percentage': 30, 'at_profit': 4.5},
                        {'percentage': 20, 'at_profit': 6.0}
                    ]
                }
            }
            
            factors = risk_factors.get(timeframe, risk_factors['4h'])
            
            stop_loss = entry_price - (atr * factors['sl_mult'])
            take_profit = entry_price + (atr * factors['tp_mult'])
            trailing_activation = entry_price * (1 + factors['trailing_start'] / 100)
            
            rr_ratio = (take_profit - entry_price) / (entry_price - stop_loss)
            if rr_ratio < 2:
                return None
                
            return {
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'trailing_activation': float(trailing_activation),
                'trailing_step': float(atr * 0.3),
                'partial_exits': factors['partial_exit'],
                'risk_reward_ratio': float(rr_ratio)
            }
            
        except Exception as e:
            self.logger.error(f"Risk yönetimi hesaplama hatası: {e}")
            return None 

    def analyze_position_direction(self, df: pd.DataFrame) -> Dict:
        """Pozisyon yönü analizi"""
        try:
            # Son kapanış fiyatı
            current_price = float(df['close'].iloc[-1])
            
            # EMA hesapla
            ema20 = df['close'].ewm(span=20, adjust=False).mean()
            ema50 = df['close'].ewm(span=50, adjust=False).mean()
            
            # RSI
            rsi = self.calculate_rsi(df)
            
            # MACD
            macd, signal, hist = self.calculate_macd(df['close'].to_numpy())
            
            # Bollinger Bands
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df['close'].to_numpy())
            
            # Pozisyon yönü belirleme
            long_signals = 0
            short_signals = 0
            
            # EMA bazlı sinyal
            if current_price > ema20.iloc[-1] and ema20.iloc[-1] > ema50.iloc[-1]:
                long_signals += 1
            elif current_price < ema20.iloc[-1] and ema20.iloc[-1] < ema50.iloc[-1]:
                short_signals += 1
            
            # RSI bazlı sinyal
            if rsi < 30:
                long_signals += 1
            elif rsi > 70:
                short_signals += 1
            
            # MACD bazlı sinyal
            if hist[-1] > 0 and hist[-1] > hist[-2]:
                long_signals += 1
            elif hist[-1] < 0 and hist[-1] < hist[-2]:
                short_signals += 1
            
            # Bollinger Bands bazlı sinyal
            if current_price <= bb_lower[-1]:
                long_signals += 1
            elif current_price >= bb_upper[-1]:
                short_signals += 1
            
            # Stop loss seviyeleri hesaplama
            atr = self.calculate_atr(df)
            volatility = self.calculate_volatility(df)
            
            # Dinamik stop loss çarpanı
            sl_multiplier = 1.5 + (volatility * 0.5)
            
            # Long pozisyon için stop loss
            long_sl = current_price - (atr * sl_multiplier)
            # Short pozisyon için stop loss
            short_sl = current_price + (atr * sl_multiplier)
            
            # Risk/Ödül oranı hesaplama
            long_tp = current_price + (atr * sl_multiplier * 2)  # 1:2 risk/ödül
            short_tp = current_price - (atr * sl_multiplier * 2)
            
            # Pozisyon yönü belirleme
            direction = "NEUTRAL"
            if long_signals > short_signals and long_signals >= 2:
                direction = "LONG"
            elif short_signals > long_signals and short_signals >= 2:
                direction = "SHORT"
            
            return {
                'direction': direction,
                'confidence': max(long_signals, short_signals) / 4 * 100,  # Güven skoru
                'current_price': current_price,
                'long_position': {
                    'stop_loss': float(long_sl),
                    'take_profit': float(long_tp),
                    'risk_reward': float((long_tp - current_price) / (current_price - long_sl))
                },
                'short_position': {
                    'stop_loss': float(short_sl),
                    'take_profit': float(short_tp),
                    'risk_reward': float((current_price - short_tp) / (short_sl - current_price))
                },
                'signals': {
                    'long_signals': long_signals,
                    'short_signals': short_signals,
                    'rsi': float(rsi),
                    'macd_hist': float(hist[-1]),
                    'bb_position': 'OVERSOLD' if current_price <= bb_lower[-1] else 'OVERBOUGHT' if current_price >= bb_upper[-1] else 'NEUTRAL'
                }
            }
            
        except Exception as e:
            self.logger.error(f"Pozisyon yönü analiz hatası: {e}")
            return {
                'direction': 'NEUTRAL',
                'confidence': 0,
                'current_price': 0,
                'long_position': {'stop_loss': 0, 'take_profit': 0, 'risk_reward': 0},
                'short_position': {'stop_loss': 0, 'take_profit': 0, 'risk_reward': 0},
                'signals': {'long_signals': 0, 'short_signals': 0, 'rsi': 0, 'macd_hist': 0, 'bb_position': 'NEUTRAL'}
            }

    async def analyze_market_parallel(self, ticker_data: list, interval: str = '4h', worker_count=None) -> list:
        """Çoklu işlemci kullanarak piyasa analizi yapan yeni fonksiyon"""
        try:
            # Başlangıç zamanını kaydet (performans ölçümü için)
            import time
            start_time = time.time()
            
            # Sayaçları sıfırla
            self.analysis_stats = {key: 0 for key in self.analysis_stats}
            self.analysis_stats['total_coins'] = len(ticker_data)
            
            # İşçi sayısını belirleme (eğer belirtilmemişse)
            if worker_count is None:
                # Sistem CPU sayısına göre işçi sayısını belirle (CPU sayısı - 1)
                worker_count = max(1, multiprocessing.cpu_count() - 1)
                # İşlemci sayısını 6 ile sınırla (daha fazla işlemci genellikle daha yavaş olabilir)
                worker_count = min(worker_count, 6)
            
            # DEBUG: İşlemci bilgilerini logla
            self.logger.info(f"🔍 Toplam {len(ticker_data)} coin {worker_count} işlemci ile taranıyor...")
            self.logger.info(f"🖥️  Sistem toplam CPU sayısı: {multiprocessing.cpu_count()}")
            
            # Tüm USDT çiftlerini al (filtreleme olmadan)
            # Blacklist tanımla - FIAT paralar ve istenmeyenler
            blacklist = [
                "EURUSDT", "GBPUSDT", "TRYUSDT", "USDTBRL", "USDTRUB", "AUDUSDT", "CADUSDT",
                "JPYUSDT", "CNHUSDT", "CHFUSDT", "AUDUSDT", "NZDSUSDT", "RUBUSDT", "BUSDUSDT",
                "TUSDUSDT", "USDCUSDT", "DAIUSDT", "FDUSDUSDT", "PYUSDUSDT", "BRLBIDR", "BRLRUB",
                "USDTBKRW", "EURUSDC", "IDRTUSDT", "UAHUSDT", "VAIUSDT", "NGNUSDT", "BIDRUSDT", "BVNDUSDT", "BKRWUSDT"
            ]
            
            # Kaldıraçlı ve hatalı tokenlar için pattern'ler
            blacklist_patterns = [
                "UP", "DOWN", "BULL", "BEAR"
            ]
            
            # Tüm USDT çiftlerini al, ancak blacklist'tekileri ve blacklist pattern'leri hariç tut
            usdt_pairs = []
            filtered_out_count = 0
            
            for ticker in ticker_data:
                symbol = ticker['symbol']
                if symbol.endswith('USDT'):
                    # Blacklist kontrolü
                    if symbol in blacklist:
                        filtered_out_count += 1
                        continue
                        
                    # Blacklist pattern kontrolü
                    if any(pattern in symbol for pattern in blacklist_patterns):
                        filtered_out_count += 1
                        continue
                        
                    usdt_pairs.append(ticker)
            
            self.logger.info(f"📊 Toplam {len(usdt_pairs)} geçerli USDT çifti bulundu (blacklist'ten {filtered_out_count} coin filtrelendi)")
            
            self.analysis_stats['valid_pairs'] = len(usdt_pairs)
            
            # Ön filtreleme (fiyat ve hacim) - Multi-threaded yaparak hızlandırma
            filtered_pairs = []
            
            def filter_pair(ticker):
                try:
                    current_price = float(ticker['lastPrice'])
                    current_volume = float(ticker['quoteVolume'])
                    
                    if current_price < self.min_price:
                        return None
                    if current_volume < self.min_volume:
                        return None
                    return ticker
                except:
                    return None
            
            # Thread havuzu ile filtreleme - ana threadleri bloklamadan
            # Önceki ve sonraki işlemlerle paralellik için
            import threading
            filter_results = []
            
            def filter_batch(batch):
                results = []
                for ticker in batch:
                    result = filter_pair(ticker)
                    if result:
                        results.append(result)
                filter_results.extend(results)
            
            # Çok büyük veri kümeleri için thread'lere böl
            batch_size = len(usdt_pairs) // 4  # 4 thread kullan
            batches = [usdt_pairs[i:i+batch_size] for i in range(0, len(usdt_pairs), batch_size)]
            
            threads = []
            for batch in batches:
                thread = threading.Thread(target=filter_batch, args=(batch,))
                threads.append(thread)
                thread.start()
                
            # Tüm threadlerin tamamlanmasını bekle
            for thread in threads:
                thread.join()
                
            filtered_pairs = filter_results
            
            # Filtreleme istatistiklerini hesapla
            self.analysis_stats['price_filtered'] = 0
            self.analysis_stats['volume_filtered'] = 0
            for ticker in usdt_pairs:
                try:
                    if ticker not in filtered_pairs:
                        current_price = float(ticker['lastPrice'])
                        current_volume = float(ticker['quoteVolume'])
                        
                        if current_price < self.min_price:
                            self.analysis_stats['price_filtered'] += 1
                        elif current_volume < self.min_volume:
                            self.analysis_stats['volume_filtered'] += 1
                except Exception as e:
                    continue
            
            # İşlemci başına batch hesaplama - load dengesini daha iyi sağlamak için
            # Not: Büyük batche düşük işlemci sayısı daha iyi olabilir
            if len(filtered_pairs) < worker_count * 5:
                # Çok az coin varsa worker sayısını azalt
                worker_count = max(1, len(filtered_pairs) // 3)
                self.logger.info(f"⚠️  Çok az coin var. İşlemci sayısı {worker_count}'e düşürüldü.")
            
            # İşlemci başına düşen coin sayısını optimize etmek için batch size'i ayarla
            batch_size = max(1, min(10, len(filtered_pairs) // worker_count))
            batches = []
            
            # Daha akıllı load balancing - hacime göre sırala ve dağıt
            # Böylece her işlemciye hem yüksek hem düşük hacimli coinler düşer
            filtered_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
            
            # Hacim sıralı listeyi işlemcilere dağıt
            for i in range(worker_count):
                batch = filtered_pairs[i::worker_count]  # Her işlemciye bir coin atla
                if batch:  # Boş batch oluşturma
                    batches.append(batch)
            
            if not filtered_pairs:
                self.logger.warning("Filtreleme sonrası coin kalmadı!")
                return []
                
            self.logger.info(f"📌 Filtreleme sonrası {len(filtered_pairs)} coin analiz edilecek")
            self.logger.info(f"🛠️  {len(batches)} batch oluşturuldu (işlemci başına ~{len(filtered_pairs)/max(1, len(batches)):.1f} coin)")
            
            # Analiz işlemini paralel olarak çalıştır
            loop = asyncio.get_event_loop()
            
            opportunities = []
            with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
                # Her batch için _analyze_batch fonksiyonunu çağır
                analyze_batch_partial = partial(self._analyze_batch, interval=interval)
                
                # Senkronize edilerek yapılan RPC çağrısını ölç
                batch_start_time = time.time()
                batch_results = await loop.run_in_executor(
                    None,
                    lambda: list(executor.map(analyze_batch_partial, batches))
                )
                batch_end_time = time.time()
                batch_elapsed = batch_end_time - batch_start_time
                
                # İşlemci başına süreyi hesapla
                self.logger.info(f"⏱️  Paralel işlemler {batch_elapsed:.2f} saniyede tamamlandı (işlemci başına ~{batch_elapsed/max(1, len(batches)):.2f}s)")
                
                # DEBUG: işlemci başına analiz edilecek coin sayısını logla
                for i, batch in enumerate(batches):
                    self.logger.debug(f"Worker {i+1}: {len(batch)} coin analiz edilecek")
                
                # Sonuçları birleştir
                for i, batch_result in enumerate(batch_results):
                    # DEBUG: Her işlemcinin sonuçlarını logla
                    self.logger.debug(f"Worker {i+1} Sonucu: {len(batch_result['opportunities'])} fırsat bulundu, " + 
                                 f"Başarılı: {batch_result['stats']['success']}, " + 
                                 f"Başarısız: {batch_result['stats']['failed']}")
                    
                    opportunities.extend(batch_result['opportunities'])
                    
                    # İstatistikleri güncelle
                    self.analysis_stats['analysis_success'] += batch_result['stats']['success']
                    self.analysis_stats['analysis_failed'] += batch_result['stats']['failed']
                
            # Süre hesaplama
            end_time = time.time()
            elapsed_time = end_time - start_time
            
            # Analiz istatistiklerini logla
            self.logger.info("\n📊 TARAMA İSTATİSTİKLERİ:")
            self.logger.info(f"📌 Toplam Coin: {self.analysis_stats['total_coins']}")
            self.logger.info(f"✅ Geçerli USDT Çiftleri: {self.analysis_stats['valid_pairs']}")
            self.logger.info(f"💰 Fiyat Filtresi: {self.analysis_stats['price_filtered']}")
            self.logger.info(f"📊 Hacim Filtresi: {self.analysis_stats['volume_filtered']}")
            self.logger.info(f"✨ Başarılı Analiz: {self.analysis_stats['analysis_success']}")
            self.logger.info(f"❌ Başarısız Analiz: {self.analysis_stats['analysis_failed']}")
            self.logger.info(f"⏱️ Toplam Süre: {elapsed_time:.2f} saniye ({worker_count} işlemci ile)")
            
            # Fırsatları puana göre sırala
            opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            if opportunities:
                self.logger.info(f"🎯 Bulunan Fırsat Sayısı: {len(opportunities)}")
            else:
                self.logger.info("❌ Fırsat bulunamadı")
            
            return opportunities[:10]  # En iyi 10 fırsatı döndür
            
        except Exception as e:
            self.logger.error(f"Parallel market analysis error: {str(e)}")
            return []
        finally:
            try:
                await self.exchange.close()
            except:
                pass

    def _analyze_batch(self, batch: list, interval: str = '4h'):
        """Bir batch içindeki coinleri seri olarak analiz et - Process havuzunda çalışır"""
        import ccxt  # Yeni process için gereken importlar
        import pandas as pd
        import numpy as np
        import concurrent.futures
        import time
        
        start_time = time.time()
        opportunities = []
        stats = {'success': 0, 'failed': 0}
        
        # API çağrı sayısını azaltmak için bir exchange nesnesi oluştur
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        
        # Eş zamanlı işlem
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as thread_executor:
            # API çağrılarını eş zamanlı yap
            future_to_symbol = {}
            
            for ticker in batch:
                symbol = ticker['symbol']
                future = thread_executor.submit(
                    self._analyze_single_coin_data, 
                    exchange, 
                    symbol, 
                    interval, 
                    float(ticker['lastPrice']),
                    float(ticker['quoteVolume'])
                )
                future_to_symbol[future] = symbol
                
            # Tüm sonuçları topla
            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result = future.result()
                    if result:
                        opportunities.append(result)
                        stats['success'] += 1
                    else:
                        stats['failed'] += 1
                except Exception as e:
                    stats['failed'] += 1
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        # Peformanns debug bilgisi
        print(f"Batch of {len(batch)} coins processed in {elapsed:.2f}s - Success: {stats['success']}, Failed: {stats['failed']}")
        
        return {'opportunities': opportunities, 'stats': stats}
    
    def _analyze_single_coin_data(self, exchange, symbol, interval, current_price, current_volume):
        """Tek bir coin için analiz işlemi yap - Thread içinde çalışır"""
        try:
            # OHLCV verileri al
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, interval, limit=50)
                if not ohlcv or len(ohlcv) < 30:
                    return None
                
                # DataFrame oluştur (gelişmiş stop/loss hesaplaması için)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
            except Exception as e:
                return None
            
            # Temel hesaplamalar
            closes = np.array([float(candle[4]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Teknik indikatörler
            indicators = self._calculate_technical_indicators(closes, volumes)
            
            # Hacim analizi
            volume_analysis = self._analyze_volume(current_volume, volumes)
            
            # Fırsat puanı hesapla
            opportunity_score = self._calculate_opportunity_score(
                indicators['rsi'][-1],
                indicators['macd_hist'][-1],
                volume_analysis['volume_surge'],
                indicators['trend'],
                current_volume,
                volume_analysis['avg_volume']
            )
            
            if opportunity_score < 40:
                return None
            
            # Pozisyon önerisi
            position_rec = self._analyze_position_recommendation(
                indicators['rsi'][-1], 
                indicators['macd_hist'][-1],
                indicators['ema20'][-1],
                indicators['ema50'][-1],
                indicators['bb_upper'],
                indicators['bb_lower'],
                current_price,
                opportunity_score,
                volume_analysis['volume_surge']
            )
            
            # Gelişmiş stop/loss ve take profit hesapla
            risk_management = None
            actual_position_type = "LONG" if "LONG" in position_rec['position'] else "SHORT" if "SHORT" in position_rec['position'] else "NEUTRAL"
            
            if actual_position_type in ["LONG", "SHORT"]:
                risk_management = self.calculate_advanced_stoploss(df, current_price, actual_position_type)
            
            # Sonuç oluştur
            result = {
                'symbol': symbol,
                'price': current_price,
                'volume': current_volume,
                'rsi': float(indicators['rsi'][-1]),
                'macd': float(indicators['macd_hist'][-1]),
                'trend': indicators['trend'],
                'volume_surge': volume_analysis['volume_surge'],
                'opportunity_score': float(opportunity_score),
                'signal': self._determine_signal(opportunity_score, indicators['rsi'][-1], indicators['trend']),
                'position_recommendation': position_rec['position'],
                'position_confidence': position_rec['confidence'],
                'recommended_leverage': position_rec['leverage'],
                'risk_level': position_rec['risk_level'],
                'analysis_reasons': position_rec['reasons'],
                'score': position_rec['score'],
                'ema20': float(indicators['ema20'][-1]),
                'ema50': float(indicators['ema50'][-1]),
                'bb_upper': float(indicators['bb_upper']),
                'bb_middle': float(indicators['bb_middle']),
                'bb_lower': float(indicators['bb_lower'])
            }
            
            # Risk yönetimi bilgilerini ekle
            if risk_management:
                result.update({
                    'advanced_stoploss': risk_management['stoploss'],
                    'take_profit_levels': risk_management['take_profits'],
                    'trailing_activation': risk_management['trailing_activation'],
                    'trailing_step': risk_management['trailing_step'],
                    'risk_percent': risk_management['risk_percent'],
                    'atr': risk_management['atr']
                })
            
            return result
            
        except Exception as e:
            return None

    def _calculate_technical_indicators(self, closes: np.ndarray, volumes: np.ndarray) -> Dict:
        """Tüm teknik indikatörleri tek bir fonksiyonda hesapla"""
        try:
            # RSI
            rsi = self._calculate_rsi_quick(closes)
            
            # MACD
            macd, signal, hist = self._calculate_macd_quick(closes)
            
            # Bollinger Bands
            bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands_quick(closes)
            
            # EMA
            ema20 = self._calculate_ema_quick(closes, 20)
            ema50 = self._calculate_ema_quick(closes, 50)
            
            # Trend
            trend = "YUKARI" if ema20[-1] > ema50[-1] else "AŞAĞI"
            
            return {
                'rsi': rsi,
                'macd': macd,
                'macd_signal': signal,
                'macd_hist': hist,
                'bb_upper': bb_upper,
                'bb_middle': bb_middle,
                'bb_lower': bb_lower,
                'ema20': ema20,
                'ema50': ema50,
                'trend': trend
            }
        except Exception as e:
            self.logger.error(f"Teknik indikatör hesaplama hatası: {e}")
            return None

    def _analyze_volume(self, current_volume: float, volumes: np.ndarray) -> Dict:
        """Hacim analizini tek bir fonksiyonda yap"""
        try:
            avg_volume = np.mean(volumes[-10:])
            volume_surge = current_volume > (avg_volume * 1.2)
            
            return {
                'avg_volume': avg_volume,
                'volume_surge': volume_surge,
                'volume_ratio': current_volume / avg_volume if avg_volume > 0 else 1
            }
        except Exception as e:
            self.logger.error(f"Hacim analizi hatası: {e}")
            return {
                'avg_volume': 0,
                'volume_surge': False,
                'volume_ratio': 1
            }

    def _calculate_rsi_quick(self, prices, period=14):
        # Orijinal metot ile aynı ama optimize edildi
        # Son verileri kullanarak hızlı hesaplama
        deltas = np.diff(prices[-period-10:])  # Son periyot+10 veri al
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum()/period
        down = -seed[seed < 0].sum()/period
        rs = up/down if down != 0 else 0
        rsi = np.zeros(len(prices[-period-10:]))
        rsi[:period] = 100. - 100./(1.+rs)

        for i in range(period, len(prices[-period-10:])):
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

        return rsi[-5:]

    def _calculate_macd_quick(self, prices):
        # Karsılaştırma için son verileri al
        prices_subset = prices[-40:]  # Son 40 veri yeterli
        exp1 = pd.Series(prices_subset).ewm(span=12, adjust=False).mean()
        exp2 = pd.Series(prices_subset).ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return macd.values, signal.values, hist.values

    def _calculate_bollinger_bands_quick(self, prices, period=20):
        # Son verileri kullanarak BB hesapla
        prices_subset = prices[-period-5:]  # Son period+5 veri
        sma = np.mean(prices_subset[-period:])
        std = np.std(prices_subset[-period:])
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        return upper, sma, lower

    def _calculate_ema_quick(self, prices, period):
        # Son verileri kullanarak EMA hesapla
        prices_subset = prices[-period-15:]  # Son period+15 veri
        return pd.Series(prices_subset).ewm(span=period, adjust=False).mean().values

    def _calculate_opportunity_score_quick(self, rsi, macd, volume_surge, trend,
                                   current_volume, avg_volume):
        # Basitleştirilmiş fırsat puanı hesaplama
        score = 0
        
        # RSI bazlı puan (0-30)
        if rsi < 30:  # Aşırı satım
            score += 30
        elif rsi > 70:  # Aşırı alım
            score += 10
        else:
            score += 20
            
        # MACD bazlı puan (0-20)
        if macd > 0:
            score += 20
        elif macd < 0:
            score += 5
        
        # Hacim bazlı puan (0-30)
        if volume_surge:
            score += 30
        else:
            score += 20 if current_volume > avg_volume else 10
            
        # Trend bazlı puan (0-20)
        if trend == "YUKARI":
            score += 20
        else:
            score += 10
            
        return min(100, score)

    def _analyze_position_recommendation_quick(self, 
                                       rsi, 
                                       macd, 
                                       ema20,
                                       ema50,
                                       bb_upper,
                                       bb_lower,
                                       current_price,
                                       opportunity_score,
                                       volume_surge):
        # Basitleştirilmiş pozisyon önerisi
        is_bullish = (ema20 > ema50) or (rsi < 40) or (macd > 0)
        is_bearish = (ema20 < ema50) or (rsi > 60) or (macd < 0)
        
        if rsi < 30 and current_price < (bb_lower * 1.05):
            position_type = "STRONG_LONG"
            confidence = 3
            reasons = ["RSI aşırı satım bölgesinde", "Fiyat BB alt bandının altında"]
        elif rsi > 70 and current_price > (bb_upper * 0.95):
            position_type = "STRONG_SHORT"
            confidence = 3
            reasons = ["RSI aşırı alım bölgesinde", "Fiyat BB üst bandının üstünde"]
        elif is_bullish and not is_bearish:
            position_type = "LONG"
            confidence = 2
            reasons = ["Eğilim yükseliyor"]
        elif is_bearish and not is_bullish:
            position_type = "SHORT"
            confidence = 2
            reasons = ["Eğilim düşüyor"]
        else:
            position_type = "NEUTRAL"
            confidence = 1
            reasons = ["Net bir eğilim yok"]
            
        # Kaldıraç önerisi
        leverage = 2  # Varsayılan düşük kaldıraç
        if opportunity_score > 80:
            leverage = 10
        elif opportunity_score > 60:
            leverage = 5
            
        return {
            'position': position_type,
            'confidence': confidence,
            'leverage': leverage,
            'reasons': reasons,
            'risk_level': "YÜKSEK" if leverage > 5 else "ORTA",
            'score': opportunity_score
        }

    def _generate_signal(self, rsi: float, macd: float, price: float, bb_upper: float, bb_lower: float) -> str:
        """Sinyal üret"""
        try:
            if any(v is None for v in [rsi, macd, price, bb_upper, bb_lower]):
                return "VERİ YOK"
            
            # BB pozisyonu hesapla (0-100 arası)
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_position = (price - bb_lower) / bb_range * 100
            else:
                bb_position = 50
            
            # 15 dakikalık işlemler için SHORT sinyallerini daha agresif değerlendir
            if rsi > 60 and price >= bb_upper * 0.95:
                return "GÜÇLÜ SHORT"
            elif rsi > 55 and macd < 0:
                return "SHORT"
            elif rsi < 30 and price <= bb_lower * 1.05:
                return "GÜÇLÜ LONG"
            elif rsi < 40 and macd > 0:
                return "LONG"
            
            # BB pozisyonuna göre ek kontrol
            if bb_position > 80:
                return "SHORT"
            elif bb_position < 20:
                return "LONG"
            
            return "BEKLE"
            
        except Exception as e:
            self.logger.error(f"Sinyal üretme hatası: {e}")
            return "HATA" 

    def calculate_advanced_stoploss(self, df: pd.DataFrame, current_price: float, position_type: str) -> Dict:
        """Gelişmiş stop loss hesaplama"""
        try:
            # ATR hesapla
            atr = self.calculate_atr(df)
            volatility = self.calculate_volatility(df)
            
            # Stop loss çarpanı (volatiliteye göre ayarlanır)
            sl_multiplier = 1.5 + (volatility * 0.5)
            
            # Stop loss ve take profit seviyeleri
            if position_type == "LONG":
                stop_loss = current_price - (atr * sl_multiplier)
                take_profit = current_price + (atr * sl_multiplier * 2)  # 1:2 risk/ödül
                trailing_activation = current_price + (atr * sl_multiplier)
            else:  # SHORT
                stop_loss = current_price + (atr * sl_multiplier)
                take_profit = current_price - (atr * sl_multiplier * 2)
                trailing_activation = current_price - (atr * sl_multiplier)
            
            # Risk yüzdesi
            risk_percent = abs(current_price - stop_loss) / current_price * 100
            
            return {
                'stoploss': float(stop_loss),
                'take_profits': [float(take_profit)],
                'trailing_activation': float(trailing_activation),
                'trailing_step': float(atr * 0.3),
                'risk_percent': float(risk_percent),
                'atr': float(atr)
            }
            
        except Exception as e:
            self.logger.error(f"Stop loss hesaplama hatası: {e}")
            return None 

    async def generate_chart(self, symbol: str, timeframe: str = "4h") -> BytesIO:
        """
        Verilen sembol için teknik analiz grafiği oluşturur
        """
        try:
            # OHLCV verilerini al
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=100)
            
            if not ohlcv or len(ohlcv) < 20:
                self.logger.error(f"{symbol} için yeterli veri bulunamadı")
                return None
                
            # DataFrame oluştur
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            
            # Timestamp'i datetime'a çevir
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Teknik indikatörleri hesapla
            ema20 = EMAIndicator(close=df['close'], window=20)
            ema50 = EMAIndicator(close=df['close'], window=50)
            ema200 = EMAIndicator(close=df['close'], window=200)
            df['EMA20'] = ema20.ema_indicator()
            df['EMA50'] = ema50.ema_indicator()
            df['EMA200'] = ema200.ema_indicator()
            
            # RSI
            rsi = RSIIndicator(close=df['close'])
            df['RSI'] = rsi.rsi()
            
            # Bollinger Bands
            bb = BollingerBands(close=df['close'])
            df['BB_UPPER'] = bb.bollinger_hband()
            df['BB_MIDDLE'] = bb.bollinger_mavg()
            df['BB_LOWER'] = bb.bollinger_lband()
            
            # MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            # Grafik ayarları
            mc = mpf.make_marketcolors(
                up='green',
                down='red',
                edge='inherit',
                wick='inherit',
                volume='in',
                ohlc='inherit'
            )
            
            s = mpf.make_mpf_style(
                marketcolors=mc,
                gridstyle='dotted',
                y_on_right=True
            )
            
            # Grafik panellerini ayarla
            fig = mpf.figure(figsize=(12, 8), style=s)
            
            # Panel boyutlarını ayarla (yükseklik oranları)
            gs = fig.add_gridspec(6, 1)
            
            # Ana grafik paneli
            ax1 = fig.add_subplot(gs[0:3, :])
            # Hacim paneli
            ax2 = fig.add_subplot(gs[3:5, :], sharex=ax1)
            # RSI paneli
            ax3 = fig.add_subplot(gs[5, :], sharex=ax1)
            
            # Ana mum grafiği
            mpf.plot(
                df,
                type='candle',
                style=s,
                ax=ax1,
                volume=ax2,  # Hacim grafiği için ax2'yi kullan
                warn_too_much_data=10000
            )
            
            # EMA'ları ekle
            ax1.plot(df.index, df['EMA20'], label='EMA20', color='blue', alpha=0.7)
            ax1.plot(df.index, df['EMA50'], label='EMA50', color='orange', alpha=0.7)
            ax1.plot(df.index, df['EMA200'], label='EMA200', color='red', alpha=0.7)
            
            # Bollinger Bands
            ax1.plot(df.index, df['BB_UPPER'], '--', label='BB Upper', color='gray', alpha=0.5)
            ax1.plot(df.index, df['BB_MIDDLE'], '--', label='BB Middle', color='gray', alpha=0.5)
            ax1.plot(df.index, df['BB_LOWER'], '--', label='BB Lower', color='gray', alpha=0.5)
            
            # RSI grafiği
            ax3.plot(df.index, df['RSI'], label='RSI', color='purple')
            ax3.axhline(y=70, color='r', linestyle='--', alpha=0.3)
            ax3.axhline(y=30, color='g', linestyle='--', alpha=0.3)
            ax3.fill_between(df.index, df['RSI'], 70, where=(df['RSI'] >= 70), color='red', alpha=0.3)
            ax3.fill_between(df.index, df['RSI'], 30, where=(df['RSI'] <= 30), color='green', alpha=0.3)
            
            # Grafik başlığı ve etiketler
            ax1.set_title(f'{symbol} {timeframe} Grafiği')
            ax1.legend(loc='upper left')
            ax2.set_ylabel('Hacim')
            ax3.set_ylabel('RSI')
            
            # Y ekseni aralıklarını ayarla
            ax3.set_ylim(0, 100)
            
            # Grafik düzenlemeleri
            plt.tight_layout()
            
            # Grafiği BytesIO'ya kaydet
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            buf.seek(0)
            plt.close()
            
            return buf
            
        except Exception as e:
            self.logger.error(f"Grafik oluşturma hatası ({symbol}): {e}")
            return None

    def calculate_rsi(self, prices, period=14):
        """RSI hesapla"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
        
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """MACD hesapla"""
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram
        
    def calculate_bollinger_bands(self, prices, period=20, std=2):
        """Bollinger Bands hesapla"""
        middle = prices.rolling(window=period).mean()
        std_dev = prices.rolling(window=period).std()
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        return upper, middle, lower

    async def analyze_opportunity(self, symbol: str, timeframe: str = "4h") -> dict:
        """
        Belirli bir sembol için fırsat analizi yapar
        """
        try:
            # Kline verilerini al
            klines = await self.client.get_klines(symbol, interval=timeframe, limit=100)
            if not klines:
                return None
                
            # DataFrame'e çevir - tüm sütunları belirterek
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'buy_base_volume',
                'buy_quote_volume', 'ignore'
            ])
            
            # Sadece gerekli sütunları seç
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            # Veri tiplerini dönüştür
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Teknik göstergeleri hesapla
            rsi = self.calculate_rsi(df['close'])
            macd, signal, hist = self.calculate_macd(df['close'])
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(df['close'])
            
            # Son değerleri al
            current_price = float(df['close'].iloc[-1])
            current_rsi = float(rsi.iloc[-1])
            current_macd = float(macd.iloc[-1])
            current_signal = float(signal.iloc[-1])
            current_hist = float(hist.iloc[-1])
            
            # Trend analizi
            trend = "NEUTRAL"
            trend_strength = 0.0
            
            if current_rsi > 70:
                trend = "BEARISH"
                trend_strength = min((current_rsi - 70) / 30, 1.0)
            elif current_rsi < 30:
                trend = "BULLISH"
                trend_strength = min((30 - current_rsi) / 30, 1.0)
                
            if current_macd > current_signal:
                if trend == "BULLISH":
                    trend_strength += 0.2
                elif trend == "NEUTRAL":
                    trend = "BULLISH"
                    trend_strength = 0.3
            elif current_macd < current_signal:
                if trend == "BEARISH":
                    trend_strength += 0.2
                elif trend == "NEUTRAL":
                    trend = "BEARISH"
                    trend_strength = 0.3
                    
            # Sonuçları döndür
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "current_price": current_price,
                "rsi": current_rsi,
                "macd": current_macd,
                "macd_signal": current_signal,
                "macd_hist": current_hist,
                "trend": trend,
                "trend_strength": trend_strength,
                "bb_upper": float(bb_upper.iloc[-1]),
                "bb_middle": float(bb_middle.iloc[-1]),
                "bb_lower": float(bb_lower.iloc[-1])
            }
            
        except Exception as e:
            self.logger.error(f"Fırsat analizi hatası ({symbol}): {str(e)}")
            return None