import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from .analysis.technical_analysis import TechnicalAnalysis, MarketDataProvider
import asyncio
from scipy.signal import argrelextrema
import random
import logging
import aiohttp
import ccxt.async_support as ccxt
import json
import os
import uuid
import math


class MarketAnalyzer:
    def __init__(self, config):
        """Market Analyzer sınıfı başlatıcısı"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._btc_closes = np.array([])
        
        # Başarı oranı takibi için
        self.signal_history = []
        self.success_history = []
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'signal_history.json')
        
        # Veritabanını yükle
        self._load_signal_history()
    
    def _load_signal_history(self):
        """Sinyal geçmişini yükle"""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.signal_history = data.get('signals', [])
                    self.success_history = data.get('results', [])
                    
                    # Son 100 sinyali tut
                    if len(self.signal_history) > 100:
                        self.signal_history = self.signal_history[-100:]
                        self.success_history = self.success_history[-100:]
                        
                    self.logger.info(f"Sinyal geçmişi yüklendi: {len(self.signal_history)} kayıt")
            else:
                self.logger.info("Sinyal geçmişi bulunamadı, yeni oluşturulacak")
                # Veritabanı dizinini oluştur
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
                self._save_signal_history()
        except Exception as e:
            self.logger.error(f"Sinyal geçmişi yükleme hatası: {e}")
    
    def _save_signal_history(self):
        """Sinyal geçmişini kaydet"""
        try:
            with open(self.db_path, 'w') as f:
                json.dump({
                    'signals': self.signal_history,
                    'results': self.success_history
                }, f, indent=2)
            self.logger.info(f"Sinyal geçmişi kaydedildi: {len(self.signal_history)} kayıt")
        except Exception as e:
            self.logger.error(f"Sinyal geçmişi kaydetme hatası: {e}")
    
    def add_signal(self, signal_data):
        """Yeni sinyal ekle"""
        try:
            # Sinyal ID'si oluştur
            signal_id = str(uuid.uuid4())
            
            # Sinyal verisi
            signal = {
                'id': signal_id,
                'symbol': signal_data['symbol'],
                'signal_type': signal_data['signal'],
                'entry_price': signal_data['current_price'],
                'stop_price': signal_data['stop_price'],
                'target_price': signal_data['target_price'],
                'score': signal_data['opportunity_score'],
                'timestamp': datetime.now().isoformat()
            }
            
            # Sinyali kaydet
            self.signal_history.append(signal)
            
            # Veritabanını güncelle
            self._save_signal_history()
            
            return signal_id
        except Exception as e:
            self.logger.error(f"Sinyal ekleme hatası: {e}")
            return None
    
    def update_signal_result(self, signal_id, result, actual_profit=None):
        """Sinyal sonucunu güncelle"""
        try:
            # Sinyali bul
            for signal in self.signal_history:
                if signal['id'] == signal_id:
                    # Sonucu kaydet
                    result_data = {
                        'signal_id': signal_id,
                        'symbol': signal['symbol'],
                        'signal_type': signal['signal_type'],
                        'result': result,  # 'success', 'failure', 'timeout'
                        'profit': actual_profit,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    self.success_history.append(result_data)
                    
                    # Veritabanını güncelle
                    self._save_signal_history()
                    
                    return True
            
            return False
        except Exception as e:
            self.logger.error(f"Sinyal sonucu güncelleme hatası: {e}")
            return False
    
    def get_success_rate(self, signal_type=None, time_period=None):
        """Başarı oranını hesapla"""
        try:
            if not self.success_history:
                return {
                    'success_rate': 0,
                    'total_signals': 0,
                    'successful_signals': 0,
                    'failed_signals': 0,
                    'avg_profit': 0
                }
            
            # Filtreleme
            filtered_results = self.success_history
            
            # Sinyal tipine göre filtrele
            if signal_type:
                filtered_results = [r for r in filtered_results if signal_type in r['signal_type']]
            
            # Zaman periyoduna göre filtrele
            if time_period:
                now = datetime.now()
                cutoff = now - timedelta(days=time_period)
                filtered_results = [r for r in filtered_results if datetime.fromisoformat(r['timestamp']) > cutoff]
            
            # Başarı sayısı
            successful = [r for r in filtered_results if r['result'] == 'success']
            failed = [r for r in filtered_results if r['result'] == 'failure']
            
            # Toplam sinyal sayısı
            total = len(filtered_results)
            
            # Başarı oranı
            success_rate = (len(successful) / total) * 100 if total > 0 else 0
            
            # Ortalama kâr
            profits = [r['profit'] for r in successful if r['profit'] is not None]
            avg_profit = sum(profits) / len(profits) if profits else 0
            
            return {
                'success_rate': round(success_rate, 2),
                'total_signals': total,
                'successful_signals': len(successful),
                'failed_signals': len(failed),
                'avg_profit': round(avg_profit, 2)
            }
        except Exception as e:
            self.logger.error(f"Başarı oranı hesaplama hatası: {e}")
            return {
                'success_rate': 0,
                'total_signals': 0,
                'successful_signals': 0,
                'failed_signals': 0,
                'avg_profit': 0,
                'error': str(e)
            }

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

    def _find_support_resistance_levels(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> dict:
        """Destek ve direnç seviyelerini bul"""
        try:
            # Son 100 mumu kullan
            window = min(100, len(closes))
            recent_highs = highs[-window:]
            recent_lows = lows[-window:]
            recent_closes = closes[-window:]
            
            # Yerel tepe ve dip noktaları bul
            peaks = []
            troughs = []
            
            for i in range(2, len(recent_highs)-2):
                # Yerel tepe
                if recent_highs[i] > recent_highs[i-1] and recent_highs[i] > recent_highs[i-2] and \
                   recent_highs[i] > recent_highs[i+1] and recent_highs[i] > recent_highs[i+2]:
                    peaks.append(recent_highs[i])
                
                # Yerel dip
                if recent_lows[i] < recent_lows[i-1] and recent_lows[i] < recent_lows[i-2] and \
                   recent_lows[i] < recent_lows[i+1] and recent_lows[i] < recent_lows[i+2]:
                    troughs.append(recent_lows[i])
            
            # Fiyat kümeleme ile destek/direnç seviyeleri bul
            def cluster_prices(prices, threshold=0.01):
                if not prices:
                    return []
                    
                # Fiyatları sırala
                sorted_prices = sorted(prices)
                
                # Kümeleri oluştur
                clusters = []
                current_cluster = [sorted_prices[0]]
                
                for i in range(1, len(sorted_prices)):
                    # Eğer fiyat önceki fiyata yakınsa, aynı kümeye ekle
                    if sorted_prices[i] <= current_cluster[-1] * (1 + threshold):
                        current_cluster.append(sorted_prices[i])
                    else:
                        # Yeni küme başlat
                        clusters.append(current_cluster)
                        current_cluster = [sorted_prices[i]]
                
                # Son kümeyi ekle
                if current_cluster:
                    clusters.append(current_cluster)
                
                # Her kümenin ortalamasını al
                return [sum(cluster) / len(cluster) for cluster in clusters]
            
            # Destek ve direnç seviyelerini kümeleme ile bul
            support_levels = cluster_prices(troughs)
            resistance_levels = cluster_prices(peaks)
            
            # Son fiyata göre sırala (yakından uzağa)
            current_price = recent_closes[-1]
            
            support_levels = sorted(support_levels, key=lambda x: abs(current_price - x))
            resistance_levels = sorted(resistance_levels, key=lambda x: abs(current_price - x))
            
            return {
                'support': support_levels[:3],  # En yakın 3 destek
                'resistance': resistance_levels[:3]  # En yakın 3 direnç
            }
            
        except Exception as e:
            self.logger.error(f"Destek/direnç bulma hatası: {e}")
            return {'support': [], 'resistance': []}

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
        """15 dakikalık zaman diliminde yüksek kaliteli al-çık fırsatları için tarama yapar"""
        exchange = None
        try:
            # Her taramada yeni bir exchange oluştur
            exchange = await self._create_exchange()
            
            # Piyasa durumunu analiz et
            market_state = await self._analyze_market_state(exchange)
            
            # BTC verilerini al (piyasa durumu için)
            btc_ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '15m', limit=100)
            if btc_ohlcv and len(btc_ohlcv) > 0:
                self._btc_closes = np.array([float(candle[4]) for candle in btc_ohlcv])
                
                # BTC trend yönünü belirle
                btc_ema9 = self._calculate_ema(self._btc_closes, 9)
                btc_ema21 = self._calculate_ema(self._btc_closes, 21)
                btc_trend = "YUKARI" if btc_ema9[-1] > btc_ema21[-1] else "AŞAĞI"
                
                self.logger.info(f"BTC trend: {btc_trend}, Piyasa durumu: {market_state['state']}")
            
            # Tüm sembolleri al
            tickers = await self._get_all_tickers(exchange)
            if not tickers or len(tickers) == 0:
                self.logger.error("Ticker verileri alınamadı")
                return []
            
            # Yüksek kaliteli al-çık fırsatları bul
            high_quality_opportunities = await self._find_high_quality_scalping_opportunities(tickers, exchange, btc_trend, market_state)
            
            # Sonuçları döndür
            return high_quality_opportunities
            
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
    
    async def _analyze_market_state(self, exchange) -> Dict:
        """Genel piyasa durumunu analiz et"""
        try:
            # BTC, ETH ve toplam piyasa durumunu analiz et
            btc_ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '15m', limit=100)
            eth_ohlcv = await exchange.fetch_ohlcv('ETH/USDT', '15m', limit=100)
            
            if not btc_ohlcv or not eth_ohlcv:
                return {"state": "NÖTR", "volatility": "NORMAL", "trend_strength": "ZAYIF"}
            
            # BTC ve ETH fiyatları
            btc_closes = np.array([float(candle[4]) for candle in btc_ohlcv])
            eth_closes = np.array([float(candle[4]) for candle in eth_ohlcv])
            
            # BTC volatilitesi (ATR/Fiyat)
            btc_highs = np.array([float(candle[2]) for candle in btc_ohlcv])
            btc_lows = np.array([float(candle[3]) for candle in btc_ohlcv])
            btc_atr = self._calculate_atr(btc_highs, btc_lows, btc_closes, 14)
            btc_volatility = btc_atr[-1] / btc_closes[-1] * 100  # Yüzde olarak
            
            # BTC trend gücü (ADX)
            btc_adx = self._calculate_adx(btc_highs, btc_lows, btc_closes, 14)
            
            # BTC ve ETH korelasyonu
            correlation = np.corrcoef(btc_closes[-20:], eth_closes[-20:])[0, 1]
            
            # BTC trend yönü
            btc_ema9 = self._calculate_ema(btc_closes, 9)
            btc_ema21 = self._calculate_ema(btc_closes, 21)
            btc_ema55 = self._calculate_ema(btc_closes, 55)
            
            # Trend yönü
            if btc_ema9[-1] > btc_ema21[-1] and btc_ema21[-1] > btc_ema55[-1]:
                trend = "GÜÇLÜ YUKARI"
            elif btc_ema9[-1] > btc_ema21[-1]:
                trend = "YUKARI"
            elif btc_ema9[-1] < btc_ema21[-1] and btc_ema21[-1] < btc_ema55[-1]:
                trend = "GÜÇLÜ AŞAĞI"
            elif btc_ema9[-1] < btc_ema21[-1]:
                trend = "AŞAĞI"
            else:
                trend = "NÖTR"
            
            # Volatilite durumu
            if btc_volatility > 3.0:
                volatility = "YÜKSEK"
            elif btc_volatility > 1.5:
                volatility = "NORMAL"
            else:
                volatility = "DÜŞÜK"
            
            # Trend gücü
            if btc_adx[-1] > 30:
                trend_strength = "GÜÇLÜ"
            elif btc_adx[-1] > 20:
                trend_strength = "ORTA"
            else:
                trend_strength = "ZAYIF"
            
            # Piyasa durumu
            if trend in ["GÜÇLÜ YUKARI", "YUKARI"] and trend_strength in ["GÜÇLÜ", "ORTA"]:
                state = "BOĞA"
            elif trend in ["GÜÇLÜ AŞAĞI", "AŞAĞI"] and trend_strength in ["GÜÇLÜ", "ORTA"]:
                state = "AYI"
            elif volatility == "YÜKSEK":
                state = "DALGALI"
            else:
                state = "NÖTR"
            
            return {
                "state": state,
                "trend": trend,
                "volatility": volatility,
                "trend_strength": trend_strength,
                "btc_adx": float(btc_adx[-1]),
                "btc_volatility": float(btc_volatility),
                "btc_eth_correlation": float(correlation)
            }
            
        except Exception as e:
            self.logger.error(f"Piyasa durumu analiz hatası: {e}")
            return {"state": "NÖTR", "volatility": "NORMAL", "trend_strength": "ZAYIF"}
    
    async def _find_high_quality_scalping_opportunities(self, ticker_data: List[Dict], exchange, btc_trend: str, market_state: Dict) -> List[Dict]:
        """Yüksek kaliteli al-çık fırsatları bul"""
        opportunities = []
        
        try:
            # USDT çiftlerini filtrele
            filtered_tickers = [t for t in ticker_data if t['symbol'].endswith('USDT')]
            
            # Minimum fiyat kontrolü
            filtered_tickers = [t for t in filtered_tickers if float(t['lastPrice']) >= 0.000001]
            
            # Minimum hacim kontrolü - daha düşük hacim eşiği kullan
            filtered_tickers = [t for t in filtered_tickers if float(t['quoteVolume']) >= 500000]  # 500K USDT
            
            # Fiyat değişimi kontrolünü kaldır (API'de bu alan olmayabilir)
            # filtered_tickers = [t for t in filtered_tickers if abs(float(t.get('priceChangePercent', 0))) >= 1.0]
            
            self.logger.info(f"Filtreleme sonrası: {len(filtered_tickers)} coin")
            
            # Piyasa durumuna göre strateji belirle
            market_condition = market_state["state"]
            
            # Piyasa durumuna göre analiz edilecek coin sayısını ve minimum puanı ayarla
            if market_condition == "BOĞA":
                max_coins = 50  # Boğa piyasasında daha fazla coin analiz et
                min_score = 60  # Daha düşük puan eşiği
            elif market_condition == "AYI":
                max_coins = 30  # Ayı piyasasında daha az coin analiz et
                min_score = 70  # Daha yüksek puan eşiği
            elif market_condition == "DALGALI":
                max_coins = 40
                min_score = 65
            else:  # NÖTR
                max_coins = 40
                min_score = 65
            
            # Hacme göre sırala
            filtered_tickers = sorted(
                filtered_tickers,
                key=lambda x: float(x['quoteVolume']),
                reverse=True
            )
            
            # En yüksek hacimli coinleri analiz et
            filtered_tickers = filtered_tickers[:max_coins]
            
            # Önce popüler coinleri kontrol et
            popular_coins = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", 
                            "ADAUSDT", "DOGEUSDT", "MATICUSDT", "AVAXUSDT", "LINKUSDT",
                            "DOTUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT",
                            "APTUSDT", "NEARUSDT", "INJUSDT", "SUIUSDT", "OPUSDT"]
            
            popular_opportunities = []
            for symbol in popular_coins:
                if any(t['symbol'] == symbol for t in filtered_tickers):
                    ticker = next(t for t in filtered_tickers if t['symbol'] == symbol)
                    opportunity = await self._analyze_for_quick_scalp(ticker, exchange, btc_trend, market_state, min_score)
                    if opportunity:
                        popular_opportunities.append(opportunity)
            
            # Diğer coinleri analiz et
            other_opportunities = []
            for ticker in filtered_tickers:
                if ticker['symbol'] not in popular_coins:
                    opportunity = await self._analyze_for_quick_scalp(ticker, exchange, btc_trend, market_state, min_score)
                    if opportunity:
                        other_opportunities.append(opportunity)
            
            # Fırsatları puanlara göre sırala
            popular_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            other_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            # En iyi 2 popüler coin ve en iyi 3 diğer coin
            opportunities = popular_opportunities[:2] + other_opportunities[:3]
            
            # Fırsatları puanlara göre tekrar sırala
            opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            # Eğer hiç fırsat bulunamazsa, kriterleri gevşet ve tekrar dene
            if len(opportunities) == 0:
                self.logger.info("İlk taramada fırsat bulunamadı, kriterler gevşetiliyor...")
                
                # Tüm coinleri tekrar analiz et, daha düşük puanları da kabul et
                all_opportunities = []
                for ticker in filtered_tickers:
                    opportunity = await self._analyze_for_quick_scalp(ticker, exchange, btc_trend, market_state, min_score-10)
                    if opportunity:
                        all_opportunities.append(opportunity)
                
                # Fırsatları puanlara göre sırala
                all_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
                
                # En iyi 3 fırsatı al
                opportunities = all_opportunities[:3]
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Yüksek kaliteli al-çık fırsatları bulma hatası: {e}")
            return []
    
    async def _analyze_for_quick_scalp(self, ticker: Dict, exchange, btc_trend: str, market_state: Dict, min_score: int = 70) -> Optional[Dict]:
        """Hızlı al-çık analizi yap"""
        try:
            symbol = ticker['symbol']
            current_price = float(ticker['lastPrice'])
            volume = float(ticker['quoteVolume'])
            
            # Fiyat değişimi hesapla (API'den gelmiyorsa kendimiz hesaplayalım)
            price_change = 0
            try:
                # Eğer API'den geliyorsa kullan
                if 'priceChangePercent' in ticker:
                    price_change = float(ticker['priceChangePercent'])
                else:
                    # 24 saatlik veri al ve kendimiz hesaplayalım
                    ohlcv_daily = await exchange.fetch_ohlcv(symbol, '1d', limit=2)
                    if ohlcv_daily and len(ohlcv_daily) >= 2:
                        yesterday_close = float(ohlcv_daily[0][4])
                        price_change = (current_price - yesterday_close) / yesterday_close * 100
            except:
                price_change = 0
            
            self.logger.info(f"Hızlı al-çık analizi: {symbol}")
            
            # OHLCV verileri al
            ohlcv = await exchange.fetch_ohlcv(symbol, '15m', limit=100)
            
            if not ohlcv or len(ohlcv) < 20:
                return None
            
            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(candle[4]) for candle in ohlcv])
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            opens = np.array([float(candle[1]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Temel indikatörler
            rsi = self._calculate_rsi(closes, 14)
            ema9 = self._calculate_ema(closes, 9)
            ema21 = self._calculate_ema(closes, 21)
            ema55 = self._calculate_ema(closes, 55)
            macd, macd_signal, macd_hist = self._calculate_macd(closes)
            
            # Bollinger Bands
            upper_band, middle_band, lower_band = self._calculate_bollinger_bands(closes, 20, 2)
            
            # Supertrend
            supertrend, supertrend_direction = self._calculate_supertrend(highs, lows, closes, 10, 3.0)
            
            # ATR
            atr = self._calculate_atr(highs, lows, closes, 14)
            
            # Stochastic RSI
            stoch_rsi, stoch_k, stoch_d = self._calculate_stochastic_rsi(closes, 14, 3, 3)
            
            # Destek ve direnç seviyeleri
            support_resistance = self._find_support_resistance_levels(highs, lows, closes)
            
            # LONG sinyali puanı
            long_score = 0
            long_reasons = []
            
            # SHORT sinyali puanı
            short_score = 0
            short_reasons = []
            
            # Piyasa durumuna göre bonus puanlar
            market_condition = market_state["state"]
            
            if market_condition == "BOĞA":
                long_score += 10
                long_reasons.append("Boğa piyasası")
            elif market_condition == "AYI":
                short_score += 10
                short_reasons.append("Ayı piyasası")
            
            # RSI
            if rsi[-1] < 30:
                long_score += 20
                long_reasons.append("Aşırı satım (RSI<30)")
            elif rsi[-1] < 40:
                long_score += 10
                long_reasons.append("Düşük RSI")
            
            if rsi[-1] > 70:
                short_score += 20
                short_reasons.append("Aşırı alım (RSI>70)")
            elif rsi[-1] > 60:
                short_score += 10
                short_reasons.append("Yüksek RSI")
            
            # EMA çaprazlamaları
            if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
                long_score += 15
                long_reasons.append("EMA çaprazlama (9>21)")
            elif ema9[-1] > ema21[-1]:
                long_score += 10
                long_reasons.append("EMA yukarı trend")
            
            if ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
                short_score += 15
                short_reasons.append("EMA çaprazlama (9<21)")
            elif ema9[-1] < ema21[-1]:
                short_score += 10
                short_reasons.append("EMA aşağı trend")
            
            # MACD
            if macd[-1] > macd_signal[-1] and macd[-2] <= macd_signal[-2]:
                long_score += 15
                long_reasons.append("MACD çaprazlama")
            elif macd_hist[-1] > 0 and macd_hist[-1] > macd_hist[-2]:
                long_score += 10
                long_reasons.append("MACD yükseliyor")
            
            if macd[-1] < macd_signal[-1] and macd[-2] >= macd_signal[-2]:
                short_score += 15
                short_reasons.append("MACD çaprazlama")
            elif macd_hist[-1] < 0 and macd_hist[-1] < macd_hist[-2]:
                short_score += 10
                short_reasons.append("MACD düşüyor")
            
            # Bollinger Bands
            if closes[-1] < lower_band[-1]:
                long_score += 15
                long_reasons.append("BB alt bandı kırıldı")
            
            if closes[-1] > upper_band[-1]:
                short_score += 15
                short_reasons.append("BB üst bandı kırıldı")
            
            # Supertrend
            if supertrend_direction[-1] == 1:
                long_score += 15
                long_reasons.append("Supertrend yukarı")
            
            if supertrend_direction[-1] == -1:
                short_score += 15
                short_reasons.append("Supertrend aşağı")
            
            # ADX
            adx = self._calculate_adx(highs, lows, closes, 14)
            if adx[-1] > 25:
                # Trend güçlüyse, mevcut trende bonus puan ver
                if supertrend_direction[-1] == 1:
                    long_score += 10
                    long_reasons.append("Güçlü trend (ADX>25)")
                else:
                    short_score += 10
                    short_reasons.append("Güçlü trend (ADX>25)")
            
            # Stochastic RSI
            if stoch_k[-1] < 20 and stoch_k[-1] > stoch_d[-1]:
                long_score += 15
                long_reasons.append("Stoch RSI dönüşü")
            
            if stoch_k[-1] > 80 and stoch_k[-1] < stoch_d[-1]:
                short_score += 15
                short_reasons.append("Stoch RSI dönüşü")
            
            # Destek seviyesine yakınlık
            if support_resistance['support'] and abs(current_price - support_resistance['support'][0]) / current_price < 0.01:
                long_score += 15
                long_reasons.append("Destek seviyesinde")
            
            # Direnç seviyesine yakınlık
            if support_resistance['resistance'] and abs(current_price - support_resistance['resistance'][0]) / current_price < 0.01:
                short_score += 15
                short_reasons.append("Direnç seviyesinde")
            
            # Hacim artışı
            if volumes[-1] > np.mean(volumes[-5:]) * 1.5:
                if closes[-1] > opens[-1]:  # Yeşil mum
                    long_score += 10
                    long_reasons.append("Hacim artışı")
                else:  # Kırmızı mum
                    short_score += 10
                    short_reasons.append("Hacim artışı")
            
            # BTC trendi ile uyum
            if btc_trend == "YUKARI" and long_score > 0:
                long_score += 10
                long_reasons.append("BTC trend uyumlu")
            
            if btc_trend == "AŞAĞI" and short_score > 0:
                short_score += 10
                short_reasons.append("BTC trend uyumlu")
            
            # LONG sinyali için minimum puan
            long_signal = long_score >= min_score
            
            # SHORT sinyali için minimum puan
            short_signal = short_score >= min_score
            
            # Sinyal belirleme
            signal = None
            score = 0
            reasons = []
            
            if long_signal and short_signal:
                # Her iki sinyal de güçlüyse, daha yüksek puanlı olanı seç
                if long_score > short_score:
                    signal = "⚡ HIZLI LONG"
                    score = long_score
                    reasons = long_reasons
                else:
                    signal = "⚡ HIZLI SHORT"
                    score = short_score
                    reasons = short_reasons
            elif long_signal:
                signal = "⚡ HIZLI LONG"
                score = long_score
                reasons = long_reasons
            elif short_signal:
                signal = "⚡ HIZLI SHORT"
                score = short_score
                reasons = short_reasons
            else:
                return None  # Sinyal yok
            
            # Stop loss ve take profit hesapla
            if "LONG" in signal:
                # LONG sinyali için
                entry_price = current_price
                stop_price = max(current_price - (atr[-1] * 1.0), lows[-1] - (atr[-1] * 0.2))
                target_price = current_price + (atr[-1] * 2.0)
                
                # Alternatif hedefler
                target1 = current_price + (atr[-1] * 1.0)  # 1 ATR (kısa hedef)
                target2 = current_price + (atr[-1] * 3.0)  # 3 ATR (uzun hedef)
            else:
                # SHORT sinyali için
                entry_price = current_price
                stop_price = min(current_price + (atr[-1] * 1.0), highs[-1] + (atr[-1] * 0.2))
                target_price = current_price - (atr[-1] * 2.0)
                
                # Alternatif hedefler
                target1 = current_price - (atr[-1] * 1.0)  # 1 ATR (kısa hedef)
                target2 = current_price - (atr[-1] * 3.0)  # 3 ATR (uzun hedef)
            
            # Risk/ödül oranı
            risk = abs(entry_price - stop_price)
            reward = abs(entry_price - target_price)
            risk_reward = reward / risk if risk > 0 else 1.0
            
            # Risk/ödül oranı en az 1.2 olmalı (daha düşük eşik)
            if risk_reward < 1.2:
                return None
            
            # Tahmini işlem süresi (dakika)
            estimated_time = 15 * 3  # Ortalama 3 mum (45 dakika)
            
            # Başarı olasılığı (%)
            success_probability = min(95, score)  # Maksimum %95
            
            # Giriş stratejisi
            entry_strategy = " + ".join(reasons[:3])  # En önemli 3 neden
            
            # Çıkış stratejisi
            if "LONG" in signal:
                exit_strategy = f"Hedef: {target_price:.6f} veya RSI>70 veya MACD çaprazlama"
            else:
                exit_strategy = f"Hedef: {target_price:.6f} veya RSI<30 veya MACD çaprazlama"
            
            # Destek ve direnç seviyeleri
            support_levels = support_resistance['support'][:2] if support_resistance['support'] else []
            resistance_levels = support_resistance['resistance'][:2] if support_resistance['resistance'] else []
            
            # Piyasa durumu bilgisi
            market_info = f"{market_state['state']} piyasa, {market_state['trend_strength']} trend"
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'signal': signal,
                'opportunity_score': score,
                'success_probability': f"%{success_probability}",
                'entry_price': entry_price,
                'stop_price': stop_price,
                'target_price': target_price,
                'target1': target1,  # Kısa hedef
                'target2': target2,  # Uzun hedef
                'risk_reward': risk_reward,
                'estimated_time': f"{estimated_time} dakika",
                'entry_strategy': entry_strategy,
                'exit_strategy': exit_strategy,
                'rsi': float(rsi[-1]),
                'volume': volume,
                'price_change_24h': f"%{price_change:.2f}",
                'support_levels': support_levels,
                'resistance_levels': resistance_levels,
                'market_state': market_info,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Hızlı al-çık analizi hatası ({symbol}): {e}")
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
    
    def _calculate_fibonacci_levels(self, highs: np.ndarray, lows: np.ndarray) -> dict:
        """Fibonacci seviyeleri hesapla"""
        # Son 20 mumun en yüksek ve en düşük değerleri
        recent_high = np.max(highs[-20:])
        recent_low = np.min(lows[-20:])
        
        # Fibonacci seviyeleri
        range_size = recent_high - recent_low
        
        return {
            'level_0': recent_low,  # 0.0
            'level_236': recent_low + range_size * 0.236,  # 23.6%
            'level_382': recent_low + range_size * 0.382,  # 38.2%
            'level_500': recent_low + range_size * 0.5,    # 50.0%
            'level_618': recent_low + range_size * 0.618,  # 61.8%
            'level_786': recent_low + range_size * 0.786,  # 78.6%
            'level_1000': recent_high  # 100.0%
        }
    
    def _calculate_volume_trend(self, volumes: np.ndarray) -> str:
        """Hacim trendini hesapla"""
        if len(volumes) < 10:
            return "NÖTR"
            
        # Son 10 mumun hacim eğilimi
        volume_sma5 = np.array(pd.Series(volumes[-10:]).rolling(window=5).mean())
        
        if np.isnan(volume_sma5[-1]) or np.isnan(volume_sma5[-2]):
            return "NÖTR"
            
        if volume_sma5[-1] > volume_sma5[-2] * 1.05:
            return "YUKARI"
        elif volume_sma5[-1] < volume_sma5[-2] * 0.95:
            return "AŞAĞI"
        else:
            return "NÖTR"
    
    def _calculate_obv(self, closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
        """On Balance Volume (OBV) hesapla"""
        obv = np.zeros_like(closes)
        
        # İlk değer
        obv[0] = volumes[0]
        
        # OBV hesapla
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv[i] = obv[i-1] + volumes[i]
            elif closes[i] < closes[i-1]:
                obv[i] = obv[i-1] - volumes[i]
            else:
                obv[i] = obv[i-1]
        
        return obv
    
    def _calculate_buying_selling_pressure(self, opens: np.ndarray, closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, volumes: np.ndarray) -> tuple:
        """Alım-Satım Baskısı hesapla"""
        buying_pressure = 0
        selling_pressure = 0
        
        # Son 5 mumu analiz et
        for i in range(max(0, len(closes)-5), len(closes)):
            if i >= len(opens) or i >= len(closes) or i >= len(highs) or i >= len(lows) or i >= len(volumes):
                continue
                
            # Mum yönü
            is_bullish = closes[i] > opens[i]
            
            # Gövde ve gölge boyutları
            body_size = abs(closes[i] - opens[i])
            if is_bullish:
                upper_shadow = highs[i] - closes[i]
                lower_shadow = opens[i] - lows[i]
            else:
                upper_shadow = highs[i] - opens[i]
                lower_shadow = closes[i] - lows[i]
            
            # Toplam boyut
            total_size = body_size + upper_shadow + lower_shadow
            
            if total_size == 0:
                continue
                
            # Hacim ağırlıklı baskı
            if is_bullish:
                # Alım baskısı: gövde + alt gölge
                buying_pressure += volumes[i] * (body_size + lower_shadow) / total_size
                # Satım baskısı: üst gölge
                selling_pressure += volumes[i] * upper_shadow / total_size
            else:
                # Alım baskısı: alt gölge
                buying_pressure += volumes[i] * lower_shadow / total_size
                # Satım baskısı: gövde + üst gölge
                selling_pressure += volumes[i] * (body_size + upper_shadow) / total_size
        
        return buying_pressure, selling_pressure
    
    def _calculate_adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> tuple:
        """Average Directional Index (ADX) hesapla"""
        if len(highs) < period + 1:
            return np.array([20]), np.array([20]), np.array([20])  # Varsayılan değerler
            
        # True Range hesapla
        tr = np.zeros(len(highs))
        tr[0] = highs[0] - lows[0]
        
        for i in range(1, len(highs)):
            tr[i] = max(
                highs[i] - lows[i],  # Günlük range
                abs(highs[i] - closes[i-1]),  # Dünkü kapanışa göre yüksek
                abs(lows[i] - closes[i-1])  # Dünkü kapanışa göre düşük
            )
        
        # Directional Movement hesapla
        plus_dm = np.zeros(len(highs))
        minus_dm = np.zeros(len(highs))
        
        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            else:
                plus_dm[i] = 0
                
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move
            else:
                minus_dm[i] = 0
        
        # Smoothed TR, +DM, -DM
        atr = np.zeros(len(tr))
        plus_di = np.zeros(len(plus_dm))
        minus_di = np.zeros(len(minus_dm))
        
        # İlk değerler
        atr[period-1] = np.sum(tr[:period])
        plus_di[period-1] = np.sum(plus_dm[:period])
        minus_di[period-1] = np.sum(minus_dm[:period])
        
        # Smoothing
        for i in range(period, len(tr)):
            atr[i] = atr[i-1] - (atr[i-1] / period) + tr[i]
            plus_di[i] = plus_di[i-1] - (plus_di[i-1] / period) + plus_dm[i]
            minus_di[i] = minus_di[i-1] - (minus_di[i-1] / period) + minus_dm[i]
        
        # +DI ve -DI hesapla
        plus_di_values = np.zeros(len(plus_di))
        minus_di_values = np.zeros(len(minus_di))
        
        for i in range(period-1, len(atr)):
            if atr[i] > 0:
                plus_di_values[i] = 100 * plus_di[i] / atr[i]
                minus_di_values[i] = 100 * minus_di[i] / atr[i]
            else:
                plus_di_values[i] = 0
                minus_di_values[i] = 0
        
        # DX hesapla
        dx = np.zeros(len(plus_di_values))
        
        for i in range(period-1, len(dx)):
            if plus_di_values[i] + minus_di_values[i] > 0:
                dx[i] = 100 * abs(plus_di_values[i] - minus_di_values[i]) / (plus_di_values[i] + minus_di_values[i])
            else:
                dx[i] = 0
        
        # ADX hesapla (DX'in period-period SMA'sı)
        adx = np.zeros(len(dx))
        
        # İlk ADX değeri
        if period*2-2 < len(dx):
            adx[period*2-2] = np.mean(dx[period-1:period*2-1])
        
        # Smoothing
        for i in range(period*2-1, len(dx)):
            adx[i] = (adx[i-1] * (period-1) + dx[i]) / period
        
        return adx, plus_di_values, minus_di_values
    
    def _analyze_market_structure(self, highs: np.ndarray, lows: np.ndarray) -> str:
        """Piyasa yapısını analiz et (Higher Highs, Lower Lows)"""
        if len(highs) < 10 or len(lows) < 10:
            return "BELİRSİZ"
            
        # Son 10 mumun yüksek ve düşük değerlerini analiz et
        # Yerel tepe ve dip noktaları bul
        peaks = []
        troughs = []
        
        for i in range(2, len(highs)-2):
            # Yerel tepe
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                peaks.append((i, highs[i]))
            
            # Yerel dip
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                troughs.append((i, lows[i]))
        
        # En az 2 tepe ve 2 dip gerekli
        if len(peaks) < 2 or len(troughs) < 2:
            return "BELİRSİZ"
            
        # Son iki tepe ve dibi karşılaştır
        peaks.sort(key=lambda x: x[0])  # Zamana göre sırala
        troughs.sort(key=lambda x: x[0])
        
        last_two_peaks = peaks[-2:]
        last_two_troughs = troughs[-2:]
        
        # Higher Highs, Higher Lows (Yükselen trend)
        if len(last_two_peaks) >= 2 and len(last_two_troughs) >= 2:
            if last_two_peaks[1][1] > last_two_peaks[0][1] and last_two_troughs[1][1] > last_two_troughs[0][1]:
                return "YÜKSELEN TREND"
            
            # Lower Highs, Lower Lows (Düşen trend)
            elif last_two_peaks[1][1] < last_two_peaks[0][1] and last_two_troughs[1][1] < last_two_troughs[0][1]:
                return "DÜŞEN TREND"
            
            # Higher Highs, Lower Lows (Genişleyen aralık)
            elif last_two_peaks[1][1] > last_two_peaks[0][1] and last_two_troughs[1][1] < last_two_troughs[0][1]:
                return "GENİŞLEYEN ARALIK"
            
            # Lower Highs, Higher Lows (Daralan aralık)
            elif last_two_peaks[1][1] < last_two_peaks[0][1] and last_two_troughs[1][1] > last_two_troughs[0][1]:
                return "DARALAN ARALIK"
        
        return "BELİRSİZ"
    
    def _calculate_correlation_with_btc(self, closes: np.ndarray) -> float:
        """BTC ile korelasyon hesapla"""
        # Eğer BTC verileri yoksa, varsayılan değer döndür
        if not hasattr(self, '_btc_closes') or len(self._btc_closes) < 20:
            return 0.0
            
        # Son 20 mumu kullan
        coin_returns = np.diff(closes[-21:]) / closes[-21:-1]
        btc_returns = np.diff(self._btc_closes[-21:]) / self._btc_closes[-21:-1]
        
        # Uzunlukları eşitle
        min_length = min(len(coin_returns), len(btc_returns))
        if min_length < 5:
            return 0.0
            
        coin_returns = coin_returns[-min_length:]
        btc_returns = btc_returns[-min_length:]
        
        # Korelasyon hesapla
        try:
            correlation = np.corrcoef(coin_returns, btc_returns)[0, 1]
            return correlation if not np.isnan(correlation) else 0.0
        except:
            return 0.0

    async def _validate_signal_with_ml(self, symbol: str, signal_type: str, ohlcv: list) -> float:
        """Makine öğrenimi ile sinyal doğrulama"""
        try:
            # Basit özellikler çıkar
            features = self._extract_ml_features(ohlcv)
            
            # Başarı geçmişine göre benzer durumları bul
            similar_signals = self._find_similar_signals(features, signal_type)
            
            # Benzer sinyallerin başarı oranını hesapla
            if similar_signals:
                success_count = sum(1 for s in similar_signals if s['result'] == 'success')
                confidence = success_count / len(similar_signals)
                
                self.logger.info(f"ML doğrulama: {symbol} için {len(similar_signals)} benzer sinyal bulundu, güven: %{round(confidence*100, 2)}")
                
                return confidence
            else:
                # Benzer sinyal bulunamazsa, genel başarı oranını kullan
                general_stats = self.get_success_rate(signal_type)
                return general_stats['success_rate'] / 100
                
        except Exception as e:
            self.logger.error(f"ML doğrulama hatası ({symbol}): {e}")
            return 0.5  # Varsayılan değer
    
    def _extract_ml_features(self, ohlcv: list) -> dict:
        """Makine öğrenimi için özellikler çıkar"""
        try:
            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(candle[4]) for candle in ohlcv])
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Temel özellikler
            rsi = self._calculate_rsi(closes, 14)
            ema9 = self._calculate_ema(closes, 9)
            ema21 = self._calculate_ema(closes, 21)
            
            # Son 5 mumun özellikleri
            last_candles = min(5, len(closes))
            recent_closes = closes[-last_candles:]
            recent_volumes = volumes[-last_candles:]
            
            # Fiyat değişimi
            price_change = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
            
            # Hacim değişimi
            volume_change = (volumes[-1] / volumes[-5] - 1) * 100 if len(volumes) >= 5 else 0
            
            # Volatilite (ATR)
            atr = self._calculate_atr(highs, lows, closes, 14)
            volatility = atr[-1] / closes[-1] * 100 if len(atr) > 0 else 0
            
            # Özellikler
            features = {
                'rsi': float(rsi[-1]) if len(rsi) > 0 else 50,
                'ema9_dist': float((closes[-1] / ema9[-1] - 1) * 100) if len(ema9) > 0 else 0,
                'ema21_dist': float((closes[-1] / ema21[-1] - 1) * 100) if len(ema21) > 0 else 0,
                'price_change': float(price_change),
                'volume_change': float(volume_change),
                'volatility': float(volatility),
                'close_position': float((closes[-1] - lows[-1]) / (highs[-1] - lows[-1]) * 100) if highs[-1] != lows[-1] else 50
            }
            
            return features
            
        except Exception as e:
            self.logger.error(f"Özellik çıkarma hatası: {e}")
            return {}
    
    def _find_similar_signals(self, features: dict, signal_type: str, max_signals: int = 10) -> list:
        """Benzer sinyalleri bul"""
        try:
            if not features or not self.success_history:
                return []
                
            # Sadece aynı sinyal tipindeki sonuçları filtrele
            filtered_history = [r for r in self.success_history if signal_type in r['signal_type']]
            
            if not filtered_history:
                return []
                
            # Her sonuç için benzerlik skoru hesapla
            scored_history = []
            
            for result in filtered_history:
                # Sinyal ID'sini bul
                signal_id = result['signal_id']
                
                # Sinyali bul
                signal = next((s for s in self.signal_history if s['id'] == signal_id), None)
                
                if not signal or 'features' not in signal:
                    continue
                    
                # Özellikler arasındaki benzerliği hesapla
                similarity = self._calculate_similarity(features, signal['features'])
                
                scored_history.append({
                    'result': result['result'],
                    'similarity': similarity
                })
            
            # Benzerliğe göre sırala
            scored_history.sort(key=lambda x: x['similarity'], reverse=True)
            
            # En benzer max_signals kadar sonucu döndür
            return scored_history[:max_signals]
            
        except Exception as e:
            self.logger.error(f"Benzer sinyal bulma hatası: {e}")
            return []
    
    def _calculate_similarity(self, features1: dict, features2: dict) -> float:
        """İki özellik seti arasındaki benzerliği hesapla"""
        try:
            # Ortak özellikleri bul
            common_features = set(features1.keys()) & set(features2.keys())
            
            if not common_features:
                return 0.0
                
            # Öklid mesafesi hesapla
            squared_diff_sum = 0
            
            for feature in common_features:
                # Özellik değerlerini normalize et
                value1 = features1[feature]
                value2 = features2[feature]
                
                # Kare farkını topla
                squared_diff_sum += (value1 - value2) ** 2
            
            # Mesafeyi benzerliğe dönüştür (1 / (1 + mesafe))
            distance = math.sqrt(squared_diff_sum)
            similarity = 1 / (1 + distance)
            
            return similarity
            
        except Exception as e:
            self.logger.error(f"Benzerlik hesaplama hatası: {e}")
            return 0.0

    async def get_performance_stats(self) -> Dict:
        """Performans istatistiklerini al"""
        try:
            # Genel başarı oranı
            overall_stats = self.get_success_rate()
            
            # Son 7 gün
            weekly_stats = self.get_success_rate(time_period=7)
            
            # Son 30 gün
            monthly_stats = self.get_success_rate(time_period=30)
            
            # Sinyal tiplerine göre
            long_stats = self.get_success_rate(signal_type="LONG")
            short_stats = self.get_success_rate(signal_type="SHORT")
            scalp_stats = self.get_success_rate(signal_type="SCALP")
            
            # Zaman dilimlerine göre
            stats_15m = self.get_success_rate(signal_type="15m")
            stats_1h = self.get_success_rate(signal_type="1h")
            stats_4h = self.get_success_rate(signal_type="4h")
            
            return {
                'overall': overall_stats,
                'weekly': weekly_stats,
                'monthly': monthly_stats,
                'by_type': {
                    'long': long_stats,
                    'short': short_stats,
                    'scalp': scalp_stats
                },
                'by_timeframe': {
                    '15m': stats_15m,
                    '1h': stats_1h,
                    '4h': stats_4h
                },
                'total_signals_tracked': len(self.signal_history),
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Performans istatistikleri alma hatası: {e}")
            return {
                'error': str(e),
                'overall': {'success_rate': 0}
            }

    def _calculate_supertrend(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 10, multiplier: float = 3.0) -> tuple:
        """Supertrend hesapla"""
        try:
            # ATR hesapla
            atr = self._calculate_atr(highs, lows, closes, period)
            
            # Supertrend hesapla
            hl2 = (highs + lows) / 2
            
            # Üst ve alt bantlar
            upper_band = hl2 + (multiplier * atr)
            lower_band = hl2 - (multiplier * atr)
            
            # Supertrend değerleri
            supertrend = np.zeros_like(closes)
            direction = np.zeros_like(closes)  # 1: yukarı trend, -1: aşağı trend
            
            # İlk değer
            supertrend[0] = closes[0]
            direction[0] = 1  # Başlangıçta yukarı trend kabul edelim
            
            # Supertrend hesapla
            for i in range(1, len(closes)):
                # Önceki değerler
                prev_upper = upper_band[i-1]
                prev_lower = lower_band[i-1]
                prev_supertrend = supertrend[i-1]
                prev_direction = direction[i-1]
                
                # Mevcut değerler
                curr_upper = upper_band[i]
                curr_lower = lower_band[i]
                curr_close = closes[i]
                
                # Yön değişimi kontrolü
                if prev_supertrend <= prev_upper and curr_close > curr_upper:
                    curr_direction = -1  # Aşağı trend
                elif prev_supertrend >= prev_lower and curr_close < curr_lower:
                    curr_direction = 1  # Yukarı trend
                else:
                    curr_direction = prev_direction  # Değişim yok
                
                # Supertrend değeri
                if curr_direction == 1:
                    curr_supertrend = curr_lower
                else:
                    curr_supertrend = curr_upper
                
                # Değerleri kaydet
                supertrend[i] = curr_supertrend
                direction[i] = curr_direction
            
            return supertrend, direction
            
        except Exception as e:
            self.logger.error(f"Supertrend hesaplama hatası: {e}")
            # Boş diziler döndür
            empty_array = np.zeros_like(closes)
            return empty_array, empty_array
    
    def _calculate_ichimoku(self, highs: np.ndarray, lows: np.ndarray) -> tuple:
        """Ichimoku Cloud hesapla"""
        try:
            # Tenkan-sen (Conversion Line): (9-period high + 9-period low)/2
            period9_high = np.array(pd.Series(highs).rolling(window=9).max())
            period9_low = np.array(pd.Series(lows).rolling(window=9).min())
            tenkan_sen = (period9_high + period9_low) / 2
            
            # Kijun-sen (Base Line): (26-period high + 26-period low)/2
            period26_high = np.array(pd.Series(highs).rolling(window=26).max())
            period26_low = np.array(pd.Series(lows).rolling(window=26).min())
            kijun_sen = (period26_high + period26_low) / 2
            
            # Senkou Span A (Leading Span A): (Conversion Line + Base Line)/2
            senkou_span_a = (tenkan_sen + kijun_sen) / 2
            
            # Senkou Span B (Leading Span B): (52-period high + 52-period low)/2
            period52_high = np.array(pd.Series(highs).rolling(window=52).max())
            period52_low = np.array(pd.Series(lows).rolling(window=52).min())
            senkou_span_b = (period52_high + period52_low) / 2
            
            return tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b
            
        except Exception as e:
            self.logger.error(f"Ichimoku hesaplama hatası: {e}")
            # Boş diziler döndür
            empty_array = np.zeros_like(highs)
            return empty_array, empty_array, empty_array, empty_array
    
    def _calculate_adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Average Directional Index (ADX) hesapla"""
        try:
            # True Range hesapla
            tr1 = np.abs(highs[1:] - lows[1:])
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(np.maximum(tr1, tr2), tr3)
            tr = np.insert(tr, 0, tr[0])  # İlk değeri ekle
            
            # Average True Range (ATR) hesapla
            atr = np.zeros_like(closes)
            atr[0] = tr[0]
            for i in range(1, len(tr)):
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
            
            # +DM ve -DM hesapla
            plus_dm = np.zeros_like(closes)
            minus_dm = np.zeros_like(closes)
            
            for i in range(1, len(closes)):
                # +DM: Bugünkü yüksek - Dünkü yüksek
                up_move = highs[i] - highs[i-1]
                # -DM: Dünkü düşük - Bugünkü düşük
                down_move = lows[i-1] - lows[i]
                
                if up_move > down_move and up_move > 0:
                    plus_dm[i] = up_move
                else:
                    plus_dm[i] = 0
                    
                if down_move > up_move and down_move > 0:
                    minus_dm[i] = down_move
                else:
                    minus_dm[i] = 0
            
            # +DI ve -DI hesapla
            plus_di = 100 * (plus_dm / atr)
            minus_di = 100 * (minus_dm / atr)
            
            # DX hesapla: |+DI - -DI| / |+DI + -DI| * 100
            dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)  # Sıfıra bölmeyi önle
            
            # ADX hesapla (DX'in period-periyotlu ortalaması)
            adx = np.zeros_like(closes)
            adx[period-1] = np.mean(dx[:period])
            
            for i in range(period, len(closes)):
                adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period
            
            return adx
            
        except Exception as e:
            self.logger.error(f"ADX hesaplama hatası: {e}")
            return np.zeros_like(closes)
    
    def _calculate_volume_profile(self, closes: np.ndarray, volumes: np.ndarray, num_bins: int = 10) -> dict:
        """Hacim Profili hesapla"""
        try:
            # Fiyat aralığını belirle
            min_price = np.min(closes)
            max_price = np.max(closes)
            
            # Fiyat aralıklarını oluştur
            price_range = max_price - min_price
            bin_size = price_range / num_bins
            
            # Boş hacim profili oluştur
            volume_profile = {
                'price_levels': [],
                'volumes': []
            }
            
            # Her fiyat seviyesi için hacim topla
            for i in range(num_bins):
                lower_bound = min_price + i * bin_size
                upper_bound = lower_bound + bin_size
                
                # Bu fiyat aralığındaki mumları bul
                in_range = (closes >= lower_bound) & (closes < upper_bound)
                volume_in_range = np.sum(volumes[in_range])
                
                # Orta fiyat noktası
                mid_price = (lower_bound + upper_bound) / 2
                
                volume_profile['price_levels'].append(mid_price)
                volume_profile['volumes'].append(volume_in_range)
            
            return volume_profile
            
        except Exception as e:
            self.logger.error(f"Hacim profili hesaplama hatası: {e}")
            return {'price_levels': [], 'volumes': []}
    
    def _calculate_macd(self, closes: np.ndarray, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> tuple:
        """MACD (Moving Average Convergence Divergence) hesapla"""
        try:
            # Hızlı EMA
            ema_fast = self._calculate_ema(closes, fast_period)
            
            # Yavaş EMA
            ema_slow = self._calculate_ema(closes, slow_period)
            
            # MACD Line = Hızlı EMA - Yavaş EMA
            macd_line = ema_fast - ema_slow
            
            # Signal Line = MACD Line'ın EMA'sı
            signal_line = np.array(pd.Series(macd_line).ewm(span=signal_period, adjust=False).mean())
            
            # Histogram = MACD Line - Signal Line
            histogram = macd_line - signal_line
            
            return macd_line, signal_line, histogram
            
        except Exception as e:
            self.logger.error(f"MACD hesaplama hatası: {e}")
            # Boş diziler döndür
            empty_array = np.zeros_like(closes)
            return empty_array, empty_array, empty_array
    
    def _calculate_rsi(self, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """RSI (Relative Strength Index) hesapla"""
        try:
            # Fiyat değişimleri
            deltas = np.diff(closes)
            
            # Pozitif ve negatif değişimler
            seed = deltas[:period+1]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            
            if down == 0:
                rs = float('inf')
            else:
                rs = up / down
            
            rsi = np.zeros_like(closes)
            rsi[period] = 100. - 100. / (1. + rs)
            
            # RSI hesapla
            for i in range(period + 1, len(closes)):
                delta = deltas[i - 1]
                
                if delta > 0:
                    upval = delta
                    downval = 0.
                else:
                    upval = 0.
                    downval = -delta
                
                up = (up * (period - 1) + upval) / period
                down = (down * (period - 1) + downval) / period
                
                if down == 0:
                    rs = float('inf')
                else:
                    rs = up / down
                
                rsi[i] = 100. - 100. / (1. + rs)
            
            return rsi
            
        except Exception as e:
            self.logger.error(f"RSI hesaplama hatası: {e}")
            return np.zeros_like(closes)
    
    def _calculate_ema(self, closes: np.ndarray, period: int) -> np.ndarray:
        """EMA (Exponential Moving Average) hesapla"""
        try:
            return np.array(pd.Series(closes).ewm(span=period, adjust=False).mean())
        except Exception as e:
            self.logger.error(f"EMA hesaplama hatası: {e}")
            return np.zeros_like(closes)
    
    def _calculate_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """ATR (Average True Range) hesapla"""
        try:
            # True Range hesapla
            tr1 = np.abs(highs[1:] - lows[1:])
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(np.maximum(tr1, tr2), tr3)
            tr = np.insert(tr, 0, tr[0])  # İlk değeri ekle
            
            # ATR hesapla
            atr = np.zeros_like(closes)
            atr[0] = tr[0]
            
            for i in range(1, len(tr)):
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
            
            return atr
            
        except Exception as e:
            self.logger.error(f"ATR hesaplama hatası: {e}")
            return np.zeros_like(closes)
    
    def _calculate_stochastic_rsi(self, closes: np.ndarray, period: int = 14, k_period: int = 3, d_period: int = 3) -> tuple:
        """Stochastic RSI hesapla"""
        try:
            # RSI hesapla
            rsi = self._calculate_rsi(closes, period)
            
            # Stochastic RSI hesapla
            stoch_rsi = np.zeros_like(closes)
            
            for i in range(period, len(closes)):
                rsi_window = rsi[i-period+1:i+1]
                
                if np.max(rsi_window) == np.min(rsi_window):
                    stoch_rsi[i] = 50  # Eğer max=min ise, 50 değerini kullan
                else:
                    stoch_rsi[i] = 100 * (rsi[i] - np.min(rsi_window)) / (np.max(rsi_window) - np.min(rsi_window))
            
            # %K ve %D hesapla
            k = np.array(pd.Series(stoch_rsi).rolling(window=k_period).mean())
            d = np.array(pd.Series(k).rolling(window=d_period).mean())
            
            return stoch_rsi, k, d
            
        except Exception as e:
            self.logger.error(f"Stochastic RSI hesaplama hatası: {e}")
            empty_array = np.zeros_like(closes)
            return empty_array, empty_array, empty_array
    
    def _calculate_bollinger_bands(self, closes: np.ndarray, period: int = 20, std_dev: float = 2.0) -> tuple:
        """Bollinger Bands hesapla"""
        try:
            # Orta bant (SMA)
            middle_band = np.array(pd.Series(closes).rolling(window=period).mean())
            
            # Standart sapma
            std = np.array(pd.Series(closes).rolling(window=period).std())
            
            # Üst ve alt bantlar
            upper_band = middle_band + (std * std_dev)
            lower_band = middle_band - (std * std_dev)
            
            return upper_band, middle_band, lower_band
            
        except Exception as e:
            self.logger.error(f"Bollinger Bands hesaplama hatası: {e}")
            # Boş diziler döndür
            empty_array = np.zeros_like(closes)
            return empty_array, empty_array, empty_array
    
    def _calculate_volume_oscillator(self, volumes: np.ndarray, fast_period: int = 5, slow_period: int = 10) -> np.ndarray:
        """Hacim Osilatörü hesapla"""
        try:
            # Hızlı ve yavaş hareketli ortalamalar
            fast_ma = np.array(pd.Series(volumes).rolling(window=fast_period).mean())
            slow_ma = np.array(pd.Series(volumes).rolling(window=slow_period).mean())
            
            # Hacim osilatörü
            volume_oscillator = ((fast_ma - slow_ma) / slow_ma) * 100
            
            return volume_oscillator
            
        except Exception as e:
            self.logger.error(f"Hacim Osilatörü hesaplama hatası: {e}")
            return np.zeros_like(volumes)
    
    def _calculate_parabolic_sar(self, highs: np.ndarray, lows: np.ndarray, acceleration: float = 0.02, maximum: float = 0.2) -> np.ndarray:
        """Parabolic SAR hesapla"""
        try:
            # Başlangıç değerleri
            sar = np.zeros_like(highs)
            trend = np.zeros_like(highs)  # 1: yukarı trend, -1: aşağı trend
            extreme_point = np.zeros_like(highs)
            acceleration_factor = np.zeros_like(highs)
            
            # İlk değerler
            trend[0] = 1  # Başlangıçta yukarı trend kabul edelim
            sar[0] = lows[0]  # Başlangıç SAR değeri
            extreme_point[0] = highs[0]  # Başlangıç EP değeri
            acceleration_factor[0] = acceleration  # Başlangıç AF değeri
            
            # Parabolic SAR hesapla
            for i in range(1, len(highs)):
                # Önceki değerler
                prev_sar = sar[i-1]
                prev_trend = trend[i-1]
                prev_ep = extreme_point[i-1]
                prev_af = acceleration_factor[i-1]
                
                # Mevcut değerler
                curr_high = highs[i]
                curr_low = lows[i]
                
                # SAR hesapla
                if prev_trend == 1:  # Yukarı trend
                    # SAR = Önceki SAR + Önceki AF * (Önceki EP - Önceki SAR)
                    curr_sar = prev_sar + prev_af * (prev_ep - prev_sar)
                    
                    # SAR değeri düzeltme
                    curr_sar = min(curr_sar, lows[i-1], lows[i-2] if i > 1 else lows[i-1])
                    
                    # Trend değişimi kontrolü
                    if curr_sar > curr_low:
                        curr_trend = -1  # Aşağı trend
                        curr_sar = prev_ep  # SAR değeri EP olur
                        curr_ep = curr_low  # EP değeri mevcut düşük olur
                        curr_af = acceleration  # AF değeri başlangıç değerine döner
                    else:
                        curr_trend = 1  # Yukarı trend devam eder
                        
                        # EP ve AF güncelleme
                        if curr_high > prev_ep:
                            curr_ep = curr_high  # EP güncelle
                            curr_af = min(prev_af + acceleration, maximum)  # AF güncelle
                        else:
                            curr_ep = prev_ep  # EP değişmez
                            curr_af = prev_af  # AF değişmez
                else:  # Aşağı trend
                    # SAR = Önceki SAR - Önceki AF * (Önceki SAR - Önceki EP)
                    curr_sar = prev_sar - prev_af * (prev_sar - prev_ep)
                    
                    # SAR değeri düzeltme
                    curr_sar = max(curr_sar, highs[i-1], highs[i-2] if i > 1 else highs[i-1])
                    
                    # Trend değişimi kontrolü
                    if curr_sar < curr_high:
                        curr_trend = 1  # Yukarı trend
                        curr_sar = prev_ep  # SAR değeri EP olur
                        curr_ep = curr_high  # EP değeri mevcut yüksek olur
                        curr_af = acceleration  # AF değeri başlangıç değerine döner
                    else:
                        curr_trend = -1  # Aşağı trend devam eder
                        
                        # EP ve AF güncelleme
                        if curr_low < prev_ep:
                            curr_ep = curr_low  # EP güncelle
                            curr_af = min(prev_af + acceleration, maximum)  # AF güncelle
                        else:
                            curr_ep = prev_ep  # EP değişmez
                            curr_af = prev_af  # AF değişmez
                
                # Değerleri kaydet
                sar[i] = curr_sar
                trend[i] = curr_trend
                extreme_point[i] = curr_ep
                acceleration_factor[i] = curr_af
            
            return sar
            
        except Exception as e:
            self.logger.error(f"Parabolic SAR hesaplama hatası: {e}")
            return np.zeros_like(highs)
    
    def _calculate_keltner_channel(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20, atr_multiplier: float = 2.0) -> tuple:
        """Keltner Channel hesapla"""
        try:
            # Orta bant (EMA)
            middle_band = self._calculate_ema(closes, period)
            
            # ATR
            atr = self._calculate_atr(highs, lows, closes, period)
            
            # Üst ve alt bantlar
            upper_band = middle_band + (atr * atr_multiplier)
            lower_band = middle_band - (atr * atr_multiplier)
            
            return upper_band, middle_band, lower_band
            
        except Exception as e:
            self.logger.error(f"Keltner Channel hesaplama hatası: {e}")
            # Boş diziler döndür
            empty_array = np.zeros_like(closes)
            return empty_array, empty_array, empty_array
    
    def _calculate_pivot_points(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> dict:
        """Pivot Noktaları hesapla (Klasik yöntem)"""
        try:
            # Son günün değerleri
            last_high = highs[-1]
            last_low = lows[-1]
            last_close = closes[-1]
            
            # Pivot noktası
            pivot = (last_high + last_low + last_close) / 3
            
            # Destek seviyeleri
            s1 = (2 * pivot) - last_high
            s2 = pivot - (last_high - last_low)
            s3 = s1 - (last_high - last_low)
            
            # Direnç seviyeleri
            r1 = (2 * pivot) - last_low
            r2 = pivot + (last_high - last_low)
            r3 = r1 + (last_high - last_low)
            
            return {
                'pivot': pivot,
                'support': [s1, s2, s3],
                'resistance': [r1, r2, r3]
            }
            
        except Exception as e:
            self.logger.error(f"Pivot Noktaları hesaplama hatası: {e}")
            return {'pivot': 0, 'support': [0, 0, 0], 'resistance': [0, 0, 0]}
    
    def _calculate_fibonacci_levels(self, high: float, low: float, is_uptrend: bool = True) -> dict:
        """Fibonacci Seviyeleri hesapla"""
        try:
            # Fibonacci oranları
            ratios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
            
            # Fiyat aralığı
            price_range = high - low
            
            # Fibonacci seviyeleri
            levels = {}
            
            if is_uptrend:
                # Yukarı trend için (düşükten yükseğe)
                for ratio in ratios:
                    levels[ratio] = low + (price_range * ratio)
            else:
                # Aşağı trend için (yüksekten düşüğe)
                for ratio in ratios:
                    levels[ratio] = high - (price_range * ratio)
            
            return levels
            
        except Exception as e:
            self.logger.error(f"Fibonacci Seviyeleri hesaplama hatası: {e}")
            return {ratio: 0 for ratio in [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]}