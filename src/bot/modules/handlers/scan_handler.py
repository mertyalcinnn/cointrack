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
            messages = self.formatter.format_opportunities(opportunities, interval)
            for i, message in enumerate(messages, 1):
                numbered_message = f"Fırsat #{i}:\n{message}"  # Her fırsata numara ekle
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