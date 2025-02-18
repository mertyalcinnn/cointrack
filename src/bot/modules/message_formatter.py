class MessageFormatter:
    @staticmethod
    def format_opportunities(opportunities: list, interval: str) -> list:
        """Fırsatları mesaj formatına çevir"""
        messages = []
        current_message = f"🎯 EN İYİ 10 FIRSAT ({interval})\n\n"
        
        for i, opp in enumerate(opportunities, 1):
            message_part = (
                f"#{i} {opp['signal']} {opp['symbol']}\n"
                f"💰 Fiyat: ${opp['price']:.4f}\n"
                f"📊 RSI: {opp['rsi']:.1f}\n"
                f"📈 Trend: {opp['trend']}\n"
                f"⭐ Puan: {opp['opportunity_score']:.1f}/100\n"
                f"━━━━━━━━━━━━━━━━\n\n"
            )
            
            if i % 5 == 0:
                current_message += message_part
                messages.append(current_message)
                current_message = f"🎯 EN İYİ 10 FIRSAT ({interval}) - devam\n\n"
            else:
                current_message += message_part
                
        if current_message != f"🎯 EN İYİ 10 FIRSAT ({interval}) - devam\n\n":
            messages.append(current_message)
            
        return messages 