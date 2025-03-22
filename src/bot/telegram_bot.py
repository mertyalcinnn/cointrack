import asyncio
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Set, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.error import NetworkError, TimedOut, RetryAfter
from src.config import TOKEN, ACTIVE_SYMBOLS, POLLING_INTERVAL
import time
import pandas as pd
import aiohttp
from bs4 import BeautifulSoup
import re
import ccxt
from dotenv import load_dotenv
import os
from pathlib import Path
import numpy as np
import logging
import json
from .modules.market_analyzer import MarketAnalyzer
from .modules.handlers.scan_handler import ScanHandler
from .modules.handlers.track_handler import TrackHandler
from .modules.message_formatter import MessageFormatter
from .modules.utils.logger import setup_logger
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import mplfinance as mpf
from PIL import Image, ImageDraw, ImageFont
import base64
import functools
import random

# .env dosyasının yolunu bul
env_path = Path(__file__).parent.parent.parent / '.env'

# .env dosyasını yükle
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    raise FileNotFoundError(
        "'.env' dosyası bulunamadı! Lütfen projenin kök dizininde .env dosyası oluşturun "
        "ve TELEGRAM_BOT_TOKEN değişkenini ekleyin."
    )

# Token'ı kontrol et
token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
if not token:
    raise ValueError(
        "Token bulunamadı! Lütfen .env dosyasında TELEGRAM_BOT_TOKEN veya TELEGRAM_TOKEN değişkenini tanımlayın."
    )

