from io import BytesIO
import matplotlib.pyplot as plt
import mplfinance as mpf

async def generate_enhanced_scalp_chart(self, symbol: str, opportunity: Dict = None) -> BytesIO:
    """Gelişmiş scalp grafiği oluştur"""
    try:
        # Eğer zaten normal bir grafik oluşturma metodu varsa onu kullan
        if hasattr(self, 'generate_chart'):
            return await self.generate_chart(symbol, "15m")
            
        # Yoksa temel bir grafik oluştur
        # Kline verilerini al
        timeframe = "15m"
        df = await self.data_provider.get_klines(symbol, timeframe, limit=100)
        
        if df.empty:
            self.logger.error(f"Grafik için veri alınamadı: {symbol}")
            return None
        
        # Matplotlib ile basit bir grafik oluştur
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # OHLC grafiği
        mpf.plot(df, type='candle', style='yahoo', ax=ax)
        
        # EMA'ları ekle
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema20 = df['close'].ewm(span=20, adjust=False).mean()
        ema50 = df['close'].ewm(span=50, adjust=False).mean()
        
        ax.plot(df.index, ema9, 'blue', linewidth=1, alpha=0.8, label='EMA9')
        ax.plot(df.index, ema20, 'orange', linewidth=1, alpha=0.8, label='EMA20')
        ax.plot(df.index, ema50, 'red', linewidth=1, alpha=0.8, label='EMA50')
        
        # Grafik başlığı
        ax.set_title(f"{symbol} - 15m Grafiği", fontweight='bold')
        ax.legend(loc='upper left')
        
        # Y ekseni fiyat formatı
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:.2f}"))
        
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
        return None
