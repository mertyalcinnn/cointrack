from typing import List, Dict

def _format_scalp_opportunities(self, opportunities: List[Dict]) -> str:
    """Hata ayıklamalı scalp fırsatları mesaj formatı"""
    try:
        # Debug: Fırsat listesinin varlığını kontrol et
        if not opportunities:
            self.logger.warning("Boş fırsat listesi _format_scalp_opportunities'e gönderildi")
            return "❌ İşlem fırsatı bulunamadı!"
            
        # Debug: İlk fırsatın yapısını logla
        self.logger.info(f"Fırsat yapısı örnekleme: {list(opportunities[0].keys())}")
        
        message = "🔥 **KISA VADELİ İŞLEM FIRSATLARI** 🔥\n\n"
        message += "Bu analiz 15 dakikalık grafik verilerini kullanır.\n"
        message += "Her fırsat 5-10$ kar potansiyeli için optimize edilmiştir.\n\n"
        
        message += "📊 **FIRSATLAR:**\n\n"
        
        for i, opp in enumerate(opportunities[:5], 1):
            # Her bir anahtarı ayrı ayrı güvenli bir şekilde al
            symbol = opp.get('symbol', f'COIN-{i}')
            
            # Debug: Signal için özel kontrol
            if 'signal' not in opp:
                self.logger.warning(f"Fırsat {i}: 'signal' anahtarı eksik")
                
            signal = opp.get('signal', '⚪ BEKLE')
            
            # Debug: current_price için özel kontrol 
            if 'current_price' not in opp:
                self.logger.warning(f"Fırsat {i}: 'current_price' anahtarı eksik")
                # Alternatif değerleri kontrol et
                if 'price' in opp:
                    self.logger.info(f"Fırsat {i}: 'price' anahtarı bulundu, bu kullanılacak")
                    price = opp['price']
                else:
                    self.logger.info(f"Fırsat {i}: Varsayılan fiyat kullanılacak")
                    price = 0
            else:
                price = opp['current_price']
                
            # Puanlama bilgisi
            score = opp.get('opportunity_score', opp.get('score', 0))
            
            # Stop ve hedef fiyatlar
            stop_price = opp.get('stop_price', opp.get('stop', price * 0.95))
            target_price = opp.get('target_price', opp.get('target', price * 1.05))
            
            # Risk/Ödül hesapla
            risk = abs(price - stop_price) or 1  # 0 bölme hatasından kaçın
            reward = abs(target_price - price) or 1
            risk_reward = reward / risk
            
            # Güvenli formatlama
            try:
                price_str = f"${price:.6f}" if isinstance(price, (int, float)) else str(price)
                stop_str = f"${stop_price:.6f}" if isinstance(stop_price, (int, float)) else str(stop_price)
                target_str = f"${target_price:.6f}" if isinstance(target_price, (int, float)) else str(target_price)
                rr_str = f"{risk_reward:.2f}" if isinstance(risk_reward, (int, float)) else str(risk_reward)
                score_str = f"{score:.1f}/100" if isinstance(score, (int, float)) else str(score)
            except Exception as format_err:
                self.logger.error(f"Formatlama hatası: {format_err}")
                price_str = str(price)
                stop_str = str(stop_price)
                target_str = str(target_price)
                rr_str = str(risk_reward)
                score_str = str(score)
            
            message += (
                f"{i}. {symbol} - {signal}\n"
                f"   💰 Fiyat: {price_str}\n"
                f"   🛑 Stop: {stop_str}\n"
                f"   🎯 Hedef: {target_str}\n"
                f"   ⚖️ R/R: {rr_str}\n"
                f"   ⭐ Puan: {score_str}\n\n"
            )
        
        message += (
            "📝 **KULLANIM:**\n"
            "• Belirli bir coin hakkında daha detaylı bilgi için:\n"
            "  `/scalp BTCUSDT`\n\n"
            "⚠️ **RİSK UYARISI:**\n"
            "• Bu sinyaller 15m grafik analizine dayanır\n"
            "• Kısa vadeli işlemlerde her zaman stop-loss kullanın\n"
            "• Yatırımınızın %1-2'sinden fazlasını riske atmayın\n"
        )
        
        return message
            
    except Exception as e:
        self.logger.error(f"Scalp fırsatları formatlama hatası: {str(e)}", exc_info=True)
        return "❌ Sonuçlar formatlanırken bir hata oluştu! Lütfen daha sonra tekrar deneyin."
