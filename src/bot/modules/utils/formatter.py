class MessageFormatter:
    @staticmethod
    def format_opportunities(opportunities: list, interval: str) -> list:
        """Fırsatları mesaj formatına çevir"""
        messages = []
        current_message = f"🎯 EN İYİ 10 FIRSAT ({interval})\n\n"
        
        for i, opp in enumerate(opportunities, 1):
            message_part = (
                f"#{i} {opp['signal']} {opp['symbol']}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💰 Fiyat: ${opp['price']:.4f}\n"
                f"📊 RSI: {opp['rsi']:.1f}\n"
                f"📈 Trend (Kısa/Ana): {opp['short_trend']}/{opp['main_trend']}\n"
                f"⚡ Hacim Artışı: {'✅' if opp['volume_surge'] else '❌'}\n\n"
                f"🎯 POZİSYON: {opp['position']}\n"
                f"🛑 Stop Loss: ${opp['stop_loss']:.4f}\n"
                f"✨ Take Profit: ${opp['take_profit']:.4f}\n"
                f"⚖️ Risk/Ödül: {opp['risk_reward']}\n"
                f"⭐ Puan: {opp['opportunity_score']:.1f}/100\n"
                f"━━━━━━━━━━━━━━━━\n\n"
            )
            
            if i % 3 == 0:  # Her 3 coinde bir mesaj gönder
                current_message += message_part
                messages.append(current_message)
                current_message = f"🎯 EN İYİ 10 FIRSAT ({interval}) - devam\n\n"
            else:
                current_message += message_part
                
        if current_message != f"🎯 EN İYİ 10 FIRSAT ({interval}) - devam\n\n":
            messages.append(current_message)
            
        return messages 