from telegram import Update
from telegram.ext import ContextTypes

class TrackHandler:
    def __init__(self, logger):
        self.logger = logger
        self.last_opportunities = {}  # {chat_id: opportunities}

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Track komutunu işle"""
        try:
            chat_id = update.effective_chat.id
            self.logger.debug(f"Track komutu çalıştı. Chat ID: {chat_id}")
            self.logger.debug(f"Mevcut fırsatlar: {self.last_opportunities.get(chat_id, [])}")
            
            if not context.args:
                await update.message.reply_text(
                    "❌ Coin numarası veya sembolü belirtilmedi!\n"
                    "Kullanım:\n"
                    "/track <numara> veya /track <sembol>\n"
                    "Örnek: /track 1 veya /track BTCUSDT"
                )
                return
                
            arg = context.args[0].upper()
            opportunities = self.last_opportunities.get(chat_id, [])
            
            if not opportunities:
                await update.message.reply_text(
                    "❌ Önce /scan komutu ile tarama yapmalısınız!\n"
                    "1. /scan yazarak tarama yapın\n"
                    "2. Sonra /track <numara> ile coin seçin"
                )
                return
            
            # Numara ile arama
            if arg.isdigit():
                index = int(arg) - 1
                if 0 <= index < len(opportunities):
                    coin = opportunities[index]
                    self.logger.debug(f"Coin bulundu (numara): {coin['symbol']}")
                else:
                    await update.message.reply_text(
                        f"❌ Geçersiz coin numarası! (1-{len(opportunities)})"
                    )
                    return
            # Sembol ile arama
            else:
                coin = next(
                    (opp for opp in opportunities if opp['symbol'] == arg),
                    None
                )
                if coin:
                    self.logger.debug(f"Coin bulundu (sembol): {coin['symbol']}")
                else:
                    await update.message.reply_text(
                        f"❌ {arg} son taramada bulunamadı!\n"
                        "Lütfen /scan ile yeni tarama yapın."
                    )
                    return
            
            # Coin detaylarını gönder
            message = (
                f"🎯 {coin['symbol']} Detaylı Analiz\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💰 Fiyat: ${coin['price']:.4f}\n"
                f"📊 RSI: {coin['rsi']:.1f}\n"
                f"📈 Trend (Kısa/Ana): {coin['short_trend']}/{coin['main_trend']}\n"
                f"⚡ Hacim Artışı: {'✅' if coin['volume_surge'] else '❌'}\n\n"
                f"🎯 POZİSYON: {coin['position']}\n"
                f"🛑 Stop Loss: ${coin['stop_loss']:.4f}\n"
                f"✨ Take Profit: ${coin['take_profit']:.4f}\n"
                f"⚖️ Risk/Ödül: {coin['risk_reward']}\n"
                f"⭐ Puan: {coin['opportunity_score']:.1f}/100\n\n"
                f"📊 PUAN DETAYI:\n"
                f"• Trend: {coin['score_details']['trend']}/30\n"
                f"• RSI: {coin['score_details']['rsi']}/25\n"
                f"• MACD: {coin['score_details']['macd']}/25\n"
                f"• Hacim: {coin['score_details']['volume']}/20\n"
                f"━━━━━━━━━━━━━━━━"
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            self.logger.error(f"Track komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Hata oluştu! Lütfen tekrar deneyin."
            )

    def update_opportunities(self, chat_id: int, opportunities: list):
        """Son fırsatları güncelle"""
        self.logger.debug(f"Fırsatlar güncelleniyor. Chat ID: {chat_id}, Fırsat sayısı: {len(opportunities)}")
        self.last_opportunities[chat_id] = opportunities.copy()  # copy() ekledik
        self.logger.debug(f"Fırsatlar güncellendi. Mevcut fırsatlar: {len(self.last_opportunities[chat_id])}") 