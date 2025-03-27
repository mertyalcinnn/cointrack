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
                    elif weekly['weekly_trend'] == 'STRONGLY_BEARISH':
                        initial_score = 40
                    elif weekly['weekly_trend'] == 'BEARISH':
                        initial_score = 30
                    result['opportunity_score'] = initial_score
                else:
                    # Haftalık ve 4 saatlik sonuçları birleştir
                    result = weekly.copy()
                    result.update(h4)
                    
                    # Fırsat puanını hesapla (0-100 arası)
                    score = 0
                    
                    # Haftalık trend puanı (0-40)
                    weekly_trend = weekly['weekly_trend']
                    if weekly_trend == 'STRONGLY_BULLISH' or weekly_trend == 'STRONGLY_BEARISH':
                        score += 40
                    elif weekly_trend == 'BULLISH' or weekly_trend == 'BEARISH':
                        score += 30
                    elif weekly_trend == 'NEUTRAL':
                        score += 10
                    
                    # 4 Saatlik trend puanı (0-40) - trend yönüne uyumlu ise
                    h4_trend = h4['h4_trend']
                    
                    # LONG için
                    if weekly_trend in ['BULLISH', 'STRONGLY_BULLISH']:
                        if h4_trend == 'STRONGLY_BULLISH':
                            score += 40
                        elif h4_trend == 'BULLISH':
                            score += 30
                        elif h4_trend == 'NEUTRAL':
                            score += 10
                    # SHORT için
                    elif weekly_trend in ['BEARISH', 'STRONGLY_BEARISH']:
                        if h4_trend == 'STRONGLY_BEARISH':
                            score += 40
                        elif h4_trend == 'BEARISH':
                            score += 30
                        elif h4_trend == 'NEUTRAL':
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
                self.data_cache.set(cache_key, binance_format_symbols)
                
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
