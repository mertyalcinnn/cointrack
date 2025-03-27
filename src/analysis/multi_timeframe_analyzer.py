import asyncio
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from io import BytesIO
import ccxt
import mplfinance as mpf
from typing import List, Dict, Optional, Any, Tuple
import time

class MultiTimeframeAnalyzer:
    """
    Üç farklı zaman dilimini (1W, 1H, 15M) kullanarak kapsamlı teknik analiz yapan sınıf.
    """
    
    def __init__(self, logger=None):
        """Initialize the analyzer with necessary components"""
        self.logger = logger or logging.getLogger('MultiTimeframeAnalyzer')
        
        # Exchange bağlantısı için
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        
        # Teknik analiz parametreleri
        self.rsi_period = 14
        self.ema_periods = [9, 20, 50, 200]
        self.volume_increase_threshold = 50  # %50 hacim artışı
        
        # Demo modu
        self.demo_mode = False
        
        # Cache ekle
        self.data_cache = {}  # Basit bir önbellek sözlüğü
        
        self.logger.info("MultiTimeframeAnalyzer başlatıldı")
    
    async def initialize(self):
        """Initialize asynchronous components"""
        try:
            # Desteklenen sembolleri al
            self.symbols = await self.get_tradable_symbols()
            self.logger.info(f"{len(self.symbols)} işlem çifti bulundu")
            
            # Data provider'ı başlat (gerekirse)
            self.data_provider = self
            
            return True
        except Exception as e:
            self.logger.error(f"Başlatma hatası: {str(e)}")
            return False
            
    async def get_tradable_symbols(self) -> List[str]:
        """İşlem yapılabilir sembolleri al"""
        try:
            # USDT çiftlerini al
            markets = self.exchange.load_markets()
            usdt_symbols = [
                symbol for symbol in markets.keys() 
                if symbol.endswith('/USDT') and not symbol.endswith('BEAR/USDT') 
                and not symbol.endswith('BULL/USDT') and not symbol.endswith('UP/USDT') 
                and not symbol.endswith('DOWN/USDT')
            ]
            
            # CCXT format (BTC/USDT) -> Binance format (BTCUSDT) çevir
            binance_symbols = [symbol.replace('/', '') for symbol in usdt_symbols]
            
            return binance_symbols
        except Exception as e:
            self.logger.error(f"Sembol alma hatası: {str(e)}")
            return []
    
    async def get_klines(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Belirli bir sembol ve zaman dilimi için kline verileri al"""
        try:
            # CCXT formatı için sembolü düzenle
            if '/' not in symbol:
                ccxt_symbol = f"{symbol[:-4]}/USDT"
            else:
                ccxt_symbol = symbol
                
            # Candlestick verilerini al
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            
            # Pandas DataFrame'e dönüştür
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
        except Exception as e:
            self.logger.error(f"Kline verisi alma hatası ({symbol}, {timeframe}): {str(e)}")
            return pd.DataFrame()
    
    async def get_ticker(self, symbol: str) -> Dict:
        """Belirli bir sembol için ticker verisi al"""
        try:
            # CCXT formatı için sembolü düzenle
            if '/' not in symbol:
                ccxt_symbol = f"{symbol[:-4]}/USDT"
            else:
                ccxt_symbol = symbol
                
            # Ticker verilerini al
            ticker = self.exchange.fetch_ticker(ccxt_symbol)
            
            return ticker
        except Exception as e:
            self.logger.error(f"Ticker verisi alma hatası ({symbol}): {str(e)}")
            return {}
    
    async def scan_market(self, symbols=None):
        """
        Dört zaman diliminde market taraması yapar (1W, 4H, 1H, 15m)
        
        1. Haftalık (1W) trendin olumlu veya olumsuz olduğu coinleri bulur
        2. Trendli coinlerin 4 saatlik (4H) analizini yapar 
        3. İyi trend gösteren coinlerin saatlik (1H) analizini yapar
        4. İyi fırsatlar gösteren coinler için 15dk analizi yapar
        
        Args:
            symbols (List[str], optional): Analiz edilecek sembol listesi. Default olarak popüler coinler.
            
        Returns:
            List[Dict]: LONG ve SHORT fırsatları listesi
        """
        try:
            start_time = time.time()
            self.logger.info(f"Çoklu zaman dilimi market taraması başlatılıyor...")
            
            # Analiz edilecek sembolleri belirle
            if not symbols:
                symbols = await self.get_top_symbols(limit=30)  # En yüksek hacimli 30 coinle başla
                self.logger.info(f"{len(symbols)} sembol taramaya alındı")
            else:
                self.logger.info(f"Belirtilen {len(symbols)} sembol taranıyor: {symbols}")
            
            # 1. ADIM: HAFTALIK ANALİZ (1W)
            self.logger.info("1/4: Haftalık (1W) analiz başladı...")
            weekly_analysis = await self.analyze_timeframe(symbols, "1w")
            
            # Belirgin trendleri filtrele - LONG ve SHORT için
            trendli_weekly = [r for r in weekly_analysis if r['trend'] in [
                'BULLISH', 'STRONGLY_BULLISH', 'BEARISH', 'STRONGLY_BEARISH'
            ]]
            self.logger.info(f"Haftalık analizde {len(trendli_weekly)} belirgin trend bulundu")
            
            if len(trendli_weekly) == 0:
                self.logger.warning("Haftalık analizde belirgin trend bulunamadı")
                if len(weekly_analysis) > 0:
                    # En azından birkaç sembol ekleyelim ki sonraki adımlarda çalışsın
                    trendli_weekly = weekly_analysis[:5] if len(weekly_analysis) >= 5 else weekly_analysis
            
            # 2. ADIM: 4 SAATLİK ANALİZ (4H)
            self.logger.info("2/4: 4 Saatlik (4H) analiz başladı...")
            filtered_symbols = [r['symbol'] for r in trendli_weekly]
            h4_analysis = await self.analyze_timeframe(filtered_symbols, "4h")
            
            # Haftalık ve 4 saatlik sonuçları birleştir
            combined_results = self._combine_timeframe_results(trendli_weekly, h4_analysis, "weekly", "h4")
            
            # İyi 4 saatlik fırsatları filtrele
            good_h4_results = []
            for result in combined_results:
                weekly_trend = result.get('weekly_trend', 'NEUTRAL')
                h4_trend = result.get('h4_trend', 'NEUTRAL')
                
                # LONG veya SHORT eğilimi varsa ekle
                if (weekly_trend in ['BULLISH', 'STRONGLY_BULLISH'] and 
                    h4_trend in ['BULLISH', 'STRONGLY_BULLISH', 'NEUTRAL']) or \
                   (weekly_trend in ['BEARISH', 'STRONGLY_BEARISH'] and 
                    h4_trend in ['BEARISH', 'STRONGLY_BEARISH', 'NEUTRAL']):
                    good_h4_results.append(result)
            
            self.logger.info(f"4 Saatlik analizde {len(good_h4_results)} uyumlu trend bulundu")
            
            if len(good_h4_results) == 0:
                self.logger.warning("4 Saatlik analizde uyumlu trend bulunamadı")
                good_h4_results = combined_results[:10] if len(combined_results) >= 10 else combined_results
            
            # 3. ADIM: SAATLİK ANALİZ (1H)
            self.logger.info("3/4: Saatlik (1H) analiz başladı...")
            filtered_symbols = [r['symbol'] for r in good_h4_results]
            hourly_analysis = await self.analyze_timeframe(filtered_symbols, "1h")
            
            # 4 saatlik ve saatlik sonuçları birleştir
            combined_h1_results = self._combine_timeframe_results(good_h4_results, hourly_analysis, "h4", "hourly")
            
            # En iyi fırsatları seç
            good_opportunities = [r for r in combined_h1_results if r.get('opportunity_score', 0) >= 30]
            self.logger.info(f"Saatlik analizde {len(good_opportunities)} iyi fırsat bulundu")
            
            if len(good_opportunities) == 0:
                self.logger.warning("Saatlik analizde iyi fırsat bulunamadı")
                good_opportunities = combined_h1_results[:10] if len(combined_h1_results) >= 10 else combined_h1_results
            
            # 4. ADIM: 15 DAKİKALIK ANALİZ (15m)
            self.logger.info("4/4: 15 dakikalık (15m) analiz başladı...")
            filtered_symbols = [r['symbol'] for r in good_opportunities]
            m15_analysis = await self.analyze_timeframe(filtered_symbols, "15m")
            
            # Tüm sonuçları birleştir
            final_results = self._combine_timeframe_results(good_opportunities, m15_analysis, "hourly", "15m")
            
            # Sinyal atama - DÜZELTME
            for result in final_results:
                weekly_trend = result.get('weekly_trend', 'NEUTRAL')
                h4_trend = result.get('h4_trend', 'NEUTRAL')
                hourly_trend = result.get('hourly_trend', 'NEUTRAL')
                m15_trend = result.get('15m_trend', 'NEUTRAL')
                
                # LONG için - STRONGLY_BULLISH veya BULLISH olması yeterli
                if m15_trend in ['STRONGLY_BULLISH', 'BULLISH'] or weekly_trend in ['STRONGLY_BULLISH', 'BULLISH']:
                    result['signal'] = "🟩 LONG"
                    result['trade_direction'] = "LONG"
                # SHORT için - STRONGLY_BEARISH veya BEARISH olması yeterli
                elif m15_trend in ['STRONGLY_BEARISH', 'BEARISH'] or weekly_trend in ['STRONGLY_BEARISH', 'BEARISH']:
                    result['signal'] = "🔴 SHORT"
                    result['trade_direction'] = "SHORT"
                else:
                    result['signal'] = "⚪ BEKLE"
                    result['trade_direction'] = "NEUTRAL"
            
            # Sonuçları fırsat puanına göre sırala
            final_results.sort(key=lambda x: x.get('opportunity_score', 0), reverse=True)
            
            elapsed = time.time() - start_time
            self.logger.info(f"Çoklu zaman dilimi taraması tamamlandı. {len(final_results)} sonuç, süre: {elapsed:.2f} saniye")
            
            return final_results
            
        except Exception as e:
            self.logger.error(f"Çoklu zaman dilimi taraması hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    async def analyze_timeframe(self, symbols: List[str], timeframe: str) -> List[Dict]:
        """
        Belirli bir zaman dilimi için sembol listesini analiz eder
        
        Args:
            symbols: Analiz edilecek sembol listesi
            timeframe: Analiz edilecek zaman dilimi (1w, 4h, 1h, 15m)
            
        Returns:
            List[Dict]: Analiz sonuçları listesi
        """
        try:
            self.logger.info(f"{timeframe} zaman dilimi için {len(symbols)} sembol analiz ediliyor...")
            results = []
            
            # Her sembol için paralel analiz
            async def analyze_single_symbol(symbol):
                try:
                    # Tarihi veriyi al
                    df = await self.get_klines(symbol, timeframe=timeframe, limit=200)
                    if df is None or len(df) < 30:  # En az 30 mum gerekli
                        return None
                    
                    # Göstergeleri hesapla
                    indicators = self.calculate_indicators(df)
                    if indicators is None:
                        return None
                    
                    # Trend analizi yap
                    trend, trend_strength = self.analyze_trend(df, indicators)
                    
                    # Stop/Target hesapla
                    current_price = df['close'].iloc[-1]
                    stop_price, target_price = 0, 0
                    risk_reward = 0
                    
                    if trend in ['BULLISH', 'STRONGLY_BULLISH', 'BEARISH', 'STRONGLY_BEARISH']:
                        direction = "LONG" if trend in ['BULLISH', 'STRONGLY_BULLISH'] else "SHORT"
                        stop_price, target_price = self.calculate_stop_and_target(df, trend, current_price, direction=direction)
                        
                        # Risk/Ödül oranını hesapla
                        if direction == "LONG":
                            risk = current_price - stop_price if stop_price > 0 else 1
                            reward = target_price - current_price if target_price > 0 else 0
                        else:
                            risk = stop_price - current_price if stop_price > 0 else 1
                            reward = current_price - target_price if target_price > 0 else 0
                        
                        risk_reward = reward / risk if risk > 0 else 0
                    
                    # Analiz sonucunu döndür
                    return {
                        'symbol': symbol,
                        'timeframe': timeframe,
                        'trend': trend,
                        'trend_strength': trend_strength,
                        'indicators': indicators,
                        'current_price': current_price,
                        'volume': df['volume'].iloc[-1],
                        'stop_price': stop_price,
                        'target_price': target_price,
                        'risk_reward': risk_reward,
                        'trend_descriptions': indicators.get('trend_messages', [])[:3] if indicators else []
                    }
                except Exception as e:
                    self.logger.error(f"{timeframe} - {symbol} analiz hatası: {str(e)}")
                    return None
            
            # Sembolleri paralel olarak analiz et
            tasks = [analyze_single_symbol(symbol) for symbol in symbols]
            results_with_none = await asyncio.gather(*tasks)
            
            # None sonuçları filtrele
            results = [r for r in results_with_none if r is not None]
            
            self.logger.info(f"{timeframe} zaman dilimi için {len(results)} başarılı analiz tamamlandı")
            return results
        
        except Exception as e:
            self.logger.error(f"{timeframe} zaman dilimi analiz hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    def calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """Teknik göstergeleri hesapla"""
        # RSI hesapla
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # MACD hesapla
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        
        # Bollinger Bands hesapla
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        bb_middle = typical_price.rolling(window=20).mean()
        bb_std = typical_price.rolling(window=20).std()
        bb_upper = bb_middle + (2 * bb_std)
        bb_lower = bb_middle - (2 * bb_std)
        
        # BB pozisyonu hesapla: %B = (Price - Lower BB) / (Upper BB - Lower BB)
        last_close = df['close'].iloc[-1]
        last_lower = bb_lower.iloc[-1]
        last_upper = bb_upper.iloc[-1]
        bb_range = last_upper - last_lower
        bb_position = ((last_close - last_lower) / bb_range) * 100 if bb_range > 0 else 50
        
        # EMA hesapla
        emas = {}
        for period in self.ema_periods:
            emas[f'ema{period}'] = df['close'].ewm(span=period, adjust=False).mean().iloc[-1]
        
        # Stochastic Oscillator hesapla
        low_min = df['low'].rolling(window=14).min()
        high_max = df['high'].rolling(window=14).max()
        k = 100 * ((df['close'] - low_min) / (high_max - low_min))
        d = k.rolling(window=3).mean()
        
        # Hacim değişimi
        volume_ma = df['volume'].rolling(window=20).mean()
        current_volume = df['volume'].iloc[-1]
        volume_change = ((current_volume - volume_ma.iloc[-1]) / volume_ma.iloc[-1]) * 100 if volume_ma.iloc[-1] > 0 else 0
        
        # Sonuçları döndür
        return {
            "rsi": rsi.iloc[-1],
            "macd": macd.iloc[-1],
            "macd_signal": signal.iloc[-1],
            "macd_hist": histogram.iloc[-1],
            "bb_upper": bb_upper.iloc[-1],
            "bb_middle": bb_middle.iloc[-1],
            "bb_lower": bb_lower.iloc[-1],
            "bb_position": bb_position,
            "emas": emas,
            "stoch_k": k.iloc[-1],
            "stoch_d": d.iloc[-1],
            "volume_change": volume_change
        }
    def calculate_stop_and_target(self, df: pd.DataFrame, trend: str, current_price: float, direction="LONG") -> Tuple[float, float]:
        """Stop-loss ve hedef fiyat seviyelerini hesapla"""
        try:
            if df is None or df.empty or current_price <= 0:
                return 0, 0
            
            # Son bir haftalık fiyat hareketine bak
            recent_df = df.tail(96)  # Son 24 saat (15dk timeframe)
            
            # ATR (Average True Range) hesapla - volatilite ölçüsü
            high = recent_df['high'].values
            low = recent_df['low'].values
            close = recent_df['close'].values
            
            tr1 = np.abs(high - low)
            tr2 = np.abs(high - np.roll(close, 1))
            tr3 = np.abs(low - np.roll(close, 1))
            
            tr = np.vstack([tr1, tr2, tr3])
            atr = np.mean(np.max(tr, axis=0))
            
            # Son N mumun en yüksek ve en düşük değerlerini bul
            if direction == "LONG":
                # LONG pozisyonlar için
                # Son 12 mumun en düşüğü (stop-loss için)
                recent_low = recent_df['low'].tail(12).min()
                distance_to_low = current_price - recent_low
                
                # Stop-loss hesapla
                if trend in ['STRONGLY_BULLISH']:
                    # Güçlü trend: ATR'nin 2 katı ya da son düşük, hangisi daha yakınsa
                    stop_distance = min(2 * atr, distance_to_low * 0.9)
                elif trend in ['BULLISH']:
                    # Normal trend: ATR'nin 1.5 katı ya da son düşük
                    stop_distance = min(1.5 * atr, distance_to_low * 0.8)
                else:
                    # Zayıf veya nötr trend: ATR veya son düşük * 0.7
                    stop_distance = min(1 * atr, distance_to_low * 0.7)
                
                stop_price = max(current_price - stop_distance, recent_low * 0.99)
                
                # Hedef fiyat (TP) - Risk/Ödül oranına göre
                risk = current_price - stop_price
                reward_ratio = 2.0 if trend in ['STRONGLY_BULLISH'] else 1.5
                target_price = current_price + (risk * reward_ratio)
                
            else:
                # SHORT pozisyonlar için
                # Son 12 mumun en yükseği (stop-loss için)
                recent_high = recent_df['high'].tail(12).max()
                distance_to_high = recent_high - current_price
                
                # Stop-loss hesapla
                if trend in ['STRONGLY_BEARISH']:
                    # Güçlü trend: ATR'nin 2 katı ya da son yüksek, hangisi daha yakınsa
                    stop_distance = min(2 * atr, distance_to_high * 0.9)
                elif trend in ['BEARISH']:
                    # Normal trend: ATR'nin 1.5 katı ya da son yüksek
                    stop_distance = min(1.5 * atr, distance_to_high * 0.8)
                else:
                    # Zayıf veya nötr trend: ATR veya son yüksek * 0.7
                    stop_distance = min(1 * atr, distance_to_high * 0.7)
                
                stop_price = min(current_price + stop_distance, recent_high * 1.01)
                
                # Hedef fiyat (TP) - Risk/Ödül oranına göre
                risk = stop_price - current_price
                reward_ratio = 2.0 if trend in ['STRONGLY_BEARISH'] else 1.5
                target_price = current_price - (risk * reward_ratio)
            
            return stop_price, target_price
        
        except Exception as e:
            self.logger.error(f"Stop ve target hesaplama hatası: {str(e)}")
            return 0, 0

    def _combine_timeframe_results(self, previous_results, new_results, prev_prefix, new_prefix):
        """İki farklı zaman dilimi analiz sonuçlarını birleştirir"""
        try:
            combined_results = []
            
            # Önceki sonuçları döngüye al
            for prev in previous_results:
                symbol = prev['symbol']
                
                # Bu sembol için yeni sonucu bul
                new = next((n for n in new_results if n['symbol'] == symbol), None)
                
                # Yeni sonuç bulunamazsa, sadece önceki ile devam et
                if new is None:
                    result = prev.copy()
                    # Yeni zaman dilimi için varsayılan değerler
                    result[f'{new_prefix}_trend'] = 'UNKNOWN'
                    result[f'{new_prefix}_trend_strength'] = 0
                    # Varsayılan puanı koru veya hesapla
                    if 'opportunity_score' not in result:
                        # Sadece trendlere göre puan hesapla
                        trend = prev.get(f'{prev_prefix}_trend', 'NEUTRAL')
                        if trend in ['STRONGLY_BULLISH', 'STRONGLY_BEARISH']:
                            result['opportunity_score'] = 60
                        elif trend in ['BULLISH', 'BEARISH']:
                            result['opportunity_score'] = 40
                        else:
                            result['opportunity_score'] = 20
                else:
                    # Tüm sonuçları birleştir
                    result = prev.copy()
                    
                    # Yeni zaman dilimi alanlarını kopyala
                    result[f'{new_prefix}_trend'] = new['trend']
                    result[f'{new_prefix}_trend_strength'] = new['trend_strength']
                    result[f'{new_prefix}_indicators'] = new['indicators']
                    
                    # Price ve Volume bilgilerini güncelle
                    result['current_price'] = new['current_price']
                    result[f'{new_prefix}_volume'] = new['volume']
                    
                    # Stop/Target bilgilerini ekle
                    if new['stop_price'] > 0:
                        result['stop_price'] = new['stop_price']
                        result['target_price'] = new['target_price']
                        result['risk_reward'] = new['risk_reward']
                    
                    # Trend açıklamalarını ekle
                    if 'trend_descriptions' in new:
                        result[f'{new_prefix}_trend_descriptions'] = new['trend_descriptions']
                    
                    # Fırsat puanını hesapla veya güncelle
                    score = result.get('opportunity_score', 0)
                    
                    # Önceki trend puanı
                    prev_trend = prev.get(f'{prev_prefix}_trend', 'NEUTRAL')
                    
                    # Yeni trend puanı
                    new_trend = new['trend']
                    
                    # LONG fırsatları için
                    if prev_trend in ['BULLISH', 'STRONGLY_BULLISH']:
                        if new_trend == 'STRONGLY_BULLISH':
                            score += 25
                        elif new_trend == 'BULLISH':
                            score += 15
                        elif new_trend == 'NEUTRAL':
                            score += 5
                        elif new_trend == 'BEARISH':
                            score -= 10
                        elif new_trend == 'STRONGLY_BEARISH':
                            score -= 20
                    
                    # SHORT fırsatları için
                    elif prev_trend in ['BEARISH', 'STRONGLY_BEARISH']:
                        if new_trend == 'STRONGLY_BEARISH':
                            score += 25
                        elif new_trend == 'BEARISH':
                            score += 15
                        elif new_trend == 'NEUTRAL':
                            score += 5
                        elif new_trend == 'BULLISH':
                            score -= 10
                        elif new_trend == 'STRONGLY_BULLISH':
                            score -= 20
                    
                    # Risk/Ödül oranına göre bonus
                    if 'risk_reward' in new and new['risk_reward'] > 0:
                        risk_reward = new['risk_reward']
                        if risk_reward >= 3:  # 3:1 veya daha iyi ise
                            score += 10
                        elif risk_reward >= 2:  # 2:1 veya daha iyi ise
                            score += 5
                    
                    # Puanı 0-100 arasına sınırla
                    result['opportunity_score'] = min(max(score, 0), 100)
                
                combined_results.append(result)
            
            return combined_results
            
        except Exception as e:
            self.logger.error(f"Zaman dilimi sonuçlarını birleştirme hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return previous_results  # Hata durumunda önceki sonuçları döndür

    async def generate_multi_timeframe_chart(self, symbol: str) -> BytesIO:
        """Çoklu zaman dilimi grafiği oluştur"""
        try:
            # Dört farklı zaman dilimi için veri al
            weekly_data = await self.get_klines(symbol, "1w", limit=20)
            h4_data = await self.get_klines(symbol, "4h", limit=60)  # Son 10 gün
            hourly_data = await self.get_klines(symbol, "1h", limit=48)
            m15_data = await self.get_klines(symbol, "15m", limit=96)
            
            if weekly_data.empty or h4_data.empty or hourly_data.empty or m15_data.empty:
                self.logger.error(f"Grafik için veri alınamadı: {symbol}")
                return None
            
            # Grafikleri oluştur (matplotlib kullanarak)
            fig, axs = plt.subplots(4, 1, figsize=(12, 24), gridspec_kw={'height_ratios': [3, 2, 2, 2]})
            
            # Her zaman dilimi için ayrı grafik
            self._plot_timeframe(axs[0], weekly_data, symbol, "1W - Ana Trend")
            self._plot_timeframe(axs[1], h4_data, symbol, "4H - Orta Vadeli Trend")
            self._plot_timeframe(axs[2], hourly_data, symbol, "1H - Kısa Vadeli Trend")
            self._plot_timeframe(axs[3], m15_data, symbol, "15M - Giriş/Çıkış Noktaları")
            
            # Genel grafik başlığı
            fig.suptitle(f"{symbol} Çoklu Zaman Dilimi Analizi", fontsize=16, fontweight='bold')
            
            # Grafik stilini düzenle
            plt.tight_layout(rect=[0, 0, 1, 0.97])  # Üst başlık için yer bırak
            
            # BytesIO nesnesine kaydet
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close(fig)
            
            return buf
            
        except Exception as e:
            self.logger.error(f"Çoklu zaman dilimi grafik oluşturma hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    def _plot_timeframe(self, ax, df, symbol, title):
        """Belirli bir zaman dilimi için grafik çiz"""
        try:
            # OHLC grafiği
            df_reset = df.reset_index()
            
            # Candlestick grafiği
            mpf.plot(df, type='candle', style='yahoo', ax=ax, no_xgrid=True, ylim=(df['low'].min()*0.99, df['high'].max()*1.01))
            
            # EMA'ları ekle
            ema9 = df['close'].ewm(span=9, adjust=False).mean()
            ema20 = df['close'].ewm(span=20, adjust=False).mean()
            ema50 = df['close'].ewm(span=50, adjust=False).mean()
            
            ax.plot(df.index, ema9, 'blue', linewidth=1, alpha=0.8, label='EMA9')
            ax.plot(df.index, ema20, 'orange', linewidth=1, alpha=0.8, label='EMA20')
            ax.plot(df.index, ema50, 'red', linewidth=1, alpha=0.8, label='EMA50')
            
            # Bollinger Bands ekle
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            bb_middle = typical_price.rolling(window=20).mean()
            bb_std = typical_price.rolling(window=20).std()
            bb_upper = bb_middle + (2 * bb_std)
            bb_lower = bb_middle - (2 * bb_std)
            
            ax.plot(df.index, bb_upper, 'g--', linewidth=1, alpha=0.5)
            ax.plot(df.index, bb_middle, 'g-', linewidth=1, alpha=0.5)
            ax.plot(df.index, bb_lower, 'g--', linewidth=1, alpha=0.5)
            
            # Trend tespiti
            indicators = self.calculate_indicators(df)
            trend, trend_strength = self.analyze_trend(df, indicators)
            
            # Trend rengini belirle
            trend_color = 'gray'
            if trend in ["STRONGLY_BULLISH", "BULLISH"]:
                trend_color = 'green'
            elif trend in ["STRONGLY_BEARISH", "BEARISH"]:
                trend_color = 'red'
            
            # Trend emoji belirle
            trend_emoji = "↗️" if trend in ["STRONGLY_BULLISH", "BULLISH"] else "↘️" if trend in ["STRONGLY_BEARISH", "BEARISH"] else "➡️"
            
            # Grafik başlığı ve trend bilgisi
            ax.set_title(f"{title} ({trend_emoji} {trend}, Güç: {trend_strength:.2f})", color=trend_color, fontweight='bold')
            ax.legend(loc='upper left')
            
            # Y ekseni fiyat formatı
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.2f}"))
            
            # Tarih formatı
            date_format = mdates.DateFormatter('%d-%m-%Y' if title.startswith('1W') else '%d-%m %H:%M')
            ax.xaxis.set_major_formatter(date_format)
            plt.xticks(rotation=45)
            
            # Tarih aralıklarını ayarla
            if title.startswith('1W'):
                ax.xaxis.set_major_locator(mdates.MonthLocator())
            elif title.startswith('1H'):
                ax.xaxis.set_major_locator(mdates.DayLocator())
            else:
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
            
            # Grid çizgileri
            ax.grid(True, alpha=0.3)
            
            # Trend açıklamalarını ekle
            if indicators and 'trend_messages' in indicators:
                y_pos = 0.02
                for msg in indicators['trend_messages'][:2]:
                    ax.text(0.02, y_pos, f"• {msg}", transform=ax.transAxes, fontsize=8)
                    y_pos += 0.05
            
        except Exception as e:
            self.logger.error(f"Timeframe plot hatası: {str(e)}")

    async def get_top_symbols(self, limit=30, quote_currency='USDT'):
        """
        İşlem hacmine göre sıralanmış en popüler sembolleri döndürür
        
        Args:
            limit (int): Kaç sembol döndürüleceği
            quote_currency (str): Baz para birimi (default: USDT)
            
        Returns:
            List[str]: Popüler sembollerin listesi
        """
        try:
            # Önbellek anahtarı oluştur
            cache_key = f"top_symbols_{limit}_{quote_currency}"
            cached_symbols = self.data_cache.get(cache_key)
            if cached_symbols:
                return cached_symbols
                
            self.logger.info(f"En popüler {limit} sembol alınıyor...")
            
            # CCXT ile tüm işlemleri al
            markets = self.exchange.load_markets()
            
            # Quote currency ile eşleşen sembolleri filtrele (örn: USDT)
            usdt_markets = [
                market for market in markets.values() 
                if isinstance(market, dict) and
                market.get('quote') == quote_currency and
                not 'BEAR' in market.get('base', '') and
                not 'BULL' in market.get('base', '') and
                not 'UP' in market.get('base', '') and
                not 'DOWN' in market.get('base', '')
            ]
            
            # 24 saatlik işlem hacmine göre sırala
            try:
                tickers = self.exchange.fetch_tickers()
                
                # Her market için hacim bilgisini al
                market_volumes = []
                for market in usdt_markets:
                    symbol = market['symbol']
                    ticker = tickers.get(symbol, {})
                    volume = ticker.get('quoteVolume', 0)
                    
                    if volume is None:  # None kontrolü
                        volume = 0
                    
                    market_volumes.append((symbol.replace('/', ''), volume))
                
                # Hacme göre sırala ve en yüksek olanları al
                sorted_markets = sorted(market_volumes, key=lambda x: x[1], reverse=True)
                top_symbols = [m[0] for m in sorted_markets[:limit]]
                
                # Yeterli sembol yoksa default listeyi kullan
                if len(top_symbols) < limit:
                    default_symbols = [
                        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", 
                        "SOLUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "MATICUSDT",
                        "LINKUSDT", "UNIUSDT", "FILUSDT", "LTCUSDT", "NEARUSDT",
                        "TRXUSDT", "ETCUSDT", "ATOMUSDT", "XLMUSDT", "APTUSDT",
                        "VETUSDT", "HBARUSDT", "ALGOUSDT", "ICPUSDT", "MANAUSDT",
                        "SANDUSDT", "AXSUSDT", "FTMUSDT", "EOSUSDT", "RUNEUSDT"
                    ]
                    # Eksik sembolleri ekle
                    remaining = limit - len(top_symbols)
                    for symbol in default_symbols:
                        if symbol not in top_symbols and remaining > 0:
                            top_symbols.append(symbol)
                            remaining -= 1
                        if remaining == 0:
                            break
                
                # Sadece Binance format sembolleri döndür (BTCUSDT gibi)
                binance_format_symbols = []
                for symbol in top_symbols:
                    if '/' in symbol:  # CCXT formatı
                        binance_format = symbol.replace('/', '')
                    else:  # Zaten Binance formatında
                        binance_format = symbol
                    binance_format_symbols.append(binance_format)
                
                # Önbelleğe kaydet
                self.data_cache[cache_key] = binance_format_symbols
                
                self.logger.info(f"{len(binance_format_symbols)} popüler sembol bulundu")
                return binance_format_symbols
                
            except Exception as e:
                self.logger.error(f"Ticker verisi alınırken hata: {str(e)}")
                # Hata durumunda default sembolleri kullan
                default_symbols = [
                    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", 
                    "SOLUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "MATICUSDT"
                ]
                return default_symbols[:limit]
        
        except Exception as e:
            self.logger.error(f"Popüler sembol alma hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            # Hata durumunda en popüler 10 coin'i döndür
            default_symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", 
                "SOLUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "MATICUSDT"
            ]
            return default_symbols[:limit]

    def analyze_trend(self, df: pd.DataFrame, indicators: Dict) -> Tuple[str, float]:
        """Gelişmiş trend analizi ve trend gücü hesaplama"""
        try:
            # Tüm göstergeleri değerlendir
            trend_factors = {}
            trend_messages = []
            
            # RSI bazlı trend analizi
            rsi = indicators["rsi"]
            if rsi > 70:
                trend_factors["rsi"] = -1  # Aşırı alım (bearish)
                trend_messages.append("RSI aşırı alım bölgesinde (>70)")
            elif rsi < 30:
                trend_factors["rsi"] = 1   # Aşırı satım (bullish)
                trend_messages.append("RSI aşırı satım bölgesinde (<30)")
            elif rsi > 55:
                trend_factors["rsi"] = 0.5  # Bullish eğilim
                trend_messages.append("RSI yükseliş bölgesinde (>55)")
            elif rsi < 45:
                trend_factors["rsi"] = -0.5  # Bearish eğilim
                trend_messages.append("RSI düşüş bölgesinde (<45)")
            else:
                trend_factors["rsi"] = 0  # Nötr
            
            # MACD bazlı trend analizi
            macd = indicators["macd"]
            macd_signal = indicators["macd_signal"]
            macd_hist = indicators["macd_hist"]
            
            if macd > macd_signal and macd_hist > 0:
                trend_factors["macd"] = 1  # Güçlü yükseliş sinyali
                trend_messages.append("MACD yükseliş sinyali veriyor")
            elif macd < macd_signal and macd_hist < 0:
                trend_factors["macd"] = -1  # Güçlü düşüş sinyali
                trend_messages.append("MACD düşüş sinyali veriyor")
            elif macd > macd_signal:
                trend_factors["macd"] = 0.5  # Yükseliş sinyali
                trend_messages.append("MACD çizgisi sinyal çizgisinin üzerinde")
            elif macd < macd_signal:
                trend_factors["macd"] = -0.5  # Düşüş sinyali
                trend_messages.append("MACD çizgisi sinyal çizgisinin altında")
            else:
                trend_factors["macd"] = 0
            
            # EMA bazlı trend analizi
            emas = indicators["emas"]
            close = df['close'].iloc[-1]
            
            ema9 = emas.get("ema9", 0)
            ema20 = emas.get("ema20", 0)
            ema50 = emas.get("ema50", 0)
            ema200 = emas.get("ema200", 0) if "ema200" in emas else None
            
            # EMA setlerinin sıralaması
            ema_trend = 0
            ema_messages = []
            
            # Fiyat tüm EMA'ların üzerinde mi (güçlü yükseliş)
            if ema200 is not None and close > ema9 > ema20 > ema50 > ema200:
                ema_trend += 2
                ema_messages.append("Fiyat tüm EMA'ların üzerinde (çok güçlü yükseliş)")
            elif close > ema9 > ema20 > ema50:
                ema_trend += 1.5
                ema_messages.append("Fiyat tüm kısa ve orta vadeli EMA'ların üzerinde (güçlü yükseliş)")
            
            # Fiyat tüm EMA'ların altında mı (güçlü düşüş)
            elif ema200 is not None and close < ema9 < ema20 < ema50 < ema200:
                ema_trend -= 2
                ema_messages.append("Fiyat tüm EMA'ların altında (çok güçlü düşüş)")
            elif close < ema9 < ema20 < ema50:
                ema_trend -= 1.5
                ema_messages.append("Fiyat tüm kısa ve orta vadeli EMA'ların altında (güçlü düşüş)")
            
            # Pozitif çapraz geçişler
            elif ema9 > ema20 > ema50 and close > ema9:
                ema_trend += 1
                ema_messages.append("Altın çapraz formasyon (EMA9 > EMA20 > EMA50)")
            elif close > ema20 > ema50:
                ema_trend += 0.8
                ema_messages.append("Fiyat orta vadeli EMA'ların üzerinde")
            elif close > ema50:
                ema_trend += 0.5
                ema_messages.append("Fiyat EMA50'nin üzerinde")
            
            # Negatif çapraz geçişler
            elif ema9 < ema20 < ema50 and close < ema9:
                ema_trend -= 1
                ema_messages.append("Ölüm çaprazı formasyon (EMA9 < EMA20 < EMA50)")
            elif close < ema20 < ema50:
                ema_trend -= 0.8
                ema_messages.append("Fiyat orta vadeli EMA'ların altında")
            elif close < ema50:
                ema_trend -= 0.5
                ema_messages.append("Fiyat EMA50'nin altında")
            
            # En önemli EMA mesajını ekle
            if ema_messages:
                trend_messages.append(ema_messages[0])
            
            trend_factors["ema"] = ema_trend
            
            # Bollinger Bands bazlı trend
            bb_position = indicators["bb_position"]
            
            if bb_position > 90:
                trend_factors["bb"] = -1  # Aşırı alım ve olası geri çekilme
                trend_messages.append("Fiyat üst BB bandının üstünde (aşırı alım)")
            elif bb_position < 10:
                trend_factors["bb"] = 1  # Aşırı satım ve olası yükseliş
                trend_messages.append("Fiyat alt BB bandının altında (aşırı satım)")
            elif bb_position > 80:
                trend_factors["bb"] = -0.5  # Üst banda yakın
                trend_messages.append("Fiyat üst BB bandına yakın")
            elif bb_position < 20:
                trend_factors["bb"] = 0.5  # Alt banda yakın
                trend_messages.append("Fiyat alt BB bandına yakın")
            else:
                trend_factors["bb"] = 0  # Bantların ortasında
            
            # Hacim analizi
            volume_change = indicators["volume_change"]
            
            # Hacim değişimi yüksekse ve fiyat yükseliyorsa güçlü sinyal
            last_close = df['close'].iloc[-1]
            last_open = df['open'].iloc[-1]
            price_up = last_close > last_open
            
            if volume_change > 100 and price_up:
                trend_factors["volume"] = 1  # Çok yüksek hacimle yükseliş
                trend_messages.append("Çok yüksek hacimle yükseliş (%100+ hacim artışı)")
            elif volume_change > 100 and not price_up:
                trend_factors["volume"] = -1  # Çok yüksek hacimle düşüş
                trend_messages.append("Çok yüksek hacimle düşüş (%100+ hacim artışı)")
            elif volume_change > 50 and price_up:
                trend_factors["volume"] = 0.7  # Yüksek hacimle yükseliş
                trend_messages.append("Yüksek hacimle yükseliş (%50+ hacim artışı)")
            elif volume_change > 50 and not price_up:
                trend_factors["volume"] = -0.7  # Yüksek hacimle düşüş
                trend_messages.append("Yüksek hacimle düşüş (%50+ hacim artışı)")
            elif volume_change > 20:
                trend_factors["volume"] = 0.3  # Orta hacim artışı
            elif volume_change < -50:
                trend_factors["volume"] = -0.3  # Hacimde büyük düşüş
                trend_messages.append("Hacimde büyük düşüş (düşük ilgi)")
            else:
                trend_factors["volume"] = 0
            
            # Stochastic Oscillator
            stoch_k = indicators.get("stoch_k", 50)
            stoch_d = indicators.get("stoch_d", 50)
            
            if stoch_k > 80 and stoch_d > 80:
                trend_factors["stoch"] = -0.7  # Aşırı alım
            elif stoch_k < 20 and stoch_d < 20:
                trend_factors["stoch"] = 0.7  # Aşırı satım
            elif stoch_k > stoch_d and stoch_k < 80:
                trend_factors["stoch"] = 0.3  # Yükseliş sinyali
            elif stoch_k < stoch_d and stoch_k > 20:
                trend_factors["stoch"] = -0.3  # Düşüş sinyali
            else:
                trend_factors["stoch"] = 0
            
            # Ağırlıklar
            weights = {
                "ema": 0.35,
                "macd": 0.20,
                "rsi": 0.15,
                "bb": 0.10,
                "volume": 0.10,
                "stoch": 0.10
            }
            
            # Ağırlıklı trend skoru hesapla
            weighted_score = 0
            for factor, score in trend_factors.items():
                if factor in weights:
                    weighted_score += score * weights[factor]
            
            # Trendi belirle
            if weighted_score >= 0.7:
                final_trend = "STRONGLY_BULLISH"
            elif weighted_score >= 0.3:
                final_trend = "BULLISH"
            elif weighted_score <= -0.7:
                final_trend = "STRONGLY_BEARISH"
            elif weighted_score <= -0.3:
                final_trend = "BEARISH"
            else:
                final_trend = "NEUTRAL"
            
            # Trend gücü: Mutlak değerin 0-1 arasında normalizasyonu
            trend_strength = min(abs(weighted_score), 1)
            
            # Trend mesajlarını kaydet
            indicators["trend_messages"] = trend_messages
            
            return final_trend, trend_strength
        
        except Exception as e:
            self.logger.error(f"Trend analizi hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return "NEUTRAL", 0
