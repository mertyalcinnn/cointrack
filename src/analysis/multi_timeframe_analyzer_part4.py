    def calculate_stop_and_target(self, df: pd.DataFrame, trend: str, current_price: float) -> Tuple[float, float]:
        """Stop-loss ve hedef fiyatları hesapla"""
        try:
            # Son 20 mumun yüksek/düşük değerlerini al
            recent_high = df['high'][-20:].max()
            recent_low = df['low'][-20:].min()
            
            # ATR (Average True Range) hesapla - volatilite ölçüsü
            high_low = df['high'] - df['low']
            high_close = (df['high'] - df['close'].shift()).abs()
            low_close = (df['low'] - df['close'].shift()).abs()
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = true_range.rolling(window=14).mean().iloc[-1]
            
            # Trend bazlı stop-loss ve hedef hesapla
            if trend in ["BULLISH", "STRONGLY_BULLISH"]:
                # LONG pozisyon
                stop_loss = current_price - (atr * 2)  # 2 ATR altında stop
                take_profit = current_price + (atr * 4)  # 4 ATR üstünde hedef (2:1 oran)
                
                # Ek olarak, son düşük değer stop olarak kullanılabilir
                alt_stop = recent_low
                # Hangisi daha yakınsa onu kullan, ama çok uzakta değilse
                if alt_stop > current_price - (atr * 3) and alt_stop < current_price:
                    stop_loss = alt_stop
                
            elif trend in ["BEARISH", "STRONGLY_BEARISH"]:
                # SHORT pozisyon
                stop_loss = current_price + (atr * 2)  # 2 ATR üstünde stop
                take_profit = current_price - (atr * 4)  # 4 ATR altında hedef (2:1 oran)
                
                # Ek olarak, son yüksek değer stop olarak kullanılabilir
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
