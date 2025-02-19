from ..data.binance_client import BinanceClient
from .indicators import Indicators
import numpy as np
import ccxt.async_support as ccxt
import pandas as pd
from typing import Dict, Optional, Tuple
from datetime import datetime
import asyncio

class MarketAnalyzer:
    def __init__(self, logger):
        self.logger = logger
        self.client = BinanceClient()
        self.indicators = Indicators()
        self.excluded_coins = ['USDCUSDT', 'BUSDUSDT']
        self.exchange = ccxt.binance()
        self.min_volume = 1000000  # Minimum 24h hacim (USDT)
        self.min_price = 0.00001   # Minimum fiyat

    async def analyze_market(self, ticker_data: list, interval: str) -> list:
        """Tüm market verilerini analiz et"""
        try:
            # USDT çiftlerini filtrele
            usdt_pairs = [
                item for item in ticker_data 
                if item['symbol'].endswith('USDT') 
                and not item['symbol'].startswith('USDC')
                and float(item['quoteVolume']) > 1000000
                and item['symbol'] not in self.excluded_coins
            ]
            
            total_pairs = len(usdt_pairs)
            self.logger.info(f"🔍 Toplam {total_pairs} coin taranacak...")
            
            opportunities = []
            for index, pair in enumerate(usdt_pairs, 1):
                try:
                    symbol = pair['symbol']
                    progress = (index / total_pairs) * 100
                    
                    if index % 10 == 0:  # Her 10 coinde bir ilerleme göster
                        self.logger.info(f"⏳ İlerleme: %{progress:.1f} ({index}/{total_pairs}) - Son taranan: {symbol}")
                    
                    analysis = await self.analyze_symbol(pair, interval)
                    if analysis and analysis['opportunity_score'] > 75:
                        opportunities.append(analysis)
                        self.logger.info(f"✨ Fırsat bulundu: {symbol} - Skor: {analysis['opportunity_score']:.1f}")
                        
                except Exception as e:
                    continue

            self.logger.info(f"✅ Tarama tamamlandı! {len(opportunities)} fırsat bulundu.")
            return sorted(opportunities, key=lambda x: x['opportunity_score'], reverse=True)[:10]
            
        except Exception as e:
            self.logger.error(f"Market analiz hatası: {e}")
            return []

    async def analyze_symbol(self, pair: dict, interval: str) -> dict:
        """Tek bir sembol için analiz yap"""
        try:
            symbol = pair['symbol']
            current_price = float(pair['lastPrice'])
            volume = float(pair['quoteVolume'])

            # Kline verilerini al
            klines = await self.client.get_klines(symbol, interval)
            if not klines or len(klines) < 100:
                return None

            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(k[4]) for k in klines])
            highs = np.array([float(k[2]) for k in klines])
            lows = np.array([float(k[3]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])
            
            # Temel göstergeleri hesapla
            rsi = self.indicators.rsi(closes)
            macd, signal = self.indicators.macd(closes)
            ema9 = self.indicators.ema(closes, 9)
            ema21 = self.indicators.ema(closes, 21)
            ema50 = self.indicators.ema(closes, 50)
            ema200 = self.indicators.ema(closes, 200)

            # Destek ve direnç seviyeleri
            support = self._find_support(lows[-20:])
            resistance = self._find_resistance(highs[-20:])

            # Hacim analizi
            volume_sma = np.mean(volumes[-20:])
            volume_surge = volume > (volume_sma * 1.5)
            
            # Trend analizi
            short_trend = "YUKARI" if ema9 > ema21 else "AŞAĞI"
            main_trend = "YUKARI" if ema50 > ema200 else "AŞAĞI"
            
            # Strateji seçimi ve sinyal üretimi
            if interval == "15m":
                strategy = self._analyze_short_term(
                    current_price, rsi, macd, signal,
                    ema9, ema21, volume_surge, support, resistance
                )
            else:  # 4h
                strategy = self._analyze_long_term(
                    current_price, rsi, macd, signal,
                    ema50, ema200, volume_surge, support, resistance
                )

            return {
                'symbol': symbol,
                'price': current_price,
                'volume': volume,
                'rsi': float(rsi),
                'macd': float(macd),
                'short_trend': short_trend,
                'main_trend': main_trend,
                'support': float(support),
                'resistance': float(resistance),
                'volume_surge': volume_surge,
                'opportunity_score': strategy['score'],
                'signal': strategy['signal'],
                'position': strategy['position'],
                'stop_loss': strategy['stop_loss'],
                'take_profit': strategy['take_profit'],
                'risk_reward': strategy['risk_reward'],
                'score_details': strategy['score_details']
            }

        except Exception as e:
            self.logger.error(f"Symbol analiz hatası ({symbol}): {e}")
            return None

    def _analyze_short_term(self, price, rsi, macd, signal, ema9, ema21, volume_surge, support, resistance):
        """15 dakikalık strateji - Puan detaylı hesaplanıyor"""
        score = 0
        position = "BEKLE"
        stop_loss = 0
        take_profit = 0
        
        # Trend Puanı (0-30)
        trend_score = 0
        if price > ema9 > ema21:  # Yükseliş trendi
            trend_score = 30
        elif price < ema9 < ema21:  # Düşüş trendi
            trend_score = 25
        elif price > ema21:  # Zayıf yükseliş
            trend_score = 15
        elif price < ema21:  # Zayıf düşüş
            trend_score = 10
        
        # RSI Puanı (0-25)
        rsi_score = 0
        if 30 <= rsi <= 70:  # İdeal bölge
            rsi_score = 25
        elif 20 <= rsi < 30 or 70 < rsi <= 80:  # Dikkat bölgesi
            rsi_score = 15
        elif rsi < 20 or rsi > 80:  # Aşırı bölge
            rsi_score = 5
            
        # MACD Puanı (0-25)
        macd_score = 0
        if macd > signal and macd > 0:  # Güçlü alım
            macd_score = 25
        elif macd > signal and macd < 0:  # Zayıf alım
            macd_score = 15
        elif macd < signal and macd < 0:  # Güçlü satım
            macd_score = 20
        elif macd < signal and macd > 0:  # Zayıf satım
            macd_score = 10
            
        # Hacim Puanı (0-20)
        volume_score = 20 if volume_surge else 10
        
        # Toplam Puan
        total_score = trend_score + rsi_score + macd_score + volume_score
        
        # Pozisyon Belirleme
        if total_score >= 75:
            if price > ema9 > ema21:  # LONG sinyali
                position = "LONG"
                stop_loss = min(support, price * 0.99)  # %1 stop loss
                take_profit = price + (price - stop_loss) * 2  # 1:2 risk/ödül
            elif price < ema9 < ema21:  # SHORT sinyali
                position = "SHORT"
                stop_loss = max(resistance, price * 1.01)  # %1 stop loss
                take_profit = price - (stop_loss - price) * 2  # 1:2 risk/ödül
        
        self.logger.debug(
            f"15m Puan Detayı:\n"
            f"Trend: {trend_score}/30\n"
            f"RSI: {rsi_score}/25\n"
            f"MACD: {macd_score}/25\n"
            f"Hacim: {volume_score}/20\n"
            f"Toplam: {total_score}/100"
        )
        
        return {
            'score': total_score,
            'signal': self._get_signal_emoji(total_score),
            'position': position,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_reward': "1:2" if total_score > 75 else "N/A",
            'score_details': {
                'trend': trend_score,
                'rsi': rsi_score,
                'macd': macd_score,
                'volume': volume_score
            }
        }

    def _analyze_long_term(self, price, rsi, macd, signal, ema50, ema200, volume_surge, support, resistance):
        """4 saatlik strateji - Puan detaylı hesaplanıyor"""
        score = 0
        position = "BEKLE"
        stop_loss = 0
        take_profit = 0
        
        # Trend Puanı (0-30)
        trend_score = 0
        if price > ema50 > ema200:  # Güçlü yükseliş trendi
            trend_score = 30
        elif price < ema50 < ema200:  # Güçlü düşüş trendi
            trend_score = 25
        elif ema50 > ema200:  # Zayıf yükseliş
            trend_score = 15
        elif ema50 < ema200:  # Zayıf düşüş
            trend_score = 10
        
        # RSI Puanı (0-25)
        rsi_score = 0
        if 40 <= rsi <= 60:  # İdeal bölge
            rsi_score = 25
        elif 30 <= rsi < 40 or 60 < rsi <= 70:  # Dikkat bölgesi
            rsi_score = 15
        elif rsi < 30 or rsi > 70:  # Aşırı bölge
            rsi_score = 5
            
        # MACD Puanı (0-25)
        macd_score = 0
        if macd > signal and macd > 0:  # Güçlü alım
            macd_score = 25
        elif macd > signal and macd < 0:  # Zayıf alım
            macd_score = 15
        elif macd < signal and macd < 0:  # Güçlü satım
            macd_score = 20
        elif macd < signal and macd > 0:  # Zayıf satım
            macd_score = 10
            
        # Hacim Puanı (0-20)
        volume_score = 20 if volume_surge else 10
        
        # Toplam Puan
        total_score = trend_score + rsi_score + macd_score + volume_score
        
        # Pozisyon Belirleme
        if total_score >= 75:
            if price > ema50 > ema200:  # LONG sinyali
                position = "LONG"
                stop_loss = min(support, price * 0.98)  # %2 stop loss
                take_profit = price + (price - stop_loss) * 3  # 1:3 risk/ödül
            elif price < ema50 < ema200:  # SHORT sinyali
                position = "SHORT"
                stop_loss = max(resistance, price * 1.02)  # %2 stop loss
                take_profit = price - (stop_loss - price) * 3  # 1:3 risk/ödül
        
        self.logger.debug(
            f"4h Puan Detayı:\n"
            f"Trend: {trend_score}/30\n"
            f"RSI: {rsi_score}/25\n"
            f"MACD: {macd_score}/25\n"
            f"Hacim: {volume_score}/20\n"
            f"Toplam: {total_score}/100"
        )
        
        return {
            'score': total_score,
            'signal': self._get_signal_emoji(total_score),
            'position': position,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_reward': "1:3" if total_score > 75 else "N/A",
            'score_details': {
                'trend': trend_score,
                'rsi': rsi_score,
                'macd': macd_score,
                'volume': volume_score
            }
        }

    def _find_support(self, lows: np.ndarray) -> float:
        """En yakın destek seviyesini bul"""
        return np.min(lows)

    def _find_resistance(self, highs: np.ndarray) -> float:
        """En yakın direnç seviyesini bul"""
        return np.max(highs)

    def _get_signal_emoji(self, score: float) -> str:
        """Skor bazlı sinyal emojisi"""
        if score >= 85:
            return "🟢 ÇOK GÜÇLÜ"
        elif score >= 75:
            return "🟡 GÜÇLÜ"
        elif score >= 65:
            return "🟠 ORTA"
        return "🔴 ZAYIF"

    async def analyze_single_coin(self, symbol: str) -> Optional[Dict]:
        """Tek bir coin için analiz yap"""
        try:
            self.logger.debug(f"Analyzing {symbol}...")
            
            # CCXT ile coin verilerini al
            ticker = await self.exchange.fetch_ticker(symbol)
            if not ticker:
                self.logger.error(f"No ticker data for {symbol}")
                return None
                
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
            current_volume = float(ticker['quoteVolume']) if 'quoteVolume' in ticker else 0
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
            
            # Sinyal belirle
            signal = self._determine_signal(opportunity_score, rsi[-1], trend)
            
            analysis_result = {
                'symbol': symbol,
                'price': float(ticker['last']),
                'volume': current_volume,
                'rsi': float(rsi[-1]),
                'macd': float(hist[-1]),
                'trend': trend,
                'volume_surge': volume_surge,
                'opportunity_score': float(opportunity_score),
                'signal': signal,
                'bb_upper': float(bb_upper),
                'bb_lower': float(bb_lower),
                'ema20': float(ema20[-1]),
                'ema50': float(ema50[-1])
            }
            
            self.logger.debug(f"Analysis completed for {symbol}")
            return analysis_result
            
        except Exception as e:
            self.logger.error(f"Single coin analysis error ({symbol}): {str(e)}")
            return None
        finally:
            # CCXT exchange'i kapat
            await self.exchange.close()

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
            score += 5
            
        return min(100, score)

    def _determine_signal(self, score: float, rsi: float, trend: str) -> str:
        """Sinyal belirle"""
        if score >= 80:
            return "🟢 GÜÇLÜ AL"
        elif score >= 65:
            return "🟡 AL"
        elif score >= 50:
            return "⚪ İZLE"
        else:
            return "🔴 BEKLE" 