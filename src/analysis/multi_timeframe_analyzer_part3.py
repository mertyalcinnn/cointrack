    def analyze_trend(self, df: pd.DataFrame, indicators: Dict) -> Tuple[str, float]:
        """Trend analizini yap ve trend gücünü hesapla"""
        try:
            # RSI bazlı trend
            rsi = indicators["rsi"]
            rsi_trend = "BULLISH" if rsi > 55 else "BEARISH" if rsi < 45 else "NEUTRAL"
            
            # MACD bazlı trend
            macd = indicators["macd"]
            macd_signal = indicators["macd_signal"]
            macd_hist = indicators["macd_hist"]
            macd_trend = "BULLISH" if macd > macd_signal else "BEARISH" if macd < macd_signal else "NEUTRAL"
            
            # EMA bazlı trend - kısa, orta ve uzun vadeli EMAlara bakarak trend belirle
            emas = indicators["emas"]
            close = df['close'].iloc[-1]
            
            ema_short = emas.get("ema9", 0)
            ema_mid = emas.get("ema20", 0)
            ema_long = emas.get("ema50", 0)
            
            ema_trend = "NEUTRAL"
            if ema_short > ema_mid > ema_long and close > ema_short:
                ema_trend = "STRONGLY_BULLISH"
            elif ema_short > ema_mid and close > ema_short:
                ema_trend = "BULLISH"
            elif ema_short < ema_mid < ema_long and close < ema_short:
                ema_trend = "STRONGLY_BEARISH"
            elif ema_short < ema_mid and close < ema_short:
                ema_trend = "BEARISH"
            
            # Bollinger Bands bazlı trend
            bb_position = indicators["bb_position"]
            bb_trend = "NEUTRAL"
            if bb_position > 80:
                bb_trend = "BEARISH"  # Fiyat üst banda yakın, aşırı alım
            elif bb_position < 20:
                bb_trend = "BULLISH"  # Fiyat alt banda yakın, aşırı satım
            
            # Stochastic bazlı trend
            stoch_k = indicators["stoch_k"]
            stoch_d = indicators["stoch_d"]
            stoch_trend = "NEUTRAL"
            if stoch_k > 80 and stoch_d > 80:
                stoch_trend = "BEARISH"  # Aşırı alım
            elif stoch_k < 20 and stoch_d < 20:
                stoch_trend = "BULLISH"  # Aşırı satım
            
            # Fiyat değişimi bazlı trend
            price_change = ((df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]) * 100
            price_trend = "BULLISH" if price_change > 2 else "BEARISH" if price_change < -2 else "NEUTRAL"
            
            # Hacim değişimi bazlı trend
            volume_change = indicators["volume_change"]
            volume_trend = "BULLISH" if volume_change > self.volume_increase_threshold else "NEUTRAL"
            
            # Tüm trendleri bir araya getir ve ağırlıklı puanlama yap
            trend_scores = {
                "STRONGLY_BULLISH": 2,
                "BULLISH": 1,
                "NEUTRAL": 0,
                "BEARISH": -1,
                "STRONGLY_BEARISH": -2
            }
            
            # Her gösterge için ağırlıklar
            weights = {
                "ema": 0.35,     # En güvenilir gösterge - uzun vadeli trend
                "rsi": 0.15,     # Momentum göstergesi
                "macd": 0.20,    # Momentum ve trend göstergesi
                "bb": 0.10,      # Volatilite göstergesi
                "stoch": 0.10,   # Momentum göstergesi
                "price": 0.05,   # Fiyat değişimi
                "volume": 0.05   # Hacim desteği
            }
            
            # String trend değerlerini sayısal skorlara dönüştür
            ema_score = trend_scores.get(ema_trend, 0)
            rsi_score = trend_scores.get(rsi_trend, 0)
            macd_score = trend_scores.get(macd_trend, 0)
            bb_score = trend_scores.get(bb_trend, 0)
            stoch_score = trend_scores.get(stoch_trend, 0)
            price_score = trend_scores.get(price_trend, 0)
            volume_score = trend_scores.get(volume_trend, 0)
            
            # Ağırlıklı toplam skoru hesapla (-2 ile +2 arasında)
            weighted_score = (
                (ema_score * weights["ema"]) +
                (rsi_score * weights["rsi"]) +
                (macd_score * weights["macd"]) +
                (bb_score * weights["bb"]) +
                (stoch_score * weights["stoch"]) +
                (price_score * weights["price"]) +
                (volume_score * weights["volume"])
            )
            
            # Skoru trende dönüştür
            final_trend = "NEUTRAL"
            if weighted_score >= 1.0:
                final_trend = "STRONGLY_BULLISH"
            elif weighted_score >= 0.3:
                final_trend = "BULLISH"
            elif weighted_score <= -1.0:
                final_trend = "STRONGLY_BEARISH"
            elif weighted_score <= -0.3:
                final_trend = "BEARISH"
            
            # Trend gücü: Mutlak değerin 0-1 arasında normalizasyonu
            trend_strength = min(abs(weighted_score), 2) / 2
            
            return final_trend, trend_strength
            
        except Exception as e:
            self.logger.error(f"Trend analiz hatası: {str(e)}")
            return "NEUTRAL", 0
