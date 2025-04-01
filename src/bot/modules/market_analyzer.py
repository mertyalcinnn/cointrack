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
        
        # Excluded coins - Sadece temel stablecoinler ve sorunlu coinler
        self.excluded_coins = [
            # Stablecoins
            "USDC", "BUSD", "DAI", "TUSD", "USDP", "UST", "PAX", "USDD", "USDP", "FDUSD", 
            # Fiat currencies
            "EUR", "GBP", "AUD", "TRY", "RUB", "CNY", "JPY", "CAD", "CHF", "SGD", "HKD",
            # Problematic coins
            "AUCTION", "BNX", "BCHA", "BCH", "BSV", "PAXG", 
            # Leveraged tokens
            "UP", "DOWN", "BULL", "BEAR"
        ]
        
        # Başarı oranı takibi için
        self.signal_history = []
        self.success_history = []
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'signal_history.json')
        
        # Minimum hacim ve fiyat filtreleri
        self.min_volume = float(self.config.get('min_volume', 100000))  # 100K $
        self.min_price = float(self.config.get('min_price', 0.00001))  # 0.00001 $
        self.max_price = float(self.config.get('max_price', 100000))  # 100,000 $
        
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
            # Teknik analiz sınıfını başlat - import edilen TechnicalAnalysis sınıfını kullan
            from .analysis.technical_analysis import TechnicalAnalysis
            self.ta = TechnicalAnalysis()
            
            # Veri sağlayıcısını başlat
            self.data_provider = MarketDataProvider(self.logger)
            await self.data_provider.initialize()
            
            # Teknik analiz sınıfını başlat
            self.ta = TechnicalAnalysis()
            
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
            btc_klines = await self.data_provider.get_klines_data("BTCUSDT", "1d")
            if not btc_klines or len(btc_klines) < 20:
                return "NORMAL"
            
            # BTC fiyatlarını numpy dizisine dönüştür
            btc_closes = np.array([float(k[4]) for k in btc_klines])
            
            # 20 günlük hareketli ortalama
            ema20 = self.ta.calculate_ema(btc_closes, 20)
            
            # Son fiyat
            btc_last_price = btc_closes[-1]
            
            # RSI hesapla
            btc_rsi = self.ta.calculate_rsi(btc_closes)
            
            # Son RSI değeri
            last_rsi = btc_rsi[-1] if len(btc_rsi) > 0 else 50
            
            # Piyasa durumunu belirle
            if btc_last_price > ema20[-1] * 1.05 and last_rsi > 70:
                return "AŞIRI_ALIM"  # Aşırı alım - düzeltme olabilir
            elif btc_last_price < ema20[-1] * 0.95 and last_rsi < 30:
                return "AŞIRI_SATIM"  # Aşırı satım - sıçrama olabilir
            elif btc_last_price > ema20[-1]:
                return "YUKARI_TREND"  # Yukarı trend
            elif btc_last_price < ema20[-1]:
                return "AŞAĞI_TREND"  # Aşağı trend
            else:
                return "NORMAL"  # Normal piyasa
            
        except Exception as e:
            self.logger.error(f"Piyasa durumu analiz hatası: {e}")
            return "NORMAL"

    async def scan_market(self, interval: str = "4h") -> List[Dict]:
        """Piyasayı tara ve fırsatları bul - belirli bir zaman diliminde"""
        exchange = None
        try:
            exchange = await self._create_exchange()
            
            tickers = await self._get_all_tickers(exchange)
            if not tickers or len(tickers) == 0:
                self.logger.error("Ticker verileri alınamadı")
                return []
            
            # İnterval 15m ise scalping metodunu kullan
            if interval == "15m":
                await exchange.close()
                return await self.scan_for_scalping()
            
            # Piyasa analizini yap
            opportunities = await self.analyze_market(tickers, interval)
            
            # Sonuçları logla
            self.logger.info(f"Toplam {len(opportunities)} fırsat bulundu")
            
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
            filtered_tickers = []
            
            for symbol, ticker in tickers.items():
                # Sadece USDT çiftleri
                if not symbol.endswith('USDT'):
                    continue
                    
                # Fiyat ve hacim bilgisi olmalı
                if not ticker['last'] or not ticker['quoteVolume']:
                    continue
                    
                # Fiat para birimleri ve stablecoinler hariç
                base_coin = symbol.replace('USDT', '')
                if base_coin.startswith(('USD', 'EUR', 'GBP', 'AUD', 'JPY', 'TRY', 'RUB', 'CNY')):
                    continue
                    
                # Excluded coins kontrolü
                if any(excluded in symbol for excluded in self.excluded_coins):
                    continue
                    
                filtered_tickers.append({
                    'symbol': symbol, 
                    'lastPrice': ticker['last'], 
                    'quoteVolume': ticker['quoteVolume']
                })
            
            return filtered_tickers
                
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
            
            # Global piyasa durumunu kontrol et
            market_status = await self._analyze_market_condition()
            
            # Tüm filtrelenmiş ticker'ları analiz et
            for ticker in filtered_tickers[:100]:  # En fazla 100 coin analiz et
                try:
                    opportunity = await self.analyze_opportunity(
                        ticker['symbol'],
                        float(ticker['lastPrice']),
                        float(ticker['quoteVolume']),
                        interval
                    )
                    
                    if opportunity:
                        # Global trend ile uyumu kontrol et
                        if market_status == "YUKARI_TREND" and "LONG" in opportunity['signal']:
                            opportunity['opportunity_score'] *= 1.1
                        elif market_status == "AŞAĞI_TREND" and "SHORT" in opportunity['signal']:
                            opportunity['opportunity_score'] *= 1.1
                        
                        # Fırsat puanı en az 45 olmalı
                        if opportunity['opportunity_score'] >= 45:
                            if "LONG" in opportunity['signal']:
                                long_opportunities.append(opportunity)
                            elif "SHORT" in opportunity['signal']:
                                short_opportunities.append(opportunity)
                        
                    # Yeterli sayıda fırsat bulunca ara
                    if len(long_opportunities) + len(short_opportunities) >= 20:
                        break
                        
                except Exception as e:
                    self.logger.debug(f"Fırsat analizi hatası ({ticker['symbol']}): {e}")
                    continue
            
            # Long/Short dağılımını dengele - her tipten en fazla 5 tane al
            long_count = min(len(long_opportunities), 5)
            short_count = min(len(short_opportunities), 5)
            
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
            
            # Hiç fırsat bulunamazsa popüler coinleri ekle
            if not opportunities:
                self.logger.info("Fırsat bulunamadı, popüler coinler ekleniyor...")
                for ticker in filtered_tickers[:5] or [{'symbol': 'BTCUSDT', 'lastPrice': 60000, 'quoteVolume': 1000000}]:
                    price = float(ticker['lastPrice'])
                    volume = float(ticker['quoteVolume'])
                    
                    if price > 0 and volume > self.min_volume:
                        opportunities.append({
                            'symbol': ticker['symbol'],
                            'current_price': price,
                            'price': price,
                            'signal': "👀 İNCELEME ÖNERİSİ",
                            'opportunity_score': 45,
                            'trend': "BELİRSİZ",
                            'timestamp': datetime.now().isoformat(),
                            'interval': interval,
                            'rsi': 50,
                            'macd': 0,
                            'volume_surge': False,
                            'ema20': price,
                            'ema50': price,
                            'stop_price': price * 0.97,
                            'target_price': price * 1.06
                        })
            
            # Rastgele sıralama yap - her seferinde farklı sırada göster
            random.shuffle(opportunities)
            
            return opportunities
            
        except Exception as e:
            self.logger.error(f"Piyasa analizi hatası: {e}")
            return []

    def _get_strategy_for_timeframe(self, interval: str) -> Dict:
        """Zaman dilimine göre strateji ayarlarını döndür"""
        if interval == "1h":
            return {
                'min_score': 55,
                'rsi_min': 30,
                'rsi_max': 70,
                'rsi_weight': 1.2, 
                'volume_weight': 1.5,
                'macd_weight': 1.6,
                'trend_weight': 1.3,
                'rsi_threshold': 30,
                'min_volume': 100000,
            }
        elif interval == "4h":
            return {
                'min_score': 55,
                'rsi_min': 35,
                'rsi_max': 65,
                'rsi_weight': 1.4,
                'volume_weight': 1.3,
                'macd_weight': 1.4,
                'trend_weight': 1.5,
                'rsi_threshold': 30,
                'min_volume': 100000,
            }
        else:
            return {
                'min_score': 60,
                'rsi_min': 30,
                'rsi_max': 70,
                'rsi_weight': 1.0,
                'volume_weight': 1.0,
                'macd_weight': 1.0,
                'trend_weight': 1.0,
                'rsi_threshold': 30,
                'min_volume': 100000,
            }
            
    async def _analyze_single_opportunity(self, symbol: str, current_price: float, volume: float, ohlcv: list, interval: str) -> Optional[Dict]:
        """Tekil fırsat analizi yap"""
        try:
            # Veri dönüşümü
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            closes = np.array([float(candle[4]) for candle in ohlcv])
            opens = np.array([float(candle[1]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Teknik göstergeler
            rsi = self._calculate_rsi(closes)
            ema20 = self._calculate_ema(closes, 20)
            ema50 = self._calculate_ema(closes, 50)
            macd, signal, hist = self._calculate_macd(closes)
            bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(closes)
            
            # Hacim analizi
            avg_volume = np.mean(volumes[-20:])  # Son 20 mumun ortalama hacmi
            volume_surge = volume > (avg_volume * 1.5)  # Hacim patlaması var mı?
            
            # Trend analizi
            trend = "BULLISH" if ema20[-1] > ema50[-1] else "BEARISH"
            
            # Önceki trend - 10 mum öncesine göre
            prev_ema_diff = ema20[-10] - ema50[-10] if len(ema20) > 10 and len(ema50) > 10 else 0
            curr_ema_diff = ema20[-1] - ema50[-1]
            trend_strengthening = abs(curr_ema_diff) > abs(prev_ema_diff)
            
            # Fırsat puanı hesaplama
            opportunity_score = self._calculate_opportunity_score(
                rsi[-1], hist[-1], volume_surge, trend, volume, avg_volume
            )
            
            # Strateji ağırlıklarını al
            strategy = self._get_strategy_for_timeframe(interval)
            
            # Bollinger Bands pozisyonu hesapla
            if bb_upper != bb_lower:
                bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
                bb_position = max(0, min(100, bb_position))  # 0-100 arasında sınırla
            else:
                bb_position = 50  # Varsayılan
                
            # RSI, MACD ve BB'ye göre sinyal oluştur
            signal = self._determine_trade_signal(
                rsi[-1], hist[-1], signal[-1], bb_position, trend
            )
            
            # Destek ve direnç seviyeleri
            support_resistance = self._find_support_resistance_levels(highs, lows, closes)
            
            # Fiyat hedefleri
            target_price, stop_price = self._calculate_target_stop(
                current_price, signal, 
                support_resistance.get('resistance', []),
                support_resistance.get('support', [])
            )
            
            # Sonuç
            result = {
                'symbol': symbol,
                'current_price': current_price,
                'price': current_price,
                'volume': volume,
                'signal': signal,
                'opportunity_score': opportunity_score,
                'trend': trend,
                'trend_strengthening': trend_strengthening,
                'rsi': float(rsi[-1]),
                'macd': float(hist[-1]),
                'ema20': float(ema20[-1]),
                'ema50': float(ema50[-1]),
                'volume_surge': volume_surge,
                'avg_volume': float(avg_volume),
                'bb_upper': float(bb_upper),
                'bb_middle': float(bb_middle), 
                'bb_lower': float(bb_lower),
                'bb_position': float(bb_position),
                'timestamp': datetime.now().isoformat(),
                'interval': interval,
                'target_price': target_price,
                'stop_price': stop_price
            }
            
            # Support/Resistance ekle
            if support_resistance and 'support' in support_resistance:
                for i, level in enumerate(support_resistance['support'][:3], 1):
                    result[f'support{i}'] = level
                    
            if support_resistance and 'resistance' in support_resistance:
                for i, level in enumerate(support_resistance['resistance'][:3], 1):
                    result[f'resistance{i}'] = level
            
            return result
        
        except Exception as e:
            self.logger.error(f"Tekil fırsat analizi hatası ({symbol}): {e}")
            return None
            
    def _calculate_target_stop(self, current_price: float, signal: str, resistance_levels: List[float], support_levels: List[float]) -> Tuple[float, float]:
        """Hedef ve stop seviyelerini hesapla"""
        try:
            # Minimum risk/ödül oranı
            min_risk_reward = 1.5
            
            # Varsayılan değerler (% bazlı)
            if "LONG" in signal or "AL" in signal:
                default_stop = current_price * 0.97  # %3 altı
                default_target = current_price * 1.045  # %4.5 üstü
            elif "SHORT" in signal or "SAT" in signal:
                default_stop = current_price * 1.03  # %3 üstü
                default_target = current_price * 0.955  # %4.5 altı
            else:
                default_stop = current_price * 0.98
                default_target = current_price * 1.03
                
            # Direnç ve destek noktalarını filtrele
            valid_resistance = [level for level in resistance_levels if level > current_price]
            valid_support = [level for level in support_levels if level < current_price]
            
            # Boş liste kontrolü
            if not valid_resistance:
                target_price = default_target
            else:
                # En yakın direnç noktasını bul
                target_price = min(valid_resistance)
                
            if not valid_support:
                stop_price = default_stop
            else:
                # En yakın destek noktasını bul
                stop_price = max(valid_support)
                
            # LONG sinyali için
            if "LONG" in signal or "AL" in signal:
                # Stop-loss, destek seviyesinin biraz altında olmalı
                adjusted_stop = stop_price * 0.99
                
                # Risk/ödül oranı kontrolü 
                risk = current_price - adjusted_stop
                reward = target_price - current_price
                
                if reward / max(risk, 0.0001) < min_risk_reward:
                    # Yeterli potansiyel kazanç yoksa hedefi yükselt
                    target_price = current_price + (risk * min_risk_reward)
                    return target_price, adjusted_stop
                else:
                    return target_price, adjusted_stop
                    
            # SHORT sinyali için
            elif "SHORT" in signal or "SAT" in signal:
                # Stop-loss, direnç seviyesinin biraz üstünde olmalı
                adjusted_stop = target_price * 1.01
                
                # Risk/ödül oranı kontrolü 
                risk = adjusted_stop - current_price
                reward = current_price - stop_price
                
                if reward / max(risk, 0.0001) < min_risk_reward:
                    # Yeterli potansiyel kazanç yoksa hedefi düşür
                    target_price = current_price - (risk * min_risk_reward)
                    return target_price, adjusted_stop
                else:
                    return stop_price, adjusted_stop
            else:
                # Nötr sinyal için varsayılan değerleri kullan
                return default_target, default_stop
                
        except Exception as e:
            self.logger.error(f"Hedef/stop hesaplama hatası: {e}")
            
            # Hata durumunda varsayılan değerlerle devam et
            if "LONG" in signal or "AL" in signal:
                return current_price * 1.045, current_price * 0.97
            elif "SHORT" in signal or "SAT" in signal:
                return current_price * 0.955, current_price * 1.03
            else:
                return current_price * 1.03, current_price * 0.98

    def _determine_trade_signal(self, rsi: float, macd: float, signal: float, bb_position: float, ema_trend: str) -> str:
        """Alım-satım sinyali belirle"""
        try:
            # Sinyal puanlama sistemi
            long_points = 0
            short_points = 0
            
            # RSI tabanlı puanlama
            if rsi <= 30:
                long_points += 2  # Aşırı satım bölgesi - LONG
            elif rsi <= 40:
                long_points += 1
            elif rsi >= 70:
                short_points += 2  # Aşırı alım bölgesi - SHORT
            elif rsi >= 60:
                short_points += 1
                
            # MACD tabanlı puanlama
            if macd > 0 and macd > signal:
                long_points += 1  # Pozitif MACD ve sinyal üzerinde - LONG
            elif macd < 0 and macd < signal:
                short_points += 1  # Negatif MACD ve sinyal altında - SHORT
                
            # Bollinger Bands tabanlı puanlama
            if bb_position <= 20:
                long_points += 1  # Alt bant yakınında - LONG
            elif bb_position >= 80:
                short_points += 1  # Üst bant yakınında - SHORT
                
            # Trend tabanlı puanlama
            if ema_trend == "BULLISH":
                long_points += 1  # Yukarı trend - LONG lehine
            elif ema_trend == "BEARISH":
                short_points += 1  # Aşağı trend - SHORT lehine
                
            # Sinyal belirleme (toplam 5 puan üzerinden)
            if long_points >= 3 and long_points > short_points:
                if long_points >= 4:
                    return "💚 GÜÇLÜ LONG"
                else:
                    return "💚 LONG"
            elif short_points >= 3 and short_points > long_points:
                if short_points >= 4:
                    return "❤️ GÜÇLÜ SHORT"
                else:
                    return "❤️ SHORT"
            else:
                return "⚪ NÖTR"
                
        except Exception as e:
            self.logger.error(f"Sinyal belirleme hatası: {e}")
            return "⚪ NÖTR"
            
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

    async def analyze_opportunity(self, symbol: str, current_price: float, volume: float, interval: str) -> Dict:
        """İşlem fırsatını analiz et"""
        try:
            # Sembole göre borsa formatına dönüştür ('/' ekleyerek)
            exchange_symbol = symbol
            if '/' not in symbol and 'USDT' in symbol:
                exchange_symbol = f"{symbol[:-4]}/USDT"
            
            # Exchange oluştur
            exchange = await self._create_exchange()
            
            # OHLCV verileri al
            ohlcv = await exchange.fetch_ohlcv(exchange_symbol, interval, limit=100)
            await exchange.close()
            
            if not ohlcv or len(ohlcv) < 30:
                self.logger.debug(f"{symbol} için yeterli veri bulunamadı")
                return None
            
            # Veri dönüşümü
            opens = np.array([float(candle[1]) for candle in ohlcv])
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            closes = np.array([float(candle[4]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Teknik göstergeler
            rsi = self.ta.calculate_rsi(closes)
            ema20 = self.ta.calculate_ema(closes, 20)
            ema50 = self.ta.calculate_ema(closes, 50)
            macd, signal, hist = self.ta.calculate_macd(closes)
            bb_upper, bb_middle, bb_lower = self.ta.calculate_bollinger_bands(closes)
            
            # Hacim analizi
            avg_volume = np.mean(volumes[-20:])  # Son 20 mumun ortalama hacmi
            volume_surge = volume > (avg_volume * 1.5)  # Hacim patlaması var mı?
            
            # Trend analizi
            trend = "YUKARI_TREND" if ema20[-1] > ema50[-1] else "AŞAĞI_TREND"
            
            # Bollinger Bands pozisyonu hesapla
            if bb_upper[-1] != bb_lower[-1]:
                bb_position = (current_price - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) * 100
                bb_position = max(0, min(100, bb_position))  # 0-100 arasında sınırla
            else:
                bb_position = 50  # Varsayılan
            
            # Alım-satım sinyali belirle
            signal_type = self._determine_trade_signal(
                rsi[-1], hist[-1], signal[-1], bb_position, trend
            )
            
            # Sinyal yoksa None döndür
            if "NÖTR" in signal_type:
                return None
                
            # Fırsat puanı hesapla
            opportunity_score = 0
            
            # RSI tabanlı puanlama
            if "LONG" in signal_type or "AL" in signal_type:
                # Aşırı satım bölgesinde mi?
                if rsi[-1] <= 30:
                    opportunity_score += 30
                elif rsi[-1] <= 40:
                    opportunity_score += 20
            elif "SHORT" in signal_type or "SAT" in signal_type:
                # Aşırı alım bölgesinde mi?
                if rsi[-1] >= 70:
                    opportunity_score += 30
                elif rsi[-1] >= 60:
                    opportunity_score += 20
            
            # Trend uyumluluğu
            if ("LONG" in signal_type and trend == "YUKARI_TREND") or \
               ("SHORT" in signal_type and trend == "AŞAĞI_TREND"):
                opportunity_score += 20
            
            # Hacim analizi
            if volume_surge:
                opportunity_score += 15
            
            # MACD sinyali
            if ("LONG" in signal_type and hist[-1] > 0 and hist[-1] > hist[-2]) or \
               ("SHORT" in signal_type and hist[-1] < 0 and hist[-1] < hist[-2]):
                opportunity_score += 15
            
            # Bollinger Bands
            if "LONG" in signal_type and current_price < bb_middle[-1]:
                opportunity_score += 10
            elif "SHORT" in signal_type and current_price > bb_middle[-1]:
                opportunity_score += 10
            
            # Destek/Direnç seviyeleri
            support_resistance = self._find_support_resistance_levels(highs, lows, closes)
            
            # Stop ve hedef belirle
            if "LONG" in signal_type or "AL" in signal_type:
                stop_price = current_price * 0.97  # %3 aşağısı
                target_price = current_price * 1.05  # %5 yukarısı
            else:
                stop_price = current_price * 1.03  # %3 yukarısı
                target_price = current_price * 0.95  # %5 aşağısı
            
            # Destek/direnç noktalarını kullanarak stop ve hedefi düzelt
            if "LONG" in signal_type and support_resistance and 'support' in support_resistance:
                # En yakın destek seviyesini bul
                supports = [s for s in support_resistance['support'] if s < current_price]
                if supports:
                    best_support = max(supports)  # En yakın (en yüksek) destek
                    # Stop-loss olarak kullan (biraz altı)
                    stop_price = best_support * 0.99
            
            if "SHORT" in signal_type and support_resistance and 'resistance' in support_resistance:
                # En yakın direnç seviyesini bul
                resistances = [r for r in support_resistance['resistance'] if r > current_price]
                if resistances:
                    best_resistance = min(resistances)  # En yakın (en düşük) direnç
                    # Stop-loss olarak kullan (biraz üstü)
                    stop_price = best_resistance * 1.01
            
            # Risk/ödül oranı en az 1:1 olmalı
            risk = abs(current_price - stop_price)
            reward = abs(target_price - current_price)
            
            if reward < risk:
                if "LONG" in signal_type:
                    target_price = current_price + risk  # 1:1 oranı için hedefi ayarla
                else:
                    target_price = current_price - risk  # 1:1 oranı için hedefi ayarla
            
            risk_reward_ratio = reward / risk if risk > 0 else 1.0
            
            # Sonuç objesi
            opportunity = {
                'symbol': symbol,
                'current_price': current_price,
                'price': current_price,
                'signal': signal_type,
                'opportunity_score': opportunity_score,
                'trend': trend,
                'rsi': float(rsi[-1]),
                'macd': float(hist[-1]),
                'volume_surge': volume_surge,
                'timestamp': datetime.now().isoformat(),
                'interval': interval,
                'stop_price': stop_price,
                'target_price': target_price,
                'risk_reward': risk_reward_ratio,
                'ema20': float(ema20[-1]),
                'ema50': float(ema50[-1])
            }
            
            return opportunity
            
        except Exception as e:
            self.logger.error(f"Fırsat analizi hatası ({symbol}): {e}")
            return None
            
    def _find_support_resistance_levels(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Dict:
        """Destek ve direnç seviyelerini bul"""
        try:
            # Son 30 mumu analiz et
            lookback = min(30, len(closes))
            
            # Yerel minimum ve maksimumları bul
            local_min_indices = argrelextrema(lows[-lookback:], np.less, order=3)[0]
            local_max_indices = argrelextrema(highs[-lookback:], np.greater, order=3)[0]
            
            # Destek seviyeleri (yerel minimum noktalar)
            support_levels = []
            for idx in local_min_indices:
                support_levels.append(lows[-lookback:][idx])
            
            # Direnç seviyeleri (yerel maksimum noktalar)
            resistance_levels = []
            for idx in local_max_indices:
                resistance_levels.append(highs[-lookback:][idx])
            
            return {
                'support': support_levels,
                'resistance': resistance_levels
            }
        except Exception as e:
            self.logger.error(f"Destek/direnç seviyesi hesaplama hatası: {e}")
            return {'support': [], 'resistance': []}

    async def scan_for_scalping(self) -> List[Dict]:
        """Scalping için kısa vadeli fırsatları tara (15 dakikalık grafikler)"""
        exchange = None
        try:
            exchange = await self._create_exchange()
            
            # Tüm sembolleri al
            tickers = await self._get_all_tickers(exchange)
            if not tickers or len(tickers) == 0:
                self.logger.error("Scalping için ticker verileri alınamadı")
                return []
            
            # Filtreleme - yalnızca yüksek hacimli coinleri al
            min_volume = 500000  # Scalping için en az 500K $ hacim
            filtered_tickers = [
                ticker for ticker in tickers 
                if float(ticker['quoteVolume']) >= min_volume
                and float(ticker['lastPrice']) > 0.1  # Düşük fiyatlı coinleri hariç tut
            ]
            
            # En fazla 50 coini işle
            random.shuffle(filtered_tickers)  # Rastgele karıştır
            filtered_tickers = filtered_tickers[:50]
            
            # Fırsatları analiz et
            opportunities = []
            for ticker in filtered_tickers:
                try:
                    symbol = ticker['symbol']
                    price = float(ticker['lastPrice'])
                    volume = float(ticker['quoteVolume'])
                    
                    opportunity = await self._analyze_scalping_opportunity(
                        symbol, price, volume, exchange
                    )
                    
                    if opportunity and opportunity['opportunity_score'] >= 75:
                        opportunities.append(opportunity)
                        
                except Exception as e:
                    self.logger.error(f"Tekil scalping analizi hatası ({ticker.get('symbol', 'Unknown')}): {e}")
                    continue
            
            # Puanlarına göre sırala
            opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            # En iyi 5 fırsatı döndür
            return opportunities[:5]
            
        except Exception as e:
            self.logger.error(f"Scalping tarama hatası: {e}")
            return []
        finally:
            try:
                if exchange:
                    await exchange.close()
            except Exception as e:
                self.logger.error(f"Exchange kapatma hatası: {e}")
                
    async def _analyze_scalping_opportunity(self, symbol: str, current_price: float, volume: float, exchange) -> Dict:
        """Scalping fırsatını analiz et (15 dakikalık grafik)"""
        try:
            # Sembole göre borsa formatına dönüştür ('/' ekleyerek)
            exchange_symbol = symbol
            if '/' not in symbol and 'USDT' in symbol:
                exchange_symbol = f"{symbol[:-4]}/USDT"
            
            # 15 dakikalık OHLCV verilerini al
            ohlcv = await exchange.fetch_ohlcv(exchange_symbol, '15m', limit=100)
            
            if not ohlcv or len(ohlcv) < 20:
                return None
            
            # Veri dönüşümü
            opens = np.array([float(candle[1]) for candle in ohlcv])
            highs = np.array([float(candle[2]) for candle in ohlcv])
            lows = np.array([float(candle[3]) for candle in ohlcv])
            closes = np.array([float(candle[4]) for candle in ohlcv])
            volumes = np.array([float(candle[5]) for candle in ohlcv])
            
            # Teknik göstergeler
            rsi = self.ta.calculate_rsi(closes)
            ema9 = self.ta.calculate_ema(closes, 9)
            ema21 = self.ta.calculate_ema(closes, 21)
            macd, signal, hist = self.ta.calculate_macd(closes, 12, 26, 9)
            bb_upper, bb_middle, bb_lower = self.ta.calculate_bollinger_bands(closes, 20, 2.0)
            
            # Son değerler
            last_rsi = rsi[-1]
            last_macd = hist[-1]
            last_close = closes[-1]
            
            # Bollinger Bands pozisyonu
            if bb_upper[-1] != bb_lower[-1]:
                bb_position = (last_close - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) * 100
            else:
                bb_position = 50
                
            # Scalping fırsatı kontrolü
            is_long_opportunity = False
            is_short_opportunity = False
            signal_type = ""
            opportunity_score = 0
            
            # LONG fırsatı
            if (
                last_rsi < 40 and  # Aşırı satış bölgesi
                last_macd > signal[-1] and  # MACD yükseliş sinyali
                last_close > ema9[-1] and  # Fiyat kısa vadeli EMA üzerinde
                bb_position < 30  # Bollinger alt bandına yakın
            ):
                is_long_opportunity = True
                signal_type = "🟢 GÜÇLÜ AL"
                opportunity_score = 80
                
                # Ek koşullar
                if last_rsi < 30:
                    opportunity_score += 5
                if last_close > ema21[-1]:
                    opportunity_score += 5
                if hist[-1] > hist[-2] > hist[-3]:  # MACD yükseliş trendi
                    opportunity_score += 5
                if volumes[-1] > np.mean(volumes[-5:]) * 1.5:  # Hacim patlaması
                    opportunity_score += 5
            
            # SHORT fırsatı
            elif (
                last_rsi > 60 and  # Aşırı alım bölgesi
                last_macd < signal[-1] and  # MACD düşüş sinyali
                last_close < ema9[-1] and  # Fiyat kısa vadeli EMA altında
                bb_position > 70  # Bollinger üst bandına yakın
            ):
                is_short_opportunity = True
                signal_type = "❤️ GÜÇLÜ SHORT"
                opportunity_score = 80
                
                # Ek koşullar
                if last_rsi > 70:
                    opportunity_score += 5
                if last_close < ema21[-1]:
                    opportunity_score += 5
                if hist[-1] < hist[-2] < hist[-3]:  # MACD düşüş trendi
                    opportunity_score += 5
                if volumes[-1] > np.mean(volumes[-5:]) * 1.5:  # Hacim patlaması
                    opportunity_score += 5
            
            # Fırsat yoksa çık
            if not is_long_opportunity and not is_short_opportunity:
                return None
            
            # Destek/Direnç seviyeleri bul
            support_resistance = self._find_support_resistance_levels(highs, lows, closes)
            
            # Stop ve hedef belirle
            if is_long_opportunity:
                # Stop-loss için en yakın destek seviyesini bul
                supports = [s for s in support_resistance.get('support', []) if s < current_price]
                if supports:
                    stop_price = max(supports) * 0.995  # En yakın desteğin biraz altı
                else:
                    stop_price = current_price * 0.95  # %5 altı
                
                # Risk hesapla
                risk = current_price - stop_price
                # Hedef: risk*1.5 uzaklıkta (1.5:1 risk-ödül oranı)
                target_price = current_price + (risk * 1.5)
                
            else:  # SHORT
                # Stop-loss için en yakın direnç seviyesini bul
                resistances = [r for r in support_resistance.get('resistance', []) if r > current_price]
                if resistances:
                    stop_price = min(resistances) * 1.005  # En yakın direncin biraz üstü
                else:
                    stop_price = current_price * 1.05  # %5 üstü
                
                # Risk hesapla
                risk = stop_price - current_price
                # Hedef: risk*1.5 uzaklıkta (1.5:1 risk-ödül oranı)
                target_price = current_price - (risk * 1.5)
            
            # Risk/Ödül oranı
            risk_reward = 1.5  # Sabit 1.5:1 oranı
            
            # Sonuç
            return {
                'symbol': symbol,
                'current_price': current_price,
                'signal': signal_type,
                'opportunity_score': opportunity_score,
                'rsi': float(last_rsi),
                'macd': float(last_macd),
                'bb_position': float(bb_position),
                'stop_price': stop_price,
                'target_price': target_price,
                'risk_reward': risk_reward,
                'timestamp': datetime.now().isoformat(),
                'interval': '15m',
                'volume': float(volume)
            }
            
        except Exception as e:
            self.logger.error(f"Scalping fırsat analizi hatası ({symbol}): {e}")
            return None

    async def scan15(self) -> List[Dict]:
        """15 dakikalık grafiklerde kısa vadeli fırsatları tara - scalping için optimize edilmiş"""
        return await self.scan_for_scalping()