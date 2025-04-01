from src.bot.ai_analysis_command import cmd_aianalysis
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
from .modules.analysis.dual_timeframe_analyzer import DualTimeframeAnalyzer
from .modules.handlers.scan_handler import ScanHandler
from .modules.handlers.track_handler import TrackHandler
from .modules.message_formatter import MessageFormatter
from .modules.scalp_command import cmd_scalp, _format_scalp_result, _format_scalp_opportunities
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
import mplfinance as mpf
from PIL import Image, ImageDraw, ImageFont
import base64
import functools
import random
from .modules.analysis.dual_timeframe_analyzer import DualTimeframeAnalyzer
from .modules.analysis.market import MarketAnalyzer
from logging.handlers import RotatingFileHandler
# Multi timeframe handler'ı başlangıçta import etme, lazım olduğunda et
# from src.bot.multi_timeframe_handler import MultiTimeframeHandler
from src.analysis.ai_analyzer import AIAnalyzer

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

def setup_logger(name: str) -> logging.Logger:
    """Bot için logger ayarla"""
    # Log klasörünü oluştur
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Logger oluştur
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Dosya handler'ı ekle (rotasyonlu)
    log_file = os.path.join(log_dir, f'{name}.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    
    # Konsol handler'ı ekle
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Formatter oluştur
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler'lara formatter ekle
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Logger'a handler'ları ekle
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

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
        
        # Initialize exchange connection
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        
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
        
        # Market analyzer'ı ekle
        self.analyzer = MarketAnalyzer(self.logger)
        self.dual_analyzer = self.analyzer  # MarketAnalyzer'ı dual analyzer olarak da kullan
        
        # Son tarama sonuçlarını saklamak için dict
        self.last_scan_results = {}
        
        # Handler'ları kaydet
        self.register_handlers()
        
        # Hata işleyicisini ekle
        self.application.add_error_handler(self.error_handler)
        
        self.logger.info("Telegram Bot hazır!")
        
        # MultiTimeframeHandler'ı başlat ve sadece bir kez oluştur
        try:
            if not hasattr(self, 'multi_handler') or self.multi_handler is None:
                from src.bot.multi_timeframe_handler import MultiTimeframeHandler
                self.multi_handler = MultiTimeframeHandler(logger=self.logger, bot_instance=self)
                self.logger.info("MultiTimeframeHandler başarıyla başlatıldı")
        except Exception as e:
            self.logger.error(f"MultiTimeframeHandler başlatma hatası: {e}")
            # Hata olsa bile devam edebilmek için varsayılan bir değer atayalım
            self.multi_handler = None
        
    @telegram_retry(max_tries=5, backoff_factor=2)
    async def start(self):
        """Bot'u başlat"""
        global bot_instance
        bot_instance = self
        
        self.logger.info("Bot başlatılıyor...")
        
        # Bot başlatılıyor
        await self.application.initialize()
        
        # MultiTimeframeHandler'ı initialize et (eğer daha önce oluşurulmadıysa)
        try:
            if hasattr(self, 'multi_handler') and self.multi_handler is not None and not hasattr(self.multi_handler, '_initialized'):
                await self.multi_handler.initialize()
                self.multi_handler._initialized = True
                self.logger.info("MultiTimeframeHandler başarıyla initialize edildi")
        except Exception as e:
            self.logger.error(f"MultiTimeframeHandler initialize hatası: {e}")
        
        # Diğer başlatma işlemleri
        await self.application.start()
        
        # MultiTimeframeHandler'ın komutlarını kaydet (sadece bir kez)
        try:
            if hasattr(self, 'multi_handler') and self.multi_handler is not None and not hasattr(self.multi_handler, '_handlers_registered'):
                self.multi_handler.register_handlers(self.application)
                self.multi_handler._handlers_registered = True
                self.logger.info("MultiTimeframeHandler komutları kaydedildi")
        except Exception as e:
            self.logger.error(f"MultiTimeframeHandler komut kayıt hatası: {e}")
        
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
        self.application.add_handler(CommandHandler("scalp", self.cmd_scalp))
        
        # Premium komutları
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("trial", self.trial_command))
        
        # Admin komutları
        self.application.add_handler(CommandHandler("addpremium", self.add_premium_command))
        
        # Takip durdurma komutu
        self.application.add_handler(CommandHandler("stoptrack", self.stop_track_command))
        
        # AI Analiz komutu
        self.application.add_handler(CommandHandler("aianalysis", self.cmd_aianalysis))
        
        # Otomatik İşlem Sistemi komutları
        try:
            from src.bot.modules.autotrader_handler import AutoTraderHandler
            autotrader_handler = AutoTraderHandler(self.logger)
            autotrader_handler.register_handlers(self.application)
            self.logger.info("AutoTrader komutları kaydedildi")
        except Exception as e:
            self.logger.error(f"AutoTrader handler yüklenemedi: {e}")
        
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
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Bot komutları hakkında yardım mesajı gönderir"""
        help_text = (
            "📚 *Coinim Bot Komutları* 📚\n\n"
            
            "🔍 *Temel Tarama Komutları:*\n"
            "/scan - Tüm market için fırsat taraması yapar\n"
            "/scalp - Tek bir coin için scalping analizi yapar\n"
            "/multiscan - Çoklu zaman dilimi analizi yapar (Haftalık + Saatlik + 15dk)\n\n"
            
            "📈 *Analiz Komutları:*\n"
            "/analysis - Detaylı teknik analiz gösterir\n"
            "/chart - Teknik analiz grafiği oluşturur\n"
            "/pattern - Fiyat formasyonları taraması yapar\n\n"
            
            "🧠 *Strateji Komutları:*\n"
            "/vwap - VWAP bazlı alım-satım stratejisi için fırsat tarar\n"
            "/rsi - RSI bazlı alım-satım stratejisi için fırsat tarar\n"
            "/dca - Dollar Cost Average (TL maliyeti düşürme) stratejisi hesaplar\n\n"
            
            "ℹ️ *Bilgi Komutları:*\n"
            "/price - Anlık fiyat bilgisi verir\n"
            "/cap - Market hacmi ve sıralama bilgisi verir\n"
            "/info - Coin hakkında temel bilgiler gösterir\n\n"
            
            "⚙️ *Özel Komutlar:*\n"
            "/alert - Belirli bir fiyat seviyesi için alarm kurar\n"
            "/settings - Bot ayarlarını değiştirir\n"
            "/track - Bir coini takibe alır\n\n"
            
            "🆕 *Yeni Eklenen:*\n"
            "/multiscan - Üç farklı zaman dilimi (haftalık, saatlik, 15dk) kullanarak en iyi alım fırsatlarını bulur\n"
            "Örnek: /multiscan veya /multiscan BTCUSDT\n\n"
            
            "📱 *Nasıl Kullanılır:*\n"
            "- Coin sembolünü USDT ile belirtin (örn: BTCUSDT)\n"
            "- Ayrıntılı bilgi için bir komutu tek başına yazabilirsiniz\n"
            "- Tüm komutlar ücretsiz olarak kullanılabilir\n"
        )
        
        await update.message.reply_text(
            help_text,
            parse_mode='Markdown'
        )
    
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
    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Market taraması yapar"""
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
                    self.logger.warning("Tarama sonucu bulunamadı")
                    await update.message.reply_text(
                        "❌ Şu anda uygun işlem fırsatı bulunamadı!\n"
                        "Lütfen daha sonra tekrar deneyin.\n\n"
                        "💡 İPUCU: Piyasa koşulları sürekli değişir. Piyasada faaliyetin artmasını bekleyebilirsiniz."
                    )
                    return
                    
            except Exception as e:
                self.logger.error(f"Tarama hatası: {e}")
                await update.message.reply_text(
                    "❌ Tarama sırasında bir hata oluştu!\n"
                    "Lütfen daha sonra tekrar deneyin."
                )
                return
            
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

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Tüm callback query'leri işle"""
        # Callback'i hemen yanıtla - kullanıcıya işlenmiş gözüksün
        await update.callback_query.answer()
        
        try:
            query = update.callback_query
            callback_data = query.data
            chat_id = query.message.chat_id
            user_id = query.from_user.id
            
            # Önemli: İşlem başladığını günlüğe yaz
            self.logger.info(f"Callback işleniyor: {callback_data} - {chat_id}")
            
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
                
            # Çoklu zaman dilimi analizi için callback işleyici
            elif callback_data == "refresh_multi":
                try:
                    if self.multi_handler:
                        await self.multi_handler.refresh_multi_callback(update, context)
                    else:
                        await update.callback_query.answer("Çoklu zaman dilimi modülü başlatılamadı!")
                except Exception as e:
                    self.logger.error(f"Çoklu zaman dilimi yenileme hatası: {e}")
                    await update.callback_query.answer("Çoklu zaman dilimi yenileme hatası!")
            
            # AI Analiz butonu için
            elif callback_data.startswith("aianalysis_coin_"):
                try:
                    symbol = callback_data.split("_")[-1]  # Son bölüm symbol
                    await query.answer(f"{symbol} için AI analizi başlatılıyor...")
                    
                    # API anahtarı kontrolü
                    from dotenv import load_dotenv
                    import os
                    load_dotenv()
                    api_key = os.getenv('ANTHROPIC_API_KEY')
                    if not api_key:
                        await query.message.reply_text(
                            "❌ Anthropic API anahtarı bulunamadı!\n"
                            ".env dosyanıza ANTHROPIC_API_KEY eklemeniz gerekiyor."
                        )
                        return
                    
                    # Kullanıcıya bilgi ver
                    msg = await query.message.reply_text(
                        f"🧠 {symbol} için GPT analizi yapılıyor...\n"
                        "Teknik veriler ve piyasa koşulları inceleniyor...\n"
                        "⏳ Lütfen bekleyin (30-40 saniye sürebilir)..."
                    )
                    
                    # AI Analyzer oluştur - eğer yoksa yeni olutur, varsa mevcudu kullan
                    if not hasattr(self, '_ai_analyzer'):
                        self._ai_analyzer = AIAnalyzer(self.logger)
                    
                    # Tek coin analizi yap
                    await self._analyze_single_coin_with_ai(chat_id, symbol, msg, self._ai_analyzer)
                    
                except Exception as e:
                    self.logger.error(f"Coin AI analiz callback hatası: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
                    try:
                        await query.message.reply_text(
                            f"❌ {symbol} için AI analiz işlemi sırasında bir hata oluştu!"
                        )
                    except:
                        pass
                
        except Exception as e:
            self.logger.error(f"Callback işleme hatası: {e}")
            try:
                await update.callback_query.message.reply_text(
                    "❌ İşlem sırasında bir hata oluştu!"
                )
            except:
                pass

    @telegram_retry()
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
                    self.logger.warning("Yenileme sonucu bulunamadı")
                    await query.edit_message_text(
                        "❌ Şu anda uygun işlem fırsatı bulunamadı!\n"
                        "Lütfen daha sonra tekrar deneyin.\n\n"
                        "💡 İPUCU: Piyasa koşulları sürekli değişir. Piyasada faaliyetin artmasını bekleyebilirsiniz."
                    )
                    return
            except Exception as e:
                self.logger.error(f"Yenileme hatası: {e}")
                await query.edit_message_text(
                    "❌ Tarama yenilenirken bir hata oluştu!\n"
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
        """Tarama sonuçlarını gönderir."""
        try:
            if not opportunities:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Şu anda {scan_type} türünde işlem fırsatı bulunamadı!"
                )
                return

            # Opportunities listesindeki anahtar adlarını kontrol et ve düzelt
            if opportunities and scan_type != "scalp":
                # Scan sonuçlarında 'current_price' yerine 'price' kullanılıyor olabilir
                for opportunity in opportunities:
                    if 'price' in opportunity and 'current_price' not in opportunity:
                        opportunity['current_price'] = opportunity['price']

            # Sonuçları formatla - tüm scan tipleri için _format_scalp_opportunities kullan
            try:
                message = self._format_scalp_opportunities(opportunities)
            except KeyError as ke:
                self.logger.error(f"Anahtar bulunamadı: {ke}")
                # Basit formatlanmış mesaj oluştur
                message = f"🔍 {scan_type.upper()} Tarama Sonuçları:\n\n"
                for i, opp in enumerate(opportunities[:10], 1):
                    symbol = opp.get('symbol', 'Bilinmeyen')
                    score = opp.get('opportunity_score', opp.get('score', 0))
                    message += f"{i}. {symbol} - Puan: {score:.1f}/100\n"
        
            # AI Analiz butonu ekle
            keyboard = []
            for i, opp in enumerate(opportunities[:5], 1):
                symbol = opp.get('symbol', 'BILINMEYEN')
                button_text = f"🧠 {symbol} Analiz Et"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"aianalysis_coin_{symbol}")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Mesajı gönder
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            
            # MarketAnalyzer için grafik oluşturma işlemini atla
            # Sadece DualTimeframeAnalyzer (scalp) için grafik oluştur
            if scan_type == "scalp" and opportunities and hasattr(self, 'dual_analyzer'):
                top_opportunity = opportunities[0]
                try:
                    chart_buf = await self.dual_analyzer.generate_enhanced_scalp_chart(
                        top_opportunity['symbol'], 
                        top_opportunity
                    )
                    if chart_buf:
                        await self.application.bot.send_photo(
                            chat_id=chat_id,
                            photo=chart_buf,
                            caption=f"📊 En Yüksek Puanlı Scalp Fırsatı: {top_opportunity['symbol']}"
                        )
                except AttributeError:
                    # DualTimeframeAnalyzer'da metod bulunmuyorsa sessizce geç
                    pass
                except Exception as e:
                    self.logger.error(f"Scalp grafik oluşturma hatası: {str(e)}")
                
        except Exception as e:
            self.logger.error(f"Tarama sonuçları gönderilirken hata: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Tarama sonuçları işlenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
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
                    # Exchange bağlantısı - CCXT sınıfının senkron versiyonunu kullan
                    exchange = ccxt.binance({
                        'enableRateLimit': True,
                        'options': {
                            'defaultType': 'spot'
                        }
                    })
                    
                    # !! Önemli: CCXT'nin senkron versiyonunda await kullanılmaz !!
                    # Bu bir senkron fonksiyon olduğu için await olmadan çağrılmalı
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
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Premium bilgilerini gösterir"""
        user_id = update.effective_user.id
        
        # Premium manager'ı kontrol edelim
        if hasattr(self, 'premium_manager'):
            # Premium özelliği artık ücretsiz
            await update.message.reply_text(
                "🎉 *Premium Özellikler*\n\n"
                "İyi haberler! Tüm premium özelliklerimiz şu anda ücretsiz olarak kullanılabilir.\n\n"
                "✅ Sınırsız tarama ve analiz\n"
                "✅ Gelişmiş teknik analiz grafikleri\n"
                "✅ Çoklu zaman dilimi taraması\n"
                "✅ Scalping fırsatları\n"
                "✅ Ve daha fazlası...\n\n"
                "Sorularınız için: @destek",
                parse_mode='Markdown'
            )
        else:
            # Premium manager yoksa
            await update.message.reply_text(
                "🎉 Tüm özelliklerimiz şu anda ücretsiz olarak kullanılabilir!",
                parse_mode='Markdown'
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

    @telegram_retry()
    async def cmd_scalp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Scalping fırsatları için tarama yapar"""
        try:
            chat_id = update.effective_chat.id
            
            # Parametreleri kontrol et
            symbol = None
            if context.args and len(context.args) > 0:
                symbol = context.args[0].upper()
                if not symbol.endswith('USDT'):
                    symbol += 'USDT'
            
            # Başlama mesajı gönder
            msg = await update.message.reply_text(
                "🔍 Kısa vadeli ticaret fırsatları aranıyor...\n"
                "Bu analiz 15 dakikalık ve 1 saatlik grafikleri birlikte kullanır.\n"
                "⏳ Lütfen bekleyin..."
            )
            
            # DualTimeframeAnalyzer oluştur
            dual_analyzer = DualTimeframeAnalyzer(self.logger)
            await dual_analyzer.initialize()
            
            # Tek coin analizi veya genel tarama
            if symbol:
                try:
                    # DualTimeframeAnalyzer ile analiz yap
                    analysis_result = await dual_analyzer.analyze_dual_timeframe(symbol)
                    
                    if not analysis_result:
                        await msg.edit_text(f"❌ {symbol} için analiz yapılamadı! Sembolü kontrol edin veya daha sonra tekrar deneyin.")
                        return
                    
                    # Sinyal metnini oluştur
                    position = analysis_result['position']
                    if 'STRONG_LONG' in position:
                        signal_text = "🟢 GÜÇLÜ LONG"
                    elif 'LONG' in position:
                        signal_text = "🟢 LONG"
                    elif 'STRONG_SHORT' in position:
                        signal_text = "🔴 GÜÇLÜ SHORT"
                    elif 'SHORT' in position:
                        signal_text = "🔴 SHORT"
                    else:
                        signal_text = "⚪ BEKLE"
                    
                    # Sonuç formatı için gerekli verileri hazırla
                    result = {
                        'symbol': symbol,
                        'current_price': analysis_result['current_price'],
                        'volume': analysis_result['volume'],
                        'signal': signal_text,
                        'opportunity_score': analysis_result['opportunity_score'],
                        'stop_price': analysis_result['stop_loss'],
                        'target_price': analysis_result['take_profit'],
                        'risk_reward': analysis_result['risk_reward'],
                        'rsi_1h': analysis_result['rsi_1h'],
                        'rsi': analysis_result['rsi_15m'],  # 15m RSI
                        'macd': analysis_result['macd_15m'],
                        'bb_position': analysis_result['bb_position_15m'],
                        'ema20': analysis_result['ema20_1h'],
                        'ema50': analysis_result['ema50_1h'],
                        'reasons': analysis_result.get('reasons', [])
                    }
                    
                    # Sonucu formatla ve gönder
                    message = self._format_scalp_result(result)
                    
                    # AI Analiz butonu ekle
                    keyboard = [[InlineKeyboardButton("🧠 GPT ile Derin Analiz", callback_data=f"aianalysis_coin_{symbol}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await msg.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup)
                    
                    # Grafik gönder
                    chart_buf = await self.analyzer.generate_chart(symbol, "15m")
                    if chart_buf:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=chart_buf,
                            caption=f"📊 {symbol} 15m Grafiği"
                        )
                except Exception as e:
                    self.logger.error(f"Tek coin analiz hatası: {e}")
                    await msg.edit_text(f"❌ {symbol} için analiz yapılırken hata oluştu: {str(e)}")
                    return
            else:
                # Popüler coinleri analiz et
                popular_coins = [
                    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", 
                    "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT"
                ]
                
                # Tarama işlemini başlat
                opportunities = await dual_analyzer.scan_market(popular_coins)
                
                if not opportunities:
                    await msg.edit_text(
                        "❌ Şu anda kısa vadeli işlem fırsatı bulunamadı!\n"
                        "Lütfen daha sonra tekrar deneyin veya belirli bir coin belirtin: /scalp BTCUSDT"
                    )
                    return
                
                # Sonuçları puanlarına göre sırala (zaten sıralanmış geliyor ama emin olmak için)
                opportunities.sort(key=lambda x: x.get('opportunity_score', 0), reverse=True)
                
                # En iyi 5 fırsatı al
                opportunities = opportunities[:5]
                
                # Kullanıcı dostu formata dönüştür
                formatted_opportunities = []
                for opp in opportunities:
                    # Sinyal metnini oluştur
                    position = opp['position']
                    if 'STRONG_LONG' in position:
                        signal_text = "🟢 GÜÇLÜ LONG"
                    elif 'LONG' in position:
                        signal_text = "🟢 LONG"
                    elif 'STRONG_SHORT' in position:
                        signal_text = "🔴 GÜÇLÜ SHORT"
                    elif 'SHORT' in position:
                        signal_text = "🔴 SHORT"
                    else:
                        signal_text = "⚪ BEKLE"
                    
                    formatted_opp = {
                        'symbol': opp['symbol'],
                        'current_price': opp['current_price'],
                        'volume': opp['volume'],
                        'signal': signal_text,
                        'opportunity_score': opp['opportunity_score'],
                        'stop_price': opp['stop_loss'],
                        'target_price': opp['take_profit'],
                        'risk_reward': opp['risk_reward']
                    }
                    formatted_opportunities.append(formatted_opp)
                
                # Sonuçları sakla
                self.last_scan_results[chat_id] = formatted_opportunities
                
                # Sonuçları formatla ve gönder
                message = self._format_scalp_opportunities(formatted_opportunities)
                await msg.edit_text(message, parse_mode='Markdown')
                
                # En iyi fırsatın grafiğini gönder
                if len(formatted_opportunities) > 0:
                    top_symbol = formatted_opportunities[0]['symbol']
                    chart_buf = await self.analyzer.generate_chart(top_symbol, "15m")
                    if chart_buf:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=chart_buf,
                            caption=f"📊 En iyi fırsat: {top_symbol} 15m Grafiği"
                        )
            
        except Exception as e:
            self.logger.error(f"Scalp komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Analiz yapılırken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
            )

    async def _analyze_single_coin_with_ai(self, chat_id, symbol, msg, ai_analyzer):
        """Tek bir coini AI ile analiz eder"""
        try:
            # Ticker verisi al
            try:
                # DÜZELTME: Senkron CCXT API'sini kullan, await kullanma
                exchange = ccxt.binance({
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'spot'
                    }
                })
                # Senkron API çağrısı - await KULLANMA
                ticker_data = exchange.fetch_ticker(symbol)
                current_price = float(ticker_data['last'])
                volume = float(ticker_data['quoteVolume'])
            except Exception as ticker_error:
                self.logger.error(f"Ticker verisi alınamadı: {ticker_error}")
                await msg.edit_text(f"❌ {symbol} için fiyat verisi alınamadı! Sembolü kontrol edin.")
                return
            
            # Teknik analiz yap - doğru parametre sayısıyla çağır
            technical_data = await self.analyzer.analyze_opportunity(symbol)
            if not technical_data:
                await msg.edit_text(f"❌ {symbol} için teknik analiz yapılamadı! Sembolü kontrol edin.")
                return
                
            # AI analizi yap
            ai_result = await ai_analyzer.analyze_opportunity(symbol, technical_data)
            
            # Sonuçları formatla ve gönder
            message = self._format_ai_analysis(symbol, technical_data, ai_result)
            await msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
            
        except Exception as e:
            self.logger.error(f"Tek coin AI analizi hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            await msg.edit_text(f"❌ {symbol} için AI analiz yapılırken hata oluştu: {str(e)}")

    async def _analyze_scan_results_with_ai(self, chat_id, msg, ai_analyzer):
        """Son tarama sonuçlarını AI ile analiz eder"""
        try:
            if chat_id not in self.last_scan_results or not self.last_scan_results[chat_id]:
                await msg.edit_text(
                    "❌ Önce /scan veya /multiscan komutu ile piyasayı taramalısınız!"
                )
                return
                
            # Son tarama sonuçlarını al
            opportunities = self.last_scan_results[chat_id]
            
            # Tarama sonuçlarını AI ile analiz et
            await msg.edit_text(
                "🧠 Tarama sonuçları GPT ile analiz ediliyor...\n"
                "En iyi 5 fırsat inceleniyor...\n"
                "⏳ Lütfen bekleyin..."
            )
            
            # Fırsatların gerekli tüm verileri içerdiğinden emin ol
            for opp in opportunities:
                # Gerekli alanları kontrol et ve düzelt
                if 'price' in opp and 'current_price' not in opp:
                    opp['current_price'] = opp['price']
                if 'symbol' not in opp:
                    continue  # Symbol yoksa analiz edemeyiz
            
            ai_results = await ai_analyzer.analyze_multiple_coins(opportunities)
            
            # Sonuçları formatla ve gönder
            message = self._format_multiple_ai_analysis(ai_results)
            await msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
            
        except Exception as e:
            self.logger.error(f"Çoklu coin AI analizi hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            await msg.edit_text("❌ AI analiz yapılırken bir hata oluştu.")

    def _format_ai_analysis(self, symbol, technical_data, ai_result):
        """AI analiz sonucunu mesaja dönüştür"""
        try:
            tech_score = technical_data.get('opportunity_score', 0)
            fund_score = ai_result.get('fundamental_score', 0)
            total_score = (tech_score + fund_score) / 2
            
            recommendation = "⚪ BEKLE"
            if ai_result.get('recommendation') == "AL" and technical_data.get('signal', '').find('LONG') >= 0:
                recommendation = "🟢 GÜÇLÜ AL"
            elif ai_result.get('recommendation') == "AL":
                recommendation = "🟢 AL"
            elif ai_result.get('recommendation') == "SAT" and technical_data.get('signal', '').find('SHORT') >= 0:
                recommendation = "🔴 GÜÇLÜ SAT"
            elif ai_result.get('recommendation') == "SAT":
                recommendation = "🔴 SAT"
            
            message = (
                f"🧠 **{symbol} DERIN ANALIZ SONUÇLARI** 🧠\n\n"
                f"📊 **Teknik Puan:** {tech_score:.1f}/100\n"
                f"📚 **Temel Puan:** {fund_score:.1f}/100\n"
                f"⭐ **Toplam Puan:** {total_score:.1f}/100\n\n"
                f"🎯 **Tavsiye:** {recommendation}\n\n"
                f"💰 **Fiyat:** ${technical_data.get('current_price', 0):.6f}\n"
                f"📈 **Trend:** {technical_data.get('trend', 'NEUTRAL')}\n\n"
                f"📝 **GPT ANALİZİ:**\n"
                f"{ai_result.get('analysis', 'Analiz bulunamadı.')[:800]}...\n\n"
                f"⚠️ *Bu analiz yatırım tavsiyesi değildir.*"
            )
            
            return message
        
        except Exception as e:
            self.logger.error(f"AI sonuç formatlama hatası: {e}")
            return "❌ Sonuç formatlanırken bir hata oluştu!"

    def _format_multiple_ai_analysis(self, results):
        """Çoklu AI analiz sonucunu mesaja dönüştür"""
        try:
            message = "🧠 **GPT ILE DERIN ANALIZ SONUÇLARI** 🧠\n\n"
            
            # En iyi 5 sonucu göster
            for i, result in enumerate(results[:5], 1):
                symbol = result['symbol']
                tech_score = result.get('opportunity_score', 0)
                fund_score = result.get('fundamental_score', 0)
                total_score = result.get('total_score', 0)
                
                # Tavsiye içeriğini zenginleştir
                recommendation = result.get('ai_recommendation', 'BEKLE')
                icon = "🟢" if recommendation == "AL" else "🔴" if recommendation == "SAT" else "⚪"
                
                # Fiyat ve hedef bilgileri
                current_price = result.get('current_price', 0)
                # Tavsiyeye göre hedef oluştur
                if recommendation == "AL":
                    target = current_price * 1.05  # %5 yükseliş
                    stop = current_price * 0.97   # %3 düşüş
                elif recommendation == "SAT":
                    target = current_price * 0.95  # %5 düşüş
                    stop = current_price * 1.03   # %3 yükseliş
                else:
                    target = current_price
                    stop = current_price
                
                # Analiz metni
                ai_analysis = result.get('ai_analysis', '')
                short_analysis = ai_analysis[:120] + "..." if len(ai_analysis) > 120 else ai_analysis
                
                message += (
                    f"{i}. **{symbol}** - {total_score:.1f}/100\n"
                    f"   💰 Fiyat: ${current_price:.4f} | {icon} **{recommendation}**\n"
                    f"   📊 Teknik: {tech_score:.1f} | 📚 Temel: {fund_score:.1f}\n"
                )
                
                # Eğer BEKLE dışında bir öneri varsa fiyat hedefleri göster
                if recommendation != "BEKLE":
                    risk_reward = abs((target - current_price) / (current_price - stop)) if current_price != stop else 0
                    message += (
                        f"   🎯 Hedef: ${target:.4f} | 🛑 Stop: ${stop:.4f}\n"
                        f"   ⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                    )
                
                # Analiz özeti
                if short_analysis and short_analysis != "...":
                    message += f"   💡 {short_analysis}\n"
                
                message += "\n"
            
            # Detaylı analiz komutu tavsiyesi
            message += (
                "📋 **KULLANIM:**\n"
                "• Detaylı analiz için: `/aianalysis BTCUSDT`\n"
                "• Grafik için: `/chart BTCUSDT`\n\n"
                "⚠️ *Bu analizler yatırım tavsiyesi değildir.*"
            )
            
            return message
        
        except Exception as e:
            self.logger.error(f"Çoklu AI sonuç formatlama hatası: {e}")
            return "❌ Sonuçlar formatlanırken bir hata oluştu!"

    def _format_scalp_result(self, result: Dict) -> str:
        """Scalp analiz sonucunu mesaja dönüştür"""
        try:
            symbol = result['symbol']
            price = result['current_price']
            signal = result.get('signal', '⚪ BEKLE')
            score = result.get('opportunity_score', 0)
            stop_price = result.get('stop_price', price * 0.95)
            target_price = result.get('target_price', price * 1.05)
            
            # Risk/Ödül oranı
            if 'LONG' in signal:
                risk = price - stop_price
                reward = target_price - price
            else:
                risk = stop_price - price
                reward = price - target_price
                
            risk_reward = abs(reward / risk) if risk != 0 else 0
            
            message = (
                f"💰 **{symbol} SCALP FIRSATI** 💰\n\n"
                f"📊 **Analiz Tipi:** 15m/1h Dual Timeframe\n"
                f"🎯 **Sinyal:** {signal}\n"
                f"💵 **Fiyat:** ${price:.6f}\n"
                f"⚡ **Güven:** %{score:.1f}\n\n"
                
                f"📈 **İŞLEM BİLGİLERİ:**\n"
                f"• Giriş Fiyatı: ${price:.6f}\n"
                f"• Stop-Loss: ${stop_price:.6f}\n"
                f"• Take-Profit: ${target_price:.6f}\n"
                f"• Risk/Ödül: {risk_reward:.2f}\n\n"
                
                f"📉 **TEKNİK GÖSTERGELER:**\n"
                f"• RSI (15m): {result.get('rsi', 0):.1f}\n"
                f"• RSI (1h): {result.get('rsi_1h', 0):.1f}\n"
                f"• MACD: {result.get('macd', 0):.6f}\n"
                f"• BB Pozisyonu: %{result.get('bb_position', 0):.1f}\n"
                f"• EMA20: {result.get('ema20', 0):.6f}\n"
                f"• EMA50: {result.get('ema50', 0):.6f}\n\n"
            )
            
            # Analiz nedenleri varsa ekle
            if 'reasons' in result and result['reasons']:
                message += "🔍 **ANALİZ NEDENLERİ:**\n"
                for reason in result['reasons'][:5]:  # En önemli 5 nedeni göster
                    message += f"• {reason}\n"
                message += "\n"
            
            # İpuçları
            message += "💡 **İPUÇLARI:**\n"
            if 'LONG' in signal or 'SHORT' in signal:
                message += (
                    "• Bu kısa vadeli işlem sinyalidir\n"
                    "• Stop-loss seviyesine sadık kalın\n"
                    "• Kârınız hedefin %70'ine ulaştığında stop'u başabaşa çekin\n"
                )
            else:
                message += "• Şu anda net bir işlem sinyali yok, beklemede kalın\n"
            
            return message
            
        except Exception as e:
            self.logger.error(f"Scalp sonuç formatlama hatası: {e}")
            return "❌ Sonuç formatlanırken bir hata oluştu!"

    def _format_scalp_opportunities(self, opportunities: List[Dict]) -> str:
        """Scalp fırsatlarını mesaja dönüştür"""
        try:
            message = "🔥 **KISA VADELİ İŞLEM FIRSATLARI** 🔥\n\n"
            message += "Bu analiz 15 dakikalık grafik verilerini kullanır.\n"
            message += "Her fırsat 5-10$ kar potansiyeli için optimize edilmiştir.\n\n"
            
            message += "📊 **FIRSATLAR:**\n\n"
            
            for i, opp in enumerate(opportunities[:5], 1):
                symbol = opp['symbol']
                signal = opp.get('signal', '⚪ BEKLE')
                price = opp['current_price']
                score = opp.get('opportunity_score', 0)
                stop_price = opp.get('stop_price', price * 0.95)
                target_price = opp.get('target_price', price * 1.05)
                
                # Risk/Ödül hesapla
                if 'LONG' in signal:
                    risk = price - stop_price
                    reward = target_price - price
                else:
                    risk = stop_price - price
                    reward = price - target_price
                    
                risk_reward = abs(reward / risk) if risk != 0 else 0
                
                message += (
                    f"{i}. {symbol} - {signal}\n"
                    f"   💰 Fiyat: ${price:.6f}\n"
                    f"   🛑 Stop: ${stop_price:.6f}\n"
                    f"   🎯 Hedef: ${target_price:.6f}\n"
                    f"   ⚖️ R/R: {risk_reward:.2f}\n"
                    f"   ⭐ Puan: {score:.1f}/100\n\n"
                )
            
            message += (
                "📝 **KULLANIM:**\n"
                "• Belirli bir coin hakkında daha detaylı bilgi için:\n"
                "  `/scalp BTCUSDT`\n\n"
                "⚠️ **RİSK UYARISI:**\n"
                "• Bu sinyaller 15m grafik analizine dayanır\n"
                "• Kısa vadeli işlemlerde her zaman stop-loss kullanın\n"
                "• Yatırımınızın %1-2'sinden fazlasını riske atmayın\n"
            )
            
            return message
            
        except Exception as e:
            self.logger.error(f"Scalp fırsatları formatlama hatası: {e}")
            return "❌ Sonuçlar formatlanırken bir hata oluştu!"

    @telegram_retry()
    async def cmd_aianalysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """AI ile detaylı analiz yapar"""
        try:
            chat_id = update.effective_chat.id
            
            # Parametreleri kontrol et
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen analiz edilecek bir coin belirtin!\n"
                    "Örnek: /aianalysis BTCUSDT"
                )
                return
            
            symbol = context.args[0].upper()
            
            # Sembol kontrolü
            if not symbol.endswith('USDT'):
                symbol += 'USDT'
            
            # Kullanıcıya bilgi ver
            msg = await update.message.reply_text(
                f"🧠 {symbol} için derin AI analizi yapılıyor...\n"
                f"Bu teknik analiz ve temel verileri birleştiren karmaşık bir işlemdir.\n"
                f"⏳ Lütfen bekleyin (1-2 dakika sürebilir)..."
            )
            
            # AI Analyzer oluştur
            from src.analysis.ai_analyzer import AIAnalyzer
            ai_analyzer = AIAnalyzer(self.logger)
            
            # Tek coin için analiz yap
            await self._analyze_single_coin_with_ai(chat_id, symbol, msg, ai_analyzer)
            
        except Exception as e:
            self.logger.error(f"AI analiz komutu hatası: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            try:
                await update.message.reply_text(
                    f"❌ {symbol} için AI analiz yapılırken bir hata oluştu: {str(e)}"
                )
            except:
                await update.message.reply_text(
                    "❌ AI analiz yapılırken bir hata oluştu! Lütfen daha sonra tekrar deneyin."
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
