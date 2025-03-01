import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .analysis.technical_analysis import TechnicalAnalysis, MarketDataProvider
import asyncio
from scipy.signal import argrelextrema
import random
import logging
import aiohttp
import ccxt.async_support as ccxt


class MarketAnalyzer:
    def __init__(self, logger):
        self.logger = logger
        
        # Exchange nesnesini her istek için yeniden oluşturacağız
        self.exchange = None
        
        self.min_volume = 500000  # Düşük hacim eşiği (500K USDT)
        self.min_price = 0.00001
        
        # Geçerli sembolleri başlangıçta boş bırak
        self.valid_symbols = set()
    
    async def _create_exchange(self):
        """Her analizde yeni bir exchange nesnesi oluştur"""
        try:
            exchange = ccxt.binance({'enableRateLimit': True})
            await exchange.load_markets()
            return exchange
        except Exception as e:
            self.logger.error(f"Exchange oluşturma hatası: {e}")
            raise

    async def initialize(self):
        """Market Analyzer'ı başlat"""
        try:
            # Veri sağlayıcısını başlat
            self.data_provider = MarketDataProvider(self.logger)
            await self.data_provider.initialize()
            
            # Geçerli sembolleri başlat
            await self._init_valid_symbols()
            
            self.logger.info("Market Analyzer başlatıldı!")
            return True
        except Exception as e:
            self.logger.error(f"Market Analyzer başlatma hatası: {e}")
            return False

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
        exchange = None
        try:
            exchange = await self._create_exchange()
            
            tickers = await self._get_all_tickers(exchange)
            if not tickers or len(tickers) == 0:
                self.logger.error("Ticker verileri alınamadı")
                return []
            
            opportunities = await self._analyze_market_with_exchange(tickers, interval, exchange)
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa tarama hatası: {e}")
            return []
        finally:
            try:
                if exchange:
                    await exchange.close()
            except Exception as e:
                self.logger.error(f"Exchange kapatma hatası: {e}")

    async def _get_all_tickers(self, exchange) -> List[Dict]:
        """Tüm sembollerin ticker verilerini al"""
        try:
            tickers = await exchange.fetch_tickers()
            return [
                {
                    'symbol': symbol, 
                    'lastPrice': ticker['last'], 
                    'quoteVolume': ticker['quoteVolume']
                } 
                for symbol, ticker in tickers.items() 
                if 'USDT' in symbol and ticker['last'] and ticker['quoteVolume']
            ]
        except Exception as e:
            self.logger.error(f"Ticker verileri alma hatası: {e}")
            symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'ADA/USDT', 'XRP/USDT']
            result = []
            for symbol in symbols:
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    result.append({
                        'symbol': symbol.replace('/', ''),  
                        'lastPrice': ticker['last'],
                        'quoteVolume': ticker['quoteVolume']
                    })
                except Exception as inner_e:
                    self.logger.error(f"Ticker verisi alma hatası ({symbol}): {inner_e}")
            return result

    async def analyze_market_with_lower_threshold(self, ticker_data: List[Dict], interval: str) -> List[Dict]:
        """Daha düşük eşikle piyasa analizi yap"""
        opportunities = []
        long_opportunities = []
        short_opportunities = []
        
        # Filtreleme kriterleri
        filtered_tickers = [
            ticker for ticker in ticker_data
            if (
                ticker['symbol'].endswith('USDT') and
                float(ticker['quoteVolume']) >= self.min_volume and
                self.min_price <= float(ticker['lastPrice']) <= self.max_price and
                not any(coin in ticker['symbol'] for coin in self.excluded_coins)
            )
        ]
        
        for ticker in filtered_tickers[:50]:
            try:
                opportunity = await self.analyze_opportunity(
                    ticker['symbol'],
                    float(ticker['lastPrice']),
                    float(ticker['quoteVolume']),
                    interval
                )
                
                if opportunity and opportunity['opportunity_score'] >= 35:  # Düşük eşik
                    if "LONG" in opportunity['signal']:
                        long_opportunities.append(opportunity)
                    elif "SHORT" in opportunity['signal']:
                        short_opportunities.append(opportunity)
                    
                if len(long_opportunities) + len(short_opportunities) >= 10:
                    break
                    
            except Exception as e:
                self.logger.debug(f"Düşük eşik analizi hatası: {e}")
        
        # Long/short dağılımını dengele
        min_opportunities = 3
        long_count = min(min(min_opportunities, len(long_opportunities)), 2)
        short_count = min(min(min_opportunities, len(short_opportunities)), 2)
        
        opportunities.extend(long_opportunities[:long_count])
        opportunities.extend(short_opportunities[:short_count])
        
        # Hiç fırsat bulunamadıysa inceleme önerisi ekle
        if not opportunities:
            for ticker in filtered_tickers[:10]:
                price = float(ticker['lastPrice'])
                volume = float(ticker['quoteVolume'])
                if price > 0 and volume > 0:
                    opportunities.append({
                        'symbol': ticker['symbol'],
                        'current_price': price,
                        'volume': volume,
                        'rsi': 50,
                        'macd': 0,
                        'signal': "👀 İNCELEME ÖNERİSİ",
                        'opportunity_score': 40,
                        'trend': "BELİRSİZ",
                        'timestamp': datetime.now().isoformat()
                    })
                    if len(opportunities) >= 3:
                        break
        
        return opportunities

    async def analyze_market(self, ticker_data: List[Dict], interval: str) -> List[Dict]:
        """Piyasayı analiz et ve fırsatları bul"""
        opportunities = []
        long_opportunities = []
        short_opportunities = []
        
        try:
            # Filtreleme kriterleri gevşetildi
            filtered_tickers = [
                ticker for ticker in ticker_data
                if (
                    ticker['symbol'].endswith('USDT') and
                    float(ticker['quoteVolume']) >= self.min_volume and
                    self.min_price <= float(ticker['lastPrice']) <= self.max_price and
                    not any(coin in ticker['symbol'] for coin in self.excluded_coins)
                )
            ]
            
            # Global piyasa durumunu kontrol et
            market_status = await self.analyze_global_market_trend()
            
            for ticker in filtered_tickers[:50]:  # İlk 50 coin ile sınırla
                try:
                    opportunity = await self.analyze_opportunity(
                        ticker['symbol'],
                        float(ticker['lastPrice']),
                        float(ticker['quoteVolume']),
                        interval
                    )
                    
                    if opportunity:
                        # Global trend ile uyumu kontrol et
                        if market_status['trend'] == "YUKARI" and "LONG" in opportunity['signal']:
                            opportunity['opportunity_score'] *= 1.1
                        elif market_status['trend'] == "AŞAĞI" and "SHORT" in opportunity['signal']:
                            opportunity['opportunity_score'] *= 1.1
                        
                        # Düşük eşik (35) ile fırsatları değerlendir
                        if opportunity['opportunity_score'] >= 35:
                            if "LONG" in opportunity['signal']:
                                long_opportunities.append(opportunity)
                            elif "SHORT" in opportunity['signal']:
                                short_opportunities.append(opportunity)
                    
                except Exception as e:
                    self.logger.debug(f"Fırsat analizi hatası ({ticker['symbol']}): {e}")
                    continue
            
            # Yeterli fırsat bulunamadıysa daha fazla coin analiz et
            if len(long_opportunities) + len(short_opportunities) < 5:
                self.logger.info("Yeterli fırsat bulunamadı, ek analiz yapılıyor...")
                
                for ticker in filtered_tickers[50:100]:  # Sonraki 50 coin
                    try:
                        opportunity = await self.analyze_opportunity(
                            ticker['symbol'],
                            float(ticker['lastPrice']),
                            float(ticker['quoteVolume']),
                            interval
                        )
                        
                        if opportunity and opportunity['opportunity_score'] >= 30:  # Daha düşük eşik
                            if "LONG" in opportunity['signal']:
                                long_opportunities.append(opportunity)
                            elif "SHORT" in opportunity['signal']:
                                short_opportunities.append(opportunity)
                        
                        if len(long_opportunities) + len(short_opportunities) >= 10:
                            break
                            
                    except Exception as e:
                        continue
            
            # Long/Short dağılımını dengele
            long_count = min(len(long_opportunities), 3)
            short_count = min(len(short_opportunities), 3)
            
            # En iyi fırsatları seç
            opportunities.extend(sorted(
                long_opportunities,
                key=lambda x: x['opportunity_score'],
                reverse=True
            )[:long_count])
            
            opportunities.extend(sorted(
                short_opportunities,
                key=lambda x: x['opportunity_score'],
                reverse=True
            )[:short_count])
            
            # Hiç fırsat bulunamazsa inceleme önerileri ekle
            if not opportunities:
                self.logger.info("Fırsat bulunamadı, inceleme önerileri ekleniyor...")
                for ticker in filtered_tickers[:5]:
                    price = float(ticker['lastPrice'])
                    volume = float(ticker['quoteVolume'])
                    
                    if price > 0 and volume > self.min_volume:
                        opportunities.append({
                            'symbol': ticker['symbol'],
                            'current_price': price,
                            'volume': volume,
                            'signal': "👀 İNCELEME ÖNERİSİ",
                            'opportunity_score': 35,
                            'trend': "BELİRSİZ",
                            'timestamp': datetime.now().isoformat(),
                            'interval': interval,
                            'rsi': 50,
                            'macd': 0,
                            'volume_surge': False,
                            'ema20': price,
                            'ema50': price
                        })
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa analizi hatası: {e}")
            return []

    def _get_strategy_for_timeframe(self, interval: str) -> Dict:
        """Zaman dilimine göre strateji parametrelerini al"""
        if interval == "15m":
            return {
                'rsi_oversold': 38,
                'rsi_overbought': 62,
                'bb_lower_threshold': 25,
                'bb_upper_threshold': 75,
                'ema_fast': 8,
                'ema_slow': 21,
                'min_score': 60,
                'long_ratio': 0.3,
                'short_ratio': 0.7,
                'volatility_weight': 1.5,
                'volume_weight': 1.8,
                'macd_weight': 1.6,
                'trend_weight': 1.3,
            }
        elif interval == "4h":
            return {
                'rsi_oversold': 32,
                'rsi_overbought': 68,
                'bb_lower_threshold': 18,
                'bb_upper_threshold': 82,
                'ema_fast': 20,
                'ema_slow': 50,
                'min_score': 65,
                'long_ratio': 0.6,
                'short_ratio': 0.4,
                'volatility_weight': 1.2,
                'volume_weight': 1.3,
                'macd_weight': 1.4,
                'trend_weight': 1.5,
            }
        else:
            return {
                'rsi_oversold': 35,
                'rsi_overbought': 65,
                'bb_lower_threshold': 20,
                'bb_upper_threshold': 80,
                'ema_fast': 12,
                'ema_slow': 26,
                'min_score': 55,
                'long_ratio': 0.5,
                'short_ratio': 0.5,
                'volatility_weight': 1.0,
                'volume_weight': 1.0,
                'macd_weight': 1.0,
                'trend_weight': 1.0,
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

    async def analyze_opportunity(self, symbol: str, current_price: float, volume: float, interval: str) -> Optional[Dict]:
        """Tek bir sembol için fırsat analizi yap"""
        try:
            # OHLCV verileri al
            ohlcv = await self.data_provider.fetch_ohlcv(symbol, interval, limit=100)
            if not ohlcv or len(ohlcv) < 50:
                return None
            
            # Teknik indikatörleri hesapla
            closes = np.array([float(candle[4]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            rsi = self._calculate_custom_rsi(closes, interval)[-1]
            macd, signal, hist = self._calculate_custom_macd(closes, interval)
            
            # Bollinger ve trend analizi
            bb_analysis = self._detect_bollinger_squeeze(closes)
            trend_analysis = self._detect_trend_breakout(ohlcv, interval)
            
            # Mum formasyonları
            candle_patterns = self._detect_candlestick_patterns(ohlcv)
            
            # Hacim analizi
            avg_volume = np.mean(volumes[-20:])
            volume_surge = volume > (avg_volume * 1.5)  # 2'den 1.5'e düşürüldü
            
            # Fırsat puanı hesapla
            opportunity_score = self._calculate_opportunity_score(
                rsi=rsi,
                macd=hist[-1],
                volume_surge=volume_surge,
                trend=trend_analysis.get('breakout', 'NEUTRAL'),
                current_volume=volume,
                avg_volume=avg_volume
            )
            
            # Stop loss ve hedef fiyatları hesapla
            risk_levels = self._calculate_optimized_stops(ohlcv, interval, "LONG")
            
            opportunity = {
                'symbol': symbol,
                'current_price': current_price,
                'volume': volume,
                'rsi': rsi,
                'macd': hist[-1],
                'volume_surge': volume_surge,
                'bb_squeeze': bb_analysis['squeeze'],
                'trend': trend_analysis.get('breakout', 'NEUTRAL'),
                'pattern': candle_patterns.get('pattern'),
                'opportunity_score': opportunity_score,
                'stop_loss': risk_levels['stop_loss'],
                'take_profit': risk_levels['take_profit'],
                'timestamp': datetime.now().isoformat(),
                'interval': interval
            }
            
            # Zaman dilimine göre ayarla
            if interval == "15m":
                opportunity = self._adjust_for_short_term(opportunity)
            elif interval == "4h":
                opportunity = self._adjust_for_medium_term(opportunity)
            
            return opportunity
            
        except Exception as e:
            self.logger.debug(f"Fırsat analizi hatası ({symbol}): {e}")
            return None

    def _adjust_for_short_term(self, opportunity: Dict) -> Dict:
        """15 dakikalık işlemler için ayarlamalar yap"""
        # Kısa vadede momentum daha önemli ama daha az agresif
        if opportunity.get('macd_hist_direction') == 'up' and opportunity['rsi'] < 60:
            opportunity['long_score'] += 10  # 20'den 10'a düşürüldü
        elif opportunity.get('macd_hist_direction') == 'down' and opportunity['rsi'] > 40:
            opportunity['short_score'] += 10  # 20'den 10'a düşürüldü
        
        # Hacim patlaması kontrolü
        if opportunity.get('volume_surge', False) and opportunity['volume'] > opportunity.get('avg_volume', 0) * 1.5:  # 2'den 1.5'e düşürüldü
            if opportunity['ema20'] > opportunity['ema50']:
                opportunity['long_score'] += 10  # 15'ten 10'a düşürüldü
            else:
                opportunity['short_score'] += 10
        
        # Volatiliteye göre puanlama
        if opportunity.get('volatility', 0) > 1.2:  # 1.5'ten 1.2'ye düşürüldü
            opportunity['opportunity_score'] *= 1.1  # 1.2'den 1.1'e düşürüldü
        
        # RSI ekstrem değerleri
        if opportunity['rsi'] < 30:
            opportunity['long_score'] += 15  # 25'ten 15'e düşürüldü
        elif opportunity['rsi'] > 70:
            opportunity['short_score'] += 15
        
        # Bollinger bantları sıkışması
        if opportunity.get('bb_squeeze', False) and opportunity.get('bb_breakout_direction'):
            if opportunity.get('bb_breakout_direction') == 'up':
                opportunity['long_score'] += 15  # 20'den 15'e düşürüldü
            else:
                opportunity['short_score'] += 15
        
        # Trend cezası azaltıldı
        if opportunity['ema20'] > opportunity['ema50'] and opportunity['short_score'] > opportunity['long_score']:
            opportunity['short_score'] -= 5  # 10'dan 5'e düşürüldü
        elif opportunity['ema20'] < opportunity['ema50'] and opportunity['long_score'] > opportunity['short_score']:
            opportunity['long_score'] -= 5
        
        # Stop loss ve TP seviyeleri daha geniş
        if 'stop_price' in opportunity and 'target_price' in opportunity:
            current_price = opportunity['current_price']
            if opportunity['long_score'] > opportunity['short_score']:
                opportunity['stop_price'] = current_price * 0.99  # %1.5'ten %1'e düşürüldü
                opportunity['target_price'] = current_price * 1.02  # %2.5'ten %2'ye düşürüldü
            else:
                opportunity['stop_price'] = current_price * 1.01
                opportunity['target_price'] = current_price * 0.98
        
        return opportunity

    def _adjust_for_medium_term(self, opportunity: Dict) -> Dict:
        """4 saatlik işlemler için ayarlamalar yap"""
        # EMA çaprazlama puanı azaltıldı
        if opportunity.get('ema_cross'):
            if opportunity.get('ema_cross') == 'golden_cross':
                opportunity['long_score'] += 15  # 25'ten 15'e düşürüldü
            elif opportunity.get('ema_cross') == 'death_cross':
                opportunity['short_score'] += 15
        
        # Trend gücü puanı azaltıldı
        ema_diff = abs(opportunity['ema20'] - opportunity['ema50']) / opportunity['ema50'] * 100
        if ema_diff > 1.5:  # 2'den 1.5'e düşürüldü
            if opportunity['ema20'] > opportunity['ema50']:
                opportunity['long_score'] += 10  # 15'ten 10'a düşürüldü
            else:
                opportunity['short_score'] += 10
        
        # Destek/Direnç puanları azaltıldı
        if opportunity.get('resistance_test') and opportunity['current_price'] < opportunity.get('resistance_level', float('inf')):
            opportunity['short_score'] += 10  # 15'ten 10'a düşürüldü
        
        if opportunity.get('support_test') and opportunity['current_price'] > opportunity.get('support_level', 0):
            opportunity['long_score'] += 10
        
        # Hacim trendi puanı azaltıldı
        if opportunity.get('volume_trend') == 'increasing':
            if opportunity['ema20'] > opportunity['ema50']:
                opportunity['long_score'] += 8  # 10'dan 8'e düşürüldü
            else:
                opportunity['short_score'] += 8
        
        # RSI ve MACD uyumu puanı azaltıldı
        if opportunity['rsi'] < 40 and opportunity.get('macd_hist', 0) > 0:
            opportunity['long_score'] += 10  # 15'ten 10'a düşürüldü
        elif opportunity['rsi'] > 60 and opportunity.get('macd_hist', 0) < 0:
            opportunity['short_score'] += 10
        
        # Volatilite kontrolü gevşetildi
        volatility = opportunity.get('volatility', 1.0)
        if 0.7 < volatility < 1.8:  # Aralık genişletildi
            opportunity['opportunity_score'] *= 1.1  # 1.15'ten 1.1'e düşürüldü
        elif volatility > 2.0:  # 2.5'ten 2.0'a düşürüldü
            opportunity['opportunity_score'] *= 0.95  # 0.9'dan 0.95'e yükseltildi
        
        # Risk/ödül oranını optimize et
        if 'stop_price' in opportunity and 'target_price' in opportunity:
            current_price = opportunity['current_price']
            if opportunity['long_score'] > opportunity['short_score']:
                opportunity['stop_price'] = current_price * 0.98  # %3'ten %2'ye düşürüldü
                opportunity['target_price'] = current_price * 1.04  # %6'dan %4'e düşürüldü
            else:
                opportunity['stop_price'] = current_price * 1.02
                opportunity['target_price'] = current_price * 0.96
        
        return opportunity

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

    def _calculate_pivot_points(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Dict:
        """Pivot noktalarını hesapla"""
        if len(highs) < 5:
            return {
                'pivot': closes[-1],
                'support1': closes[-1] * 0.99,
                'support2': closes[-1] * 0.98,
                'resistance1': closes[-1] * 1.01,
                'resistance2': closes[-1] * 1.02
            }
        
        # Son günün değerlerini al
        high = highs[-1]
        low = lows[-1]
        close = closes[-1]
        
        # Pivot noktası
        pivot = (high + low + close) / 3
        
        # Destek ve direnç seviyeleri
        support1 = (2 * pivot) - high
        support2 = pivot - (high - low)
        resistance1 = (2 * pivot) - low
        resistance2 = pivot + (high - low)
        
        return {
            'pivot': pivot,
            'support1': support1,
            'support2': support2,
            'resistance1': resistance1,
            'resistance2': resistance2
        }

    async def generate_chart(self, symbol: str, interval: str = "4h") -> Optional[bytes]:
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

    def _calculate_custom_rsi(self, prices: np.ndarray, interval: str) -> np.ndarray:
        """Zaman dilimine göre özelleştirilmiş RSI hesapla"""
        if interval == "15m":
            period = 9  # 15 dakikalık için daha hızlı RSI
        elif interval == "4h":
            period = 14  # 4 saatlik için standart RSI
        else:
            period = 14  # Varsayılan
        
        delta = np.diff(prices)
        gain = (delta > 0) * delta
        loss = (delta < 0) * -delta
        
        avg_gain = np.zeros_like(prices)
        avg_loss = np.zeros_like(prices)
        
        avg_gain[period] = np.mean(gain[:period])
        avg_loss[period] = np.mean(loss[:period])
        
        for i in range(period + 1, len(prices)):
            avg_gain[i] = (avg_gain[i-1] * (period-1) + gain[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period-1) + loss[i-1]) / period
        
        rs = avg_gain / np.where(avg_loss == 0, 0.0001, avg_loss)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi

    def _calculate_custom_macd(self, prices: np.ndarray, interval: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Zaman dilimine göre özelleştirilmiş MACD hesapla"""
        if interval == "15m":
            fast_period = 8
            slow_period = 17
            signal_period = 5
        elif interval == "4h":
            fast_period = 12
            slow_period = 26
            signal_period = 9
        else:
            fast_period = 12
            slow_period = 26
            signal_period = 9
        
        exp1 = pd.Series(prices).ewm(span=fast_period, adjust=False).mean()
        exp2 = pd.Series(prices).ewm(span=slow_period, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        hist = macd - signal
        
        return macd.values, signal.values, hist.values

    def _detect_candlestick_patterns(self, ohlcv: list) -> Dict:
        """Temel mum formasyonlarını tespit et"""
        if len(ohlcv) < 5:
            return {'pattern': None, 'signal': None}
        
        opens = np.array([float(candle[1]) for candle in ohlcv[-5:]])
        highs = np.array([float(candle[2]) for candle in ohlcv[-5:]])
        lows = np.array([float(candle[3]) for candle in ohlcv[-5:]])
        closes = np.array([float(candle[4]) for candle in ohlcv[-5:]])
        
        # Son mum
        last_open = opens[-1]
        last_close = closes[-1]
        last_high = highs[-1]
        last_low = lows[-1]
        
        # Önceki mum
        prev_open = opens[-2]
        prev_close = closes[-2]
        prev_high = highs[-2]
        prev_low = lows[-2]
        
        patterns = []
        
        # Çekiç formasyonu
        if (last_close > last_open and  # Alış mumu
                (last_high - last_close) < 0.2 * (last_high - last_low) and  # Kısa üst gölge
                (last_open - last_low) > 2 * (last_close - last_open)):  # Uzun alt gölge
            patterns.append(('hammer', 'LONG', 80))
        
        # Yutan formasyon
        if (prev_close < prev_open and  # Önceki mum satış
                last_close > last_open and  # Şimdiki mum alış
                last_open < prev_close and  # Şimdiki açılış önceki kapanışın altında
                last_close > prev_open):  # Şimdiki kapanış önceki açılışın üstünde
            patterns.append(('bullish_engulfing', 'LONG', 85))
        
        if (prev_close > prev_open and  # Önceki mum alış
                last_close < last_open and  # Şimdiki mum satış
                last_open > prev_close and  # Şimdiki açılış önceki kapanışın üstünde
                last_close < prev_open):  # Şimdiki kapanış önceki açılışın altında
            patterns.append(('bearish_engulfing', 'SHORT', 85))
        
        # Shooting Star
        if (last_close < last_open and  # Satış mumu
                (last_close - last_low) < 0.2 * (last_high - last_low) and  # Kısa alt gölge
                (last_high - last_open) > 2 * (last_open - last_close)):  # Uzun üst gölge
            patterns.append(('shooting_star', 'SHORT', 80))
        
        # Doji
        if abs(last_close - last_open) < 0.1 * (last_high - last_low):
            patterns.append(('doji', 'NEUTRAL', 50))
        
        # En güçlü sinyali döndür
        if patterns:
            return {'pattern': patterns[0][0], 'signal': patterns[0][1], 'strength': patterns[0][2]}
        
        return {'pattern': None, 'signal': None, 'strength': 0}

    def _detect_trend_breakout(self, ohlcv: list, interval: str) -> Dict:
        """Trend kırılımlarını tespit et"""
        if len(ohlcv) < 50:
            return {'breakout': None, 'strength': 0}
        
        closes = np.array([float(candle[4]) for candle in ohlcv])
        volumes = np.array([float(candle[5]) for candle in ohlcv])
        
        # EMA hesapla
        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().values
        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().values
        
        # Son fiyat
        last_price = closes[-1]
        
        # Son hacim ve ortalama hacim
        last_volume = volumes[-1]
        avg_volume = np.mean(volumes[-20:])
        
        # Kırılma tespiti
        breakout = None
        strength = 0
        
        # EMA Çaprazlama
        if (ema20[-2] < ema50[-2] and ema20[-1] >= ema50[-1]):
            breakout = "golden_cross"
            strength = 80
        elif (ema20[-2] > ema50[-2] and ema20[-1] <= ema50[-1]):
            breakout = "death_cross"
            strength = 80
        
        # Hacim destekli kırılım
        elif (last_price > ema20[-1] * 1.02 and last_volume > avg_volume * 1.5):
            breakout = "volume_supported_up"
            strength = 70
        elif (last_price < ema20[-1] * 0.98 and last_volume > avg_volume * 1.5):
            breakout = "volume_supported_down"
            strength = 70
        
        # Özel zaman dilimi kontrolleri
        if interval == "15m":
            if (last_price > ema20[-1] * 1.01):
                breakout = "short_term_up"
                strength = 65
            elif (last_price < ema20[-1] * 0.99):
                breakout = "short_term_down"
                strength = 65
        elif interval == "4h":
            if (all(closes[-3:] > ema50[-3:]) and all(closes[-6:-3] < ema50[-6:-3])):
                breakout = "medium_term_up"
                strength = 75
            elif (all(closes[-3:] < ema50[-3:]) and all(closes[-6:-3] > ema50[-6:-3])):
                breakout = "medium_term_down"
                strength = 75
        
        return {
            'breakout': breakout,
            'strength': strength,
            'ema_cross': "golden_cross" if (ema20[-2] < ema50[-2] and ema20[-1] >= ema50[-1]) else
                        "death_cross" if (ema20[-2] > ema50[-2] and ema20[-1] <= ema50[-1]) else None
        }

    def _detect_bollinger_squeeze(self, closes: np.ndarray, window: int = 20) -> Dict:
        """Bollinger Sıkışması tespit et"""
        if len(closes) < window + 10:
            return {'squeeze': False, 'direction': None, 'strength': 0}
        
        # Bollinger Bands
        sma = pd.Series(closes).rolling(window=window).mean()
        stdev = pd.Series(closes).rolling(window=window).std()
        
        # Son 10 gün için BB genişliği
        bb_width_history = []
        for i in range(10):
            idx = -1 - i
            upper = sma[idx] + (stdev[idx] * 2)
            lower = sma[idx] - (stdev[idx] * 2)
            bb_width_history.append(upper - lower)
        
        # Son değer
        current_bb_width = (sma.iloc[-1] + (stdev.iloc[-1] * 2)) - (sma.iloc[-1] - (stdev.iloc[-1] * 2))
        
        # Sıkışma tespiti
        min_width = min(bb_width_history)
        is_squeeze = current_bb_width < min_width * 1.1
        
        # Sıkışma sonrası yön tahmini
        direction = None
        strength = 0
        
        if is_squeeze:
            price_change = closes[-1] - closes[-2]
            
            if price_change > 0:
                direction = "up"
                strength = abs(price_change) / stdev.iloc[-1] * 50
            else:
                direction = "down"
                strength = abs(price_change) / stdev.iloc[-1] * 50
        
        return {
            'squeeze': is_squeeze,
            'direction': direction,
            'strength': min(100, float(strength)),
            'current_width': float(current_bb_width),
            'min_width': float(min_width)
        }

    def _analyze_macd_histogram_direction(self, hist_values: np.ndarray) -> str:
        """MACD histogram yönünü analiz et"""
        if len(hist_values) < 5:
            return "unknown"
        
        # Son 3 değeri al
        last_3 = hist_values[-3:]
        
        # Sürekli artış
        if all(last_3[i] > last_3[i-1] for i in range(1, len(last_3))):
            return "up"
        # Sürekli azalış
        elif all(last_3[i] < last_3[i-1] for i in range(1, len(last_3))):
            return "down"
        # Son değer artmış mı?
        elif last_3[-1] > last_3[-2]:
            return "turning_up"
        # Son değer azalmış mı?
        elif last_3[-1] < last_3[-2]:
            return "turning_down"
        else:
            return "flat"

    def _generate_custom_15m_signal(self, analysis: Dict) -> str:
        """15 dakikalık zaman dilimine özel sinyal üret"""
        # RSI ekstrem bölgelerden dönüş
        if analysis['rsi'] < 30 and analysis.get('rsi_direction') == 'up':
            return "💚 GÜÇLÜ LONG (RSI aşırı satım bölgesinden dönüş)"
        
        if analysis['rsi'] > 70 and analysis.get('rsi_direction') == 'down':
            return "❤️ GÜÇLÜ SHORT (RSI aşırı alım bölgesinden dönüş)"
        
        # Bollinger kırılmaları
        if analysis['current_price'] < analysis['bb_lower'] and analysis.get('volume_surge', False):
            return "💚 LONG (BB alt bandı kırılımı + hacim desteği)"
        
        if analysis['current_price'] > analysis['bb_upper'] and analysis.get('volume_surge', False):
            return "❤️ SHORT (BB üst bandı kırılımı + hacim desteği)"
        
        # MACD çaprazlamaları
        if analysis.get('macd_cross') == 'up' and analysis['rsi'] < 55:
            return "💚 LONG (MACD çaprazlama yukarı)"
        
        if analysis.get('macd_cross') == 'down' and analysis['rsi'] > 45:
            return "❤️ SHORT (MACD çaprazlama aşağı)"
        
        # Mum formasyonları
        if analysis.get('candlestick_pattern') in ['hammer', 'bullish_engulfing']:
            return "💚 LONG (Güçlü alım formasyonu)"
        
        if analysis.get('candlestick_pattern') in ['shooting_star', 'bearish_engulfing']:
            return "❤️ SHORT (Güçlü satım formasyonu)"
        
        # Varsayılan - EMA trendini kontrol et
        if analysis['ema20'] > analysis['ema50'] and analysis['rsi'] > 50:
            return "💛 ZAYIF LONG (EMA trend yukarı)"
        
        if analysis['ema20'] < analysis['ema50'] and analysis['rsi'] < 50:
            return "🧡 ZAYIF SHORT (EMA trend aşağı)"
        
        return "⚪ BEKLE (Net sinyal yok)"

    def _generate_custom_4h_signal(self, analysis: Dict) -> str:
        """4 saatlik zaman dilimine özel sinyal üret"""
        # EMA Çaprazlama
        if analysis.get('ema_cross') == 'golden_cross':
            return "💚 GÜÇLÜ LONG (EMA Çaprazlama Yukarı)"
        
        if analysis.get('ema_cross') == 'death_cross':
            return "❤️ GÜÇLÜ SHORT (EMA Çaprazlama Aşağı)"
        
        # Destek/Direnç testi
        if analysis.get('support_test') and analysis['current_price'] > analysis.get('support_level', 0):
            return "💚 LONG (Destek seviyesi testi başarılı)"
        
        if analysis.get('resistance_test') and analysis['current_price'] < analysis.get('resistance_level', float('inf')):
            return "❤️ SHORT (Direnç seviyesi testi başarılı)"
        
        # RSI ve MACD uyumu
        if analysis['rsi'] < 40 and analysis.get('macd_hist', 0) > 0:
            return "💚 LONG (RSI düşük + MACD pozitif)"
        
        if analysis['rsi'] > 60 and analysis.get('macd_hist', 0) < 0:
            return "❤️ SHORT (RSI yüksek + MACD negatif)"
        
        # Bollinger Squeeze
        if analysis.get('bb_squeeze', False) and analysis.get('bb_breakout_direction') == 'up':
            return "💚 LONG (Bollinger sıkışması sonrası yukarı kırılım)"
        
        if analysis.get('bb_squeeze', False) and analysis.get('bb_breakout_direction') == 'down':
            return "❤️ SHORT (Bollinger sıkışması sonrası aşağı kırılım)"
        
        # Trend ve hacim uyumu
        if analysis['ema20'] > analysis['ema50'] and analysis.get('volume_trend') == 'increasing':
            return "💛 LONG (Güçlü yukarı trend + artan hacim)"
        
        if analysis['ema20'] < analysis['ema50'] and analysis.get('volume_trend') == 'increasing':
            return "🧡 SHORT (Güçlü aşağı trend + artan hacim)"
        
        return "⚪ BEKLE (Net sinyal yok)"

    def _calculate_optimized_stops(self, ohlcv: list, interval: str, signal_type: str) -> Dict:
        """Zaman dilimine göre optimize edilmiş stop ve hedef fiyatları hesapla"""
        if len(ohlcv) < 20:
            return {'stop_loss': None, 'take_profit': None, 'risk_reward': 0}
        
        closes = np.array([float(candle[4]) for candle in ohlcv])
        highs = np.array([float(candle[2]) for candle in ohlcv])
        lows = np.array([float(candle[3]) for candle in ohlcv])
        
        current_price = closes[-1]
        
        # ATR hesapla
        high_low = highs - lows
        high_close = np.abs(highs - closes[:-1])
        low_close = np.abs(lows - closes[:-1])
        ranges = np.vstack([high_low, high_close, low_close])
        true_range = np.max(ranges, axis=0)
        atr = np.mean(true_range[-14:])
        
        if interval == "15m":
            stop_mult = 1.5
            target_mult = 2.0
            
            if "LONG" in signal_type:
                stop_price = min(lows[-3:]) * 0.998
                target_price = current_price + ((current_price - stop_price) * target_mult)
            else:
                stop_price = max(highs[-3:]) * 1.002
                target_price = current_price - ((stop_price - current_price) * target_mult)
        
        elif interval == "4h":
            stop_mult = 2.0
            target_mult = 3.0
            
            if "LONG" in signal_type:
                stop_price = current_price - (atr * stop_mult)
                target_price = current_price + (atr * stop_mult * target_mult)
            else:
                stop_price = current_price + (atr * stop_mult)
                target_price = current_price - (atr * stop_mult * target_mult)
        
        else:
            stop_mult = 2.0
            target_mult = 2.0
            
            if "LONG" in signal_type:
                stop_price = current_price - (atr * stop_mult)
                target_price = current_price + (atr * stop_mult * target_mult)
            else:
                stop_price = current_price + (atr * stop_mult)
                target_price = current_price - (atr * stop_mult * target_mult)
        
        # Risk/ödül oranını hesapla
        if "LONG" in signal_type:
            risk = current_price - stop_price
            reward = target_price - current_price
        else:
            risk = stop_price - current_price
            reward = current_price - target_price
        
        risk_reward = reward / risk if risk > 0 else 0
        
        return {
            'stop_loss': float(stop_price),
            'take_profit': float(target_price),
            'risk_reward': float(risk_reward)
        }

    def _calculate_opportunity_score(self, rsi: float, macd: float, 
                                   volume_surge: bool, trend: str,
                                   current_volume: float, avg_volume: float) -> float:
        """Fırsat puanı hesapla (0-100)"""
        score = 0
        
        # RSI bazlı puan (0-30)
        if rsi < 30:  # Aşırı satım
            score += 30
        elif rsi > 70:  # Aşırı alım
            score += 30  # SHORT sinyaller için de yüksek puan
        elif 30 <= rsi <= 40 or 60 <= rsi <= 70:  # Satım/alım bölgelerine yakın
            score += 25
        else:
            score += 15
                
        # MACD bazlı puan (0-20)
        if abs(macd) > 0.01:  # Mutlak değer kontrolü
            score += 20
        else:
            score += 10
        
        # Hacim bazlı puan (0-30)
        if volume_surge:
            score += 30
        else:
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            score += min(30, volume_ratio * 20)
                
        # Trend bazlı puan (0-20)
        if trend in ["YUKARI", "AŞAĞI"]:  # Her iki trend de değerli
            score += 20
        else:
            score += 10
                
        return min(100, score)

    def _detect_support_resistance_levels(self, ohlcv: list, lookback: int = 100, tolerance: float = 0.01) -> Dict:
        """Gelişmiş destek ve direnç seviyelerini tespit et"""
        if len(ohlcv) < lookback:
            return {'support': [], 'resistance': []}
        
        highs = np.array([float(candle[2]) for candle in ohlcv[-lookback:]])
        lows = np.array([float(candle[3]) for candle in ohlcv[-lookback:]])
        closes = np.array([float(candle[4]) for candle in ohlcv[-lookback:]])
        volumes = np.array([float(candle[5]) for candle in ohlcv[-lookback:]])
        
        current_price = closes[-1]
        
        # Hacim ağırlıklı fiyat seviyeleri
        vwap_levels = []
        for i in range(len(closes)):
            vwap = np.sum(closes[i:i+20] * volumes[i:i+20]) / np.sum(volumes[i:i+20])
            if not np.isnan(vwap):
                vwap_levels.append(vwap)
        
        # Yerel maksimum ve minimumları bul
        resistance_points = []
        support_points = []
        
        # Fiyat ve hacim bazlı analiz
        for i in range(5, len(closes)-5):
            # Yüksek hacimli bölgeleri kontrol et
            volume_significance = volumes[i] > np.mean(volumes[i-5:i+5]) * 1.5
            
            # Dirençler
            if (all(highs[i] > highs[i-j] for j in range(1, 4)) and 
                all(highs[i] > highs[i+j] for j in range(1, 4))):
                if volume_significance:
                    resistance_points.append((highs[i], 1.2))  # Yüksek hacim ağırlığı
                else:
                    resistance_points.append((highs[i], 1.0))
            
            # Destekler
            if (all(lows[i] < lows[i-j] for j in range(1, 4)) and 
                all(lows[i] < lows[i+j] for j in range(1, 4))):
                if volume_significance:
                    support_points.append((lows[i], 1.2))
                else:
                    support_points.append((lows[i], 1.0))
        
        # Seviyeleri birleştir ve ağırlıklandır
        resistance_levels = self._consolidate_price_levels(
            [r[0] for r in resistance_points],
            [r[1] for r in resistance_points],
            current_price,
            tolerance
        )
        
        support_levels = self._consolidate_price_levels(
            [s[0] for s in support_points],
            [s[1] for s in support_points],
            current_price,
            tolerance
        )
        
        return {
            'resistance': sorted([r for r in resistance_levels if r > current_price])[:3],
            'support': sorted([s for s in support_levels if s < current_price], reverse=True)[:3],
            'vwap': np.mean(vwap_levels[-20:]) if vwap_levels else current_price
        }

    def _consolidate_price_levels(self, levels: list, weights: list, current_price: float, tolerance: float) -> list:
        """Fiyat seviyelerini birleştir ve ağırlıklandır"""
        if not levels:
            return []
        
        consolidated = []
        level_groups = []
        current_group = [(levels[0], weights[0])]
        
        # Yakın seviyeleri grupla
        for i in range(1, len(levels)):
            if abs(levels[i] - levels[i-1]) / current_price < tolerance:
                current_group.append((levels[i], weights[i]))
            else:
                level_groups.append(current_group)
                current_group = [(levels[i], weights[i])]
        level_groups.append(current_group)
        
        # Her grup için ağırlıklı ortalama hesapla
        for group in level_groups:
            total_weight = sum(weight for _, weight in group)
            weighted_level = sum(level * weight for level, weight in group) / total_weight
            consolidated.append(weighted_level)
        
        return consolidated

    async def analyze_global_market_trend(self) -> Dict:
        """Global piyasa trendini analiz et"""
        try:
            # BTC ve ETH verilerini al
            btc_data = await self.data_provider.fetch_ohlcv('BTCUSDT', '4h', limit=100)
            eth_data = await self.data_provider.fetch_ohlcv('ETHUSDT', '4h', limit=100)
            
            if not btc_data or not eth_data:
                return {'trend': 'NEUTRAL', 'strength': 0}
            
            # BTC analizi
            btc_closes = np.array([float(candle[4]) for candle in btc_data])
            btc_volumes = np.array([float(candle[5]) for candle in btc_data])
            btc_rsi = self._calculate_custom_rsi(btc_closes, '4h')[-1]
            btc_ema20 = pd.Series(btc_closes).ewm(span=20, adjust=False).mean().values
            btc_ema50 = pd.Series(btc_closes).ewm(span=50, adjust=False).mean().values
            
            # ETH analizi
            eth_closes = np.array([float(candle[4]) for candle in eth_data])
            eth_volumes = np.array([float(candle[5]) for candle in eth_data])
            eth_rsi = self._calculate_custom_rsi(eth_closes, '4h')[-1]
            eth_ema20 = pd.Series(eth_closes).ewm(span=20, adjust=False).mean().values
            
            # Trend belirleme
            btc_trend = "YUKARI" if btc_ema20[-1] > btc_ema50[-1] else "AŞAĞI"
            eth_trend = "YUKARI" if eth_closes[-1] > eth_ema20[-1] else "AŞAĞI"
            
            # Hacim analizi
            btc_vol_trend = np.mean(btc_volumes[-3:]) > np.mean(btc_volumes[-10:-3])
            eth_vol_trend = np.mean(eth_volumes[-3:]) > np.mean(eth_volumes[-10:-3])
            
            # Global trend belirleme
            if btc_trend == eth_trend and btc_vol_trend and eth_vol_trend:
                trend = btc_trend
                strength = 80
            elif btc_trend == eth_trend:
                trend = btc_trend
                strength = 60
            else:
                trend = "KARIŞIK"
                strength = 40
            
            # RSI uyumu
            if btc_rsi < 30 and eth_rsi < 30:
                trend = "YUKARI"
                strength = 70
            elif btc_rsi > 70 and eth_rsi > 70:
                trend = "AŞAĞI"
                strength = 70
            
            return {
                'trend': trend,
                'strength': strength,
                'btc_trend': btc_trend,
                'eth_trend': eth_trend,
                'btc_rsi': float(btc_rsi),
                'eth_rsi': float(eth_rsi),
                'volume_trend': "ARTIYOR" if btc_vol_trend and eth_vol_trend else "AZALIYOR"
            }
            
        except Exception as e:
            self.logger.error(f"Global piyasa trend analizi hatası: {e}")
            return {'trend': 'NEUTRAL', 'strength': 0}

    def _calculate_simple_score(self, symbol: str, rsi: float, ema20: float, 
                              ema50: float, price: float, volume: float) -> Dict:
        """Basit bir puanlama algoritması"""
        score = 50  # Başlangıç puanı
        signal = "NÖTR"
        
        # RSI temelli sinyaller
        if rsi < 30:
            score += 20
            signal = "LONG"
        elif rsi > 70:
            score += 20
            signal = "SHORT"
        
        # EMA temelli sinyaller
        if ema20 > ema50:
            if signal != "SHORT":  # RSI short demiyorsa
                score += 10
                signal = "LONG" 
        else:
            if signal != "LONG":  # RSI long demiyorsa
                score += 10
                signal = "SHORT"
        
        # Hacim kontrolü
        if volume > self.min_volume:
            score += 10
        
        return {
            'symbol': symbol,
            'current_price': price,
            'volume': volume,
            'rsi': rsi,
            'ema20': ema20,
            'ema50': ema50,
            'opportunity_score': score,
            'signal': signal,
            'timestamp': datetime.now().isoformat()
        }

    async def analyze_market_simple(self, ticker_data: List[Dict], interval: str = "4h") -> List[Dict]:
        """Basitleştirilmiş piyasa analizi"""
        opportunities = []
        analyzed_count = 0
        
        try:
            self.logger.info(f"Basit analiz başlatılıyor. {len(ticker_data)} coin...")
            
            # Veri kontrolü
            if not ticker_data:
                self.logger.warning("Ticker verisi boş!")
                return self.get_test_signals()
            
            # Sadece USDT çiftleri
            usdt_pairs = [t for t in ticker_data if t['symbol'].endswith('USDT')]
            self.logger.info(f"USDT çiftleri: {len(usdt_pairs)}")
            
            if not usdt_pairs:
                self.logger.warning("USDT çifti bulunamadı!")
                return self.get_test_signals()
            
            # Minimum fiyat ve hacim filtresi - sıfır kontrolü eklendi
            filtered_pairs = []
            for t in usdt_pairs:
                try:
                    price = float(t['lastPrice'])
                    volume = float(t['quoteVolume'])
                    
                    if (price > 0.00001 and 
                        volume > 100000 and 
                        price < 100000):
                        filtered_pairs.append(t)
                except (ValueError, KeyError, TypeError) as e:
                    self.logger.debug(f"Filtreleme hatası {t.get('symbol', 'bilinmeyen')}: {e}")
                    continue
            
            self.logger.info(f"Filtreleme sonrası: {len(filtered_pairs)} coin")
            
            if not filtered_pairs:
                self.logger.warning("Filtre sonrası coin kalmadı!")
                return self.get_test_signals()
            
            # Sıralama - hacme göre
            sorted_pairs = sorted(
                filtered_pairs,
                key=lambda x: float(x.get('quoteVolume', 0)),
                reverse=True
            )
            
            # Analiz edilecek maksimum coin sayısı
            max_to_analyze = min(50, len(sorted_pairs))
            
            for ticker in sorted_pairs[:max_to_analyze]:
                try:
                    symbol = ticker['symbol']
                    price = float(ticker['lastPrice'])
                    volume = float(ticker['quoteVolume'])
                    
                    # OHLCV verilerini al
                    ohlcv = await self.data_provider.fetch_ohlcv(symbol, interval, limit=50)
                    
                    # Veri kontrolü
                    if not await self.validate_data(symbol, ohlcv):
                        continue
                    
                    analyzed_count += 1
                    
                    # Verileri numpy dizilerine dönüştür
                    closes = np.array([float(candle[4]) for candle in ohlcv])
                    
                    # Sıfır kontrolü
                    if len(closes) == 0 or np.any(closes == 0):
                        self.logger.debug(f"Geçersiz kapanış değerleri {symbol}")
                        continue
                    
                    # Basit indikatörler - try-except bloğu içinde
                    try:
                        rsi = self._calculate_custom_rsi(closes, interval)[-1]
                        ema20 = pd.Series(closes).ewm(span=20, adjust=False).mean().values[-1]
                        ema50 = pd.Series(closes).ewm(span=50, adjust=False).mean().values[-1]
                        
                        # NaN kontrolü
                        if np.isnan(rsi) or np.isnan(ema20) or np.isnan(ema50):
                            self.logger.debug(f"NaN değerler {symbol}: RSI={rsi}, EMA20={ema20}, EMA50={ema50}")
                            continue
                        
                    except Exception as e:
                        self.logger.debug(f"İndikatör hesaplama hatası {symbol}: {e}")
                        continue
                    
                    # Basit puanlama
                    opportunity = self._calculate_simple_score(
                        symbol, rsi, ema20, ema50, price, volume
                    )
                    
                    # Düşük puan eşiği
                    if opportunity['opportunity_score'] >= 60:
                        opportunities.append(opportunity)
                    
                except Exception as e:
                    self.logger.error(f"Coin analiz hatası {symbol}: {e}")
                    continue
            
            # Sonuçları puanlara göre sırala
            opportunities = sorted(
                opportunities,
                key=lambda x: x['opportunity_score'],
                reverse=True
            )
            
            # Hiç fırsat bulunamazsa test sinyalleri döndür
            if not opportunities:
                self.logger.info("Fırsat bulunamadı, test sinyalleri döndürülüyor...")
                return self.get_test_signals()
            
            return opportunities[:10]
            
        except Exception as e:
            self.logger.error(f"Genel analiz hatası: {e}")
            return self.get_test_signals()

    def get_test_signals(self) -> List[Dict]:
        """Test amaçlı sinyaller oluştur"""
        current_time = datetime.now().isoformat()
        return [
            {
                'symbol': 'BTCUSDT',
                'current_price': 96000.0,
                'volume': 1000000000.0,
                'rsi': 45.0,
                'macd': 0.001,
                'ema20': 95000.0,
                'ema50': 93000.0,
                'trend': 'YUKARI',
                'signal': '💚 LONG',
                'opportunity_score': 85.0,
                'timestamp': current_time
            },
            {
                'symbol': 'ETHUSDT',
                'current_price': 3500.0,
                'volume': 500000000.0,
                'rsi': 65.0,
                'macd': -0.002,
                'ema20': 3520.0,
                'ema50': 3450.0,
                'trend': 'AŞAĞI',
                'signal': '❤️ SHORT',
                'opportunity_score': 75.0,
                'timestamp': current_time
            },
            {
                'symbol': 'BNBUSDT',
                'current_price': 420.0,
                'volume': 200000000.0,
                'rsi': 35.0,
                'macd': 0.003,
                'ema20': 415.0,
                'ema50': 410.0,
                'trend': 'YUKARI',
                'signal': '💚 LONG',
                'opportunity_score': 70.0,
                'timestamp': current_time
            }
        ]

    def _get_bb_signal(self, bb_position: float) -> str:
        """Bollinger Bands sinyali belirle"""
        if bb_position <= 20:
            return "💚 ALIM"
        elif bb_position >= 80:
            return "🔴 SATIŞ"
        else:
            return "⚪ NÖTR"

    async def validate_data(self, symbol: str, ohlcv: List) -> bool:
        """OHLCV verilerinin geçerliliğini kontrol et"""
        if not ohlcv or len(ohlcv) < 20:
            self.logger.debug(f"📈 {symbol} yetersiz OHLCV verisi: {len(ohlcv) if ohlcv else 0}")
            return False
        
        try:
            # Veri yapısını kontrol et
            for candle in ohlcv[:2]:
                if len(candle) != 6:  # timestamp, open, high, low, close, volume
                    self.logger.error(f"Geçersiz OHLCV format {symbol}: {candle}")
                    return False
                
                # Değerlerin sayı olduğunu kontrol et
                if not all(isinstance(float(val), float) for val in candle[1:]):
                    self.logger.error(f"Geçersiz veri tipi {symbol}: {candle}")
                    return False
                
                # Mantıksız değerleri kontrol et
                if float(candle[2]) < float(candle[3]):  # high < low
                    self.logger.error(f"Geçersiz high/low değerleri {symbol}: {candle}")
                    return False
                
                if float(candle[5]) <= 0:  # volume <= 0
                    self.logger.error(f"Geçersiz hacim {symbol}: {candle}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Veri doğrulama hatası {symbol}: {str(e)}")
            return False

    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """EMA hesapla"""
        if len(prices) < period:
            return prices
            
        ema = np.zeros_like(prices)
        ema[:period] = np.mean(prices[:period])
        
        multiplier = 2 / (period + 1)
        for i in range(period, len(prices)):
            ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1]
            
        return ema

    async def _analyze_market_with_exchange(self, ticker_data: List[Dict], interval: str, exchange) -> List[Dict]:
        """Exchange parametreli piyasa analizi - Binance Global coinleri için"""
        opportunities = []
        long_opportunities = []
        short_opportunities = []
        
        try:
            # USDT çiftlerini filtrele
            filtered_tickers = [t for t in ticker_data if t['symbol'].endswith('USDT')]
            
            self.logger.info(f"USDT çiftleri: {len(filtered_tickers)} coin")
            
            # Minimum fiyat kontrolü
            filtered_tickers = [t for t in filtered_tickers if float(t['lastPrice']) >= 0.000001]
            
            # Minimum hacim kontrolü
            filtered_tickers = [t for t in filtered_tickers if float(t['quoteVolume']) >= 100000]  # 100K USDT
            
            self.logger.info(f"Fiyat ve hacim filtresi sonrası: {len(filtered_tickers)} coin")
            
            # Binance Global filtrelemesini kaldıralım - sorun burada
            # Doğrudan tüm coinleri analiz edelim
            
            # Hacme göre sırala
            filtered_tickers = sorted(
                filtered_tickers,
                key=lambda x: float(x['quoteVolume']),
                reverse=True
            )
            
            # En yüksek hacimli 100 coini analiz et
            filtered_tickers = filtered_tickers[:100]
            
            self.logger.info(f"Analiz edilecek: {len(filtered_tickers)} coin")
            
            analyzed_count = 0
            for ticker in filtered_tickers:
                symbol = ticker['symbol']
                current_price = float(ticker['lastPrice'])
                volume = float(ticker['quoteVolume'])
                
                # Sembol formatını kontrol et
                if '/' not in symbol:
                    exchange_symbol = f"{symbol[:-4]}/USDT" if symbol.endswith('USDT') else f"{symbol}/USDT"
                else:
                    exchange_symbol = symbol
                
                try:
                    # OHLCV verilerini al
                    ohlcv = await exchange.fetch_ohlcv(exchange_symbol, interval, limit=100)
                    
                    if not ohlcv or len(ohlcv) < 20:
                        continue
                    
                    analyzed_count += 1
                    if analyzed_count % 10 == 0:
                        self.logger.info(f"Analiz ilerleme: {analyzed_count}/{len(filtered_tickers)}")
                    
                    # Analizi yap
                    opportunity = await self._analyze_single_opportunity(symbol, current_price, volume, ohlcv, interval)
                    
                    if opportunity and opportunity['opportunity_score'] >= 60:  # Minimum 60 puan
                        # Fırsatları grupla
                        if "LONG" in opportunity['signal']:
                            long_opportunities.append(opportunity)
                        elif "SHORT" in opportunity['signal']:
                            short_opportunities.append(opportunity)
                
                except Exception as e:
                    self.logger.error(f"Coin analizi hatası {symbol}: {e}")
                    continue
            
            self.logger.info(f"Toplam {analyzed_count} coin analiz edildi")
            self.logger.info(f"Bulunan fırsatlar: {len(long_opportunities)} LONG, {len(short_opportunities)} SHORT")
            
            # Hiç fırsat bulunamazsa, kriterleri gevşet ve tekrar dene
            if len(long_opportunities) == 0 and len(short_opportunities) == 0:
                self.logger.warning("Fırsat bulunamadı, basit analiz yapılıyor...")
                return await self._fallback_simple_analysis(filtered_tickers, interval, exchange)
            
            # Fırsatları puanlara göre sırala
            long_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            short_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            # En iyi 5 LONG ve 5 SHORT 
            opportunities = long_opportunities[:5] + short_opportunities[:5]
            
            # Fırsatları karıştır
            random.shuffle(opportunities)
            
            # En fazla 10 fırsat göster
            opportunities = opportunities[:10]
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa analizi hatası: {e}")
            return []

    async def _analyze_single_opportunity(self, symbol: str, current_price: float, volume: float, ohlcv: list, interval: str) -> Optional[Dict]:
        """Geliştirilmiş fırsat analizi - RSI 50 ve minimum 60 puan"""
        try:
            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(candle[4]) for candle in ohlcv])
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Temel indikatörler
            rsi = self._calculate_rsi(closes, 14)
            ema20 = self._calculate_ema(closes, 20)
            ema50 = self._calculate_ema(closes, 50)
            ema200 = self._calculate_ema(closes, 200) if len(closes) >= 200 else np.array([closes.mean()] * len(closes))
            
            # RSI 50 kontrolü - RSI 50'nin altında ise LONG, üstünde ise SHORT
            if rsi[-1] == 50:  # Tam 50 ise sinyal üretme
                return None
                
            # MACD hesapla
            ema12 = self._calculate_ema(closes, 12)
            ema26 = self._calculate_ema(closes, 26)
            macd_line = ema12 - ema26
            signal_line = self._calculate_ema(macd_line, 9)
            macd_histogram = macd_line - signal_line
            
            # Bollinger Bands
            sma20 = np.array(pd.Series(closes).rolling(window=20).mean())
            std20 = np.array(pd.Series(closes).rolling(window=20).std())
            upper_band = sma20 + (std20 * 2)
            lower_band = sma20 - (std20 * 2)
            
            # Hacim analizi
            volume_sma20 = np.array(pd.Series(volumes).rolling(window=20).mean())
            volume_increase = volumes[-1] > volume_sma20[-1] * 1.5 if not np.isnan(volume_sma20[-1]) else False
            
            # Destek ve direnç seviyeleri
            pivot_points = self._calculate_pivot_points(highs, lows, closes)
            
            # Gelişmiş sinyal puanlaması
            long_score = 0
            short_score = 0
            
            # 1. RSI 50 kontrolü (30 puan)
            if rsi[-1] < 50:
                long_score += 30  # RSI 50'nin altında - LONG
            else:
                short_score += 30  # RSI 50'nin üstünde - SHORT
            
            # 2. Trend analizi (30 puan)
            # EMA eğilimi
            if ema20[-1] > ema50[-1] and ema50[-1] > ema200[-1]:
                long_score += 15  # Güçlü yukarı trend
            elif ema20[-1] < ema50[-1] and ema50[-1] < ema200[-1]:
                short_score += 15  # Güçlü aşağı trend
            elif ema20[-1] > ema50[-1]:
                long_score += 10  # Orta yukarı trend
            elif ema20[-1] < ema50[-1]:
                short_score += 10  # Orta aşağı trend
            
            # Fiyat pozisyonu
            if closes[-1] > ema200[-1]:
                long_score += 10  # Uzun vadeli trend üzerinde
            else:
                short_score += 10  # Uzun vadeli trend altında
                
            # Trend gücü - son 5 mum analizi
            if all(closes[-5:] > ema20[-5:]):
                long_score += 5  # Güçlü momentum
            elif all(closes[-5:] < ema20[-5:]):
                short_score += 5  # Güçlü düşüş
            
            # 3. Momentum analizi (20 puan)
            # MACD
            if macd_line[-1] > signal_line[-1] and macd_histogram[-3:].mean() > 0:
                long_score += 10  # Yukarı momentum
            elif macd_line[-1] < signal_line[-1] and macd_histogram[-3:].mean() < 0:
                short_score += 10  # Aşağı momentum
            
            # MACD çapraz geçiş
            if macd_line[-2] < signal_line[-2] and macd_line[-1] > signal_line[-1]:
                long_score += 10  # Taze MACD kesişimi (yukarı)
            elif macd_line[-2] > signal_line[-2] and macd_line[-1] < signal_line[-1]:
                short_score += 10  # Taze MACD kesişimi (aşağı)
            
            # 4. Destek/Direnç analizi (20 puan)
            # Bollinger Bands
            if closes[-1] < lower_band[-1]:
                long_score += 10  # Alt bant desteği
            elif closes[-1] > upper_band[-1]:
                short_score += 10  # Üst bant direnci
            
            # Pivot noktaları
            if pivot_points['support1'] <= current_price <= pivot_points['support1'] * 1.01:
                long_score += 10  # Destek noktasında
            elif pivot_points['resistance1'] * 0.99 <= current_price <= pivot_points['resistance1']:
                short_score += 10  # Direnç noktasında
            
            # Toplam puanlar (maksimum 100)
            long_score = min(long_score, 100)
            short_score = min(short_score, 100)
            
            # Sinyal belirleme - minimum 60 puan gerekli
            signal = "NÖTR"
            opportunity_score = 0
            
            if long_score >= 60 and long_score > short_score:
                opportunity_score = long_score
                if long_score >= 80:
                    signal = "💚 GÜÇLÜ LONG"
                else:
                    signal = "💚 LONG"
            elif short_score >= 60 and short_score > long_score:
                opportunity_score = short_score
                if short_score >= 80:
                    signal = "❤️ GÜÇLÜ SHORT"
                else:
                    signal = "❤️ SHORT"
            else:
                # Yeterli puan yoksa sinyal üretme
                return None
            
            # Stop loss ve take profit seviyeleri - ATR tabanlı
            atr = self._calculate_atr(highs, lows, closes, 14)
            
            if "LONG" in signal:
                # LONG sinyali için
                stop_price = current_price - (atr * 2)  # 2 ATR altı
                target_price = current_price + (atr * 4)  # 4 ATR üstü (2:1 risk-ödül)
            else:
                # SHORT sinyali için
                stop_price = current_price + (atr * 2)  # 2 ATR üstü
                target_price = current_price - (atr * 4)  # 4 ATR altı (2:1 risk-ödül)
            
            # Risk/ödül oranı
            risk = abs(current_price - stop_price)
            reward = abs(current_price - target_price)
            risk_reward = reward / risk if risk > 0 else 1.0
            
            # Risk/ödül oranı en az 1.5 olmalı
            if risk_reward < 1.5:
                return None
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'volume': volume,
                'rsi': float(rsi[-1]),
                'macd': float(macd_histogram[-1]),
                'ema20': float(ema20[-1]),
                'ema50': float(ema50[-1]),
                'ema200': float(ema200[-1]),
                'trend': "YUKARI" if ema20[-1] > ema50[-1] else "AŞAĞI",
                'signal': signal,
                'opportunity_score': opportunity_score,
                'stop_price': stop_price,
                'target_price': target_price,
                'risk_reward': risk_reward,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Fırsat analizi hatası ({symbol}): {e}")
            return None

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> np.ndarray:
        """RSI hesapla"""
        if len(prices) < period + 1:
            # Yeterli veri yoksa varsayılan değer
            return np.array([50] * len(prices))
            
        deltas = np.diff(prices)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum()/period
        down = -seed[seed < 0].sum()/period
        
        # Sıfır kontrolü ekle
        rs = up/down if down != 0 else float('inf')
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
            
            # Sıfır kontrolü ekle
            rs = up/down if down != 0 else float('inf')
            rsi[i] = 100. - 100./(1.+rs)

        return rsi
    
    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """EMA hesapla"""
        if len(prices) < period:
            # Yeterli veri yoksa fiyatları döndür
            return prices
            
        ema = np.zeros_like(prices)
        ema[:period] = np.mean(prices[:period])
        
        multiplier = 2 / (period + 1)
        for i in range(period, len(prices)):
            ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1]
            
        return ema

    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
        """Average True Range hesapla"""
        if len(highs) < period + 1:
            return (highs[-1] - lows[-1])  # Yeterli veri yoksa basit range döndür
        
        tr = np.zeros(len(highs))
        tr[0] = highs[0] - lows[0]
        
        for i in range(1, len(highs)):
            tr[i] = max(
                highs[i] - lows[i],  # Günlük range
                abs(highs[i] - closes[i-1]),  # Dünkü kapanışa göre yüksek
                abs(lows[i] - closes[i-1])  # Dünkü kapanışa göre düşük
            )
        
        # ATR hesapla (Wilder's smoothing)
        atr = np.zeros(len(tr))
        atr[period-1] = np.mean(tr[:period])
        
        for i in range(period, len(tr)):
            atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
        
        return atr[-1]

    async def _fallback_simple_analysis(self, filtered_tickers: List[Dict], interval: str, exchange) -> List[Dict]:
        """Basit analiz - hiç sinyal bulunamazsa kullanılır"""
        opportunities = []
        
        try:
            # En yüksek hacimli 20 coini al
            top_volume_tickers = sorted(
                filtered_tickers, 
                key=lambda x: float(x['quoteVolume']), 
                reverse=True
            )[:20]
            
            for ticker in top_volume_tickers:
                symbol = ticker['symbol']
                current_price = float(ticker['lastPrice'])
                volume = float(ticker['quoteVolume'])
                
                # Sembol formatını kontrol et
                if '/' not in symbol:
                    exchange_symbol = f"{symbol[:-4]}/USDT" if symbol.endswith('USDT') else f"{symbol}/USDT"
                else:
                    exchange_symbol = symbol
                
                try:
                    # OHLCV verilerini al
                    ohlcv = await exchange.fetch_ohlcv(exchange_symbol, interval, limit=50)
                    
                    if not ohlcv or len(ohlcv) < 20:
                        continue
                    
                    # Basit analiz
                    closes = np.array([float(candle[4]) for candle in ohlcv])
                    
                    # RSI ve EMA hesapla
                    rsi = self._calculate_rsi(closes, 14)
                    ema20 = self._calculate_ema(closes, 20)
                    ema50 = self._calculate_ema(closes, 50)
                    
                    # Basit sinyal
                    signal = "NÖTR"
                    score = 50
                    
                    # RSI bazlı sinyal
                    if rsi[-1] < 30:
                        signal = "💚 LONG"
                        score = 70
                    elif rsi[-1] > 70:
                        signal = "❤️ SHORT"
                        score = 70
                    # EMA bazlı sinyal
                    elif ema20[-1] > ema50[-1] and closes[-1] > ema20[-1]:
                        signal = "💚 LONG"
                        score = 60
                    elif ema20[-1] < ema50[-1] and closes[-1] < ema20[-1]:
                        signal = "❤️ SHORT"
                        score = 60
                    
                    # Nötr değilse ekle
                    if signal != "NÖTR":
                        opportunities.append({
                            'symbol': symbol,
                            'current_price': current_price,
                            'volume': volume,
                            'rsi': float(rsi[-1]),
                            'ema20': float(ema20[-1]),
                            'ema50': float(ema50[-1]),
                            'trend': "YUKARI" if ema20[-1] > ema50[-1] else "AŞAĞI",
                            'signal': signal,
                            'opportunity_score': score,
                            'stop_price': current_price * 0.97 if "LONG" in signal else current_price * 1.03,
                            'target_price': current_price * 1.05 if "LONG" in signal else current_price * 0.95,
                            'risk_reward': 1.67,  # 5:3 risk-ödül
                            'timestamp': datetime.now().isoformat()
                        })
                
                except Exception as e:
                    self.logger.error(f"Basit analiz hatası {symbol}: {e}")
                    continue
            
            # Yine de fırsat bulunamazsa, en popüler 3 coini öner
            if len(opportunities) == 0:
                self.logger.warning("Basit analizde de fırsat bulunamadı, popüler coinler öneriliyor...")
                popular_coins = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
                
                for symbol in popular_coins:
                    if '/' not in symbol:
                        exchange_symbol = f"{symbol[:-4]}/USDT" if symbol.endswith('USDT') else f"{symbol}/USDT"
                    else:
                        exchange_symbol = symbol
                    
                    try:
                        ticker = await exchange.fetch_ticker(exchange_symbol)
                        current_price = ticker['last']
                        volume = ticker['quoteVolume']
                        
                        opportunities.append({
                            'symbol': symbol,
                            'current_price': current_price,
                            'volume': volume,
                            'rsi': 50.0,
                            'ema20': current_price,
                            'ema50': current_price,
                            'trend': "NÖTR",
                            'signal': "👀 İNCELEMEYE DEĞER",
                            'opportunity_score': 50,
                            'stop_price': current_price * 0.95,
                            'target_price': current_price * 1.05,
                            'risk_reward': 1.0,
                            'timestamp': datetime.now().isoformat()
                        })
                    except Exception as e:
                        self.logger.error(f"Popüler coin verisi alma hatası {symbol}: {e}")
                        continue
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Yedek analiz hatası: {e}")
            return []

    async def _get_binance_global_coins(self, exchange) -> List[str]:
        """Binance Global'de listelenen coinleri al"""
        try:
            # Futures ve Margin işlem gören coinler genellikle ana coinlerdir
            # Önce tüm sembolleri al
            markets = exchange.markets
            
            # Binance Global'de listelenen coinler (USDT çiftleri)
            global_coins = set()
            
            # Popüler coinleri ekle
            popular_coins = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", 
                "DOGEUSDT", "DOTUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT", 
                "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT", "BCHUSDT", "XLMUSDT",
                "NEARUSDT", "ALGOUSDT", "ICPUSDT", "FILUSDT", "AAVEUSDT", "AXSUSDT",
                "SANDUSDT", "MANAUSDT", "APTUSDT", "SUIUSDT", "INJUSDT", "ARBUSDT",
                "OPUSDT", "LDOUSDT", "FTMUSDT", "GMTUSDT", "GALAUSDT", "CHZUSDT",
                "RNDRUSDT", "THETAUSDT", "EOSUSDT", "RUNEUSDT", "SNXUSDT", "GRTUSDT"
            ]
            
            for coin in popular_coins:
                global_coins.add(coin)
            
            # Futures işlem gören coinleri ekle
            try:
                futures_markets = await exchange.fapiPublicGetExchangeInfo()
                if 'symbols' in futures_markets:
                    for market in futures_markets['symbols']:
                        if market['status'] == 'TRADING' and market['quoteAsset'] == 'USDT':
                            global_coins.add(f"{market['baseAsset']}USDT")
            except Exception as e:
                self.logger.warning(f"Futures bilgisi alınamadı: {e}")
            
            # Margin işlem gören coinleri ekle
            try:
                margin_markets = await exchange.sapiGetMarginAllPairs()
                for market in margin_markets:
                    if market['isMarginTrade'] and 'USDT' in market['symbol']:
                        global_coins.add(market['symbol'])
            except Exception as e:
                self.logger.warning(f"Margin bilgisi alınamadı: {e}")
            
            # Spot piyasadaki yüksek hacimli coinleri ekle
            for symbol, market in markets.items():
                if 'USDT' in symbol and market['active']:
                    base = market['base']
                    global_coins.add(f"{base}USDT")
            
            self.logger.info(f"Toplam {len(global_coins)} Binance Global coini bulundu")
            return list(global_coins)
            
        except Exception as e:
            self.logger.error(f"Binance Global coin listesi alınamadı: {e}")
            # Hata durumunda popüler coinleri döndür
            return [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", 
                "DOGEUSDT", "DOTUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT"
            ]

    async def scan15(self) -> List[Dict]:
        """15 dakikalık zaman diliminde anlık al-kaç fırsatları için tarama yapar"""
        exchange = None
        try:
            # Her taramada yeni bir exchange oluştur
            exchange = await self._create_exchange()
            
            # Tüm sembolleri al
            tickers = await self._get_all_tickers(exchange)
            if not tickers or len(tickers) == 0:
                self.logger.error("Ticker verileri alınamadı")
                return []
            
            # 15 dakikalık analiz yap
            opportunities = await self._analyze_15min_opportunities(tickers, exchange)
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"15 dakikalık tarama hatası: {e}")
            return []
        finally:
            # Exchange'i temizle
            try:
                if exchange:
                    await exchange.close()
            except Exception as e:
                self.logger.error(f"Exchange kapatma hatası: {e}")
    
    async def _analyze_15min_opportunities(self, ticker_data: List[Dict], exchange) -> List[Dict]:
        """15 dakikalık zaman diliminde anlık al-kaç fırsatları analizi"""
        opportunities = []
        scalping_opportunities = []
        
        try:
            # USDT çiftlerini filtrele
            filtered_tickers = [t for t in ticker_data if t['symbol'].endswith('USDT')]
            
            self.logger.info(f"USDT çiftleri: {len(filtered_tickers)} coin")
            
            # Minimum fiyat kontrolü
            filtered_tickers = [t for t in filtered_tickers if float(t['lastPrice']) >= 0.000001]
            
            # Minimum hacim kontrolü - scalping için daha yüksek hacim gerekli
            filtered_tickers = [t for t in filtered_tickers if float(t['quoteVolume']) >= 1000000]  # 1M USDT
            
            self.logger.info(f"Fiyat ve hacim filtresi sonrası: {len(filtered_tickers)} coin")
            
            # Hacme göre sırala
            filtered_tickers = sorted(
                filtered_tickers,
                key=lambda x: float(x['quoteVolume']),
                reverse=True
            )
            
            # En yüksek hacimli 50 coini analiz et (scalping için daha az coin)
            filtered_tickers = filtered_tickers[:50]
            
            self.logger.info(f"Analiz edilecek: {len(filtered_tickers)} coin")
            
            analyzed_count = 0
            for ticker in filtered_tickers:
                symbol = ticker['symbol']
                current_price = float(ticker['lastPrice'])
                volume = float(ticker['quoteVolume'])
                
                # Sembol formatını kontrol et
                if '/' not in symbol:
                    exchange_symbol = f"{symbol[:-4]}/USDT" if symbol.endswith('USDT') else f"{symbol}/USDT"
                else:
                    exchange_symbol = symbol
                
                try:
                    # 15 dakikalık OHLCV verilerini al
                    ohlcv = await exchange.fetch_ohlcv(exchange_symbol, '15m', limit=100)
                    
                    if not ohlcv or len(ohlcv) < 20:
                        continue
                    
                    analyzed_count += 1
                    
                    # Scalping analizi yap
                    opportunity = await self._analyze_scalping_opportunity(symbol, current_price, volume, ohlcv)
                    
                    if opportunity and opportunity['opportunity_score'] >= 70:  # Scalping için daha yüksek puan
                        scalping_opportunities.append(opportunity)
                
                except Exception as e:
                    self.logger.error(f"Coin analizi hatası {symbol}: {e}")
                    continue
            
            self.logger.info(f"Toplam {analyzed_count} coin analiz edildi")
            self.logger.info(f"Bulunan scalping fırsatları: {len(scalping_opportunities)}")
            
            # Hiç fırsat bulunamazsa, popüler coinleri kontrol et
            if len(scalping_opportunities) == 0:
                self.logger.warning("Scalping fırsatı bulunamadı, popüler coinler kontrol ediliyor...")
                return await self._check_popular_coins_for_scalping(exchange)
            
            # Fırsatları puanlara göre sırala
            scalping_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            # En iyi 5 fırsatı göster
            opportunities = scalping_opportunities[:5]
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"15 dakikalık analiz hatası: {e}")
            return []
    
    async def _analyze_scalping_opportunity(self, symbol: str, current_price: float, volume: float, ohlcv: list) -> Optional[Dict]:
        """Scalping fırsatı analizi - 15 dakikalık zaman dilimi için"""
        try:
            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(candle[4]) for candle in ohlcv])
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            opens = np.array([float(candle[1]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            timestamps = np.array([int(candle[0]) for candle in ohlcv])
            
            # Son 3 mumun zaman farkını kontrol et - veri güncelliği için
            current_time = int(datetime.now().timestamp() * 1000)
            if current_time - timestamps[-1] > 900000:  # 15 dakikadan eski veri
                return None
            
            # Scalping için özel indikatörler
            rsi = self._calculate_rsi(closes, 14)
            stoch_rsi = self._calculate_stochastic_rsi(closes, 14, 3, 3)
            ema9 = self._calculate_ema(closes, 9)
            ema21 = self._calculate_ema(closes, 21)
            ema55 = self._calculate_ema(closes, 55)
            
            # Bollinger Bands (daha dar bantlar - scalping için)
            sma20 = np.array(pd.Series(closes).rolling(window=20).mean())
            std20 = np.array(pd.Series(closes).rolling(window=20).std())
            upper_band = sma20 + (std20 * 1.5)  # 2 yerine 1.5 kullanıyoruz
            lower_band = sma20 - (std20 * 1.5)
            
            # VWAP hesapla (Volume Weighted Average Price)
            vwap = self._calculate_vwap(highs, lows, closes, volumes)
            
            # Mum formasyonları
            is_hammer = self._is_hammer(opens[-1], highs[-1], lows[-1], closes[-1])
            is_engulfing = self._is_bullish_engulfing(opens[-2:], closes[-2:])
            is_doji = self._is_doji(opens[-1], highs[-1], lows[-1], closes[-1])
            
            # Hacim analizi
            volume_surge = volumes[-1] > volumes[-2] * 1.5  # Son hacim öncekinin 1.5 katı
            
            # Scalping puanlaması
            score = 0
            signal = "NÖTR"
            entry_type = ""
            
            # 1. RSI ve Stochastic RSI (30 puan)
            if rsi[-1] < 30 and stoch_rsi[-1] < 20:
                score += 30  # Güçlü aşırı satım
                entry_type = "RSI AŞIRI SATIM"
            elif rsi[-1] > 70 and stoch_rsi[-1] > 80:
                score += 30  # Güçlü aşırı alım (SHORT için)
                entry_type = "RSI AŞIRI ALIM"
            elif rsi[-1] < 40 and stoch_rsi[-1] < 30:
                score += 20  # Orta aşırı satım
                entry_type = "RSI SATIM"
            elif rsi[-1] > 60 and stoch_rsi[-1] > 70:
                score += 20  # Orta aşırı alım (SHORT için)
                entry_type = "RSI ALIM"
            
            # 2. EMA Crossover (20 puan)
            if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
                score += 20  # Taze altın çapraz
                entry_type = "EMA ÇAPRAZ (YUKARI)"
            elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
                score += 20  # Taze ölüm çaprazı (SHORT için)
                entry_type = "EMA ÇAPRAZ (AŞAĞI)"
            
            # 3. Bollinger Bands (20 puan)
            if closes[-1] < lower_band[-1]:
                score += 20  # Alt bant kırılımı
                entry_type = "BB ALT BANT"
            elif closes[-1] > upper_band[-1]:
                score += 20  # Üst bant kırılımı (SHORT için)
                entry_type = "BB ÜST BANT"
            
            # 4. Mum formasyonları (15 puan)
            if is_hammer and rsi[-1] < 50:
                score += 15  # Çekiç formasyonu
                entry_type = "ÇEKİÇ FORMASYONU"
            elif is_engulfing and rsi[-1] < 50:
                score += 15  # Yutan formasyonu
                entry_type = "YUTAN FORMASYON"
            elif is_doji and closes[-1] < sma20[-1]:
                score += 10  # Doji formasyonu
                entry_type = "DOJI FORMASYON"
            
            # 5. VWAP (10 puan)
            if closes[-1] < vwap[-1] * 0.995:  # VWAP'ın %0.5 altında
                score += 10
                entry_type += " + VWAP ALTI"
            elif closes[-1] > vwap[-1] * 1.005:  # VWAP'ın %0.5 üstünde (SHORT için)
                score += 10
                entry_type += " + VWAP ÜSTÜ"
            
            # 6. Hacim (5 puan)
            if volume_surge:
                score += 5
                entry_type += " + HACİM ARTIŞI"
            
            # Sinyal belirleme
            if score >= 70 and rsi[-1] < 50:
                signal = "⚡ SCALP LONG"
            elif score >= 70 and rsi[-1] > 50:
                signal = "⚡ SCALP SHORT"
            else:
                return None
            
            # Scalping için daha dar stop loss ve take profit
            atr = self._calculate_atr(highs, lows, closes, 14)
            
            if "LONG" in signal:
                # LONG sinyali için
                entry_price = current_price
                stop_price = current_price - (atr * 1.0)  # 1 ATR altı
                target_price = current_price + (atr * 2.0)  # 2 ATR üstü (2:1 risk-ödül)
            else:
                # SHORT sinyali için
                entry_price = current_price
                stop_price = current_price + (atr * 1.0)  # 1 ATR üstü
                target_price = current_price - (atr * 2.0)  # 2 ATR altı (2:1 risk-ödül)
            
            # Risk/ödül oranı
            risk = abs(entry_price - stop_price)
            reward = abs(entry_price - target_price)
            risk_reward = reward / risk if risk > 0 else 1.0
            
            # Risk/ödül oranı en az 1.5 olmalı
            if risk_reward < 1.5:
                return None
            
            # Tahmini işlem süresi (dakika)
            estimated_time = 15 * 3  # Ortalama 3 mum (45 dakika)
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'volume': volume,
                'rsi': float(rsi[-1]),
                'stoch_rsi': float(stoch_rsi[-1]),
                'ema9': float(ema9[-1]),
                'ema21': float(ema21[-1]),
                'signal': signal,
                'entry_type': entry_type,
                'opportunity_score': score,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'target_price': target_price,
                'risk_reward': risk_reward,
                'estimated_time': f"{estimated_time} dakika",
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Scalping analizi hatası ({symbol}): {e}")
            return None

    def _calculate_stochastic_rsi(self, prices: np.ndarray, period: int = 14, k_period: int = 3, d_period: int = 3) -> np.ndarray:
        """Stochastic RSI hesapla"""
        # Önce RSI hesapla
        rsi_values = self._calculate_rsi(prices, period)
        
        # Stochastic RSI hesapla
        stoch_rsi = np.zeros_like(rsi_values)
        
        for i in range(period, len(rsi_values)):
            rsi_window = rsi_values[i-period+1:i+1]
            
            if len(rsi_window) < period:
                stoch_rsi[i] = 50  # Yeterli veri yoksa orta değer
                continue
                
            rsi_min = np.min(rsi_window)
            rsi_max = np.max(rsi_window)
            
            if rsi_max == rsi_min:
                stoch_rsi[i] = 50  # Aynı değerler varsa orta değer
            else:
                stoch_rsi[i] = 100 * (rsi_values[i] - rsi_min) / (rsi_max - rsi_min)
        
        # %K değeri (ham stochastic RSI)
        k_values = stoch_rsi
        
        # %D değeri (SMA(3) of %K)
        d_values = np.zeros_like(k_values)
        for i in range(k_period, len(k_values)):
            d_values[i] = np.mean(k_values[i-k_period+1:i+1])
        
        return d_values  # %D değerini döndür
    
    def _calculate_vwap(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
        """Volume Weighted Average Price hesapla"""
        typical_price = (highs + lows + closes) / 3
        vwap = np.zeros_like(closes)
        
        cumulative_tp_vol = 0
        cumulative_vol = 0
        
        for i in range(len(closes)):
            cumulative_tp_vol += typical_price[i] * volumes[i]
            cumulative_vol += volumes[i]
            
            if cumulative_vol > 0:
                vwap[i] = cumulative_tp_vol / cumulative_vol
            else:
                vwap[i] = typical_price[i]
        
        return vwap
    
    def _is_hammer(self, open_price: float, high: float, low: float, close: float) -> bool:
        """Çekiç formasyonu kontrolü"""
        body_size = abs(close - open_price)
        total_range = high - low
        
        if total_range == 0:
            return False
            
        # Alt gölge en az toplam boyun %60'ı olmalı
        lower_shadow = min(open_price, close) - low
        lower_shadow_ratio = lower_shadow / total_range
        
        # Üst gölge en fazla toplam boyun %10'u olmalı
        upper_shadow = high - max(open_price, close)
        upper_shadow_ratio = upper_shadow / total_range
        
        # Gövde en fazla toplam boyun %30'u olmalı
        body_ratio = body_size / total_range
        
        return (lower_shadow_ratio >= 0.6 and 
                upper_shadow_ratio <= 0.1 and 
                body_ratio <= 0.3)
    
    def _is_bullish_engulfing(self, opens: np.ndarray, closes: np.ndarray) -> bool:
        """Yutan formasyonu kontrolü"""
        if len(opens) < 2 or len(closes) < 2:
            return False
            
        # İlk mum düşüş mumu olmalı
        prev_bearish = closes[-2] < opens[-2]
        
        # İkinci mum yükseliş mumu olmalı
        curr_bullish = closes[-1] > opens[-1]
        
        # İkinci mum ilk mumu yutmalı
        engulfing = (opens[-1] <= closes[-2] and 
                    closes[-1] >= opens[-2])
        
        return prev_bearish and curr_bullish and engulfing
    
    def _is_doji(self, open_price: float, high: float, low: float, close: float) -> bool:
        """Doji formasyonu kontrolü"""
        body_size = abs(close - open_price)
        total_range = high - low
        
        if total_range == 0:
            return False
            
        # Gövde çok küçük olmalı (toplam boyun en fazla %10'u)
        body_ratio = body_size / total_range
        
        return body_ratio <= 0.1
    
    async def _check_popular_coins_for_scalping(self, exchange) -> List[Dict]:
        """Popüler coinleri scalping için kontrol et"""
        popular_coins = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", 
                         "ADAUSDT", "DOGEUSDT", "MATICUSDT", "AVAXUSDT", "LINKUSDT"]
        opportunities = []
        
        for symbol in popular_coins:
            try:
                if '/' not in symbol:
                    exchange_symbol = f"{symbol[:-4]}/USDT" if symbol.endswith('USDT') else f"{symbol}/USDT"
                else:
                    exchange_symbol = symbol
                
                # Ticker bilgisi al
                ticker = await exchange.fetch_ticker(exchange_symbol)
                current_price = ticker['last']
                volume = ticker['quoteVolume']
                
                # 15 dakikalık OHLCV verilerini al
                ohlcv = await exchange.fetch_ohlcv(exchange_symbol, '15m', limit=100)
                
                if not ohlcv or len(ohlcv) < 20:
                    continue
                
                # Scalping analizi yap
                opportunity = await self._analyze_scalping_opportunity(symbol, current_price, volume, ohlcv)
                
                if opportunity:
                    opportunities.append(opportunity)
                
            except Exception as e:
                self.logger.error(f"Popüler coin analizi hatası {symbol}: {e}")
                continue
        
        # Fırsatları puanlara göre sırala
        opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
        
        # En iyi 3 fırsatı göster
        return opportunities[:3]