    def combine_multi_timeframe_analysis(self, weekly: List[Dict], hourly: List[Dict], minute15: List[Dict]) -> List[Dict]:
        """Üç zaman diliminden gelen analizleri birleştir ve puanla"""
        try:
            combined_results = []
            
            # Haftalık ve saatlik analizleri bir dict'e dönüştür (hızlı arama için)
            weekly_dict = {item["symbol"]: item for item in weekly}
            hourly_dict = {item["symbol"]: item for item in hourly}
            
            # 15 dakikalık analiz sonuçları üzerinden geç
            for m15_item in minute15:
                symbol = m15_item["symbol"]
                
                # Bu sembol için haftalık ve saatlik veriler var mı kontrol et
                if symbol in weekly_dict and symbol in hourly_dict:
                    w_item = weekly_dict[symbol]
                    h_item = hourly_dict[symbol]
                    
                    # Trendleri sayısal değerlere dönüştür
                    trend_map = {
                        "STRONGLY_BULLISH": 2,
                        "BULLISH": 1,
                        "NEUTRAL": 0,
                        "BEARISH": -1,
                        "STRONGLY_BEARISH": -2
                    }
                    
                    weekly_trend_score = trend_map.get(w_item["trend"], 0)
                    hourly_trend_score = trend_map.get(h_item["trend"], 0)
                    m15_trend_score = trend_map.get(m15_item["trend"], 0)
                    
                    # Ağırlıklandırılmış trend puanı
                    # Haftalık (ana trend): %40, Saatlik (orta vadeli): %30, 15dk (kısa vadeli): %30
                    trend_score = (weekly_trend_score * 0.4) + (hourly_trend_score * 0.3) + (m15_trend_score * 0.3)
                    
                    # Sinyal türünü belirle
                    signal = "⚪ BEKLE"
                    if trend_score >= 1.0:
                        signal = "🟩 GÜÇLÜ LONG"
                    elif trend_score >= 0.5:
                        signal = "🟩 LONG"
                    elif trend_score <= -1.0:
                        signal = "🔴 GÜÇLÜ SHORT"
                    elif trend_score <= -0.5:
                        signal = "🔴 SHORT"
                    
                    # Fırsat puanı hesapla (0-100 arası)
                    base_score = abs(trend_score) * 50  # -2 ile +2 arasındaki değeri 0-100 arasına dönüştür
                    
                    # Risk/Ödül oranı puanı (0-30 puan)
                    risk_reward_score = min(m15_item["risk_reward"] * 10, 30)
                    
                    # Hacim puanı (0-20 puan)
                    volume_score = 0
                    volume_change = m15_item["indicators"]["volume_change"]
                    if volume_change > 100:
                        volume_score = 20
                    elif volume_change > 50:
                        volume_score = 15
                    elif volume_change > 20:
                        volume_score = 10
                    elif volume_change > 0:
                        volume_score = 5
                    
                    # Toplam fırsat puanı (max 100)
                    opportunity_score = min(base_score + risk_reward_score + volume_score, 100)
                    
                    # Hangi zaman dilimlerine bakılarak karar verildiğine dair metin bilgisi oluştur
                    trend_descriptions = []
                    # Haftalık trend
                    if w_item["trend"] in ["STRONGLY_BULLISH", "BULLISH"]:
                        trend_descriptions.append("✅ 1W: Yükseliş trendi")
                    elif w_item["trend"] in ["STRONGLY_BEARISH", "BEARISH"]:
                        trend_descriptions.append("❌ 1W: Düşüş trendi")
                    else:
                        trend_descriptions.append("➖ 1W: Nötr")
                        
                    # Saatlik trend
                    if h_item["trend"] in ["STRONGLY_BULLISH", "BULLISH"]:
                        trend_descriptions.append("✅ 1H: Yükseliş trendi")
                    elif h_item["trend"] in ["STRONGLY_BEARISH", "BEARISH"]:
                        trend_descriptions.append("❌ 1H: Düşüş trendi")
                    else:
                        trend_descriptions.append("➖ 1H: Nötr")
                        
                    # 15 dakikalık trend
                    if m15_item["trend"] in ["STRONGLY_BULLISH", "BULLISH"]:
                        trend_descriptions.append("✅ 15M: Yükseliş sinyali")
                    elif m15_item["trend"] in ["STRONGLY_BEARISH", "BEARISH"]:
                        trend_descriptions.append("❌ 15M: Düşüş sinyali")
                    else:
                        trend_descriptions.append("➖ 15M: Nötr")
                    
                    # Sonuçları birleştir
                    combined = {
                        "symbol": symbol,
                        "current_price": m15_item["current_price"],
                        "volume": m15_item["volume"],
                        "signal": signal,
                        "opportunity_score": opportunity_score,
                        "stop_price": m15_item["stop_price"],
                        "target_price": m15_item["target_price"],
                        "timeframes": {
                            "weekly": w_item["trend"],
                            "hourly": h_item["trend"],
                            "minute15": m15_item["trend"]
                        },
                        "trend_score": trend_score,
                        "trend_descriptions": trend_descriptions,
                        "risk_reward": m15_item["risk_reward"],
                        "indicators": {
                            "rsi_w": w_item["indicators"]["rsi"],
                            "rsi_h": h_item["indicators"]["rsi"],
                            "rsi_15m": m15_item["indicators"]["rsi"],
                            "macd_15m": m15_item["indicators"]["macd"],
                            "bb_position_15m": m15_item["indicators"]["bb_position"],
                            "volume_change": m15_item["indicators"]["volume_change"]
                        }
                    }
                    
                    combined_results.append(combined)
            
            # Fırsat puanına göre sırala
            combined_results.sort(key=lambda x: x["opportunity_score"], reverse=True)
            
            return combined_results
            
        except Exception as e:
            self.logger.error(f"Çoklu zaman dilimi birleştirme hatası: {str(e)}")
            return []
