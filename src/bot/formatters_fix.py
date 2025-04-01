def _format_scalp_opportunities(self, opportunities: List[Dict]) -> str:
    """Scalp fırsatlarını mesaja dönüştür"""
    try:
        message = "🔥 **KISA VADELİ İŞLEM FIRSATLARI** 🔥\n\n"
        message += "Bu analiz 15 dakikalık grafik verilerini kullanır.\n"
        message += "Her fırsat 5-10$ kar potansiyeli için optimize edilmiştir.\n\n"
        
        message += "📊 **FIRSATLAR:**\n\n"
        
        for i, opp in enumerate(opportunities[:5], 1):
            symbol = opp.get('symbol', 'UNKNOWN')
            signal = opp.get('signal', '⚪ BEKLE')
            
            # 'current_price' anahtarı yoksa varsayılan değer kullan
            price = opp.get('current_price', 0)
            score = opp.get('opportunity_score', 0)
            stop_price = opp.get('stop_price', price * 0.95)
            target_price = opp.get('target_price', price * 1.05)
            
            # Risk/Ödül hesapla
            if 'LONG' in signal:
                risk = price - stop_price if price > stop_price else 1
                reward = target_price - price if target_price > price else 1
            else:
                risk = stop_price - price if stop_price > price else 1
                reward = price - target_price if price > target_price else 1
                
            risk_reward = abs(reward / risk) if risk != 0 else 0
            
            message += (
                f"{i}. {symbol} - {signal}\n"
                f"   💰 Fiyat: ${price:.6f}\n"
                f"   🛑 Stop: ${stop_price:.6f}\n"
                f"   🎯 Hedef: ${target_price:.6f}\n"
                f"   ⚖️ R/R: {risk_reward:.2f}\n"
                f"   ⭐ Puan: {score:.1f}/100\n\n"
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
        self.logger.error(f"Scalp fırsatları formatlama hatası: {e}")
        return "❌ Sonuçlar formatlanırken bir hata oluştu!"
