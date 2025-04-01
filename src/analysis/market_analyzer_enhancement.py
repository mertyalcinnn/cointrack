from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
import mplfinance as mpf
from typing import Dict, Optional

class MarketAnalyzerEnhancement:
    """
    MarketAnalyzer sınıfına eklenecek metodlar
    """
    
    async def generate_enhanced_scalp_chart(self, symbol: str, opportunity: Dict = None) -> BytesIO:
        """
        Gelişmiş scalp grafiği oluşturur.
        
        Bu metod, MarketAnalyzer sınıfına eklenmelidir.
        """
        try:
            # Kline verilerini al
            timeframe = "15m"
            df = await self.data_provider.get_klines(symbol, timeframe, limit=100)
            
            if df.empty:
                self.logger.error(f"Grafik için veri alınamadı: {symbol}")
                return None
            
            # Matplotlib ile grafik oluştur
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={'height_ratios': [3, 1]})
            
            # OHLC grafiği
            mpf.plot(df, type='candle', style='yahoo', ax=ax1)
            
            # Teknik göstergeleri hesapla
            ema9 = df['close'].ewm(span=9, adjust=False).mean()
            ema20 = df['close'].ewm(span=20, adjust=False).mean()
            ema50 = df['close'].ewm(span=50, adjust=False).mean()
            
            # EMA'ları grafik 1'e ekle
            ax1.plot(df.index, ema9, 'blue', linewidth=1, alpha=0.8, label='EMA9')
            ax1.plot(df.index, ema20, 'orange', linewidth=1, alpha=0.8, label='EMA20')
            ax1.plot(df.index, ema50, 'red', linewidth=1, alpha=0.8, label='EMA50')
            
            # Bollinger Bands hesapla
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            bb_middle = typical_price.rolling(window=20).mean()
            bb_std = typical_price.rolling(window=20).std()
            bb_upper = bb_middle + (2 * bb_std)
            bb_lower = bb_middle - (2 * bb_std)
            
            # Bollinger Bands'leri grafik 1'e ekle
            ax1.plot(df.index, bb_upper, 'g--', linewidth=1, alpha=0.5, label='BB Upper')
            ax1.plot(df.index, bb_middle, 'g-', linewidth=1, alpha=0.5, label='BB Middle')
            ax1.plot(df.index, bb_lower, 'g--', linewidth=1, alpha=0.5, label='BB Lower')
            
            # RSI hesapla
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            # RSI grafiği
            ax2.plot(df.index, rsi, 'purple', linewidth=1.5)
            ax2.axhline(y=70, color='r', linestyle='-', alpha=0.3)
            ax2.axhline(y=30, color='g', linestyle='-', alpha=0.3)
            ax2.axhline(y=50, color='b', linestyle='--', alpha=0.2)
            ax2.fill_between(df.index, rsi, 70, where=(rsi >= 70), color='r', alpha=0.3)
            ax2.fill_between(df.index, rsi, 30, where=(rsi <= 30), color='g', alpha=0.3)
            ax2.set_ylim(0, 100)
            ax2.set_ylabel('RSI')
            
            # Eğer opportunity verisi varsa, sinyal ve giriş/çıkış noktalarını ekle
            if opportunity and isinstance(opportunity, dict):
                signal = opportunity.get('signal', '')
                
                # Trend ve sinyal tipleri için renkler
                signal_color = 'green' if 'LONG' in signal else 'red' if 'SHORT' in signal else 'gray'
                
                # Son fiyat işaretle
                last_price = df['close'].iloc[-1]
                ax1.axhline(y=last_price, color='black', linestyle='-', alpha=0.5, label='Current Price')
                
                # Stop Loss ve Take Profit çizgileri ekle
                stop_price = opportunity.get('stop_price')
                target_price = opportunity.get('target_price')
                
                if stop_price:
                    ax1.axhline(y=stop_price, color='red', linestyle='--', alpha=0.7, label='Stop Loss')
                
                if target_price:
                    ax1.axhline(y=target_price, color='green', linestyle='--', alpha=0.7, label='Take Profit')
                
                # R/R oranını hesapla
                risk_reward = opportunity.get('risk_reward', 0)
                
                # Grafik başlığı
                ax1.set_title(f"{symbol} - 15m Scalp Analizi | {signal} (R/R: {risk_reward:.2f})", 
                            color=signal_color, fontweight='bold', fontsize=14)
            else:
                # Basit başlık
                ax1.set_title(f"{symbol} - 15m Scalp Analizi", fontweight='bold', fontsize=14)
            
            # Göstergeleri göster
            ax1.legend(loc='upper left')
            
            # Grafik etiketleri
            ax1.set_ylabel('Fiyat (USD)')
            ax2.set_xlabel('Tarih')
            
            # Y ekseni fiyat formatı
            ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.2f}"))
            
            # Tarih formatı düzenle
            date_format = mdates.DateFormatter('%d-%m %H:%M')
            ax1.xaxis.set_major_formatter(date_format)
            ax2.xaxis.set_major_formatter(date_format)
            
            plt.xticks(rotation=45)
            
            # Grafik düzenini ayarla
            plt.tight_layout()
            
            # BytesIO nesnesine kaydet
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close(fig)
            
            return buf
            
        except Exception as e:
            self.logger.error(f"Gelişmiş scalp grafik oluşturma hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            # Hata durumunda None döndür
            return None
