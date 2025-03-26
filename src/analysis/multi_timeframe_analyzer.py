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
    
    """
    Multi Timeframe Analyzer modülü

    Bu modül şunları yapar:
    1. Haftalık grafikler için trend analizi
    2. Saatlik grafikler için detaylandırma
    3. Olumlu haftalık ve saatlik trende sahip coinler için 15dk analizi
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
    
    async def scan_market(self, symbols=None, demo=True):
        """
        Dört zaman diliminde market taraması yapar (1W, 4H, 1H, 15m)
        
        1. Haftalık (1W) trendin olumlu olduğu coinleri bulur
        2. Olumlu haftalık trende sahip coinlerin 4 saatlik (4H) analizini yapar
        3. Olumlu haftalık ve 4 saatlik trende sahip coinlerin saatlik (1H) analizini yapar
        4. Tüm trenler olumlu olan coinler için 15dk analizi yapar
        
        Args:
            symbols (List[str], optional): Analiz edilecek sembol listesi. Default olarak popüler coinler.
            demo (bool, optional): Demo mod aktifse bütün sembolleri analiz eder. Default True.
            
        Returns:
            List[Dict]: Alım fırsatları listesi
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
                # Tek sembol analizi ise demo modu aç (filtreleme yapma)
                if len(symbols) == 1:
                    demo = True
            
            # 1. ADIM: HAFTALIK ANALİZ (1W)
            self.logger.info("1/4: Haftalık (1W) analiz başladı...")
            
            # ThreadPoolExecutor ile paralel işlem
            weekly_results = []
            
            async def analyze_symbol_weekly(symbol):
                try:
                    weekly_df = await self.get_klines(symbol, timeframe='1w', limit=52)
                    if weekly_df is None or len(weekly_df) < 26:
                        return None
                    
                    # Göstergeleri hesapla
                    indicators = self.calculate_indicators(weekly_df)
                    if indicators is None:
                        return None
                    
                    # Trend analizi yap
                    trend, trend_strength = self.analyze_trend(weekly_df, indicators)
                    
                    # Sonuç döndür
                    return {
                        'symbol': symbol,
                        'weekly_trend': trend,
                        'weekly_trend_strength': trend_strength,
                        'weekly_indicators': indicators,
                        'weekly_price': weekly_df['close'].iloc[-1],
                        'weekly_volume': weekly_df['volume'].iloc[-1],
                        'opportunity_score': 0  # Başlangıçta 0
                    }
                except Exception as e:
                    self.logger.error(f"Haftalık {symbol} analiz hatası: {str(e)}")
                    return None
            
            # Sembolleri paralel olarak analiz et
            tasks = [analyze_symbol_weekly(symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks)
            weekly_results = [r for r in results if r is not None]
            
            # Olumlu trendleri filtrele
            if not demo:  # Demo mod değilse sadece olumlu trendleri seç
                positive_weekly = [r for r in weekly_results if r['weekly_trend'] in ['BULLISH', 'STRONGLY_BULLISH']]
                self.logger.info(f"Haftalık analizde {len(positive_weekly)} olumlu trend bulundu")
            else:
                positive_weekly = weekly_results
                self.logger.info(f"Demo mod: Haftalık analizde tüm semboller kullanılıyor ({len(positive_weekly)})")
            
            if len(positive_weekly) == 0 and not demo:
                self.logger.warning("Haftalık analizde olumlu trend bulunamadı")
                # En azından birkaç sembol ekleyelim ki sonraki adımlarda çalışsın
                positive_weekly = weekly_results[:5] if len(weekly_results) >= 5 else weekly_results
            
            # 2. ADIM: 4 SAATLİK ANALİZ (4H) - YENİ EKLENEN KISIM
            self.logger.info("2/4: 4 Saatlik (4H) analiz başladı...")
            filtered_symbols = [r['symbol'] for r in positive_weekly]
            
            async def analyze_symbol_4hour(symbol):
                try:
                    h4_df = await self.get_klines(symbol, timeframe='4h', limit=120)  # Son 20 gün
                    if h4_df is None or len(h4_df) < 50:
                        return None
                    
                    # Göstergeleri hesapla
                    indicators = self.calculate_indicators(h4_df)
                    if indicators is None:
                        return None
                    
                    # Trend analizi yap
                    trend, trend_strength = self.analyze_trend(h4_df, indicators)
                    
                    # Sonuç döndür
                    return {
                        'symbol': symbol,
                        'h4_trend': trend,
                        'h4_trend_strength': trend_strength,
                        'h4_indicators': indicators,
                        'h4_price': h4_df['close'].iloc[-1],
                        'h4_volume': h4_df['volume'].iloc[-1]
                    }
                except Exception as e:
                    self.logger.error(f"4 Saatlik {symbol} analiz hatası: {str(e)}")
                    return None
            
            # Paralel olarak 4 saatlik analizleri yap
            tasks = [analyze_symbol_4hour(symbol) for symbol in filtered_symbols]
            results = await asyncio.gather(*tasks)
            h4_results = [r for r in results if r is not None]
            
            # Haftalık ve 4 saatlik sonuçları birleştir
            four_hour_combined = self._combine_weekly_and_4h_results(positive_weekly, h4_results)
            
            # İyi 4 saatlik fırsatları filtrele
            if not demo:
                positive_4h = [r for r in four_hour_combined if r.get('h4_trend') in ['BULLISH', 'STRONGLY_BULLISH']]
                self.logger.info(f"4 Saatlik analizde {len(positive_4h)} olumlu trend bulundu")
            else:
                positive_4h = four_hour_combined
                self.logger.info(f"Demo mod: 4 Saatlik analizde tüm semboller kullanılıyor ({len(positive_4h)})")
            
            if len(positive_4h) == 0 and not demo:
                self.logger.warning("4 Saatlik analizde olumlu trend bulunamadı")
                positive_4h = four_hour_combined[:10] if len(four_hour_combined) >= 10 else four_hour_combined
            
            # 3. ADIM: SAATLİK ANALİZ (1H)
            self.logger.info("3/4: Saatlik (1H) analiz başladı...")
            filtered_symbols = [r['symbol'] for r in positive_4h]
            
            async def analyze_symbol_hourly(symbol):
                try:
                    hourly_df = await self.get_klines(symbol, timeframe='1h', limit=168)  # Son 7 gün
                    if hourly_df is None or len(hourly_df) < 48:
                        return None
                    
                    # Göstergeleri hesapla
                    indicators = self.calculate_indicators(hourly_df)
                    if indicators is None:
                        return None
                    
                    # Trend analizi yap
                    trend, trend_strength = self.analyze_trend(hourly_df, indicators)
                    
                    # Sonuç döndür
                    return {
                        'symbol': symbol,
                        'hourly_trend': trend,
                        'hourly_trend_strength': trend_strength,
                        'hourly_indicators': indicators,
                        'hourly_price': hourly_df['close'].iloc[-1],
                        'hourly_volume': hourly_df['volume'].iloc[-1]
                    }
                except Exception as e:
                    self.logger.error(f"Saatlik {symbol} analiz hatası: {str(e)}")
                    return None
            
            # Paralel olarak saatlik analizleri yap
            tasks = [analyze_symbol_hourly(symbol) for symbol in filtered_symbols]
            results = await asyncio.gather(*tasks)
            hourly_results = [r for r in results if r is not None]
            
            # Ön sonuçları birleştir - weekly, 4h ve hourly
            preliminary_results = self._combine_preliminary_results(positive_4h, hourly_results)
            
            # En iyi fırsatları seç
            if not demo:  # Demo mod değilse puanı yüksek olanları filtrele
                good_opportunities = [r for r in preliminary_results if r.get('opportunity_score', 0) >= 40]
                self.logger.info(f"Haftalık+4Saatlik+Saatlik analizde {len(good_opportunities)} iyi fırsat bulundu")
            else:
                good_opportunities = preliminary_results
                self.logger.info(f"Demo mod: Tüm ön sonuçlar kullanılıyor ({len(good_opportunities)})")
            
            if len(good_opportunities) == 0:
                self.logger.warning("Tüm zaman dilimlerinde uygun fırsat bulunamadı")
                # Birkaç sembol ekleyelim
                good_opportunities = preliminary_results[:10] if len(preliminary_results) >= 10 else preliminary_results
            
            # 4. ADIM: 15 DAKİKALIK ANALİZ (15m)
            self.logger.info("4/4: 15 dakikalık (15m) analiz başladı...")
            final_symbols = [r['symbol'] for r in good_opportunities]
            
            async def analyze_symbol_15min(symbol):
                try:
                    df_15m = await self.get_klines(symbol, timeframe='15m', limit=200)
                    if df_15m is None or len(df_15m) < 48:
                        return None
                    
                    # Göstergeleri hesapla
                    indicators = self.calculate_indicators(df_15m)
                    if indicators is None:
                        return None
                    
                    # Trend analizi yap
                    trend, trend_strength = self.analyze_trend(df_15m, indicators)
                    
                    # Stop/Target hesapla
                    current_price = df_15m['close'].iloc[-1]
                    stop_price, target_price = self.calculate_stop_and_target(df_15m, trend, current_price)
                    
                    # Risk/Ödül oranını hesapla
                    risk = abs(current_price - stop_price) if stop_price > 0 else 1
                    reward = abs(target_price - current_price) if target_price > 0 else 0
                    risk_reward = reward / risk if risk > 0 else 0
                    
                    # Sinyal belirle
                    signal = "🟩 LONG" if trend in ['BULLISH', 'STRONGLY_BULLISH'] else "🔴 SHORT" if trend in ['BEARISH', 'STRONGLY_BEARISH'] else "⚪ BEKLE"
                    
                    # Sonuç döndür
                    return {
                        'symbol': symbol,
                        'signal': signal,
                        '15m_trend': trend,
                        '15m_trend_strength': trend_strength,
                        '15m_indicators': indicators,
                        'current_price': current_price,
                        'stop_price': stop_price,
                        'target_price': target_price,
                        'risk_reward': risk_reward,
                        'trend_descriptions': indicators.get('trend_messages', [])[:3] if indicators else []
                    }
                except Exception as e:
                    self.logger.error(f"15dk {symbol} analiz hatası: {str(e)}")
                    return None
            
            # Paralel olarak 15dk analizleri yap
            tasks = [analyze_symbol_15min(symbol) for symbol in final_symbols]
            results = await asyncio.gather(*tasks)
            m15_results = [r for r in results if r is not None]
            
            # Tüm sonuçları birleştir
            final_results = self._combine_final_results(good_opportunities, m15_results)
            
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
        """Belirli bir zaman dilimi için sembolleri analiz et"""
        analysis_results = []
        
        # Her sembol için analiz yap
        for symbol in symbols:
            try:
                # Kline verilerini al
                df = await self.get_klines(symbol, timeframe, limit=100)
                
                if df.empty:
                    self.logger.warning(f"Boş kline verisi ({symbol}, {timeframe}), atlıyor...")
                    continue
                
                # Ticker verilerini al
                ticker = await self.get_ticker(symbol)
                
                # Ticker bilgisi yoksa veya df boşsa devam et
                if not ticker or df.empty:
                    self.logger.warning(f"Ticker bilgisi yok ({symbol}), atlıyor...")
                    continue
                
                # Temel fiyat bilgileri - None kontrolü ekle
                current_price = ticker.get('last', df['close'].iloc[-1])
                if current_price is None:
                    current_price = df['close'].iloc[-1]  # Ticker'da fiyat yoksa son kapanışı kullan
                
                volume = ticker.get('quoteVolume', df['volume'].sum())
                if volume is None:
                    volume = df['volume'].sum()  # Ticker'da hacim yoksa toplam hacmi kullan
                
                # Teknik göstergeleri hesapla
                indicators = self.calculate_indicators(df)
                
                # Eğer indicators None ise devam et
                if indicators is None:
                    self.logger.warning(f"Göstergeler hesaplanamadı ({symbol}, {timeframe}), atlıyor...")
                    continue
                
                # Trend analizini yap
                trend, trend_strength = self.analyze_trend(df, indicators)
                
                # Stop-loss ve hedef fiyatları belirle
                stop_loss, take_profit = self.calculate_stop_and_target(df, trend, current_price)
                
                # Risk/Ödül oranını hesapla - sıfıra bölünmeyi önle
                risk = abs(current_price - stop_loss)
                reward = abs(take_profit - current_price)
                risk_reward = reward / risk if risk > 0 else 0
                
                # Sonuçları ekle
                result = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "current_price": current_price,
                    "volume": volume,
                    "trend": trend,
                    "trend_strength": trend_strength,
                    "indicators": indicators,
                    "stop_price": stop_loss,
                    "target_price": take_profit,
                    "risk_reward": risk_reward
                }
                
                analysis_results.append(result)
                
            except Exception as e:
                self.logger.error(f"Analiz hatası ({symbol}, {timeframe}): {str(e)}")
                continue
        
        return analysis_results
    
    def calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """Gelişmiş teknik göstergeler hesapla"""
        try:
            # Veri kontrolü
            if df.empty or len(df) < 30:  # En az 30 mum gerekli
                self.logger.warning("Gösterge hesaplama için yeterli veri yok")
                return None
            
            # Temel göstergeler
            indicators = {}
            
            # RSI (Göreli Güç Endeksi)
            close_diff = df['close'].diff().fillna(0)
            gain = close_diff.where(close_diff > 0, 0)
            loss = -close_diff.where(close_diff < 0, 0)
            
            avg_gain = gain.rolling(window=self.rsi_period).mean().fillna(0)
            avg_loss = loss.rolling(window=self.rsi_period).mean().fillna(0)
            
            # İlk değer için ayrı hesaplama
            if len(df) >= self.rsi_period + 1:
                first_avg_gain = gain.iloc[1:self.rsi_period+1].mean()
                first_avg_loss = loss.iloc[1:self.rsi_period+1].mean()
                
                avg_gain.iloc[self.rsi_period] = first_avg_gain
                avg_loss.iloc[self.rsi_period] = first_avg_loss
                
                # Takip eden değerler için Wilder'ın düzgünleştirme formülü
                for i in range(self.rsi_period + 1, len(df)):
                    avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (self.rsi_period - 1) + gain.iloc[i]) / self.rsi_period
                    avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (self.rsi_period - 1) + loss.iloc[i]) / self.rsi_period
            
            # Sıfıra bölünme kontrolü
            rs = avg_gain / avg_loss.replace(0, 1e-9)
            rsi = 100 - (100 / (1 + rs))
            
            indicators['rsi'] = float(rsi.iloc[-1])
            
            # RSI eğilimi (son 5 dönem boyunca yükseliyor mu, düşüyor mu?)
            if len(rsi) >= 5:
                rsi_slope = np.polyfit(range(5), rsi.iloc[-5:].values, 1)[0]
                indicators['rsi_trend'] = 'RISING' if rsi_slope > 0 else 'FALLING'
            else:
                indicators['rsi_trend'] = 'NEUTRAL'
            
            # MACD (Hareketli Ortalama Yakınsama/Iraksama)
            ema12 = df['close'].ewm(span=12, adjust=False).mean()
            ema26 = df['close'].ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - signal_line
            
            indicators['macd'] = float(macd_line.iloc[-1])
            indicators['macd_signal'] = float(signal_line.iloc[-1])
            indicators['macd_hist'] = float(histogram.iloc[-1])
            
            # MACD çizgisinin eğilimi
            if len(macd_line) >= 5:
                macd_slope = np.polyfit(range(5), macd_line.iloc[-5:].values, 1)[0]
                indicators['macd_trend'] = 'RISING' if macd_slope > 0 else 'FALLING'
            else:
                indicators['macd_trend'] = 'NEUTRAL'
            
            # MACD histogramı eğilimi (ivme)
            if len(histogram) >= 5:
                hist_values = histogram.iloc[-5:].values
                hist_diff = np.diff(hist_values)
                hist_trend = 'RISING' if np.sum(hist_diff > 0) >= 3 else 'FALLING'
                indicators['macd_hist_trend'] = hist_trend
            else:
                indicators['macd_hist_trend'] = 'NEUTRAL'
            
            # Bollinger Bantları
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            sma20 = typical_price.rolling(window=20).mean()
            std20 = typical_price.rolling(window=20).std()
            
            bb_upper = sma20 + (2 * std20)
            bb_lower = sma20 - (2 * std20)
            
            indicators['bb_upper'] = float(bb_upper.iloc[-1])
            indicators['bb_middle'] = float(sma20.iloc[-1])
            indicators['bb_lower'] = float(bb_lower.iloc[-1])
            
            # BB genişliği (volatilite göstergesi)
            bb_width = (bb_upper - bb_lower) / sma20
            indicators['bb_width'] = float(bb_width.iloc[-1])
            
            # BB'nin daralıp genişleme durumu
            if len(bb_width) >= 5:
                width_slope = np.polyfit(range(5), bb_width.iloc[-5:].values, 1)[0]
                indicators['bb_width_trend'] = 'EXPANDING' if width_slope > 0 else 'CONTRACTING'
            else:
                indicators['bb_width_trend'] = 'NEUTRAL'
            
            # BB'da fiyat pozisyonu
            last_close = df['close'].iloc[-1]
            pct_b = (last_close - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1] + 1e-9)
            indicators['bb_position'] = float(pct_b * 100)
            
            # EMA Hesaplamaları
            emas = {}
            for period in self.ema_periods:
                ema_value = df['close'].ewm(span=period, adjust=False).mean().iloc[-1]
                emas[f'ema{period}'] = float(ema_value)
            
            indicators['emas'] = emas
            
            # EMA çapraz geçişleri
            indicators['ema_cross'] = {}
            
            # EMA9 ve EMA20 çapraz geçişi
            if 'ema9' in emas and 'ema20' in emas:
                ema9_values = df['close'].ewm(span=9, adjust=False).mean()
                ema20_values = df['close'].ewm(span=20, adjust=False).mean()
                
                if ema9_values.iloc[-1] > ema20_values.iloc[-1] and ema9_values.iloc[-2] <= ema20_values.iloc[-2]:
                    indicators['ema_cross']['9_20'] = 'GOLDEN_CROSS'
                elif ema9_values.iloc[-1] < ema20_values.iloc[-1] and ema9_values.iloc[-2] >= ema20_values.iloc[-2]:
                    indicators['ema_cross']['9_20'] = 'DEATH_CROSS'
                else:
                    indicators['ema_cross']['9_20'] = 'NONE'
            
            # EMA20 ve EMA50 çapraz geçişi
            if 'ema20' in emas and 'ema50' in emas:
                ema20_values = df['close'].ewm(span=20, adjust=False).mean()
                ema50_values = df['close'].ewm(span=50, adjust=False).mean()
                
                if ema20_values.iloc[-1] > ema50_values.iloc[-1] and ema20_values.iloc[-2] <= ema50_values.iloc[-2]:
                    indicators['ema_cross']['20_50'] = 'GOLDEN_CROSS'
                elif ema20_values.iloc[-1] < ema50_values.iloc[-1] and ema20_values.iloc[-2] >= ema50_values.iloc[-2]:
                    indicators['ema_cross']['20_50'] = 'DEATH_CROSS'
                else:
                    indicators['ema_cross']['20_50'] = 'NONE'
            
            # Hacim analizi
            current_volume = df['volume'].iloc[-1]
            volume_sma20 = df['volume'].rolling(window=20).mean().iloc[-1]
            
            indicators['volume'] = float(current_volume)
            indicators['volume_sma20'] = float(volume_sma20)
            indicators['volume_change'] = float(((current_volume - volume_sma20) / (volume_sma20 + 1e-9)) * 100)
            
            # Hacim trendi (son 5 dönemde)
            if len(df) >= 5:
                volume_trend = np.polyfit(range(5), df['volume'].iloc[-5:].values, 1)[0]
                indicators['volume_trend'] = 'RISING' if volume_trend > 0 else 'FALLING'
            else:
                indicators['volume_trend'] = 'NEUTRAL'
            
            # Fiyat Aksiyonu Analizi
            # Son 3 mumun yükseliş/düşüş durumu
            if len(df) >= 3:
                last_candles = df.iloc[-3:]
                bullish_candles = sum(1 for i in range(len(last_candles)) if last_candles['close'].iloc[i] > last_candles['open'].iloc[i])
                bearish_candles = sum(1 for i in range(len(last_candles)) if last_candles['close'].iloc[i] < last_candles['open'].iloc[i])
                
                indicators['price_action'] = 'BULLISH' if bullish_candles > bearish_candles else 'BEARISH' if bearish_candles > bullish_candles else 'NEUTRAL'
            else:
                indicators['price_action'] = 'NEUTRAL'
                
            # Momentum hesaplama (Rate of Change)
            if len(df) >= 10:
                roc = ((df['close'].iloc[-1] - df['close'].iloc[-10]) / df['close'].iloc[-10]) * 100
                indicators['roc'] = float(roc)
                indicators['momentum'] = 'STRONG_BULLISH' if roc > 5 else 'BULLISH' if roc > 2 else 'BEARISH' if roc < -2 else 'STRONG_BEARISH' if roc < -5 else 'NEUTRAL'
            else:
                indicators['roc'] = 0
                indicators['momentum'] = 'NEUTRAL'
            
            return indicators
            
        except Exception as e:
            self.logger.error(f"Gösterge hesaplama hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None


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
            
            # RSI trendi de değerlendir
            if indicators.get("rsi_trend") == "RISING" and rsi < 70:
                trend_factors["rsi_trend"] = 0.5
                trend_messages.append("RSI yükseliş trendinde")
            elif indicators.get("rsi_trend") == "FALLING" and rsi > 30:
                trend_factors["rsi_trend"] = -0.5
                trend_messages.append("RSI düşüş trendinde")
            else:
                trend_factors["rsi_trend"] = 0
            
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
            
            # MACD histogram trendi
            if indicators.get("macd_hist_trend") == "RISING":
                trend_factors["macd_hist"] = 0.5
                trend_messages.append("MACD histogramı yükseliyor (momentum artıyor)")
            elif indicators.get("macd_hist_trend") == "FALLING":
                trend_factors["macd_hist"] = -0.5
                trend_messages.append("MACD histogramı düşüyor (momentum azalıyor)")
            else:
                trend_factors["macd_hist"] = 0
            
            # EMA bazlı trend analizi - daha kapsamlı
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
            
            # EMA çapraz geçiş sinyalleri
            ema_cross = indicators.get("ema_cross", {})
            if ema_cross.get("9_20") == "GOLDEN_CROSS":
                ema_trend += 0.5
                ema_messages.append("Yeni altın çapraz (EMA9 > EMA20)")
            elif ema_cross.get("9_20") == "DEATH_CROSS":
                ema_trend -= 0.5
                ema_messages.append("Yeni ölüm çaprazı (EMA9 < EMA20)")
            
            if ema_cross.get("20_50") == "GOLDEN_CROSS":
                ema_trend += 0.7
                ema_messages.append("Güçlü altın çapraz (EMA20 > EMA50)")
            elif ema_cross.get("20_50") == "DEATH_CROSS":
                ema_trend -= 0.7
                ema_messages.append("Güçlü ölüm çaprazı (EMA20 < EMA50)")
            
            # En önemli EMA mesajını ekle
            if ema_messages:
                trend_messages.append(ema_messages[0])
            
            trend_factors["ema"] = ema_trend
            
            # Bollinger Bands bazlı trend
            bb_position = indicators["bb_position"]
            bb_width_trend = indicators.get("bb_width_trend", "NEUTRAL")
            
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
            
            # Bantlar daralıyorsa (düşük volatilite, olası breakout)
            if bb_width_trend == "CONTRACTING":
                trend_factors["bb_width"] = 0.2  # Hafif pozitif etki
                trend_messages.append("BB bantları daralıyor (olası breakout)")
            elif bb_width_trend == "EXPANDING":
                trend_factors["bb_width"] = 0.1  # Çok hafif pozitif etki
                trend_messages.append("BB bantları genişliyor (volatilite artıyor)")
            else:
                trend_factors["bb_width"] = 0
            
            # Fiyat Aksiyonu
            price_action = indicators.get("price_action", "NEUTRAL")
            if price_action == "BULLISH":
                trend_factors["price_action"] = 0.5
                trend_messages.append("Son mumlar yükseliş gösteriyor")
            elif price_action == "BEARISH":
                trend_factors["price_action"] = -0.5
                trend_messages.append("Son mumlar düşüş gösteriyor")
            else:
                trend_factors["price_action"] = 0
            
            # Hacim analizi
            volume_change = indicators["volume_change"]
            volume_trend = indicators.get("volume_trend", "NEUTRAL")
            
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
            
            # Hacim trendi
            if volume_trend == "RISING" and price_up:
                trend_factors["volume_trend"] = 0.3
                trend_messages.append("Artan hacim trendi ile yükseliş")
            elif volume_trend == "RISING" and not price_up:
                trend_factors["volume_trend"] = -0.3
                trend_messages.append("Artan hacim trendi ile düşüş")
            elif volume_trend == "FALLING":
                trend_factors["volume_trend"] = -0.1
                trend_messages.append("Azalan hacim trendi")
            else:
                trend_factors["volume_trend"] = 0
            
            # Ağırlıklar
            weights = {
                "ema": 0.35,
                "macd": 0.15,
                "rsi": 0.15,
                "bb": 0.10,
                "volume": 0.10,
                "price_action": 0.05,
                "macd_hist": 0.05,
                "rsi_trend": 0.03,
                "volume_trend": 0.02
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
            
            # En önemli 3 trend faktörünü seç
            indicators["trend_messages"] = trend_messages[:3]
            
            return final_trend, trend_strength
        
        except Exception as e:
            self.logger.error(f"Trend analizi hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return "NEUTRAL", 0


    def calculate_stop_and_target(self, df: pd.DataFrame, trend: str, current_price: float) -> Tuple[float, float]:
        """Stop-loss ve hedef fiyatları hesapla"""
        try:
            # None kontrolü ekleyelim
            if current_price is None:
                self.logger.warning("Geçerli fiyat değeri None. Varsayılan değerler kullanılıyor.")
                # Veri varsa son kapanış fiyatını kullan, yoksa 0 döndür
                current_price = df['close'].iloc[-1] if not df.empty else 0
            
            # Veri kontrolü
            if df.empty:
                self.logger.warning("DataFrame boş, varsayılan stop-loss ve hedef değerleri kullanılıyor.")
                return current_price * 0.95, current_price * 1.10
            
            # Son 20 mumun yüksek/düşük değerlerini al
            recent_high = df['high'][-20:].max()
            recent_low = df['low'][-20:].min()
            
            # ATR (Average True Range) hesapla - volatilite ölçüsü
            high_low = df['high'] - df['low']
            high_close = (df['high'] - df['close'].shift()).abs()
            low_close = (df['low'] - df['close'].shift()).abs()
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = true_range.rolling(window=14).mean().iloc[-1]
            
            # ATR değeri None ise güvenli bir değer kullan
            if pd.isna(atr) or atr is None:
                self.logger.warning("ATR değeri hesaplanamadı, varsayılan değer kullanılıyor.")
                atr = current_price * 0.02  # Varsayılan olarak fiyatın %2'si
            
            # Trend bazlı stop-loss ve hedef hesapla
            if trend in ["BULLISH", "STRONGLY_BULLISH"]:
                # LONG pozisyon
                stop_loss = current_price - (atr * 2)  # 2 ATR altında stop
                take_profit = current_price + (atr * 4)  # 4 ATR üstünde hedef (2:1 oran)
                
                # Ek olarak, son düşük değer stop olarak kullanılabilir
                # None ve NaN kontrolü yap
                if pd.notna(recent_low) and recent_low is not None:
                    alt_stop = recent_low
                    # Hangisi daha yakınsa onu kullan, ama çok uzakta değilse
                    if alt_stop > current_price - (atr * 3) and alt_stop < current_price:
                        stop_loss = alt_stop
            
            elif trend in ["BEARISH", "STRONGLY_BEARISH"]:
                # SHORT pozisyon
                stop_loss = current_price + (atr * 2)  # 2 ATR üstünde stop
                take_profit = current_price - (atr * 4)  # 4 ATR altında hedef (2:1 oran)
                
                # Ek olarak, son yüksek değer stop olarak kullanılabilir
                # None ve NaN kontrolü yap
                if pd.notna(recent_high) and recent_high is not None:
                    alt_stop = recent_high
                    # Hangisi daha yakınsa onu kullan, ama çok uzakta değilse
                    if alt_stop < current_price + (atr * 3) and alt_stop > current_price:
                        stop_loss = alt_stop
            
            else:
                # NEUTRAL trend
                stop_loss = current_price * 0.95  # %5 aşağıda varsayılan stop
                take_profit = current_price * 1.10  # %10 yukarıda varsayılan hedef
            
            return stop_loss, take_profit
            
        except Exception as e:
            self.logger.error(f"Stop-loss ve hedef hesaplama hatası: {str(e)}")
            # Varsayılan değerler
            return current_price * 0.95, current_price * 1.10


    def _combine_preliminary_results(self, four_hour_results, hourly_results):
        """4 saatlik ve saatlik analiz sonuçlarını birleştirir"""
        try:
            combined_results = []
            
            # 4 saatlik sonuçları döngüye al
            for h4_result in four_hour_results:
                symbol = h4_result['symbol']
                
                # Bu sembol için saatlik sonucu bul
                hourly = next((h for h in hourly_results if h['symbol'] == symbol), None)
                
                # Eğer saatlik sonuç bulunamazsa, sadece 4 saatlik ile devam et
                if hourly is None:
                    result = h4_result.copy()
                    result['hourly_trend'] = 'UNKNOWN'
                    result['hourly_trend_strength'] = 0
                    # Puanı olduğu gibi koru
                else:
                    # 4 saatlik ve saatlik sonuçları birleştir
                    result = h4_result.copy()
                    result.update(hourly)
                    
                    # Fırsat puanını güncelle
                    score = result.get('opportunity_score', 0)
                    
                    # Saatlik trend puanı (0-20 arası)
                    if hourly['hourly_trend'] == 'STRONGLY_BULLISH':
                        score += 20
                    elif hourly['hourly_trend'] == 'BULLISH':
                        score += 15
                    elif hourly['hourly_trend'] == 'NEUTRAL':
                        score += 5
                    elif hourly['hourly_trend'] == 'BEARISH':
                        score -= 10
                    
                    # RSI değerlendirmesi
                    hourly_rsi = hourly['hourly_indicators'].get('rsi', 50)
                    
                    # RSI 30-70 arasında ise bonus puan
                    if 30 <= hourly_rsi <= 70:
                        score += 5
                    
                    # RSI trendle uyumlu ise bonus
                    if hourly['hourly_trend'] in ['BULLISH', 'STRONGLY_BULLISH'] and hourly_rsi > 50:
                        score += 5
                    
                    # Puanı 0-100 arasına sınırla
                    result['opportunity_score'] = min(max(score, 0), 100)
                
                combined_results.append(result)
            
            return combined_results
            
        except Exception as e:
            self.logger.error(f"Ön sonuçları birleştirme hatası: {str(e)}")
            return four_hour_results  # Hata durumunda 4 saatlik sonuçları döndür


    def _combine_final_results(self, preliminary_results, m15_results):
        """Ön sonuçlar ile 15dk analizini birleştirir"""
        try:
            final_results = []
            
            # Ön sonuçları döngüye al
            for prelim in preliminary_results:
                symbol = prelim['symbol']
                
                # Bu sembol için 15dk sonucunu bul
                m15 = next((m for m in m15_results if m['symbol'] == symbol), None)
                
                # 15dk sonucu bulunamazsa, ön sonuçla devam et
                if m15 is None:
                    result = prelim.copy()
                    result['signal'] = "⚪ BEKLE"
                    result['15m_trend'] = 'UNKNOWN'
                    result['15m_trend_strength'] = 0
                    result['current_price'] = prelim.get('hourly_price', prelim.get('weekly_price', 0))
                    result['stop_price'] = 0
                    result['target_price'] = 0
                    result['risk_reward'] = 0
                else:
                    # Tüm sonuçları birleştir
                    result = prelim.copy()
                    result.update(m15)
                    
                    # Fırsat puanını güncelle (15dk analizine göre)
                    score = result.get('opportunity_score', 0)
                    
                    # 15dk trend puanı (0-20)
                    if m15['15m_trend'] == 'STRONGLY_BULLISH':
                        score += 20
                    elif m15['15m_trend'] == 'BULLISH':
                        score += 15
                    elif m15['15m_trend'] == 'NEUTRAL':
                        score += 5
                    elif m15['15m_trend'] == 'BEARISH':
                        score -= 10
                    elif m15['15m_trend'] == 'STRONGLY_BEARISH':
                        score -= 20
                    
                    # Risk/Ödül oranına göre bonus
                    risk_reward = m15.get('risk_reward', 0)
                    if risk_reward >= 3:  # 3:1 veya daha iyi ise
                        score += 10
                    elif risk_reward >= 2:  # 2:1 veya daha iyi ise
                        score += 5
                    
                    # Son fiyata göre trend değişimi kontrolü
                    weekly_price = prelim.get('weekly_price', 0)
                    hourly_price = prelim.get('hourly_price', 0)
                    current_price = m15.get('current_price', 0)
                    
                    # Fiyat artışı varsa bonus
                    if current_price > hourly_price > weekly_price:
                        score += 5  # Sürekli artış var
                    elif current_price < hourly_price < weekly_price:
                        score -= 5  # Sürekli düşüş var
                    
                    # Puanı 0-100 arasına sınırla
                    result['opportunity_score'] = min(max(score, 0), 100)
                
                final_results.append(result)
            
            return final_results
            
        except Exception as e:
            self.logger.error(f"Final sonuçları birleştirme hatası: {str(e)}")
            return preliminary_results  # Hata durumunda ön sonuçları döndür


    def _combine_weekly_and_4h_results(self, weekly_results, h4_results):
        """Haftalık ve 4 saatlik analiz sonuçlarını birleştirir"""
        try:
            combined_results = []
            
            # Haftalık sonuçları döngüye al
            for weekly in weekly_results:
                symbol = weekly['symbol']
                
                # Bu sembol için 4 saatlik sonucu bul
                h4 = next((h for h in h4_results if h['symbol'] == symbol), None)
                
                # Eğer 4 saatlik sonuç bulunamazsa, sadece haftalık ile devam et
                if h4 is None:
                    result = weekly.copy()
                    result['h4_trend'] = 'UNKNOWN'
                    result['h4_trend_strength'] = 0
                    # Varsayılan puanı ayarla (sadece haftalık analiz)
                    initial_score = 0
                    if weekly['weekly_trend'] == 'STRONGLY_BULLISH':
                        initial_score = 40
                    elif weekly['weekly_trend'] == 'BULLISH':
                        initial_score = 30
                    result['opportunity_score'] = initial_score
                else:
                    # Haftalık ve 4 saatlik sonuçları birleştir
                    result = weekly.copy()
                    result.update(h4)
                    
                    # Fırsat puanını hesapla (0-100 arası)
                    score = 0
                    
                    # Haftalık trend puanı (0-40)
                    if weekly['weekly_trend'] == 'STRONGLY_BULLISH':
                        score += 40
                    elif weekly['weekly_trend'] == 'BULLISH':
                        score += 30
                    elif weekly['weekly_trend'] == 'NEUTRAL':
                        score += 10
                    
                    # 4 Saatlik trend puanı (0-40)
                    if h4['h4_trend'] == 'STRONGLY_BULLISH':
                        score += 40
                    elif h4['h4_trend'] == 'BULLISH':
                        score += 30
                    elif h4['h4_trend'] == 'NEUTRAL':
                        score += 10
                    
                    # Trend gücü puanı (0-20)
                    trend_strength_score = (weekly['weekly_trend_strength'] * 10 + h4['h4_trend_strength'] * 10)
                    score += trend_strength_score
                    
                    # Puanı 0-100 arasına sınırla
                    result['opportunity_score'] = min(max(score, 0), 100)
                
                combined_results.append(result)
            
            return combined_results
            
        except Exception as e:
            self.logger.error(f"4 saatlik sonuçları birleştirme hatası: {str(e)}")
            return weekly_results  # Hata durumunda haftalık sonuçları döndür


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
            
            # Grafik stilini düzenle
            plt.tight_layout()
            
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
            
            # Grafik başlığı ve trend bilgisi
            ax.set_title(f"{title} ({trend}, Güç: {trend_strength:.2f})", color=trend_color, fontweight='bold')
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


