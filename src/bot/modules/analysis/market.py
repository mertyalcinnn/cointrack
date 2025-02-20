from ..data.binance_client import BinanceClient
from .indicators import Indicators
import numpy as np
import ccxt.async_support as ccxt
import pandas as pd
from typing import Dict, Optional, Tuple
from datetime import datetime
import asyncio
from .advanced_analysis import AdvancedAnalyzer, SignalStrength

class MarketAnalyzer:
    def __init__(self, logger):
        self.logger = logger
        self.client = BinanceClient()
        self.indicators = Indicators()
        self.exchange = ccxt.binance()
        self.min_volume = 500000  # Minimum hacmi düşürdük
        self.min_price = 0.00001
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

    async def _init_valid_symbols(self):
        """Geçerli USDT sembollerini asenkron olarak al"""
        try:
            markets = await self.exchange.load_markets()
            self.valid_symbols = {
                symbol for symbol in markets.keys() 
                if symbol.endswith('USDT') and 
                markets[symbol].get('active', False)
            }
            self.logger.info(f"Loaded {len(self.valid_symbols)} valid USDT pairs")
        except Exception as e:
            self.logger.error(f"Error loading markets: {e}")
            # Varsayılan olarak popüler çiftleri ekle
            self.valid_symbols = {
                'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'ADA/USDT', 'XRP/USDT',
                'DOGE/USDT', 'DOT/USDT', 'UNI/USDT', 'SOL/USDT', 'LINK/USDT'
            }

    async def analyze_market(self, ticker_data: list, interval: str = '4h') -> list:
        """Tüm market analizi"""
        try:
            # Önce geçerli sembolleri yükle
            await self._init_valid_symbols()
            
            opportunities = []
            
            # Sayaçları sıfırla
            self.analysis_stats = {key: 0 for key in self.analysis_stats}
            self.analysis_stats['total_coins'] = len(ticker_data)
            
            self.logger.info(f"🔍 Toplam {len(ticker_data)} coin taranıyor...")
            
            for ticker in ticker_data:
                try:
                    symbol = ticker['symbol']
                    
                    # Sadece USDT çiftlerini analiz et
                    if not symbol.endswith('USDT'):
                        continue
                    self.analysis_stats['valid_pairs'] += 1
                    
                    # Minimum fiyat kontrolü
                    current_price = float(ticker['lastPrice'])
                    if current_price < self.min_price:
                        self.analysis_stats['price_filtered'] += 1
                        self.logger.debug(f"💰 {symbol} düşük fiyat nedeniyle atlandı: {current_price}")
                        continue
                        
                    # Minimum hacim kontrolü
                    current_volume = float(ticker['quoteVolume'])
                    if current_volume < self.min_volume:
                        self.analysis_stats['volume_filtered'] += 1
                        self.logger.debug(f"📊 {symbol} düşük hacim nedeniyle atlandı: {current_volume:.2f} USDT")
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
                            
                            opportunity = {
                                'symbol': symbol,
                                'price': current_price,
                                'volume': current_volume,
                                'rsi': float(rsi[-1]),
                                'macd': float(hist[-1]),
                                'trend': trend,
                                'volume_surge': volume_surge,
                                'opportunity_score': float(opportunity_score),
                                'signal': self._format_position_signal(position_rec['position']),
                                'ema20': float(ema20[-1]),
                                'ema50': float(ema50[-1]),
                                'bb_upper': float(bb_upper),
                                'bb_middle': float(bb_middle),
                                'bb_lower': float(bb_lower),
                                'position_recommendation': position_rec['position'],
                                'position_confidence': position_rec['confidence'],
                                'recommended_leverage': position_rec['leverage'],
                                'risk_level': position_rec['risk_level'],
                                'analysis_reasons': position_rec['reasons'],
                                'score': position_rec['score']
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
            # Sembol formatını düzelt
            if '/' not in symbol:
                symbol = f"{symbol[:-4]}/USDT" if symbol.endswith('USDT') else f"{symbol}/USDT"

            # Geçerli sembolleri kontrol et ve gerekirse yeniden yükle
            if not self.valid_symbols:
                await self._init_valid_symbols()

            if symbol not in self.valid_symbols:
                self.logger.error(f"Invalid symbol: {symbol}")
                return None

            self.logger.debug(f"Analyzing {symbol}...")
            
            # OHLCV verilerini al
            ohlcv = await self.exchange.fetch_ohlcv(symbol, '1h', limit=100)
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
                'ema20': float(ema20[-1]),
                'ema50': float(ema50[-1]),
                'bb_upper': float(bb_upper),
                'bb_middle': float(bb_middle),
                'bb_lower': float(bb_lower)
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
        """Long/Short pozisyon önerisi analizi"""
        long_points = 0
        short_points = 0
        reasons = []
        
        # RSI Analizi
        if rsi < 30:
            long_points += 3
            reasons.append("💚 RSI aşırı satım bölgesinde (LONG)")
        elif rsi > 70:
            short_points += 3
            reasons.append("❤️ RSI aşırı alım bölgesinde (SHORT)")
        elif rsi < 45:
            long_points += 1
            reasons.append("💚 RSI satım bölgesine yakın (LONG)")
        elif rsi > 55:
            short_points += 1
            reasons.append("❤️ RSI alım bölgesine yakın (SHORT)")
            
        # MACD Analizi
        if macd > 0 and macd > abs(macd) * 0.02:  # Pozitif ve belirli bir eşiğin üzerinde
            long_points += 2
            reasons.append("💚 MACD güçlü pozitif sinyal (LONG)")
        elif macd < 0 and abs(macd) > abs(macd) * 0.02:  # Negatif ve belirli bir eşiğin üzerinde
            short_points += 2
            reasons.append("❤️ MACD güçlü negatif sinyal (SHORT)")
            
        # EMA Trend Analizi
        if ema20 > ema50:
            if (ema20 - ema50) / ema50 * 100 > 1:  # %1'den fazla fark
                long_points += 3
                reasons.append("💚 Güçlü yükseliş trendi - EMA20 > EMA50 (LONG)")
            else:
                long_points += 1
                reasons.append("💚 Yükseliş trendi başlangıcı (LONG)")
        else:
            if (ema50 - ema20) / ema50 * 100 > 1:  # %1'den fazla fark
                short_points += 3
                reasons.append("❤️ Güçlü düşüş trendi - EMA20 < EMA50 (SHORT)")
            else:
                short_points += 1
                reasons.append("❤️ Düşüş trendi başlangıcı (SHORT)")
            
        # Bollinger Bands Analizi
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower)
        if bb_position < 0.1:
            long_points += 3
            reasons.append("💚 Fiyat BB alt bandının altında (GÜÇLÜ LONG)")
        elif bb_position < 0.2:
            long_points += 2
            reasons.append("💚 Fiyat BB alt bandına yakın (LONG)")
        elif bb_position > 0.9:
            short_points += 3
            reasons.append("❤️ Fiyat BB üst bandının üstünde (GÜÇLÜ SHORT)")
        elif bb_position > 0.8:
            short_points += 2
            reasons.append("❤️ Fiyat BB üst bandına yakın (SHORT)")

        # Hacim analizi
        if volume_surge:
            if long_points > short_points:
                long_points += 2
                reasons.append("💚 Yüksek hacimle yükseliş (LONG)")
            elif short_points > long_points:
                short_points += 2
                reasons.append("❤️ Yüksek hacimle düşüş (SHORT)")

        # Pozisyon türünü ve gücünü belirle
        if long_points > short_points:
            if long_points - short_points >= 5:
                position_type = "STRONG_LONG"
                confidence = 3
            else:
                position_type = "LONG"
                confidence = 2
        elif short_points > long_points:
            if short_points - long_points >= 5:
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
        
        return {
            'position': position_type,
            'confidence': confidence,
            'leverage': leverage,
            'reasons': reasons,
            'risk_level': self._get_risk_level(leverage),
            'score': opportunity_score
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