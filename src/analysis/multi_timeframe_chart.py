async def generate_multi_timeframe_chart(self, symbol: str) -> BytesIO:
    """Çoklu zaman dilimi grafiği oluştur"""
    try:
        # Üç farklı zaman dilimi için veri al
        weekly_data = await self.get_klines(symbol, "1w", limit=20)
        hourly_data = await self.get_klines(symbol, "1h", limit=48)
        m15_data = await self.get_klines(symbol, "15m", limit=96)
        
        if weekly_data.empty or hourly_data.empty or m15_data.empty:
            self.logger.error(f"Grafik için veri alınamadı: {symbol}")
            return None
        
        # Grafikleri oluştur (matplotlib kullanarak)
        fig, axs = plt.subplots(3, 1, figsize=(12, 18), gridspec_kw={'height_ratios': [3, 2, 2]})
        
        # Her zaman dilimi için ayrı grafik
        self._plot_timeframe(axs[0], weekly_data, symbol, "1W - Ana Trend")
        self._plot_timeframe(axs[1], hourly_data, symbol, "1H - Günlük Hareketler")
        self._plot_timeframe(axs[2], m15_data, symbol, "15M - Giriş/Çıkış Noktaları")
        
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
