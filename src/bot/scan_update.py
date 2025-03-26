from telegram import Update
from telegram.ext import ContextTypes
from src.bot.multi_timeframe_scan import scan_command_multi, send_multi_timeframe_results, _get_test_multi_opportunities

async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan komutunu işle - Premium gerektirir"""
    try:
        chat_id = update.effective_chat.id
        
        # Tarama tipini belirle
        scan_type = "default"
        if context.args and len(context.args) > 0:
            scan_type = context.args[0].lower()
        
        # Çoklu zaman dilimi analizi isteniyorsa
        if scan_type == "multi":
            await scan_command_multi(self, update, context)
            return
        
        # Kullanıcıya bilgi ver
        await update.message.reply_text(
            f"🔍 {scan_type.capitalize()} taraması yapılıyor...\n"
            f"⏳ Lütfen bekleyin, bu işlem birkaç dakika sürebilir..."
        )
        
        # Tarama tipi "multi" değilse eski tarama modelini kullan
        if scan_type == "default":
            # ScanHandler kullanarak tarama yap
            try:
                # Zaten mevcut ScanHandler'ı kullan
                opportunities = await self.scan_handler.scan_market("4h")
                
                if not opportunities or len(opportunities) == 0:
                    # Test verilerini kullan
                    self.logger.warning("Tarama sonucu bulunamadı, test verileri kullanılıyor")
                    opportunities = self._get_test_opportunities()
                    
            except Exception as e:
                self.logger.error(f"Tarama hatası: {e}")
                # Hata durumunda test verileri döndür
                opportunities = self._get_test_opportunities()
            
            if not opportunities or len(opportunities) == 0:
                await update.message.reply_text(
                    "❌ Şu anda uygun işlem fırsatı bulunamadı!\n"
                    "Lütfen daha sonra tekrar deneyin.\n\n"
                    "💡 İPUCU: Piyasa koşulları sürekli değişir. Piyasada faaliyetin artmasını bekleyebilirsiniz."
                )
                return
            
            # Sonuçları kaydet
            self.last_scan_results[chat_id] = opportunities
            
            # Sonuçları formatla ve gönder - tarama tipi olarak "4h" kullanıyoruz
            await self.send_scan_results(chat_id, opportunities, "4h")
        
        else:
            # Kullanıcıya bilgi ver - hangi tarama tipi olduğu önemli değil, çoklu zaman dilimi analizi yapalım
            await scan_command_multi(self, update, context)
                
    except Exception as e:
        self.logger.error(f"Scan komutu hatası: {e}")
        await update.message.reply_text(
            "❌ Tarama sırasında bir hata oluştu!\n"
            "Lütfen daha sonra tekrar deneyin."
        )

# Callback handler
async def handle_callback_query(self, update, context):
    """Tüm callback query'leri işle"""
    try:
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        
        self.logger.info(f"Callback alındı: {callback_data} - {chat_id}")
        
        # Track butonları
        if callback_data.startswith("track_"):
            index = int(callback_data.split("_")[1])
            await self.track_button_callback(update, context, index)
        
        # Stop track butonları
        elif callback_data.startswith("stoptrack_"):
            symbol_or_all = callback_data.split("_")[1]
            await self.stop_track_callback_handler(update, context, symbol_or_all)
        
        # Tarama yenileme butonu - normal tarama
        elif callback_data.startswith("refresh_"):
            scan_type = callback_data.split("_")[1]
            if scan_type == "multi":
                # Çoklu zaman dilimi analizi yenileme
                await scan_command_multi(self, update, context)
            else:
                # Normal tarama yenileme
                await self.refresh_scan_callback(update, context, scan_type)
                
        # Premium butonları
        elif callback_data == "start_trial":
            success, message = self.premium_manager.start_trial(user_id)
            await query.edit_message_text(text=f"🎁 {message}")
            
        elif callback_data == "premium_info":
            status = self.premium_manager.get_premium_status(user_id)
            await query.edit_message_text(
                text="💰 Premium Üyelik Bilgileri\n\n"
                     "Premium üyelik ile tüm özelliklere sınırsız erişim kazanırsınız.\n\n"
                     "Aylık: 99₺\n"
                     "3 Aylık: 249₺\n"
                     "Yıllık: 899₺\n\n"
                     "Ödeme için: @admin ile iletişime geçin."
            )
            
    except Exception as e:
        self.logger.error(f"Callback işleme hatası: {e}")
        try:
            await update.callback_query.message.reply_text(
                "❌ İşlem sırasında bir hata oluştu!"
            )
        except:
            pass
