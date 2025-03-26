from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, Application
import logging
from typing import List, Dict, Optional, Any, Tuple
from src.analysis.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from datetime import datetime

class MultiTimeframeHandler:
    """
    Çoklu zaman dilimi analizi için Telegram bot entegrasyonu.
    Bu sınıf /multiscan komutunu ve ilgili callback işlevlerini yönetir.
    """
    
    def __init__(self, logger=None, bot_instance=None):
        """Initialize the handler with necessary components"""
        self.logger = logger or logging.getLogger('MultiTimeframeHandler')
        self.bot = bot_instance
        self.analyzer = MultiTimeframeAnalyzer(logger=self.logger)
        self.logger.info("MultiTimeframeHandler başlatıldı")
    
    async def initialize(self):
        """Initialize asynchronous components"""
        try:
            self.logger.info("MultiTimeframeHandler başlatılıyor...")
            success = await self.analyzer.initialize()
            return success
        except Exception as e:
            self.logger.error(f"MultiTimeframeHandler başlatma hatası: {str(e)}")
            return False
    
    def register_handlers(self, application: Application):
        """Register command and callback handlers"""
        try:
            self.logger.info("MultiTimeframeHandler komutları kaydediliyor...")
            application.add_handler(CommandHandler("multiscan", self.multiscan_command))
            # Refresh callback'i zaten telegram_bot.py'de eklendi
            self.logger.info("MultiTimeframeHandler komutları başarıyla kaydedildi")
        except Exception as e:
            self.logger.error(f"Handler kayıt hatası: {str(e)}")
    
    async def multiscan_command(self, update, context):
        """İşlem gören tüm coinler için çoklu zaman dilimli analiz yap"""
        try:
            # Mesajı ve kullanıcıyı al
            message = update.effective_message
            user_id = update.effective_user.id
            
            # Argümanları kontrol et
            args = context.args
            symbol = None
            if args and len(args) > 0:
                symbol = args[0].upper().strip()
                if not symbol.endswith('USDT'):
                    symbol += 'USDT'
                
                # Bekleme mesajı
                wait_message = await message.reply_text(f"⏳ {symbol} için çoklu zaman dilimi analizi yapılıyor...")
            else:
                # Genel market taraması
                wait_message = await message.reply_text("⏳ Tüm market çoklu zaman dilimi ile taranıyor, lütfen bekleyin...")
            
            # Analizi yap - self.analyzer kullan, self.bot.scanner yerine
            if symbol:
                results = await self.analyzer.scan_market([symbol])
            else:
                results = await self.analyzer.scan_market()
            
            # Sonuçları formatlayıp gönder
            try:
                formatted_text = self._format_multi_results(results)
                
                # HTML veya Markdown ile ilgili sorunları önlemek için parse_mode=None olarak ayarla
                # ve çok uzun mesajlar için metni böl
                if len(formatted_text) > 4000:
                    # Metni böl ve birden fazla mesaj gönder
                    chunks = [formatted_text[i:i+4000] for i in range(0, len(formatted_text), 4000)]
                    for i, chunk in enumerate(chunks):
                        if i == 0:  # İlk kısım için mevcut mesajı güncelle
                            await wait_message.edit_text(
                                text=chunk,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                        else:  # Diğer kısımlar için yeni mesajlar gönder
                            await message.reply_text(
                                text=chunk,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                else:
                    # Tek mesaj olarak gönder
                    await wait_message.edit_text(
                        text=formatted_text,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                    
                # Sonuçları yenileme butonu ekle
                refresh_button = InlineKeyboardButton(
                    "🔄 Yenile", 
                    callback_data=f"refresh_multi{'_'+symbol if symbol else ''}"
                )
                await wait_message.edit_reply_markup(
                    reply_markup=InlineKeyboardMarkup([[refresh_button]])
                )
                
            except BadRequest as e:
                # Telegram API hatası durumunda formatlama olmadan dene
                self.logger.error(f"Mesaj gönderme hatası: {str(e)}")
                
                # Basitleştirilmiş mesaj gönder
                simple_msg = f"⚠️ Sonuçlar formatlanırken hata oluştu. {len(results)} sonuç bulundu."
                await wait_message.edit_text(simple_msg)
                
                # Hata ayrıntılarını logla
                import traceback
                self.logger.error(traceback.format_exc())
            
        except Exception as e:
            self.logger.error(f"Multiscan komutu hatası: {str(e)}")
            import traceback 
            self.logger.error(traceback.format_exc())
            
            # Kullanıcıya bilgi ver
            if 'wait_message' in locals():
                await wait_message.edit_text("❌ Analiz sırasında bir hata oluştu. Lütfen daha sonra tekrar deneyin.")
            else:
                await message.reply_text("❌ Analiz sırasında bir hata oluştu. Lütfen daha sonra tekrar deneyin.")
    
    async def refresh_multi_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Çoklu zaman dilimi analizini yenileyen callback işleyici"""
        try:
            query = update.callback_query
            await query.answer("Analiz yenileniyor...")
            
            # Mevcut sembol kontrolü
            message_text = query.message.text
            symbol_line = message_text.split('\n', 1)[0]
            symbol = None
            
            # Mesaj başlığından sembolü çıkart
            if "Analiz Sonuçları:" in symbol_line:
                symbol_parts = symbol_line.split()
                if len(symbol_parts) > 0 and symbol_parts[0].endswith("USDT"):
                    symbol = symbol_parts[0]
            
            # Analizi yenile
            results = await self.analyzer.scan_market([symbol] if symbol else None)
            
            if results:
                # Sonuçları formatla
                message_text = self._format_multi_results(results)
                
                # Refresh butonu ekle
                keyboard = [
                    [InlineKeyboardButton("🔄 Yenile", callback_data="refresh_multi")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Mesajı güncelle
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                
                # Grafik için yeni bir mesaj gönder
                top_opportunity = results[0]
                chart_buf = await self.analyzer.generate_multi_timeframe_chart(top_opportunity["symbol"])
                if chart_buf:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=chart_buf,
                        caption=f"📊 {top_opportunity['symbol']} Çoklu Zaman Dilimi Analizi (Yenilendi)"
                    )
            else:
                scan_type = f"{symbol} çoklu zaman dilimi" if symbol else "çoklu zaman dilimi"
                await query.edit_message_text(
                    f"❌ {scan_type.capitalize()} analizi için uygun fırsat bulunamadı!"
                )
            
        except Exception as e:
            self.logger.error(f"Refresh multi callback hatası: {str(e)}")
            await query.answer("Yenileme sırasında bir hata oluştu!")
    
    def _format_multi_results(self, results):
        """Çoklu zaman dilimi analiz sonuçlarını okunabilir ve Telegram-uyumlu bir metne dönüştür"""
        try:
            if not results or len(results) == 0:
                return "⚠️ Hiçbir uygun fırsat bulunamadı."
            
            # Sonuçları fırsat puanına göre filtrele ve sırala
            filtered_results = [r for r in results if r.get("opportunity_score", 0) > 0]
            filtered_results.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
            
            if len(filtered_results) == 0:
                return "⚠️ Filtreleme sonrası uygun fırsat bulunamadı."
            
            # En iyi 10 fırsatı seç (mesaj çok uzun olmasın)
            top_results = filtered_results[:10]
            
            # Başlık ve açıklama
            header = (
                "🔍 *ÇOK ZAMAN DİLİMLİ MARKET TARAMASI*\n\n"
                f"🕒 _Tarama zamanı: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}_\n\n"
                f"✅ *Bulunan fırsatlar: {len(filtered_results)}*\n\n"
            )
            
            # Her sembol için özet bilgiler
            results_text = []
            
            for idx, result in enumerate(top_results, 1):
                symbol = result.get("symbol", "")
                score = result.get("opportunity_score", 0)
                signal = result.get("signal", "⚪ BEKLE")
                price = result.get("current_price", 0)
                
                # Risk/Ödül ve stop/hedef bilgileri
                risk_reward = result.get("risk_reward", 0)
                stop_price = result.get("stop_price", 0)
                target_price = result.get("target_price", 0)
                
                # Emoji belirle
                emoji = "🟩" if signal.startswith("🟩") else "🔴" if signal.startswith("🔴") else "⚪"
                
                # Sonuç metni
                result_str = (
                    f"{idx}. *{symbol}* ({emoji} {score:.0f}/100)\n"
                    f"💲 Fiyat: ${price:.4f}\n"
                    f"📊 Sinyal: {signal}\n"
                )
                
                # Stop ve hedef bilgileri (fiyat sıfırdan büyükse)
                if stop_price > 0 and target_price > 0:
                    # Parantez karakterlerini [] ile değiştir - Telegram'da sorun çıkartabilir
                    result_str += f"🎯 Hedef: ${target_price:.4f} "
                    result_str += f"🛑 Stop: ${stop_price:.4f}\n"
                    result_str += f"⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                
                # Trend açıklamaları - burada önemli: Markdown/HTML karakterlerini temizle
                trend_descriptions = result.get("trend_descriptions", [])
                if trend_descriptions:
                    # Sadece ilk 3 açıklamayı göster
                    for desc in trend_descriptions[:3]:
                        # Parantezleri ve özel karakterleri güvenli hale getir
                        # "text (info)" formatındaki metinler için özel işlem
                        safe_desc = desc.replace("(", "[").replace(")", "]")
                        # Yüzdelik işaretleri ve diğer özel karakterler
                        safe_desc = safe_desc.replace("%", "%%")
                        result_str += f"{safe_desc}\n"
                
                results_text.append(result_str)
            
            # Sonuçları birleştir ve not ekle
            final_text = header + "\n".join(results_text)
            
            # Footer
            footer = (
                "\n\n💡 *Nasıl Kullanılır:*\n"
                "- Sinyal sonuçları 3 zaman diliminden (1W, 1H, 15M) gelen analizleri birleştirir\n"
                "- 🟩: LONG (Alım), 🔴: SHORT (Satım), ⚪: BEKLE\n"
                "- Tek bir sembol için detaylı analiz: /multi + sembol (örn: /multi BTCUSDT)\n"
            )
            
            return final_text + footer
        
        except Exception as e:
            self.logger.error(f"Sonuç formatlarken hata: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return "❌ Sonuçları formatlarken hata oluştu."
