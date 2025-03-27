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
            
            # Analizi yap - demo parametresini kaldır
            if symbol:
                # Tek sembol analizi
                results = await self.analyzer.scan_market([symbol])
            else:
                # Genel tarama
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
    
    async def refresh_multi_callback(self, update, context):
        """Çoklu zaman dilimi analizini yenile"""
        try:
            query = update.callback_query
            await query.answer("Analiz yenileniyor...")
            
            # Callback verilerini ayrıştır
            callback_data = query.data
            parts = callback_data.split('_')
            
            symbol = None
            if len(parts) > 2:
                symbol = parts[2]
            
            # Analizi yenile - demo parametresi kaldırıldı
            if symbol:
                # Tek sembol analizi
                results = await self.analyzer.scan_market([symbol])
            else:
                # Genel tarama
                results = await self.analyzer.scan_market()
            
            # Sonuçları formatlayıp mesajı güncelle
            try:
                formatted_text = self._format_multi_results(results)
                
                # Mesajı güncelle
                await query.edit_message_text(
                    text=formatted_text,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                
                # Yenileme butonunu ekle
                refresh_button = InlineKeyboardButton(
                    "🔄 Yenile", 
                    callback_data=callback_data
                )
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup([[refresh_button]])
                )
                
            except BadRequest as e:
                self.logger.error(f"Yenileme mesajı güncellenirken hata: {str(e)}")
                await query.edit_message_text(f"⚠️ Sonuçlar formatlanırken hata oluştu. {len(results)} sonuç bulundu.")
        
        except Exception as e:
            self.logger.error(f"Multi refresh callback hatası: {str(e)}")
            try:
                await query.edit_message_text("❌ Analiz yenilenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin.")
            except:
                pass
    
    def _format_multi_results(self, results):
        """Çoklu zaman dilimi analiz sonuçlarını okunabilir ve Telegram-uyumlu bir metne dönüştür"""
        try:
            if not results or len(results) == 0:
                return "⚠️ Hiçbir uygun fırsat bulunamadı."
            
            # Debug: Daha detaylı sonuç bilgisi
            self.logger.info(f"Format öncesi sonuçlar: {len(results)} adet")
            for idx, r in enumerate(results[:10]):  # İlk 10 sonucu logla
                signal = r.get('signal', 'SIGNAL_YOK')
                weekly = r.get('weekly_trend', 'TREND_YOK')
                m15 = r.get('15m_trend', 'TREND_YOK')
                score = r.get('opportunity_score', 0)
                self.logger.info(f"Sonuç {idx+1}: {r.get('symbol')} - Sinyal: {signal} - Weekly: {weekly} - 15M: {m15} - Skor: {score}")
            
            # Sinyal belirleme (eksik ise)
            for result in results:
                # Sinyal yoksa veya BEKLE ise, trend durumuna göre belirle
                if not result.get('signal') or result.get('signal') == "⚪ BEKLE":
                    m15_trend = result.get('15m_trend', 'NEUTRAL')
                    weekly_trend = result.get('weekly_trend', 'NEUTRAL')
                    
                    # Herhangi bir zaman diliminde güçlü trend varsa sinyal ata
                    if m15_trend in ['STRONGLY_BULLISH', 'BULLISH'] or weekly_trend in ['STRONGLY_BULLISH', 'BULLISH']:
                        result['signal'] = "🟩 LONG"
                    elif m15_trend in ['STRONGLY_BEARISH', 'BEARISH'] or weekly_trend in ['STRONGLY_BEARISH', 'BEARISH']:
                        result['signal'] = "🔴 SHORT"
                    else:
                        result['signal'] = "⚪ BEKLE"
            
            # Sonuçları puana göre sırala
            filtered_results = results.copy()
            filtered_results.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
            
            # LONG ve SHORT fırsatlarını ayır - ÖNEMLİ DÜZELTME
            long_results = []
            short_results = []
            
            for result in filtered_results:
                signal = result.get("signal", "")
                
                # Sinyal tipine göre kategorize et
                if signal.startswith("🟩") or "LONG" in signal:
                    long_results.append(result)
                    self.logger.info(f"LONG eklendi: {result.get('symbol')} - {signal}")
                elif signal.startswith("🔴") or "SHORT" in signal:
                    short_results.append(result)
                    self.logger.info(f"SHORT eklendi: {result.get('symbol')} - {signal}")
            
            # Debug: Kategorilere ayrılmış sonuçları logla
            self.logger.info(f"LONG: {len(long_results)}, SHORT: {len(short_results)}")
            
            # Tüm sonuçlar için doğru sayıları göster
            total_opportunities = len(long_results) + len(short_results)
            
            # Başlık ve açıklama
            header = (
                "🔍 *ÇOK ZAMAN DİLİMLİ MARKET TARAMASI*\n\n"
                f"🕒 _Tarama zamanı: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}_\n\n"
                f"✅ *Bulunan fırsatlar: {total_opportunities}* (LONG: {len(long_results)}, SHORT: {len(short_results)})\n\n"
            )
            
            # LONG fırsatları başlığı ve içeriği
            long_section = ""
            if long_results:
                long_section = "🟩 *LONG (ALIŞ) FIRSATLARI*\n\n"
                long_items = []
                
                for idx, result in enumerate(long_results, 1):
                    symbol = result.get("symbol", "")
                    score = result.get("opportunity_score", 0)
                    price = result.get("current_price", 0)
                    
                    # Risk/Ödül ve stop/hedef bilgileri
                    risk_reward = result.get("risk_reward", 0)
                    stop_price = result.get("stop_price", 0)
                    target_price = result.get("target_price", 0)
                    
                    # Trend bilgileri
                    weekly_trend = result.get("weekly_trend", "UNKNOWN")
                    h4_trend = result.get("h4_trend", "UNKNOWN")
                    hourly_trend = result.get("hourly_trend", "UNKNOWN")
                    m15_trend = result.get("15m_trend", "UNKNOWN")
                    
                    # Sonuç metni
                    result_str = (
                        f"{idx}. *{symbol}* (🟩 {score:.0f}/100)\n"
                        f"💲 Fiyat: ${price:.4f}\n"
                        f"📈 Trendler: 1W:{self._trend_emoji(weekly_trend)} 4H:{self._trend_emoji(h4_trend)} 1H:{self._trend_emoji(hourly_trend)} 15M:{self._trend_emoji(m15_trend)}\n"
                    )
                    
                    # Stop ve hedef bilgileri (fiyat sıfırdan büyükse)
                    if stop_price > 0 and target_price > 0:
                        result_str += f"🎯 Hedef: ${target_price:.4f} "
                        result_str += f"🛑 Stop: ${stop_price:.4f}\n"
                        result_str += f"⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                    
                    # Trend açıklamaları
                    trend_descriptions = result.get("trend_descriptions", [])
                    if trend_descriptions:
                        # Sadece ilk 2 açıklamayı göster
                        for desc in trend_descriptions[:2]:
                            # Parantezleri ve özel karakterleri güvenli hale getir
                            safe_desc = desc.replace("(", "[").replace(")", "]").replace("%", "%%")
                            result_str += f"• {safe_desc}\n"
                    
                    long_items.append(result_str)
                
                long_section += "\n".join(long_items)
            
            # SHORT fırsatları başlığı ve içeriği
            short_section = ""
            if short_results:
                short_section = "\n\n🔴 *SHORT (SATIŞ) FIRSATLARI*\n\n"
                short_items = []
                
                for idx, result in enumerate(short_results, 1):
                    symbol = result.get("symbol", "")
                    score = result.get("opportunity_score", 0)
                    price = result.get("current_price", 0)
                    
                    # Risk/Ödül ve stop/hedef bilgileri
                    risk_reward = result.get("risk_reward", 0)
                    stop_price = result.get("stop_price", 0)
                    target_price = result.get("target_price", 0)
                    
                    # Trend bilgileri
                    weekly_trend = result.get("weekly_trend", "UNKNOWN")
                    h4_trend = result.get("h4_trend", "UNKNOWN")
                    hourly_trend = result.get("hourly_trend", "UNKNOWN")
                    m15_trend = result.get("15m_trend", "UNKNOWN")
                    
                    # Sonuç metni
                    result_str = (
                        f"{idx}. *{symbol}* (🔴 {score:.0f}/100)\n"
                        f"💲 Fiyat: ${price:.4f}\n"
                        f"📉 Trendler: 1W:{self._trend_emoji(weekly_trend)} 4H:{self._trend_emoji(h4_trend)} 1H:{self._trend_emoji(hourly_trend)} 15M:{self._trend_emoji(m15_trend)}\n"
                    )
                    
                    # Stop ve hedef bilgileri (fiyat sıfırdan büyükse)
                    if stop_price > 0 and target_price > 0:
                        result_str += f"🎯 Hedef: ${target_price:.4f} "
                        result_str += f"🛑 Stop: ${stop_price:.4f}\n"
                        result_str += f"⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                    
                    # Trend açıklamaları
                    trend_descriptions = result.get("trend_descriptions", [])
                    if trend_descriptions:
                        # Sadece ilk 2 açıklamayı göster
                        for desc in trend_descriptions[:2]:
                            # Parantezleri ve özel karakterleri güvenli hale getir
                            safe_desc = desc.replace("(", "[").replace(")", "]").replace("%", "%%")
                            result_str += f"• {safe_desc}\n"
                    
                    short_items.append(result_str)
                
                short_section += "\n".join(short_items)
            
            # Fırsat yoksa mesaj
            if not long_section and not short_section:
                combined_section = "⚠️ Şu anda işlem için uygun bir alım/satım fırsatı bulunamadı."
            else:
                combined_section = long_section + short_section
            
            # Footer
            footer = (
                "\n\n💡 *Nasıl Kullanılır:*\n"
                "- Analiz 4 zaman dilimini (1W, 4H, 1H, 15M) birleştirir\n"
                "- 🟩: LONG pozisyon (alım fırsatı), 🔴: SHORT pozisyon (satış fırsatı)\n"
                "- Tek bir sembol için: /multiscan + sembol (örn: /multiscan BTCUSDT)\n"
                "- 🔄 Yenile butonuyla güncel fırsatları görebilirsiniz\n"
            )
            
            return header + combined_section + footer
        
        except Exception as e:
            self.logger.error(f"Sonuç formatlarken hata: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return "❌ Sonuçları formatlarken hata oluştu."

    def _trend_emoji(self, trend):
        """Trend durumuna göre emoji döndürür"""
        if trend == "STRONGLY_BULLISH":
            return "🟢🟢"
        elif trend == "BULLISH":
            return "🟢"
        elif trend == "STRONGLY_BEARISH":
            return "🔴🔴"
        elif trend == "BEARISH":
            return "🔴"
        elif trend == "NEUTRAL":
            return "⚪"
        else:
            return "❓"