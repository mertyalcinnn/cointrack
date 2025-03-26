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
    
    async def scan_market(self, symbols: List[str] = None) -> List[Dict]:
        """
        Üç zaman dilimini kullanarak piyasayı tara
        1. Haftalık grafik analizi (ana trend)
        2. Sadece olumlu haftalık trende sahip coinler için saatlik analiz
        3. Olumlu haftalık ve saatlik trende sahip coinler için 15dk analizi
        """
        try:
            # Semboller belirtilmemişse, popüler semboller veya desteklenen tüm sembolleri kullan
            if not symbols:
                popular_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", 
                                  "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT",
                                  "MATICUSDT", "SANDUSDT", "VETUSDT", "SHIBUSDT", "LTCUSDT"]
                symbols = popular_symbols
            
            self.logger.info(f"Çoklu zaman dilimi analizi başlatılıyor. {len(symbols)} sembol taranacak.")
            
            # 1. Haftalık grafik analizi (ana trend)
            self.logger.info("1. Adım: Haftalık grafik analizi")
            weekly_analysis = await self.analyze_timeframe(symbols, "1w")
            
            if self.demo_mode:
                # Demo modda adım adım ilerlemek için tüm sembolleri kullan
                positive_weekly_symbols = symbols
            else:
                # 2. Sadece olumlu haftalık trende sahip coinler için saatlik analiz
                positive_weekly_symbols = [item["symbol"] for item in weekly_analysis 
                                         if item["trend"] in ["BULLISH", "STRONGLY_BULLISH"]]
            
            self.logger.info(f"Haftalık analiz tamamlandı. {len(positive_weekly_symbols)} olumlu trend bulundu.")
            
            # Saatlik analiz
            self.logger.info("2. Adım: Saatlik grafik analizi")
            hourly_analysis = await self.analyze_timeframe(positive_weekly_symbols, "1h")
            
            if self.demo_mode:
                # Demo modda adım adım ilerlemek için tüm sembolleri kullan
                positive_hourly_symbols = positive_weekly_symbols
            else:
                # 3. Olumlu haftalık ve saatlik trende sahip coinler için 15dk analizi
                positive_hourly_symbols = [item["symbol"] for item in hourly_analysis 
                                         if item["trend"] in ["BULLISH", "STRONGLY_BULLISH"]]
            
            self.logger.info(f"Saatlik analiz tamamlandı. {len(positive_hourly_symbols)} olumlu trend bulundu.")
            
            # 15 dakikalık analiz
            self.logger.info("3. Adım: 15 dakikalık grafik analizi")
            minute15_analysis = await self.analyze_timeframe(positive_hourly_symbols, "15m")
            
            self.logger.info("4. Adım: Sonuçları birleştirme")
            # 4. Tüm sonuçları birleştir ve puanla
            final_opportunities = self.combine_multi_timeframe_analysis(
                weekly_analysis, hourly_analysis, minute15_analysis
            )
            
            self.logger.info(f"Çoklu zaman dilimi analizi tamamlandı. {len(final_opportunities)} fırsat bulundu.")
            
            return final_opportunities
        
        except Exception as e:
            self.logger.error(f"Market tarama hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