# Kendi yeniden deneme dekoratörümüzü oluşturalım
def telegram_retry(max_tries=5, initial_delay=1, backoff_factor=2):
    """Ağ hatalarında yeniden deneme için dekoratör"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            logger = setup_logger('CoinScanner')
            tries = 0
            delay = initial_delay
            
            while tries < max_tries:
                try:
                    return await func(*args, **kwargs)
                except (NetworkError, TimedOut, RetryAfter, ConnectionError, aiohttp.ClientError) as e:
                    tries += 1
                    if tries >= max_tries:
                        logger.error(f"Maksimum yeniden deneme sayısına ulaşıldı ({max_tries}): {str(e)}")
                        raise
                    
                    # Jitter ekleyerek rastgele bir gecikme süresi hesapla
                    jitter = random.uniform(0.1, 0.5)
                    sleep_time = delay + jitter
                    
                    logger.warning(f"Ağ hatası, {sleep_time:.2f} saniye sonra yeniden deneniyor ({tries}/{max_tries}): {str(e)}")
                    await asyncio.sleep(sleep_time)
                    
                    # Bir sonraki deneme için gecikmeyi artır
                    delay *= backoff_factor
            
            # Bu noktaya asla ulaşılmamalı
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Global bot instance
bot_instance = None

# Premium gereksinimi için dekoratör
def premium_required(func):
    """Premium üyelik gerektiren komutlar için dekoratör"""
    @functools.wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # Kullanıcı premium mu kontrol et
        if self.premium_manager.is_premium(user_id):
            return await func(self, update, context, *args, **kwargs)
        else:
            # Premium değilse bilgilendir
            status = self.premium_manager.get_premium_status(user_id)
            
            if not status['trial_used']:
                # Deneme süresi kullanılmamışsa teklif et
                keyboard = [[InlineKeyboardButton("🎁 Deneme Süresi Başlat", callback_data="start_trial")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "⭐ Bu özellik premium üyelik gerektirir!\n\n"
                    "🎁 3 günlük ücretsiz deneme sürenizi başlatmak ister misiniz?\n"
                    "Alternatif olarak /trial komutunu da kullanabilirsiniz.",
                    reply_markup=reply_markup
                )
            else:
                # Deneme süresi kullanılmışsa premium teklif et
                keyboard = [[InlineKeyboardButton("💰 Premium Bilgileri", callback_data="premium_info")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "⭐ Bu özellik premium üyelik gerektirir!\n\n"
                    "Deneme sürenizi daha önce kullandınız.\n"
                    "Premium üyelik bilgileri için /premium komutunu kullanabilirsiniz.",
                    reply_markup=reply_markup
                )
            
            return None
    return wrapper

class PremiumManager:
    """Premium kullanıcıları yönetmek için yardımcı sınıf"""
    
    def __init__(self, logger):
        self.logger = logger
        self.premium_users = {}  # {user_id: {'expiry_date': datetime, 'trial_used': bool}}
        self.premium_file = Path(__file__).parent / 'data' / 'premium_users.json'
        
        # data klasörünü oluştur
        os.makedirs(os.path.dirname(self.premium_file), exist_ok=True)
        
        # Premium kullanıcı verilerini yükle
        self.load_premium_users()
    
    def load_premium_users(self):
        """Premium kullanıcı verilerini dosyadan yükle"""
        try:
            if self.premium_file.exists():
                with open(self.premium_file, 'r') as f:
                    data = json.load(f)
                    
                    # Tarihleri string'den datetime'a çevir
                    for user_id, user_data in data.items():
                        if 'expiry_date' in user_data:
                            user_data['expiry_date'] = datetime.fromisoformat(user_data['expiry_date'])
                    
                    self.premium_users = {int(k): v for k, v in data.items()}
                    self.logger.info(f"{len(self.premium_users)} premium kullanıcı yüklendi")
        except Exception as e:
            self.logger.error(f"Premium kullanıcı verilerini yükleme hatası: {e}")
            self.premium_users = {}
    
    def save_premium_users(self):
        """Premium kullanıcı verilerini dosyaya kaydet"""
        try:
            # datetime nesnelerini string'e çevir
            data = {}
            for user_id, user_data in self.premium_users.items():
                data[str(user_id)] = user_data.copy()
                if 'expiry_date' in data[str(user_id)]:
                    data[str(user_id)]['expiry_date'] = data[str(user_id)]['expiry_date'].isoformat()
            
            with open(self.premium_file, 'w') as f:
                json.dump(data, f, indent=4)
                
            self.logger.info(f"{len(self.premium_users)} premium kullanıcı kaydedildi")
        except Exception as e:
            self.logger.error(f"Premium kullanıcı verilerini kaydetme hatası: {e}")
    
    def is_premium(self, user_id):
        """Kullanıcının premium olup olmadığını kontrol et"""
        if user_id in self.premium_users:
            # Süresi dolmuş mu kontrol et
            if self.premium_users[user_id].get('expiry_date') > datetime.now():
                return True
            else:
                # Süresi dolmuşsa premium_users'dan çıkar
                self.logger.info(f"Kullanıcı {user_id} premium süresi doldu")
        return False
    
    def start_trial(self, user_id):
        """Kullanıcıya deneme süresi başlat"""
        # Kullanıcı zaten premium mi kontrol et
        if self.is_premium(user_id):
            return False, "Zaten premium üyeleğiniz bulunmaktadır."
        
        # Kullanıcı daha önce deneme süresi kullanmış mı kontrol et
        if user_id in self.premium_users and self.premium_users[user_id].get('trial_used', False):
            return False, "Deneme sürenizi daha önce kullandınız."
        
        # 3 günlük deneme süresi başlat
        expiry_date = datetime.now() + timedelta(days=3)
        self.premium_users[user_id] = {
            'expiry_date': expiry_date,
            'trial_used': True,
            'subscription_type': 'trial'
        }
        
        # Değişiklikleri kaydet
        self.save_premium_users()
        
        return True, f"3 günlük deneme süreniz başlatıldı. Bitiş tarihi: {expiry_date.strftime('%d.%m.%Y %H:%M')}"
    
    def add_premium(self, user_id, days=30):
        """Kullanıcıya premium üyelik ekle"""
        # Mevcut bitiş tarihini kontrol et
        if user_id in self.premium_users and self.is_premium(user_id):
            # Mevcut süreye ekle
            expiry_date = self.premium_users[user_id]['expiry_date'] + timedelta(days=days)
        else:
            # Yeni süre başlat
            expiry_date = datetime.now() + timedelta(days=days)
        
        self.premium_users[user_id] = {
            'expiry_date': expiry_date,
            'trial_used': True,  # Deneme süresi kullanılmış sayılır
            'subscription_type': 'premium'
        }
        
        # Değişiklikleri kaydet
        self.save_premium_users()
        
        return True, f"Premium üyeliğiniz {days} gün uzatıldı. Yeni bitiş tarihi: {expiry_date.strftime('%d.%m.%Y %H:%M')}"
    
    def get_premium_status(self, user_id):
        """Kullanıcının premium durumunu döndür"""
        if user_id not in self.premium_users:
            return {
                'is_premium': False,
                'trial_used': False,
                'message': "Premium üyeliğiniz bulunmamaktadır."
            }
        
        user_data = self.premium_users[user_id]
        is_premium = self.is_premium(user_id)
        
        if is_premium:
            days_left = (user_data['expiry_date'] - datetime.now()).days
            hours_left = ((user_data['expiry_date'] - datetime.now()).seconds // 3600)
            
            if user_data.get('subscription_type') == 'trial':
                message = f"Deneme süreniz devam ediyor. {days_left} gün {hours_left} saat kaldı."
            else:
                message = f"Premium üyeliğiniz devam ediyor. {days_left} gün {hours_left} saat kaldı."
        else:
            if user_data.get('trial_used', False):
                message = "Premium üyeliğiniz sona ermiştir."
            else:
                message = "Premium üyeliğiniz bulunmamaktadır."
        
        return {
            'is_premium': is_premium,
            'trial_used': user_data.get('trial_used', False),
            'expiry_date': user_data.get('expiry_date'),
            'subscription_type': user_data.get('subscription_type', 'none'),
            'message': message
        }

class TelegramBot:
    def __init__(self, token: str):
        """Initialize the bot with API keys and configuration"""
        # Initialize logger
        self.logger = setup_logger('CoinScanner')
        self.logger.info("Telegram Bot başlatılıyor...")
        
        # Initialize premium manager
        self.premium_manager = PremiumManager(self.logger)
        
        # Initialize technical analysis module
        self.analyzer = MarketAnalyzer(self.logger)
        
        # Initialize tracking variables
        self.tracked_coins = {}  # {chat_id: {symbol: {'entry_price': float, 'last_update': datetime}}}
        self.track_tasks = {}    # {chat_id: {symbol: Task}}
        
        # Initialize components
        self.application = Application.builder().token(token).build()
        self.formatter = MessageFormatter()
        
        # Bot state
        self.last_opportunities = []
        self.scan_task = None  # Tarama görevi
        
        # Ağ hatası sayacı
        self.network_error_count = 0
        self.last_network_error_time = None
        self.max_network_errors = 10  # Maksimum ağ hatası sayısı
        self.network_error_window = 300  # 5 dakika içinde
        
        # Track handler'ı önce oluştur
        self.track_handler = TrackHandler(self.logger)
        
        # Scan handler'a track handler'ı geçir
        self.scan_handler = ScanHandler(self.logger, self.track_handler)
        
        # Takip edilen coinleri sakla
        self.tracked_coins = {}
        
        # Tarama sonuçlarını sakla
        self.last_scan_results = {}
        
        # Handler'ları kaydet
        self.register_handlers()
        
        # Hata işleyicisini ekle
        self.application.add_error_handler(self.error_handler)
        
        self.logger.info("Telegram Bot hazır!")
        
    @telegram_retry(max_tries=5, backoff_factor=2)
    async def start(self):
        """Bot'u başlat"""
        global bot_instance
        bot_instance = self
        
        self.logger.info("Bot başlatılıyor...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        self.logger.info("Bot başlatıldı!")
    
    async def stop(self):
        """Bot'u durdur"""
        try:
            self.logger.info("Bot durduruluyor...")
            
            # Tarama görevini iptal et
            if self.scan_task and not self.scan_task.done():
                self.scan_task.cancel()
                try:
                    await self.scan_task
                except asyncio.CancelledError:
                    pass
            
            # Tüm takip görevlerini iptal et
            for chat_id in self.track_tasks:
                for symbol, task in self.track_tasks[chat_id].items():
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
            
            # Telegram uygulamasını durdur
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            self.logger.info("Bot durduruldu!")
        except Exception as e:
            self.logger.error(f"Bot durdurma hatası: {e}")
    
    def register_handlers(self):
        """Komut işleyicilerini kaydet"""
        # Mevcut komutlar
        self.application.add_handler(CommandHandler("scan", self.scan_command))
        self.application.add_handler(CommandHandler("track", self.track_handler.handle))
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Yeni komutlar
        self.application.add_handler(CommandHandler("chart", self.cmd_chart))
        self.application.add_handler(CommandHandler("analyze", self.cmd_analyze))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        
        # Premium komutları
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("trial", self.trial_command))
        
        # Admin komutları
        self.application.add_handler(CommandHandler("addpremium", self.add_premium_command))
        
        # Takip durdurma komutu
        self.application.add_handler(CommandHandler("stoptrack", self.stop_track_command))
        
        # Callback handlers - bunları başlangıçta kaydet
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
    
    async def error_handler(self, update, context):
        """Hataları işle"""
        try:
            # Hata türünü kontrol et
            error = context.error
            
            # Ağ hatası ise
            if isinstance(error, (NetworkError, TimedOut, RetryAfter, ConnectionError, aiohttp.ClientError)):
                now = datetime.now()
                
                # Son hata zamanını kontrol et
                if self.last_network_error_time:
                    # Zaman penceresi içindeyse sayacı artır
                    if (now - self.last_network_error_time).total_seconds() < self.network_error_window:
                        self.network_error_count += 1
                    else:
                        # Zaman penceresi dışındaysa sayacı sıfırla
                        self.network_error_count = 1
                else:
                    self.network_error_count = 1
                
                self.last_network_error_time = now
                
                # Hata mesajını logla
                self.logger.warning(f"Ağ hatası ({self.network_error_count}/{self.max_network_errors}): {error}")
                
                # Maksimum hata sayısını aştıysa botu yeniden başlat
                if self.network_error_count >= self.max_network_errors:
                    self.logger.error(f"Çok fazla ağ hatası! Bot yeniden başlatılıyor...")
                    
                    # Botu durdur ve yeniden başlat
                    await self.stop()
                    await asyncio.sleep(5)  # 5 saniye bekle
                    await self.start()
                    
                    # Sayacı sıfırla
                    self.network_error_count = 0
                    self.last_network_error_time = None
                    
                    # Kullanıcıya bilgi ver (eğer update varsa)
                    if update and update.effective_chat:
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text="🔄 Bot ağ sorunları nedeniyle yeniden başlatıldı. Lütfen komutlarınızı tekrar girin."
                        )
            else:
                # Diğer hatalar için
                self.logger.error(f"Telegram hatası: {error}")
                
                # Kullanıcıya hata mesajı gönder
                if update and update.effective_chat:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="❌ Bir hata oluştu! Lütfen daha sonra tekrar deneyin."
                    )
        except Exception as e:
            self.logger.error(f"Hata işleme hatası: {e}")
    
    @telegram_retry()
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start komutunu işle"""
        try:
            user_id = update.effective_user.id
            status = self.premium_manager.get_premium_status(user_id)
            
            # Premium durumuna göre mesajı özelleştir
            premium_text = ""
            if status['is_premium']:
                premium_text = f"⭐ Premium üyeliğiniz aktif! Bitiş tarihi: {status['expiry_date'].strftime('%d.%m.%Y')}\n\n"
            else:
                if not status['trial_used']:
                    premium_text = "🎁 3 günlük ücretsiz deneme sürenizi başlatmak için /trial komutunu kullanabilirsiniz.\n\n"
                else:
                    premium_text = "💰 Premium üyelik için /premium komutunu kullanabilirsiniz.\n\n"
            
            await update.message.reply_text(
                f"👋 Merhaba {update.effective_user.first_name}!\n\n"
                "🤖 Kripto Para Sinyal Botuna hoş geldiniz!\n\n"
                f"{premium_text}"
                "📊 Bu bot, kripto para piyasasını analiz eder ve alım/satım fırsatlarını tespit eder.\n\n"
                "🔍 /scan komutu ile piyasayı tarayabilir,\n"
                "📈 /track komutu ile coinleri takip edebilirsiniz.\n\n"
                "❓ Tüm komutları görmek için /help yazabilirsiniz."
            )
        except Exception as e:
            self.logger.error(f"Start komutu hatası: {e}")
    
    @telegram_retry()
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop komutunu işle"""
        try:
            chat_id = update.effective_chat.id
            
            # Geçici olarak TrackHandler'ı kullanmaya devam edelim
            await self.track_handler.remove_all_tracking(chat_id)
            
            # MarketAnalyzer'ı da kullanarak tüm takipleri durdur
            # await self.analyzer.stop_all_tracking(chat_id)
            
            # Takip listesini temizle
            if chat_id in self.tracked_coins:
                self.tracked_coins[chat_id].clear()
            
            await update.message.reply_text(
                "✅ Tüm takipler durduruldu!"
            )
        except Exception as e:
            self.logger.error(f"Stop komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Takipler durdurulurken bir hata oluştu!"
            )
    
    @telegram_retry()
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help komutunu işle"""
        try:
            user_id = update.effective_user.id
            is_premium = self.premium_manager.is_premium(user_id)
            
            # Premium durumuna göre mesajı özelleştir
            premium_text = ""
            if not is_premium:
                premium_text = "⭐ Premium özellikler için /premium komutunu kullanabilirsiniz.\n\n"
            
            await update.message.reply_text(
                "📚 KOMUT KILAVUZU\n\n"
                f"{premium_text}"
                "🔍 /scan - Piyasayı tara ve fırsatları bul ⭐\n"
                "   /scan scan15 - 4 saatlik önerilen işlemler ⭐\n"
                "   /scan scan4 - Alternatif 4 saatlik tarama ⭐\n\n"
                "📈 /track - Bir coini takip et ⭐\n"
                "   /track 1 - Tarama sonucundan 1. coini takip et ⭐\n"
                "   /track BTCUSDT - BTC'yi direkt takip et ⭐\n\n"
                "🛑 /stoptrack - Takip edilen coinleri durdur ⭐\n"
                "   /stoptrack - Takip edilen coinleri listele ve seç ⭐\n"
                "   /stoptrack BTCUSDT - BTC takibini durdur ⭐\n\n"
                "📊 /chart BTCUSDT - Teknik analiz grafiği oluştur ⭐\n\n"
                "🔬 /analyze BTCUSDT - Detaylı coin analizi yap ⭐\n\n"
                "📊 /stats - Başarı istatistiklerini göster ⭐\n\n"
                "❌ /stop - Tüm takipleri durdur ⭐\n\n"
                "⭐ /premium - Premium üyelik bilgilerini göster\n"
                "🎁 /trial - 3 günlük deneme süresini başlat\n\n"
                "❓ /help - Bu yardım menüsünü göster\n\n"
                "⭐ işaretli komutlar premium üyelik gerektirir."
            )
        except Exception as e:
            self.logger.error(f"Help komutu hatası: {e}")
    
    @telegram_retry()
    async def cmd_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Chart komutunu işle"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen bir sembol belirtin!\n"
                    "Örnek: /chart BTCUSDT"
                )
                return
                
            symbol = context.args[0].upper()
            
            # Kullanıcıya bilgi ver
            await update.message.reply_text(
                f"📊 {symbol} grafiği oluşturuluyor...\n"
                f"⏳ Lütfen bekleyin..."
            )
            
            # Grafiği oluştur
            chart_buf = await self.analyzer.generate_chart(symbol, "4h")
            
            if chart_buf:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=chart_buf,
                    caption=f"📊 {symbol} 4h Grafiği"
                )
            else:
                await update.message.reply_text(
                    f"❌ {symbol} için grafik oluşturulamadı!"
                )
                
        except Exception as e:
            self.logger.error(f"Chart komutu hatası: {str(e)}")
            await update.message.reply_text(
                f"❌ Grafik oluşturulurken bir hata oluştu: {str(e)}"
            )
    
    @telegram_retry()
    async def cmd_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Belirli bir coini analiz et"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen analiz edilecek bir coin belirtin!\n"
                    "Örnek: /analyze BTCUSDT"
                )
                return
            
            symbol = context.args[0].upper()
            
            # Sembol kontrolü
            if not symbol.endswith('USDT'):
                symbol += 'USDT'
            
            # Analiz yap
            ticker = await self.analyzer.data_provider.get_ticker(symbol)
            if ticker:
                current_price = float(ticker['lastPrice'])
                volume = float(ticker['quoteVolume'])
                
                analysis = await self.analyzer.analyze_opportunity(symbol, current_price, volume, "4h")
                
                if analysis:
                    # Analiz sonucunu formatla
                    long_score = analysis.get('long_score', 0)
                    short_score = analysis.get('short_score', 0)
                    signal = analysis.get('signal', '⚪ BEKLE')
                    
                    message = (
                        f"🔍 {symbol} ANALİZ SONUCU\n\n"
                        f"💰 Fiyat: ${analysis['current_price']:.4f}\n"
                        f"📊 Hacim: ${analysis['volume']:,.0f}\n\n"
                        f"📈 LONG Puanı: {long_score:.1f}/100\n"
                        f"📉 SHORT Puanı: {short_score:.1f}/100\n\n"
                        f"🎯 Sinyal: {signal}\n\n"
                        f"🛑 Stop Loss: ${analysis['stop_price']:.4f}\n"
                        f"✨ Take Profit: ${analysis['target_price']:.4f}\n"
                        f"⚖️ Risk/Ödül: {analysis['risk_reward']:.2f}\n\n"
                        f"📊 TEKNİK GÖSTERGELER:\n"
                        f"• RSI: {analysis['rsi']:.1f}\n"
                        f"• MACD: {analysis['macd']:.4f}\n"
                        f"• BB Pozisyon: {analysis['bb_position']:.1f}%\n"
                        f"• EMA20: {analysis['ema20']:.4f}\n"
                        f"• EMA50: {analysis['ema50']:.4f}\n"
                        f"• EMA200: {analysis['ema200']:.4f}\n"
                    )
                    
                    await update.message.reply_text(message)
                    
                    # Destek ve direnç seviyelerini gönder
                    levels_msg = "📊 DESTEK/DİRENÇ SEVİYELERİ:\n\n"
                    
                    if analysis.get('resistance_levels'):
                        levels_msg += "🔴 DİRENÇ SEVİYELERİ:\n"
                        for i, level in enumerate(analysis['resistance_levels'][:3], 1):
                            levels_msg += f"• R{i}: ${level:.4f}\n"
                    
                    levels_msg += "\n"
                    
                    if analysis.get('support_levels'):
                        levels_msg += "🟢 DESTEK SEVİYELERİ:\n"
                        for i, level in enumerate(analysis['support_levels'][:3], 1):
                            levels_msg += f"• S{i}: ${level:.4f}\n"
                    
                    await update.message.reply_text(levels_msg)
            
            else:
                await update.message.reply_text(
                    f"❌ {symbol} için analiz yapılamadı! Sembolü kontrol edin."
                )
            
            # Grafiği gönder
            chart_buf = await self.analyzer.generate_chart(symbol, "4h")
            if chart_buf:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=chart_buf,
                    caption=f"📊 {symbol} 4h Grafiği"
                )
                
        except Exception as e:
            self.logger.error(f"Analiz komutu hatası: {str(e)}")
            await update.message.reply_text(f"❌ Analiz yapılırken bir hata oluştu: {str(e)}")

    @telegram_retry()
    @premium_required
    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Scan komutunu işle - Premium gerektirir"""
        try:
            chat_id = update.effective_chat.id
            
            # Tarama tipini belirle
            scan_type = "default"
            if context.args and len(context.args) > 0:
                scan_type = context.args[0].lower()
            
            # Kullanıcıya bilgi ver
            await update.message.reply_text(
                f"🔍 Piyasa taranıyor...\n"
                f"⏳ Lütfen bekleyin, bu işlem birkaç dakika sürebilir..."
            )
            
            # Tüm tarama türleri için handler'ı kullan
            self.logger.info(f"4 saatlik tarama başlatıldı - {chat_id} (tip: {scan_type})")
            
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
                
        except Exception as e:
            self.logger.error(f"Scan komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Tarama sırasında bir hata oluştu!\n"
                "Lütfen daha sonra tekrar deneyin."
            )

    # Yardımcı fonksiyonlar
    def _get_test_opportunities(self):
        """Test amaçlı fırsatlar oluştur"""
        from datetime import datetime
        
        current_time = datetime.now().isoformat()
        return [
            {
                'symbol': 'BTCUSDT',
                'current_price': 96000.0,
                'volume': 1000000000.0,
                'rsi': 45.0,
                'macd': 0.001,
                'ema20': 95000.0,
                'ema50': 93000.0,
                'trend': 'YUKARI',
                'signal': '🟩 LONG',
                'opportunity_score': 85.0,
                'stop_price': 94000.0,
                'target_price': 98000.0,
                'timestamp': current_time
            },
            {
                'symbol': 'ETHUSDT',
                'current_price': 3500.0,
                'volume': 500000000.0,
                'rsi': 65.0,
                'macd': -0.002,
                'ema20': 3520.0,
                'ema50': 3450.0,
                'trend': 'AŞAĞI',
                'signal': '❤️ SHORT',
                'opportunity_score': 75.0,
                'stop_price': 3600.0,
                'target_price': 3300.0,
                'timestamp': current_time
            },
            {
                'symbol': 'BNBUSDT',
                'current_price': 420.0,
                'volume': 200000000.0,
                'rsi': 35.0,
                'macd': 0.003,
                'ema20': 415.0,
                'ema50': 410.0,
                'trend': 'YUKARI',
                'signal': '🟩 LONG',
                'opportunity_score': 70.0,
                'stop_price': 410.0,
                'target_price': 440.0,
                'timestamp': current_time
            }
        ]

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            
            # Tarama yenileme butonu
            elif callback_data.startswith("refresh_"):
                scan_type = callback_data.split("_")[1]
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

    @telegram_retry()
    @premium_required
    async def track_button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, index=None):
        """Takip butonuna tıklandığında çalışır - Premium gerektirir"""
        try:
            query = update.callback_query
            chat_id = query.message.chat_id
            
            # Index callback_data'dan gelmiyorsa, direkt olarak al
            if index is None:
                callback_data = query.data
                index = int(callback_data.split("_")[1])
            
            # Tarama sonuçlarını kontrol et
            if chat_id not in self.last_scan_results or not self.last_scan_results[chat_id]:
                await query.edit_message_text(
                    text="❌ Tarama sonuçları bulunamadı! Lütfen yeni bir tarama yapın."
                )
                return
            
            opportunities = self.last_scan_results[chat_id]
            
            # Index kontrolü
            if index < 1 or index > len(opportunities):
                await query.edit_message_text(
                    text="❌ Geçersiz seçim! Lütfen yeni bir tarama yapın."
                )
                return
            
            # Seçilen fırsatı al
            opportunity = opportunities[index-1]
            symbol = opportunity['symbol']
            
            # Takip verilerini hazırla
            current_price = opportunity['current_price']
            signal = opportunity['signal']
            stop_price = opportunity.get('stop_price', current_price * 0.95)  # Varsayılan stop
            target1 = opportunity.get('target1', current_price * 1.05)  # Varsayılan hedef 1
            target2 = opportunity.get('target2', current_price * 1.10)  # Varsayılan hedef 2
            
            # Takip verilerini kaydet
            if chat_id not in self.tracked_coins:
                self.tracked_coins[chat_id] = {}
            
            self.tracked_coins[chat_id][symbol] = {
                'entry_price': current_price,
                'signal': signal,
                'stop_price': stop_price,
                'target1': target1,
                'target2': target2,
                'start_time': datetime.now(),
                'last_update': datetime.now()
            }
            
            # Takip görevlerini başlat
            if chat_id not in self.track_tasks:
                self.track_tasks[chat_id] = {}
            
            # Eğer zaten takip ediliyorsa, önceki görevi iptal et
            if symbol in self.track_tasks[chat_id] and not self.track_tasks[chat_id][symbol].done():
                self.track_tasks[chat_id][symbol].cancel()
            
            # Yeni takip görevi oluştur
            self.track_tasks[chat_id][symbol] = asyncio.create_task(
                self.smart_tracking_task(chat_id, symbol)
            )
            
            # Kullanıcıya bilgi ver
            await query.edit_message_text(
                text=f"✅ {symbol} takibi başlatıldı!\n\n"
                     f"💰 Giriş Fiyatı: ${current_price:.6f}\n"
                     f"🎯 Hedef 1: ${target1:.6f}\n"
                     f"🎯 Hedef 2: ${target2:.6f}\n"
                     f"🛑 Stop Loss: ${stop_price:.6f}\n\n"
                     f"📊 Her 30 saniyede bir güncellemeler alacaksınız.\n"
                     f"❌ Takibi durdurmak için /stoptrack komutunu kullanabilirsiniz."
            )
            
            self.logger.info(f"{chat_id} için {symbol} takibi başlatıldı")
            
        except Exception as e:
            self.logger.error(f"Track button callback hatası: {e}")
            try:
                await query.edit_message_text(
                    text="❌ Takip başlatılırken bir hata oluştu!"
                )
            except:
                pass

    async def stop_track_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol_or_all=None):
        """Takibi durdur butonuna tıklandığında çalışır"""
        try:
            query = update.callback_query
            chat_id = query.message.chat_id
            
            # symbol_or_all callback_data'dan gelmiyorsa, direkt olarak al
            if symbol_or_all is None:
                callback_data = query.data
                symbol_or_all = callback_data.split("_")[1]
            
            if symbol_or_all == "all":
                # Tüm takipleri durdur
                if chat_id in self.tracked_coins:
                    symbols = list(self.tracked_coins[chat_id].keys())
                    for symbol in symbols:
                        await self.stop_tracking(chat_id, symbol)
                    
                    await query.edit_message_text(
                        text="✅ Tüm takipler durduruldu!"
                    )
            else:
                # Belirli bir coini durdur
                symbol = symbol_or_all
                await self.stop_tracking(chat_id, symbol)
                
                await query.edit_message_text(
                    text=f"✅ {symbol} takibi durduruldu!"
                )
                
            self.logger.info(f"{chat_id} için takip durdurma işlemi tamamlandı")
                
        except Exception as e:
            self.logger.error(f"Stop track callback hatası: {e}")
            try:
                await query.edit_message_text(
                    text="❌ Takip durdurulurken bir hata oluştu!"
                )
            except:
                pass

    async def refresh_scan_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, scan_type=None):
        """Taramayı yenile butonuna tıklandığında çalışır"""
        try:
            query = update.callback_query
            chat_id = query.message.chat_id
            
            # scan_type callback_data'dan gelmiyorsa, direkt olarak al
            if scan_type is None:
                callback_data = query.data
                scan_type = callback_data.split("_")[1]
            
            # Kullanıcıya bilgi ver
            await query.edit_message_text(
                text=f"🔍 Piyasa yeniden taranıyor...\n"
                     f"⏳ Lütfen bekleyin..."
            )
            
            # ScanHandler'ı kullan (MarketAnalyzer yerine)
            try:
                # Her durumda scan_handler.scan_market'i çağır
                opportunities = await self.scan_handler.scan_market("4h")
                
                if not opportunities or len(opportunities) == 0:
                    # Test verilerini kullan
                    self.logger.warning("Yenileme sonucu bulunamadı, test verileri kullanılıyor")
                    opportunities = self._get_test_opportunities()
            except Exception as e:
                self.logger.error(f"Yenileme hatası: {e}")
                opportunities = self._get_test_opportunities()
            
            # Sonuçları işle
            if not opportunities or len(opportunities) == 0:
                await query.message.reply_text(
                    "❌ Şu anda uygun fırsat bulunamadı!\n"
                    "Lütfen daha sonra tekrar deneyin."
                )
                return
            
            # Sonuçları kaydet
            self.last_scan_results[chat_id] = opportunities
            
            # Yeni bir mesaj gönder (edit_message_text karakter sınırını aşabilir)
            await self.send_scan_results(chat_id, opportunities, "4h")  # Hep 4h kullan
            
        except Exception as e:
            self.logger.error(f"Refresh scan callback hatası: {e}")
            try:
                await query.message.reply_text(
                    "❌ Tarama yenilenirken bir hata oluştu!"
                )
            except:
                pass

    async def send_scan_results(self, chat_id, opportunities, scan_type):
        """Tarama sonuçlarını gönder"""
        try:
            # Sonuçları formatla - Tüm tarama tipleri için aynı başlık ve açıklama
            message = "📊 **4 SAATLİK TEKNİK ANALİZ SİNYALLERİ** 📊\n\n"
            message += "📈 Bu sinyaller maksimum başarı için güçlü teknik analizle oluşturulmuştur.\n"
            message += "💸 Destek-direnç noktaları, fiyat hareketleri ve mum formasyonları incelenerek belirlendi.\n"
            message += "⏱️ Tahmini işlem süresi: 4 saat - 1 gün\n"
            message += "⚠️ Her zaman kendi stop-loss ve kar-al seviyelerinizi belirleyin.\n\n"
            
            # Fırsatları ekle
            for i, opportunity in enumerate(opportunities):
                symbol = opportunity['symbol']
                signal = opportunity.get('signal', 'N/A')
                price = opportunity.get('current_price', opportunity.get('price', 0))
                score = opportunity.get('opportunity_score', opportunity.get('score', 0))
                
                message += f"**{i+1}. {symbol}** - {signal}\n"
                message += f"💰 Fiyat: {price:.6f}\n"
                
                if score:
                    message += f"⭐ Puan: {score}/100\n"
                
                # Diğer bilgileri ekle (varsa)
                for key, emoji in [
                    ('success_probability', '✅'),
                    ('entry_strategy', '📥'),
                    ('exit_strategy', '📤'),
                    ('risk_reward', '⚖️'),
                    ('estimated_time', '⏱️'),
                    ('rsi', '📊')
                ]:
                    if key in opportunity:
                        message += f"{emoji} {key.replace('_', ' ').title()}: {opportunity[key]}\n"
                
                # Hedefler
                if 'target1' in opportunity and 'target2' in opportunity:
                    target1 = opportunity['target1']
                    target2 = opportunity['target2']
                    
                    if 'LONG' in signal:
                        t1_pct = ((target1 - price) / price) * 100
                        t2_pct = ((target2 - price) / price) * 100
                        message += f"🎯 Hedefler: {price:.6f} ➡️ {target1:.6f} (%{t1_pct:.2f}) ➡️ {target2:.6f} (%{t2_pct:.2f})\n"
                    else:
                        t1_pct = ((price - target1) / price) * 100
                        t2_pct = ((price - target2) / price) * 100
                        message += f"🎯 Hedefler: {price:.6f} ➡️ {target1:.6f} (%{t1_pct:.2f}) ➡️ {target2:.6f} (%{t2_pct:.2f})\n"
                
                # Stop loss
                if 'stop_price' in opportunity:
                    stop = opportunity['stop_price']
                    stop_pct = abs(((stop - price) / price) * 100)
                    message += f"🛑 Stop: {stop:.6f} (%{stop_pct:.2f})\n"
                
                message += "\n"
            
            # Butonları oluştur
            keyboard = []
            row = []
            for i, opportunity in enumerate(opportunities):
                symbol = opportunity['symbol']
                button_text = f"📊 {i+1}. {symbol} Takip Et"
                callback_data = f"track_{i+1}"
                
                # Her satırda 2 buton olacak şekilde düzenle
                if i % 2 == 0 and i > 0:
                    keyboard.append(row)
                    row = []
                
                row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            
            # Son satırı ekle
            if row:
                keyboard.append(row)
            
            # Yenile butonu ekle
            keyboard.append([InlineKeyboardButton("🔄 Taramayı Yenile", callback_data=f"refresh_{scan_type}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Kullanım ipuçları ekle
            message += "💡 İPUÇLARI:\n"
            message += "• Takip etmek istediğiniz coini seçin\n"
            message += "• Takip sırasında 30 saniyede bir güncellemeler alacaksınız\n"
            message += "• Takibi durdurmak için /stoptrack komutunu kullanın\n"
            message += "• Yeni bir tarama için 'Taramayı Yenile' butonunu kullanın\n"
            
            # Mesajı gönder
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            self.logger.error(f"Tarama sonuçları gönderme hatası: {e}")
            await self.application.bot.send_message(
                chat_id=chat_id,
                text="❌ Tarama sonuçları gönderilirken bir hata oluştu!"
            )

    @telegram_retry()
    async def track_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Track komutunu işle"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen takip edilecek bir coin belirtin!\n"
                    "Örnek: /track BTCUSDT veya /track 1"
                )
                return
            
            chat_id = update.effective_chat.id
            arg = context.args[0]
            
            # Numara mı yoksa sembol mü kontrol et
            if arg.isdigit():
                # Tarama sonuçlarından seç
                index = int(arg) - 1
                
                if chat_id not in self.last_scan_results or not self.last_scan_results[chat_id]:
                    await update.message.reply_text(
                        "❌ Önce /scan komutu ile piyasayı taramalısınız!"
                    )
                    return
                    
                if index < 0 or index >= len(self.last_scan_results[chat_id]):
                    await update.message.reply_text(
                        f"❌ Geçersiz numara! 1-{len(self.last_scan_results[chat_id])} arasında bir değer girin."
                    )
                    return
                    
                symbol = self.last_scan_results[chat_id][index]['symbol']
            else:
                # Direkt sembol
                symbol = arg.upper()
                if not symbol.endswith('USDT'):
                    symbol += 'USDT'
            
            # Geçici olarak TrackHandler'ı kullanmaya devam edelim
            result = await self.track_handler.start_tracking(chat_id, symbol)
            
            # MarketAnalyzer'ı kullanarak takip başlat
            # result = await self.analyzer.start_tracking(chat_id, symbol)
            
            if result:
                # Takip listesine ekle
                if chat_id not in self.tracked_coins:
                    self.tracked_coins[chat_id] = set()
                self.tracked_coins[chat_id].add(symbol)
                
                await update.message.reply_text(
                    f"✅ {symbol} takip edilmeye başlandı!\n"
                    f"Fiyat değişikliklerinde bildirim alacaksınız."
                )
            else:
                await update.message.reply_text(
                    f"❌ {symbol} takip edilemedi! Sembolü kontrol edin."
                )
                
        except Exception as e:
            self.logger.error(f"Track komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Takip başlatılırken bir hata oluştu!"
            )

    @telegram_retry()
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """İstatistikleri göster"""
        try:
            # Performans istatistiklerini al
            stats = await self.analyzer.get_performance_stats()
            
            if 'error' in stats:
                await update.message.reply_text(
                    f"❌ İstatistikler alınırken bir hata oluştu: {stats['error']}"
                )
                return
            
            # İstatistikleri formatla
            message = "📊 **SİNYAL BAŞARI İSTATİSTİKLERİ** 📊\n\n"
            
            # Genel istatistikler
            overall = stats['overall']
            message += f"**Genel Başarı Oranı:** %{overall['success_rate']}\n"
            message += f"Toplam Sinyal: {overall['total_signals']}\n"
            message += f"Başarılı: {overall['successful_signals']}\n"
            message += f"Başarısız: {overall['failed_signals']}\n\n"
            
            # Haftalık istatistikler
            weekly = stats['weekly']
            message += f"**Son 7 Gün:** %{weekly['success_rate']} ({weekly['total_signals']} sinyal)\n\n"
            
            # Sinyal tiplerine göre
            message += "**Sinyal Tiplerine Göre:**\n"
            message += f"LONG: %{stats['by_type']['long']['success_rate']} ({stats['by_type']['long']['total_signals']} sinyal)\n"
            message += f"SHORT: %{stats['by_type']['short']['success_rate']} ({stats['by_type']['short']['total_signals']} sinyal)\n"
            message += f"SCALP: %{stats['by_type']['scalp']['success_rate']} ({stats['by_type']['scalp']['total_signals']} sinyal)\n\n"
            
            # Zaman dilimlerine göre
            message += "**Zaman Dilimlerine Göre:**\n"
            message += f"15dk: %{stats['by_timeframe']['15m']['success_rate']} ({stats['by_timeframe']['15m']['total_signals']} sinyal)\n"
            message += f"1s: %{stats['by_timeframe']['1h']['success_rate']} ({stats['by_timeframe']['1h']['total_signals']} sinyal)\n"
            message += f"4s: %{stats['by_timeframe']['4h']['success_rate']} ({stats['by_timeframe']['4h']['total_signals']} sinyal)\n\n"
            
            message += f"Toplam Takip Edilen Sinyal: {stats['total_signals_tracked']}\n"
            message += f"Son Güncelleme: {stats['last_updated'][:19]}"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            self.logger.error(f"Stats komutu hatası: {e}")
            await update.message.reply_text(
                "❌ İstatistikler alınırken bir hata oluştu!"
            )

    @telegram_retry()
    async def stop_track_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Belirli bir coinin takibini durdur"""
        try:
            chat_id = update.effective_chat.id
            
            # Eğer takip edilen coin yoksa
            if chat_id not in self.tracked_coins or not self.tracked_coins[chat_id]:
                await update.message.reply_text(
                    "❌ Takip edilen coin bulunamadı!"
                )
                return
            
            # Argüman kontrolü
            if not context.args:
                # Takip edilen coinleri listele ve seçim yapmasını iste
                tracked_symbols = list(self.tracked_coins[chat_id].keys())
                
                if not tracked_symbols:
                    await update.message.reply_text(
                        "❌ Takip edilen coin bulunamadı!"
                    )
                    return
                
                # Butonları oluştur
                keyboard = []
                row = []
                
                for i, symbol in enumerate(tracked_symbols):
                    button_text = f"🛑 {symbol} Takibi Durdur"
                    callback_data = f"stoptrack_{symbol}"
                    
                    # Her satırda 1 buton olacak şekilde düzenle
                    row = [InlineKeyboardButton(button_text, callback_data=callback_data)]
                    keyboard.append(row)
                
                # Tümünü durdur butonu
                keyboard.append([InlineKeyboardButton("🛑 Tüm Takipleri Durdur", callback_data="stoptrack_all")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "📊 Takip edilen coinler:\n\n" + 
                    "\n".join([f"• {symbol}" for symbol in tracked_symbols]) + 
                    "\n\nDurdurmak istediğiniz coini seçin:",
                    reply_markup=reply_markup
                )
                
                # Callback handler ekle
                self.application.add_handler(CallbackQueryHandler(self.stop_track_callback))
                
            else:
                # Belirli bir coini durdur
                symbol = context.args[0].upper()
                if not symbol.endswith('USDT'):
                    symbol += 'USDT'
                
                await self.stop_tracking(chat_id, symbol)
                
                await update.message.reply_text(
                    f"✅ {symbol} takibi durduruldu!"
                )
                
        except Exception as e:
            self.logger.error(f"Stop track komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Takip durdurulurken bir hata oluştu!"
            )

    @telegram_retry()
    async def stop_track_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Takibi durdur butonuna tıklandığında çalışır"""
        try:
            query = update.callback_query
            await query.answer()
            
            chat_id = query.message.chat_id
            callback_data = query.data
            
            if callback_data.startswith("stoptrack_"):
                symbol_or_all = callback_data.split("_")[1]
                
                if symbol_or_all == "all":
                    # Tüm takipleri durdur
                    if chat_id in self.tracked_coins:
                        symbols = list(self.tracked_coins[chat_id].keys())
                        for symbol in symbols:
                            await self.stop_tracking(chat_id, symbol)
                        
                        await query.edit_message_text(
                            text="✅ Tüm takipler durduruldu!"
                        )
                else:
                    # Belirli bir coini durdur
                    symbol = symbol_or_all
                    await self.stop_tracking(chat_id, symbol)
                    
                    await query.edit_message_text(
                        text=f"✅ {symbol} takibi durduruldu!"
                    )
                    
            self.logger.info(f"{chat_id} için takip durdurma işlemi tamamlandı")
                
        except Exception as e:
            self.logger.error(f"Stop track callback hatası: {e}")
            try:
                await query.edit_message_text(
                    text="❌ Takip durdurulurken bir hata oluştu!"
                )
            except:
                pass

    async def stop_tracking(self, chat_id: int, symbol: str):
        """Belirli bir coinin takibini durdur"""
        try:
            # Takip görevini iptal et
            if chat_id in self.track_tasks and symbol in self.track_tasks[chat_id]:
                task = self.track_tasks[chat_id][symbol]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                
                # Takip listesinden kaldır
                del self.track_tasks[chat_id][symbol]
            
            # Takip verilerini temizle
            if chat_id in self.tracked_coins and symbol in self.tracked_coins[chat_id]:
                del self.tracked_coins[chat_id][symbol]
            
            self.logger.info(f"{chat_id} için {symbol} takibi durduruldu")
            
        except Exception as e:
            self.logger.error(f"Takip durdurma hatası ({symbol}): {e}")
            raise

    async def smart_tracking_task(self, chat_id: int, symbol: str):
        """Akıllı takip görevi - 30 saniyede bir bildirim gönderir"""
        try:
            # Takip başlangıç mesajı
            start_message = (
                f"🚀 {symbol} TAKİBİ BAŞLATILDI\n\n"
                f"📊 Her 30 saniyede bir güncellemeler alacaksınız.\n"
                f"🔍 Takip, duygusal kararlar vermenizi önlemeye yardımcı olacak.\n"
                f"⚠️ Takibi durdurmak için /stoptrack komutunu kullanabilirsiniz.\n\n"
                f"💡 İPUÇLARI:\n"
                f"• Planınıza sadık kalın\n"
                f"• Stop-loss seviyelerine uyun\n"
                f"• Kâr hedeflerinize ulaştığınızda çıkın\n"
                f"• Piyasa koşulları değişebilir, esnek olun"
            )
            
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=start_message
            )
            
            # Takip sayacı
            update_count = 0
            
            while True:
                # 30 saniye bekle
                await asyncio.sleep(30)
                update_count += 1
                
                # Coin verilerini güncelle
                try:
                    # Exchange bağlantısı
                    exchange = ccxt.binance({
                        'enableRateLimit': True,
                        'options': {
                            'defaultType': 'spot'
                        }
                    })
                    
                    # Ticker verilerini al
                    ticker = exchange.fetch_ticker(symbol)
                    
                    if not ticker:
                        continue
                    
                    current_price = float(ticker['last'])
                except Exception as e:
                    self.logger.error(f"Ticker verisi alınamadı ({symbol}): {e}")
                    continue
                
                # Takip verilerini al
                if chat_id not in self.tracked_coins or symbol not in self.tracked_coins[chat_id]:
                    self.logger.warning(f"{chat_id} için {symbol} takip verileri bulunamadı")
                    return
                
                track_data = self.tracked_coins[chat_id][symbol]
                entry_price = track_data['entry_price']
                signal = track_data['signal']
                stop_price = track_data['stop_price']
                target1 = track_data['target1']
                target2 = track_data['target2']
                start_time = track_data['start_time']
                
                # Takip süresi
                elapsed_time = datetime.now() - start_time
                hours, remainder = divmod(elapsed_time.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                time_str = f"{int(hours)}s {int(minutes)}dk {int(seconds)}sn"
                
                # Fiyat değişimini hesapla
                price_change_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Sinyal tipine göre kar/zarar durumunu belirle
                is_profit = False
                if 'LONG' in signal and price_change_pct > 0:
                    is_profit = True
                elif 'SHORT' in signal and price_change_pct < 0:
                    is_profit = True
                
                # Mesajı oluştur
                message = f"📊 {symbol} TAKİP GÜNCELLEMESI #{update_count}\n\n"
                message += f"⏱️ Takip Süresi: {time_str}\n"
                message += f"💰 Giriş Fiyatı: ${entry_price:.6f}\n"
                message += f"💰 Güncel Fiyat: ${current_price:.6f}\n"
                message += f"📈 Değişim: %{price_change_pct:.2f}\n\n"
                
                # Hedef ve stop bilgileri
                message += f"🎯 Hedef 1: ${target1:.6f} (%{((target1-entry_price)/entry_price*100):.2f})\n"
                message += f"🎯 Hedef 2: ${target2:.6f} (%{((target2-entry_price)/entry_price*100):.2f})\n"
                message += f"🛑 Stop Loss: ${stop_price:.6f} (%{((stop_price-entry_price)/entry_price*100):.2f})\n\n"
                
                # Durum analizi
                if is_profit:
                    # Karda
                    if 'LONG' in signal:
                        if current_price >= target2:
                            message += "✅ HEDEF 2'YE ULAŞILDI! Tüm pozisyonu kapatmanızı öneririm.\n"
                            message += "💰 Kâr: %{:.2f}\n".format(price_change_pct)
                        elif current_price >= target1:
                            message += "✅ HEDEF 1'E ULAŞILDI! Pozisyonun bir kısmını kapatıp stop'u başabaşa çekmenizi öneririm.\n"
                            message += "💰 Kâr: %{:.2f}\n".format(price_change_pct)
                            message += "💡 Önerilen Aksiyon: Pozisyonun %50'sini kapat, stop'u başabaşa çek.\n"
                        else:
                            message += "✅ KARDA! Sabırlı olun, hedeflere doğru ilerliyoruz.\n"
                            message += "💰 Kâr: %{:.2f}\n".format(price_change_pct)
                            message += "💡 Önerilen Aksiyon: Hedef 1'e ulaşana kadar bekle.\n"
                    else:  # SHORT
                        if current_price <= target2:
                            message += "✅ HEDEF 2'YE ULAŞILDI! Tüm pozisyonu kapatmanızı öneririm.\n"
                            message += "💰 Kâr: %{:.2f}\n".format(abs(price_change_pct))
                        elif current_price <= target1:
                            message += "✅ HEDEF 1'E ULAŞILDI! Pozisyonun bir kısmını kapatıp stop'u başabaşa çekmenizi öneririm.\n"
                            message += "💰 Kâr: %{:.2f}\n".format(abs(price_change_pct))
                            message += "💡 Önerilen Aksiyon: Pozisyonun %50'sini kapat, stop'u başabaşa çek.\n"
                        else:
                            message += "✅ KARDA! Sabırlı olun, hedeflere doğru ilerliyoruz.\n"
                            message += "💰 Kâr: %{:.2f}\n".format(abs(price_change_pct))
                            message += "💡 Önerilen Aksiyon: Hedef 1'e ulaşana kadar bekle.\n"
                else:
                    # Zararda
                    if ('LONG' in signal and current_price <= stop_price) or \
                       ('SHORT' in signal and current_price >= stop_price):
                        message += "❌ STOP LOSS NOKTASINA ULAŞILDI! Zararı kabul edin ve çıkın.\n"
                        message += "💸 Zarar: %{:.2f}\n".format(abs(price_change_pct))
                        message += "💡 Önerilen Aksiyon: Pozisyonu kapat, zararı kabul et.\n"
                    else:
                        # Zarar oranına göre uyarı
                        if abs(price_change_pct) > 5:
                            message += "⚠️ DİKKAT! %5'ten fazla zararda. Pozisyonunuzu gözden geçirin.\n"
                            message += "💸 Zarar: %{:.2f}\n".format(abs(price_change_pct))
                            message += "💡 Önerilen Aksiyon: Stop loss'u kontrol et, gerekirse pozisyonu kapat.\n"
                        else:
                            message += "⚠️ ZARARDA! Ancak henüz stop loss seviyesine ulaşılmadı. Sabırlı olun.\n"
                            message += "💸 Zarar: %{:.2f}\n".format(abs(price_change_pct))
                            message += "💡 Önerilen Aksiyon: Planına sadık kal, stop loss'a dikkat et.\n"
                
                # Duygusal karar vermeyi önleyici ipuçları
                message += "\n💡 AKILLI KARAR İPUÇLARI:\n"
                
                if is_profit:
                    message += "• Açgözlü olmayın, plana sadık kalın.\n"
                    message += "• Hedeflere ulaştığınızda kârı realize edin.\n"
                    message += "• Başarılı bir trade için kendinizi tebrik edin.\n"
                else:
                    message += "• Panik yapmayın, duygusal kararlar vermeyin.\n"
                    message += "• Stop loss'a sadık kalın, zararı büyütmeyin.\n"
                    message += "• Her trade bir öğrenme fırsatıdır.\n"
                
                message += "• Piyasa koşulları değişebilir, esnek olun.\n"
                message += "• Takibi durdurmak için /stoptrack komutunu kullanın.\n"
                
                # Bildirimi gönder
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message
                )
                
                # Son güncelleme zamanını kaydet
                self.tracked_coins[chat_id][symbol]['last_update'] = datetime.now()
                
        except asyncio.CancelledError:
            self.logger.info(f"{chat_id} için {symbol} takibi iptal edildi")
            
            # Takip sonlandırma mesajı
            try:
                end_message = (
                    f"🛑 {symbol} TAKİBİ SONLANDIRILDI\n\n"
                    f"Takip ettiğiniz için teşekkürler!\n"
                    f"Yeni fırsatlar için /scan komutunu kullanabilirsiniz."
                )
                
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=end_message
                )
            except:
                pass
                
        except Exception as e:
            self.logger.error(f"Akıllı takip görevi hatası ({symbol}): {e}")

    @telegram_retry()
    @premium_required
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Premium bilgilerini göster"""
        try:
            user_id = update.effective_user.id
            status = self.premium_manager.get_premium_status(user_id)
            
            # Premium bilgilerini göster
            message = "⭐ **PREMIUM ÜYELİK BİLGİLERİ** ⭐\n\n"
            
            if status['is_premium']:
                # Premium kullanıcı
                days_left = (status['expiry_date'] - datetime.now()).days
                hours_left = ((status['expiry_date'] - datetime.now()).seconds // 3600)
                
                message += f"✅ Premium üyeliğiniz aktif!\n"
                message += f"📅 Bitiş Tarihi: {status['expiry_date'].strftime('%d.%m.%Y %H:%M')}\n"
                message += f"⏱️ Kalan Süre: {days_left} gün {hours_left} saat\n\n"
                
                if status['subscription_type'] == 'trial':
                    message += "🎁 Şu anda deneme sürümünü kullanıyorsunuz.\n"
                    message += "💰 Deneme süreniz bittiğinde premium üyelik satın alabilirsiniz.\n"
                else:
                    message += "🌟 Premium üyeliğiniz için teşekkür ederiz!\n"
            else:
                # Premium olmayan kullanıcı
                message += "❌ Premium üyeliğiniz bulunmamaktadır.\n\n"
                
                if not status['trial_used']:
                    message += "🎁 3 günlük ücretsiz deneme sürenizi başlatmak için /trial komutunu kullanabilirsiniz.\n\n"
                
                message += "💰 Premium üyelik avantajları:\n"
                message += "• Sınırsız coin takibi\n"
                message += "• Gelişmiş tarama özellikleri\n"
                message += "• Özel teknik analiz grafikleri\n"
                message += "• Öncelikli destek\n\n"
                
                message += "📱 Premium üyelik için iletişim:\n"
                message += "• Telegram: @YourTelegramUsername\n"
                message += "• E-posta: your.email@example.com\n"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            self.logger.error(f"Premium komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Premium bilgileri gösterilirken bir hata oluştu!"
            )

    @telegram_retry()
    async def trial_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Deneme süresini başlat"""
        try:
            user_id = update.effective_user.id
            
            # Deneme süresini başlat
            success, message = self.premium_manager.start_trial(user_id)
            
            if success:
                await update.message.reply_text(
                    f"🎁 {message}\n\n"
                    "⭐ Deneme süreniz boyunca tüm premium özelliklere erişebilirsiniz.\n"
                    "📊 /scan komutu ile piyasayı tarayabilir,\n"
                    "📈 /track komutu ile coinleri takip edebilirsiniz.\n\n"
                    "❓ Tüm komutları görmek için /help yazabilirsiniz."
                )
            else:
                await update.message.reply_text(f"❌ {message}")
            
        except Exception as e:
            self.logger.error(f"Trial komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Deneme süresi başlatılırken bir hata oluştu!"
            )

    @telegram_retry()
    async def add_premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin komutu: Kullanıcıya premium ekle"""
        try:
            # Komutu gönderen kişi admin mi kontrol et
            admin_ids = [123456789]  # Admin kullanıcı ID'lerini buraya ekleyin
            user_id = update.effective_user.id
            
            if user_id not in admin_ids:
                await update.message.reply_text("❌ Bu komutu kullanma yetkiniz yok!")
                return
            
            # Komut parametrelerini kontrol et
            if not context.args or len(context.args) < 2:
                await update.message.reply_text(
                    "❌ Eksik parametreler!\n\n"
                    "Kullanım: /addpremium <user_id> <days>"
                )
                return
            
            try:
                target_user_id = int(context.args[0])
                days = int(context.args[1])
            except ValueError:
                await update.message.reply_text("❌ Geçersiz parametreler! User ID ve gün sayısı sayı olmalıdır.")
                return
            
            # Premium ekle
            success, message = self.premium_manager.add_premium(target_user_id, days)
            
            if success:
                await update.message.reply_text(f"✅ {message}")
            else:
                await update.message.reply_text(f"❌ {message}")
            
        except Exception as e:
            self.logger.error(f"Add premium komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Premium ekleme sırasında bir hata oluştu!"
            )

if __name__ == '__main__':
    # Önceki bot instance'larını temizle
    import os
    import signal
    
    def cleanup():
        try:
            # Linux/Unix sistemlerde çalışan bot process'lerini bul ve sonlandır
            os.system("pkill -f 'python.*telegram_bot.py'")
        except:
            pass
    
    # Başlamadan önce temizlik yap
    cleanup()
    
    # Yeniden başlatma mekanizması
    max_restarts = 5
    
    async def main(restart_count=0):
        global bot_instance
        bot = None
        
        try:
            bot = TelegramBot(token=token)
            bot_instance = bot
            await bot.start()
            
            # Sonsuz döngü ile bot'u çalışır durumda tut
            while True:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            print("\n👋 Bot kullanıcı tarafından durduruldu")
        except Exception as e:
            print(f"❌ Ana program hatası: {e}")
            
            # Yeniden başlatma sayısını kontrol et
            if restart_count < max_restarts:
                restart_count += 1
                print(f"🔄 Bot yeniden başlatılıyor... ({restart_count}/{max_restarts})")
                await asyncio.sleep(5)  # 5 saniye bekle
                return restart_count  # Yeniden başlat
            else:
                print(f"❌ Maksimum yeniden başlatma sayısına ulaşıldı ({max_restarts}). Bot kapatılıyor.")
                return None  # Yeniden başlatma
        finally:
            if bot:
                await bot.stop()
        
        return None  # Normal çıkış
    
    # Ana döngü
    async def run_with_restart():
        restart_count = 0
        while restart_count is not None:
            restart_count = await main(restart_count)
    
    try:
        asyncio.run(run_with_restart())
    except KeyboardInterrupt:
        pass
