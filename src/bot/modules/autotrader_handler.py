#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AutoTrader Handler - Telegram botu için Otomatik Kaldıraçlı İşlem sistemini başlatıp yöneten modül
"""

import os
import sys
import asyncio
import subprocess
import logging
import signal
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

class AutoTraderHandler:
    """Telegram botu üzerinden otomatik işlem sistemini yöneten sınıf"""
    
    def __init__(self, logger=None):
        """Initialize the handler"""
        self.logger = logger or logging.getLogger('AutoTraderHandler')
        self.process = None
        self.active_chats = set()  # Hangi sohbetlerde aktif olduğunu takip et
    
    def register_handlers(self, application):
        """Register command handlers with the application"""
        application.add_handler(CommandHandler("autoscan", self.handle_autoscan))
        application.add_handler(CommandHandler("stopautoscan", self.handle_stopautoscan))
        self.logger.info("AutoTrader komutları kaydedildi!")
    
    async def handle_autoscan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /autoscan command - start the autotrader process"""
        chat_id = update.effective_chat.id
        
        # İşlem halihazırda çalışıyor mu kontrol et
        if self.process is not None and self.process.poll() is None:
            await update.message.reply_text(
                "⚠️ Otomatik işlem sistemi zaten çalışıyor!\n"
                "Durdurmak için /stopautoscan komutunu kullanabilirsiniz."
            )
            return
        
        # Kullanıcıya bilgi ver
        await update.message.reply_text(
            "🚀 Otomatik Kaldıraçlı İşlem Sistemi başlatılıyor...\n"
            "Bu sistem, AI analizlerini kullanarak piyasada fırsatları tespit edecek ve işlem açacaktır.\n"
            "⏳ Lütfen bekleyin..."
        )
        
        try:
            # Autotrader.py'nin tam yolunu bul
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            autotrader_path = os.path.join(root_dir, 'autotrader.py')
            
            if not os.path.exists(autotrader_path):
                await update.message.reply_text(
                    f"❌ Autotrader.py dosyası bulunamadı: {autotrader_path}\n"
                    "Lütfen dosyanın varlığını kontrol edin."
                )
                return
            
            # Subprocess olarak Python scripti başlat
            env = os.environ.copy()
            env["TELEGRAM_CHAT_ID"] = str(chat_id)  # AutoTrader'a mesaj göndermek için chat ID'yi aktarıyoruz
            
            # Scripti başlat
            self.process = subprocess.Popen(
                [sys.executable, autotrader_path],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Aktif sohbete ekle
            self.active_chats.add(chat_id)
            
            # Başarı mesajı
            await update.message.reply_text(
                "✅ Otomatik Kaldıraçlı İşlem Sistemi başarıyla başlatıldı!\n\n"
                "📊 Sistem şu anda piyasayı inceliyor ve fırsat arıyor.\n"
                "💰 Uygun bir işlem fırsatı bulunduğunda otomatik olarak pozisyon açılacak ve size bildirilecektir.\n\n"
                "⚠️ Sistemi durdurmak için: /stopautoscan"
            )
            
            # Process başlatma bilgisini logla
            self.logger.info(f"AutoTrader başlatıldı, PID: {self.process.pid}, chat_id: {chat_id}")
            
            # Çıktıları takip et ve Telegram'a gönder
            asyncio.create_task(self._monitor_process_output(chat_id))
            
        except Exception as e:
            self.logger.error(f"AutoTrader başlatma hatası: {e}")
            await update.message.reply_text(
                f"❌ Otomatik işlem sistemi başlatılırken bir hata oluştu: {str(e)}"
            )
    
    async def handle_stopautoscan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /stopautoscan command - stop the autotrader process"""
        chat_id = update.effective_chat.id
        
        # İşlem çalışıyor mu kontrol et
        if self.process is None or self.process.poll() is not None:
            await update.message.reply_text(
                "⚠️ Otomatik işlem sistemi zaten çalışmıyor!"
            )
            return
        
        try:
            # İşlemi sonlandır
            if self.process:
                self.logger.info(f"AutoTrader durduruluyor, PID: {self.process.pid}")
                
                # Unix: SIGTERM sinyali gönder
                os.kill(self.process.pid, signal.SIGTERM)
                
                # 5 saniye bekle
                for _ in range(5):
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(1)
                
                # Hala çalışıyorsa SIGKILL gönder
                if self.process.poll() is None:
                    self.logger.warning(f"AutoTrader SIGTERM ile durdurulamadı, SIGKILL gönderiliyor")
                    os.kill(self.process.pid, signal.SIGKILL)
                
                # Process'i None yap
                self.process = None
                
                # Aktif sohbetlerden çıkar
                if chat_id in self.active_chats:
                    self.active_chats.remove(chat_id)
                
                # Başarı mesajı
                await update.message.reply_text(
                    "✅ Otomatik Kaldıraçlı İşlem Sistemi durduruldu!\n"
                    "Tüm açık pozisyonlar kapatıldı."
                )
            
        except Exception as e:
            self.logger.error(f"AutoTrader durdurma hatası: {e}")
            await update.message.reply_text(
                f"❌ Otomatik işlem sistemi durdurulurken bir hata oluştu: {str(e)}"
            )
    
    async def _monitor_process_output(self, chat_id):
        """Monitor the output of the autotrader process and forward to Telegram"""
        if not self.process:
            return
            
        try:
            # Çıktıları oku ve Telegram'a gönder
            from telegram.ext import ApplicationBuilder
            
            # Bot token'ı al
            from dotenv import load_dotenv
            load_dotenv()
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if not token:
                self.logger.error("Telegram bot token bulunamadı!")
                return
                
            # Basit uygulama oluştur
            application = ApplicationBuilder().token(token).build()
            
            while self.process and self.process.poll() is None:
                # stdout'dan bir satır oku
                line = await asyncio.to_thread(self.process.stdout.readline)
                if line:
                    line = line.strip()
                    self.logger.info(f"AutoTrader çıktısı: {line}")
                    
                    # Önemli bilgileri Telegram'a gönder
                    if any(keyword in line for keyword in ["AÇILDI", "KAPANDI", "UYARI", "FAYDA", "UYARI", "HATA"]):
                        try:
                            await application.bot.send_message(chat_id=chat_id, text=f"🤖 {line}")
                        except Exception as e:
                            self.logger.error(f"Telegram mesajı gönderme hatası: {e}")
                
                # stderr'den bir satır oku
                error_line = await asyncio.to_thread(self.process.stderr.readline)
                if error_line:
                    error_line = error_line.strip()
                    self.logger.error(f"AutoTrader hatası: {error_line}")
                    
                    # Hata mesajlarını Telegram'a gönder
                    try:
                        await application.bot.send_message(
                            chat_id=chat_id, 
                            text=f"⚠️ AutoTrader Hatası: {error_line}"
                        )
                    except Exception as e:
                        self.logger.error(f"Telegram hata mesajı gönderme hatası: {e}")
                
                # Kısa bekle
                await asyncio.sleep(0.1)
            
            # Process çıkış kodu
            exit_code = self.process.poll()
            self.logger.info(f"AutoTrader sonlandı, çıkış kodu: {exit_code}")
            
            # Çıkış mesajını gönder
            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=f"ℹ️ Otomatik Kaldıraçlı İşlem Sistemi sonlandı. Çıkış kodu: {exit_code}"
                )
            except Exception as e:
                self.logger.error(f"Telegram çıkış mesajı gönderme hatası: {e}")
                
        except Exception as e:
            self.logger.error(f"Process çıktı izleme hatası: {e}")
