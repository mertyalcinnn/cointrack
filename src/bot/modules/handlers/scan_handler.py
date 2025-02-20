from telegram import Update
from telegram.ext import ContextTypes
from ..data.binance_client import BinanceClient
from ..analysis.market import MarketAnalyzer
from ..utils.formatter import MessageFormatter
import time

class ScanHandler:
    def __init__(self, logger, track_handler):
        self.logger = logger
        self.client = BinanceClient()
        self.analyzer = MarketAnalyzer(logger)
        self.formatter = MessageFormatter()
        self.track_handler = track_handler

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            chat_id = update.effective_chat.id
            interval = self._get_interval(context.args)
            if not interval:
                await self._send_usage_message(update)
                return

            progress_message = await update.message.reply_text(
                f"🔍 {interval} taraması başlatıldı...\n"
                f"⏳ Veriler alınıyor..."
            )
            
            start_time = time.time()
            
            # Market verilerini al
            ticker_data = await self.client.get_ticker()
            if not ticker_data:
                await progress_message.edit_text("❌ Market verileri alınamadı!")
                return
                
            await progress_message.edit_text(
                f"📊 Market verileri alındı!\n"
                f"⏳ Coinler analiz ediliyor..."
            )
            
            # Fırsatları analiz et
            opportunities = await self.analyzer.analyze_market(ticker_data, interval)
            
            if not opportunities:
                await progress_message.edit_text("❌ Fırsat bulunamadı!")
                return
            
            scan_duration = time.time() - start_time
            
            # Önemli: Fırsatları track handler'a aktar
            self.track_handler.update_opportunities(chat_id, opportunities)
            
            # İlk mesajı güncelle
            await progress_message.edit_text(
                f"✅ Tarama tamamlandı!\n"
                f"📊 {len(opportunities)} fırsat bulundu.\n"
                f"⏳ Sonuçlar hazırlanıyor..."
            )
            
            # Fırsatları listele
            messages = self._format_opportunities(opportunities, interval)
            for i, message in enumerate(messages, 1):
                numbered_message = f"Fırsat #{i}:\n{message}"
                await update.message.reply_text(numbered_message)
            
            # Özet ve kullanım mesajı
            summary = (
                f"📈 TARAMA ÖZET ({interval})\n\n"
                f"🔍 Taranan Coin: {len(ticker_data)}\n"
                f"✨ Bulunan Fırsat: {len(opportunities)}\n"
                f"⭐ En Yüksek Skor: {opportunities[0]['opportunity_score']:.1f}\n"
                f"⏱ Tarama Süresi: {scan_duration:.1f}s\n\n"
                f"🎯 Coin takip etmek için:\n"
                f"/track <numara> komutunu kullanın\n"
                f"Örnek: /track 1"
            )
            await update.message.reply_text(summary)

        except Exception as e:
            self.logger.error(f"Scan error: {e}")
            await update.message.reply_text(f"❌ Tarama hatası: {str(e)}")

    def _format_opportunities(self, opportunities: list, interval: str) -> list:
        """Fırsatları formatla"""
        messages = []
        for opp in opportunities:
            # EMA Sinyalleri
            ema_signal = "📈 YUKARI" if opp['ema20'] > opp['ema50'] else "📉 AŞAĞI"
            ema_cross = abs(opp['ema20'] - opp['ema50']) / opp['ema50'] * 100
            
            # Bollinger Bands Analizi
            bb_position = (opp['price'] - opp['bb_lower']) / (opp['bb_upper'] - opp['bb_lower']) * 100
            bb_signal = self._get_bb_signal(bb_position)
            
            message = (
                f"💰 {opp['symbol']}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💵 Fiyat: ${opp['price']:.4f}\n"
                f"📊 RSI: {opp['rsi']:.1f}\n"
                f"📈 Trend: {opp['trend']}\n"
                f"⚡ Hacim: ${opp['volume']:,.0f}\n"
                f"📊 Hacim Artışı: {'✅' if opp['volume_surge'] else '❌'}\n\n"
                f"📈 TEKNİK ANALİZ:\n"
                f"• EMA Trend: {ema_signal} ({ema_cross:.1f}%)\n"
                f"• BB Pozisyon: {bb_signal} ({bb_position:.1f}%)\n"
                f"• MACD: {opp['macd']:.4f}\n"
                f"• RSI: {opp['rsi']:.1f}\n\n"
                f"🎯 Sinyal: {opp['signal']}\n"
                f"⭐ Fırsat Puanı: {opp['opportunity_score']:.1f}/100\n"
                f"━━━━━━━━━━━━━━━━"
            )
            messages.append(message)
        return messages

    def _get_bb_signal(self, bb_position: float) -> str:
        """Bollinger Bands sinyali belirle"""
        if bb_position <= 0:
            return "💚 GÜÇLÜ ALIM"
        elif bb_position <= 20:
            return "💛 ALIM"
        elif bb_position >= 100:
            return "🔴 GÜÇLÜ SATIŞ"
        elif bb_position >= 80:
            return "🟡 SATIŞ"
        else:
            return "⚪ NÖTR"

    def _get_interval(self, args):
        """Tarama aralığını belirle"""
        if not args:
            return "4h"
        arg = args[0].lower()
        return {
            "scan15": "15m",
            "scan4": "4h"
        }.get(arg)

    async def _send_usage_message(self, update):
        """Kullanım mesajını gönder"""
        await update.message.reply_text(
            "❌ Geçersiz komut!\n"
            "Kullanım:\n"
            "/scan - 4 saatlik tarama\n"
            "/scan scan15 - 15 dakikalık tarama\n"
            "/scan scan4 - 4 saatlik tarama"
        )

    async def _get_opportunities(self, interval):
        ticker_data = await self.client.get_ticker()
        if not ticker_data:
            return []
        return await self.analyzer.analyze_market(ticker_data, interval)

    async def _send_opportunities(self, update, opportunities, interval):
        messages = self.formatter.format_opportunities(opportunities, interval)
        for message in messages:
            await update.message.reply_text(message) 