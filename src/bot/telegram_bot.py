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

class TelegramBot:
    def __init__(self, token: str):
        """Initialize the bot with API keys and configuration"""
        # Initialize logger
        self.logger = setup_logger('CoinScanner')
        self.logger.info("Telegram Bot başlatılıyor...")
        
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
            await update.message.reply_text(
                f"👋 Merhaba {update.effective_user.first_name}!\n\n"
                "🤖 Kripto Para Sinyal Botuna hoş geldiniz!\n\n"
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
            await update.message.reply_text(
                "📚 KOMUT KILAVUZU\n\n"
                "🔍 /scan - Piyasayı tara ve fırsatları bul\n"
                "   /scan scan15 - 15 dakikalık hızlı al-çık fırsatları\n"
                "   /scan scan4 - 4 saatlik tarama\n\n"
                "📈 /track - Bir coini takip et\n"
                "   /track 1 - Tarama sonucundan 1. coini takip et\n"
                "   /track BTCUSDT - BTC'yi direkt takip et\n\n"
                "📊 /chart BTCUSDT - Teknik analiz grafiği oluştur\n\n"
                "🔬 /analyze BTCUSDT - Detaylı coin analizi yap\n\n"
                "📊 /stats - Başarı istatistiklerini göster\n\n"
                "❌ /stop - Tüm takipleri durdur\n\n"
                "❓ /help - Bu yardım menüsünü göster"
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
    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Scan komutunu işle"""
        try:
            chat_id = update.effective_chat.id
            
            # Tarama tipini belirle
            scan_type = "default"
            if context.args and len(context.args) > 0:
                scan_type = context.args[0].lower()
            
            # Kullanıcıya bilgi ver
            await update.message.reply_text(
                f"🔍 Piyasa taranıyor...\n"
                f"⏳ Lütfen bekleyin..."
            )
            
            # Tarama tipine göre işlem yap
            if scan_type == "scan15":
                # 15 dakikalık tarama
                self.logger.info(f"15 dakikalık tarama başlatıldı - {chat_id}")
                opportunities = await self.analyzer.scan15()
                
                if not opportunities or len(opportunities) == 0:
                    await update.message.reply_text(
                        "❌ Şu anda uygun al-çık fırsatı bulunamadı!\n"
                        "Lütfen daha sonra tekrar deneyin."
                    )
                    return
                
                # Sonuçları kaydet
                self.last_scan_results[chat_id] = opportunities
                
                # Sonuçları formatla ve gönder
                message = "⚡ **HIZLI AL-ÇIK FIRSATLARI (15dk)** ⚡\n\n"
                
                for i, opportunity in enumerate(opportunities):
                    symbol = opportunity['symbol']
                    signal = opportunity['signal']
                    price = opportunity['current_price']
                    score = opportunity['opportunity_score']
                    success_prob = opportunity['success_probability']
                    entry_strategy = opportunity.get('entry_strategy', 'N/A')
                    exit_strategy = opportunity.get('exit_strategy', 'N/A')
                    
                    message += f"**{i+1}. {symbol}** - {signal}\n"
                    message += f"💰 Fiyat: {price:.6f}\n"
                    message += f"⭐ Puan: {score}/100\n"
                    message += f"✅ Başarı Olasılığı: {success_prob}\n"
                    message += f"📥 Giriş: {entry_strategy}\n"
                    message += f"📤 Çıkış: {exit_strategy}\n"
                    
                    # Hedefler
                    if 'target1' in opportunity and 'target2' in opportunity:
                        target1 = opportunity['target1']
                        target2 = opportunity['target2']
                        
                        if 'LONG' in signal:
                            message += f"🎯 Hedefler: {price:.6f} ➡️ {target1:.6f} ➡️ {target2:.6f}\n"
                        else:
                            message += f"🎯 Hedefler: {price:.6f} ➡️ {target1:.6f} ➡️ {target2:.6f}\n"
                    
                    # Stop loss
                    if 'stop_price' in opportunity:
                        stop = opportunity['stop_price']
                        message += f"🛑 Stop: {stop:.6f}\n"
                    
                    # Tahmini süre
                    if 'estimated_time' in opportunity:
                        message += f"⏱️ Tahmini Süre: {opportunity['estimated_time']}\n"
                    
                    message += "\n"
                
                message += "📊 Takip etmek için: /track <numara>\n"
                message += "📈 Grafik için: /chart <sembol>"
                
                await update.message.reply_text(message, parse_mode='Markdown')
                
            elif scan_type == "scan4":
                # 4 saatlik tarama
                self.logger.info(f"4 saatlik tarama başlatıldı - {chat_id}")
                opportunities = await self.analyzer.scan4h()
                
                # Sonuçları işle
                # ... (mevcut kod)
            else:
                # Varsayılan tarama
                self.logger.info(f"Varsayılan tarama başlatıldı - {chat_id}")
                opportunities = await self.scan_handler.scan_market()
                
                # Sonuçları işle
                # ... (mevcut kod)
                
        except Exception as e:
            self.logger.error(f"Scan komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Tarama sırasında bir hata oluştu!"
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
