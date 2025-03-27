            # Trend gücü: Mutlat değerin 0-1 arasında normalizasyonu
            trend_strength = min(abs(weighted_score), 1)
            
            # En önemli 3 trend faktörünü seç
            indicators["trend_messages"] = trend_messages[:3]
            
            return final_trend, trend_strength
        
        except Exception as e:
            self.logger.error(f"Trend analizi hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return "NEUTRAL", 0


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
                    
                    # Sinyal belirleme - sadece weekly trend'e göre
                    weekly_trend = prelim.get('weekly_trend', 'NEUTRAL')
                    if weekly_trend in ['STRONGLY_BULLISH', 'BULLISH']:
                        result['signal'] = "🟩 LONG"
                    elif weekly_trend in ['STRONGLY_BEARISH', 'BEARISH']:
                        result['signal'] = "🔴 SHORT"
                    else:
                        result['signal'] = "⚪ BEKLE"
                        
                    result['15m_trend'] = 'UNKNOWN'
                    result['15m_trend_strength'] = 0
                    result['current_price'] = prelim.get('hourly_price', prelim.get('h4_price', prelim.get('weekly_price', 0)))
                    result['stop_price'] = 0
                    result['target_price'] = 0
                    result['risk_reward'] = 0
                else:
                    # Tüm sonuçları birleştir
                    result = prelim.copy()
                    result.update(m15)
                    
                    # LONG/SHORT yönünü belirle
                    weekly_trend = prelim.get('weekly_trend', 'NEUTRAL')
                    if weekly_trend in ['STRONGLY_BULLISH', 'BULLISH']:
                        result['trade_direction'] = "LONG"
                    elif weekly_trend in ['STRONGLY_BEARISH', 'BEARISH']:
                        result['trade_direction'] = "SHORT"
                    else:
                        result['trade_direction'] = "NEUTRAL"
                    
                    # Sinyal değerini otomatik belirle (trade_direction ve 15m trend'e göre)
                    trade_direction = result.get('trade_direction', 'NEUTRAL')
                    m15_trend = result.get('15m_trend', 'NEUTRAL')
                    
                    if trade_direction == "LONG" and m15_trend in ['BULLISH', 'STRONGLY_BULLISH', 'NEUTRAL']:
                        result['signal'] = "🟩 LONG"
                    elif trade_direction == "SHORT" and m15_trend in ['BEARISH', 'STRONGLY_BEARISH', 'NEUTRAL']:
                        result['signal'] = "🔴 SHORT"
                    else:
                        result['signal'] = "⚪ BEKLE"
                    
                    # Fırsat puanını güncelle (15dk analizine göre)
                    score = result.get('opportunity_score', 0)
                    
                    # 15dk trend puanı (0-20)
                    if trade_direction == "LONG":
                        # LONG fırsatları için
                        if m15_trend == 'STRONGLY_BULLISH':
                            score += 20
                        elif m15_trend == 'BULLISH':
                            score += 15
                        elif m15_trend == 'NEUTRAL':
                            score += 5
                        elif m15_trend == 'BEARISH':
                            score -= 10
                        elif m15_trend == 'STRONGLY_BEARISH':
                            score -= 20
                    else:
                        # SHORT fırsatları için
                        if m15_trend == 'STRONGLY_BEARISH':
                            score += 20
                        elif m15_trend == 'BEARISH':
                            score += 15
                        elif m15_trend == 'NEUTRAL':
                            score += 5
                        elif m15_trend == 'BULLISH':
                            score -= 10
                        elif m15_trend == 'STRONGLY_BULLISH':
                            score -= 20
                    
                    # Risk/Ödül oranına göre bonus
                    risk_reward = m15.get('risk_reward', 0)
                    if risk_reward >= 3:  # 3:1 veya daha iyi ise
                        score += 10
                    elif risk_reward >= 2:  # 2:1 veya daha iyi ise
                        score += 5
                    
                    # Sinyal BEKLE ise puanı düşür
                    if result['signal'] == "⚪ BEKLE":
                        score = max(0, score - 20)  # 20 puan düşür ama negatife düşürme
                    
                    # Puanı 0-100 arasına sınırla
                    result['opportunity_score'] = min(max(score, 0), 100)
                
                # Sonuçları ekle, hiç filtreleme yapma
                final_results.append(result)
            
            return final_results
            
        except Exception as e:
            self.logger.error(f"Final sonuçları birleştirme hatası: {str(e)}")
            return preliminary_results  # Hata durumunda ön sonuçları döndür
