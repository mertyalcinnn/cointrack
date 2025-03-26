    async def analyze_timeframe(self, symbols: List[str], timeframe: str) -> List[Dict]:
        """Belirli bir zaman dilimi için sembolleri analiz et"""
        analysis_results = []
        
        # Her sembol için analiz yap
        for symbol in symbols:
            try:
                # Kline verilerini al
                df = await self.get_klines(symbol, timeframe, limit=100)
                
                if df.empty:
                    continue
                
                # Ticker verilerini al
                ticker = await self.get_ticker(symbol)
                
                if not ticker:
                    continue
                
                # Temel fiyat bilgileri
                current_price = ticker.get('last', df['close'].iloc[-1])
                volume = ticker.get('quoteVolume', df['volume'].sum())
                
                # Teknik göstergeleri hesapla
                indicators = self.calculate_indicators(df)
                
                # Trend analizini yap
                trend, trend_strength = self.analyze_trend(df, indicators)
                
                # Stop-loss ve hedef fiyatları belirle
                stop_loss, take_profit = self.calculate_stop_and_target(df, trend, current_price)
                
                # Risk/Ödül oranını hesapla
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
