from telegram import Update
from telegram.ext import ContextTypes
from ..analysis.market import MarketAnalyzer
from datetime import datetime

class TrackHandler:
    def __init__(self, logger):
        self.logger = logger
        self.last_opportunities = {}  # {chat_id: opportunities}
        self.analyzer = MarketAnalyzer(logger)
        self.tracked_coins = {}  # {chat_id: {symbol: {'last_update': datetime}}}

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Track komutunu işle"""
        try:
            chat_id = update.effective_chat.id
            self.logger.debug(f"Track komutu çalıştı. Chat ID: {chat_id}")
            
            # Komut argümanlarını kontrol et
            if not context.args:
                await update.message.reply_text(
                    "❌ Kullanım:\n"
                    "1️⃣ Tarama sonrası takip:\n"
                    "   /track <numara>\n"
                    "   Örnek: /track 1\n\n"
                    "2️⃣ Direkt coin takibi:\n"
                    "   /track <sembol>\n"
                    "   Örnek: /track BTCUSDT"
                )
                return

            for arg in context.args:
                arg = arg.upper()
                
                # Numara ile takip (scan sonrası)
                if arg.isdigit():
                    await self._handle_scan_tracking(update, arg, chat_id)
                # Sembol ile direkt takip
                else:
                    await self._handle_direct_tracking(update, arg, chat_id)

        except Exception as e:
            self.logger.error(f"Track komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Hata oluştu! Lütfen tekrar deneyin."
            )

    async def _handle_scan_tracking(self, update, number: str, chat_id: int):
        """Scan sonrası coin takibi"""
        opportunities = self.last_opportunities.get(chat_id, [])
        
        if not opportunities:
            await update.message.reply_text(
                "❌ Önce /scan komutu ile tarama yapmalısınız!\n"
                "1. /scan yazarak tarama yapın\n"
                "2. Sonra /track <numara> ile coin seçin"
            )
            return
            
        index = int(number) - 1
        if 0 <= index < len(opportunities):
            coin = opportunities[index]
            await self._add_to_tracking(update, coin, chat_id)
        else:
            await update.message.reply_text(
                f"❌ Geçersiz coin numarası: {number}\n"
                f"Lütfen 1-{len(opportunities)} arası bir numara girin."
            )

    async def _handle_direct_tracking(self, update, symbol: str, chat_id: int):
        """Direkt coin takibi"""
        try:
            # Sembol formatını kontrol et
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
            
            # Coin analizi yap
            analysis = await self.analyzer.analyze_single_coin(symbol)
            
            if analysis:
                await self._add_to_tracking(update, analysis, chat_id)
            else:
                await update.message.reply_text(f"❌ {symbol} analiz edilemedi veya bulunamadı.")
                
        except Exception as e:
            await update.message.reply_text(f"❌ {symbol} takip edilemedi: {str(e)}")

    async def _add_to_tracking(self, update, coin: dict, chat_id: int):
        """Coini takip listesine ekle"""
        symbol = coin['symbol']
        
        if chat_id not in self.tracked_coins:
            self.tracked_coins[chat_id] = {}
            
        self.tracked_coins[chat_id][symbol] = {
            'last_update': datetime.now(),
            'data': coin
        }
        
        message = (
            f"✅ {symbol} takibe alındı!\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 Fiyat: ${coin['price']:.4f}\n"
            f"📊 RSI: {coin['rsi']:.1f}\n"
            f"📈 Trend: {coin.get('trend', 'N/A')}\n"
            f"⚡ Hacim Artışı: {'✅' if coin.get('volume_surge', False) else '❌'}\n\n"
            f"🎯 Sinyal: {coin.get('signal', 'N/A')}\n"
            f"⭐ Fırsat Puanı: {coin['opportunity_score']:.1f}/100\n\n"
            f"📊 TEKNİK ANALİZ:\n"
            f"• RSI: {coin.get('rsi', 0):.1f}\n"
            f"• MACD: {coin.get('macd', 0):.4f}\n"
            f"• Hacim: ${coin.get('volume', 0):,.0f}\n"
            f"━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(message)

    def update_opportunities(self, chat_id: int, opportunities: list):
        """Son fırsatları güncelle"""
        self.logger.debug(f"Fırsatlar güncelleniyor. Chat ID: {chat_id}, Fırsat sayısı: {len(opportunities)}")
        self.last_opportunities[chat_id] = opportunities.copy()
        self.logger.debug(f"Fırsatlar güncellendi. Mevcut fırsatlar: {len(self.last_opportunities[chat_id])}")

    async def get_tracked_coins(self, chat_id: int) -> list:
        """Takip edilen coinleri getir"""
        if chat_id in self.tracked_coins:
            return list(self.tracked_coins[chat_id].keys())
        return []

    async def remove_from_tracking(self, chat_id: int, symbol: str) -> bool:
        """Coini takipten çıkar"""
        if chat_id in self.tracked_coins and symbol in self.tracked_coins[chat_id]:
            del self.tracked_coins[chat_id][symbol]
            return True
        return False 