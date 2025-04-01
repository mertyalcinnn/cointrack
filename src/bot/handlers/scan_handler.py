def _format_opportunities(self, opportunities: list, interval: str) -> list:
    """Fırsatları formatla"""
    messages = []
    for opp in opportunities:
        try:
            # ... existing code ...
            
            # Gelişmiş risk yönetimi bilgilerini ekle
            advanced_sl = opp.get('advanced_stoploss')
            take_profit_levels = opp.get('take_profit_levels', [])
            risk_percent = opp.get('risk_percent', 0)
            
            # Gelişmiş risk yönetimi mesajı hazırla
            risk_management_text = ""
            if advanced_sl and take_profit_levels:
                risk_management_text = f"\n\n🛡️ GELİŞMİŞ RİSK YÖNETİMİ:\n"
                risk_management_text += f"• Gelişmiş Stop Loss: ${advanced_sl:.4f} (Risk: %{risk_percent:.2f})\n"
                
                # Take profit seviyeleri
                for i, tp in enumerate(take_profit_levels[:3], 1):
                    tp_percent = abs(tp - opp['price']) / opp['price'] * 100
                    risk_reward = tp_percent / risk_percent if risk_percent > 0 else 0
                    risk_management_text += f"• Take Profit {i}: ${tp:.4f} (Kâr: %{tp_percent:.2f}, R/R: {risk_reward:.1f})\n"
                    
                # Trailing stop bilgisi
                if opp.get('trailing_activation'):
                    risk_management_text += f"• Trailing Aktivasyon: ${opp['trailing_activation']:.4f}\n"
            
            # Ana mesajı güncelle
            message = (
                f"🪙 {symbol}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💵 Fiyat: ${price:.4f}\n"
                f"📊 RSI: {rsi:.1f}\n"
                f"📈 Trend: {trend}\n"
                f"⚡ Hacim: ${volume:,.0f}\n"
                f"📊 Hacim Artışı: {'✅' if volume_surge else '❌'}\n\n"
                f"📊 TEKNİK ANALİZ:\n"
                f"• EMA Trend: {ema_signal} ({ema_cross:.1f}%)\n"
                f"• BB Pozisyon: {bb_signal} ({bb_position:.1f}%)\n"
                f"• MACD: {macd:.4f}\n"
                f"• RSI: {rsi:.1f}\n\n"
                f"🎯 Sinyal: {signal}\n"
                f"🛑 Stop Loss: ${stop_loss:.4f}\n"
                f"✨ Take Profit: ${take_profit:.4f}\n"
                f"⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                f"⭐ Fırsat Puanı: {score:.1f}/100"
                f"{risk_management_text}\n"
                f"━━━━━━━━━━━━━━━━"
            )
            messages.append(message)
        except Exception as format_error:
            self.logger.error(f"Mesaj formatı hatası ({opp.get('symbol', 'Bilinmeyen')}): {format_error}")
            continue
                
    return messages 