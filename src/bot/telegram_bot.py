import asyncio
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Set, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from src.analysis.signal_analyzer import SignalAnalyzer
from src.config import TOKEN, ACTIVE_SYMBOLS, POLLING_INTERVAL
import time
from src.analysis.trade_monitor import TradeMonitor
from src.analysis.market_scanner import MarketScanner
from src.analysis.news_tracker import NewsTracker
import pandas as pd
import aiohttp
from bs4 import BeautifulSoup
import re
import ccxt
from dotenv import load_dotenv
import os
from pathlib import Path
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice
from ta.trend import MACD
from ta.volatility import BollingerBands
import numpy as np
from scipy.signal import argrelextrema
import stripe

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

class TelegramBot:
    def __init__(self, token: str):
        """Bot başlatma"""
        self.token = token
        self.application = Application.builder().token(token).build()
        self.bot = self.application.bot  # Bot referansını doğru şekilde al
        self.market_scanner = MarketScanner()
        
        # Tarama ve takip durumları
        self.scan_active = False
        self.track_active = False
        
        # Görev yönetimi
        self.scan_task = None
        self.track_task = None
        self.watch_tasks = {}
        self.monitoring_task = None
        
        # Veri takibi
        self.last_scan_time = None
        self.tracked_prices = {}
        self.tracked_symbols = set()
        self.user_chat_ids = set()
        
        # Komutları ekle
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("scan", self.scan_command))
        self.application.add_handler(CommandHandler("track", self.track_command))
        self.application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/analyze_"), self.analyze_command))
        
        # Initialize analyzers
        self.signal_analyzer = SignalAnalyzer()
        
        # Initialize tracking variables
        self.watched_coins = {}  # {chat_id: {symbol: {'last_alert': datetime, 'entry_price': float}}}
        self.active_symbols = set()  # Aktif takip edilen semboller
        
        # User management
        self.user_chat_ids = set()  # Tüm aktif kullanıcıların chat ID'leri
        
        # Excluded coins
        self.excluded_coins = {
            'USDC/USDT', 'USDD/USDT', 'TUSD/USDT', 'USDD/USDT', 
            'BUSD/USDT', 'DAI/USDT', 'USDP/USDT', 'FDUSD/USDT',
            'UST/USDT', 'SUSD/USDT'
        }  # Stablecoin'ler ve istenmeyen coinler
        
        # Notification control
        self.notification_cooldown = 60  # saniye
        self.last_notification_time = {}  # {symbol: timestamp}
        
        # Setup command handlers
        self._setup_handlers()
        print("🤖 Bot başlatılıyor...")
        
        # Haber kaynakları
        self.news_sources = {
            'coindesk': 'https://www.coindesk.com/search?q={}',
            'cointelegraph': 'https://cointelegraph.com/search?query={}',
            'investing': 'https://tr.investing.com/search/?q={}&tab=news'
        }
        
        # Ödeme sistemi ayarları
        self.stripe = stripe
        self.stripe.api_key = "your_stripe_secret_key"
        
        # Kullanıcı veritabanı (gerçek uygulamada bir DB kullanılmalı)
        self.users: Dict[int, Dict] = {}
        
        # Premium özellik fiyatları
        self.PREMIUM_PRICE = 500  # USD
        self.TRIAL_DAYS = 3
        
    def _setup_handlers(self):
        """Telegram komut işleyicilerini ayarla"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("scan", self.scan_command))
        self.application.add_handler(CommandHandler("track", self.track_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Text handler'ı en sona ekleyin
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.handle_coin_input
            )
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yardım mesajını gönder"""
        help_text = """🤖 Kripto Sinyal Botu - Komutlar

/scan - Piyasa taraması başlat/durdur
/track - Tüm coinleri takip et/durdur
/analyze_BTCUSDT - BTC analizi (diğer coinler için de kullanılabilir)
/help - Bu mesajı göster

ℹ️ Özellikler:
• Otomatik piyasa taraması
• Tüm coinleri takip
• Anlık fiyat bildirimleri
• Detaylı teknik analiz
• Alım/satım sinyalleri"""

        await update.message.reply_text(help_text)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kullanıcı başlangıç komutu"""
        try:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id
            
            # Yeni kullanıcı kontrolü
            if user_id not in self.users:
                trial_end = datetime.now() + timedelta(days=self.TRIAL_DAYS)
                self.users[user_id] = {
                    'trial_end': trial_end,
                    'is_premium': False,
                    'subscription_end': None,
                    'chat_id': chat_id
                }
                
                await update.message.reply_text(
                    f"""🎉 Hoş Geldiniz!

🎯 Size özel 3 günlük ÜCRETSİZ VIP deneme başlatıldı!

✨ Premium Özellikler:
• Anlık kripto sinyalleri
• Detaylı piyasa analizleri
• VIP destek grubu erişimi
• Özel portföy önerileri
• Haftalık strateji raporları
• Risk yönetimi tavsiyeleri

💎 Premium Üyelik: $500/ay

⏰ Deneme Süreniz: {trial_end.strftime('%d/%m/%Y %H:%M')} tarihine kadar

📌 Ödeme Seçenekleri:
• Kredi Kartı
• USDT/USDC

/premium → Premium üyelik bilgileri
/help → Tüm komutlar""")
            else:
                await self._check_and_notify_subscription(user_id)
        
        except Exception as e:
            print(f"Start komut hatası: {str(e)}")

    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Premium üyelik bilgileri ve ödeme"""
        try:
            user_id = update.effective_user.id
            user = self.users.get(user_id)
            
            if not user:
                await update.message.reply_text("❌ Lütfen önce /start komutunu kullanın!")
                return
            
            if user.get('is_premium'):
                sub_end = user.get('subscription_end')
                await update.message.reply_text(
                    f"""✨ Premium Üyeliğiniz Aktif!

⏰ Bitiş Tarihi: {sub_end.strftime('%d/%m/%Y %H:%M')}

/extend → Üyelik uzatma
/cancel → İptal""")
                return
            
            # Ödeme bağlantısı oluştur
            payment_link = await self._create_payment_link(user_id)
            
            await update.message.reply_text(
                f"""💎 Premium Üyelik

💰 Aylık Ücret: $500

✨ Premium Özellikleri:
• Anlık kripto sinyalleri
• Detaylı piyasa analizleri
• VIP destek grubu erişimi
• Özel portföy önerileri
• Haftalık strateji raporları
• Risk yönetimi tavsiyeleri

🎁 Özel Teklifler:
• İlk ay %20 indirim
• Yıllık ödemede 2 ay hediye
• Referans programı

💳 Ödeme için: {payment_link}""")
        
        except Exception as e:
            print(f"Premium komut hatası: {str(e)}")

    async def _check_and_notify_subscription(self, user_id: int):
        """Üyelik durumu kontrolü ve bildirimleri"""
        try:
            user = self.users.get(user_id)
            if not user:
                return
            
            now = datetime.now()
            
            # Deneme süresi kontrolü
            if not user.get('is_premium'):
                trial_end = user.get('trial_end')
                if trial_end:
                    if now > trial_end:
                        # Deneme süresi bitmiş
                        await self.application.bot.send_message(
                            chat_id=user['chat_id'],
                            text="""⚠️ Deneme Süreniz Sona Erdi!

💎 Premium özelliklere erişim için üyelik almanız gerekiyor.

/premium → Üyelik bilgileri""")
                        return False
                    
                    # Son 24 saat ve 6 saat uyarıları
                    hours_left = (trial_end - now).total_seconds() / 3600
                    if 23 < hours_left < 24:
                        await self.application.bot.send_message(
                            chat_id=user['chat_id'],
                            text="""⚠️ Deneme Süreniz Yarın Sona Eriyor!

🎯 Premium üyelik avantajlarından yararlanmaya devam etmek için:
/premium""")
                    elif 5 < hours_left < 6:
                        await self.application.bot.send_message(
                            chat_id=user['chat_id'],
                            text="""🚨 Son 6 Saat!

⏰ Deneme süreniz yakında sona erecek.
/premium → Hemen üye olun""")
            
            return True
            
        except Exception as e:
            print(f"Üyelik kontrol hatası: {str(e)}")
            return False

    async def _create_payment_link(self, user_id: int) -> str:
        """Ödeme bağlantısı oluştur"""
        try:
            # Stripe ödeme bağlantısı (örnek)
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': 50000,  # $500.00
                        'product_data': {
                            'name': 'Premium Bot Üyeliği',
                            'description': 'Aylık Premium Üyelik'
                        },
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                success_url='https://t.me/your_bot?start=success',
                cancel_url='https://t.me/your_bot?start=cancel',
                client_reference_id=str(user_id)
            )
            return session.url
            
        except Exception as e:
            print(f"Ödeme bağlantısı hatası: {str(e)}")
            return "Ödeme sistemi geçici olarak kullanılamıyor."

    async def broadcast_signal(self, message: str, symbol: str = None):
        """Tüm aktif kullanıcılara sinyal gönder"""
        try:
            for chat_id in self.user_chat_ids:
                try:
                    # Eğer sembol belirtilmişse, sadece o coini takip edenlere gönder
                    if symbol:
                        if (chat_id in self.watched_coins and 
                            symbol in self.watched_coins[chat_id]):
                            await self.application.send_message(
                                chat_id=chat_id,
                                text=message
                            )
                    # Sembol belirtilmemişse herkese gönder
                    else:
                        await self.application.send_message(
                            chat_id=chat_id,
                            text=message
                        )
                except Exception as e:
                    print(f"Mesaj gönderme hatası {chat_id}: {str(e)}")
                    continue
                    
        except Exception as e:
            print(f"Broadcast hatası: {str(e)}")

    async def monitor_signals(self):
        """Sürekli sinyal takibi"""
        while self.is_running:
            try:
                current_time = time.time()
                
                for symbol in self.active_symbols:
                    # Son bildirimden bu yana geçen süreyi kontrol et
                    last_time = self.last_notification_time.get(symbol, 0)
                    if current_time - last_time >= self.notification_cooldown:
                        try:
                            analysis = await self.signal_analyzer.get_market_analysis(symbol)
                            if analysis and not analysis.get('error'):
                                await self.broadcast_signal(analysis.get('analysis', 'Analiz verisi bulunamadı'), symbol)
                                # Bildirim zamanını güncelle
                                self.last_notification_time[symbol] = current_time
                                print(f"✅ {symbol} analizi gönderildi - {datetime.now().strftime('%H:%M:%S')}")
                        except Exception as e:
                            print(f"⚠️ {symbol} sinyal hatası: {e}")
                    
                    await asyncio.sleep(1)  # Semboller arası bekleme
                
                # Kısa bir bekleme
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                print("\n💬 Sinyal izleme durduruldu")
                break
            except Exception as e:
                print(f"\n❌ Monitoring hatası: {e}")
                await asyncio.sleep(5)

    async def interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bildirim aralığını değiştir"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text(
                    "ℹ️ Kullanım: /interval <dakika>\n"
                    "Örnek: /interval 10"
                )
                return

            minutes = int(args[0])
            if minutes < 1 or minutes > 60:
                await update.message.reply_text("⚠️ Bildirim aralığı 1-60 dakika arasında olmalıdır.")
                return

            self.notification_cooldown = minutes * 60
            await update.message.reply_text(f"✅ Bildirim aralığı {minutes} dakika olarak ayarlandı.")
            
        except ValueError:
            await update.message.reply_text("❌ Geçersiz değer. Lütfen sayı girin.")
        except Exception as e:
            print(f"❌ Interval komutu hatası: {e}")
            await update.message.reply_text("❌ Bir hata oluştu. Lütfen tekrar deneyin.")

    async def monitor_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """İşlem takibi başlat"""
        try:
            args = context.args
            if len(args) < 6:
                await update.message.reply_text(
                    "❌ Eksik parametre! Kullanım:\n"
                    "/monitor SYMBOL TYPE ENTRY SL TP LEVERAGE\n"
                    "Örnek: /monitor BTC/USDT LONG 45000 44000 47000 5"
                )
                return
                
            symbol = args[0]
            position_type = args[1].upper()
            entry_price = float(args[2])
            stop_loss = float(args[3])
            take_profit = float(args[4])
            leverage = int(args[5])
            
            if position_type not in ['LONG', 'SHORT']:
                await update.message.reply_text("❌ Geçersiz pozisyon tipi! LONG veya SHORT kullanın.")
                return
                
            # Takibi başlat
            asyncio.create_task(
                self.trade_monitor.start_trade_monitoring(
                    symbol=symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_type=position_type,
                    leverage=leverage,
                    chat_id=update.effective_chat.id,
                    bot=self.application
                )
            )
            
        except ValueError:
            await update.message.reply_text("❌ Geçersiz sayısal değer!")
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def stop_monitor_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """İşlem takibini durdur"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text("❌ Symbol belirtilmedi! Örnek: /stop BTC/USDT")
                return
                
            symbol = args[0]
            if symbol in self.trade_monitor.active_positions:
                self.trade_monitor.active_positions[symbol].monitoring = False
                await update.message.reply_text(f"✅ {symbol} takibi durduruldu!")
            else:
                await update.message.reply_text(f"❌ {symbol} için aktif takip bulunamadı!")
                
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Piyasa taraması başlat/durdur"""
        try:
            chat_id = update.effective_chat.id
            self.user_chat_ids.add(chat_id)
            
            if not self.scan_active:
                self.scan_active = True
                
                await update.message.reply_text(
                    "🔍 Binance taraması başladı!\n"
                    "Fırsat görülen coinler için bildirim alacaksınız.\n"
                    "Durdurmak için tekrar /scan yazın."
                )
                
                self.scan_task = asyncio.create_task(self._scan_market(chat_id))
                
            else:
                self.scan_active = False
                if self.scan_task:
                    self.scan_task.cancel()
                await update.message.reply_text("🛑 Piyasa taraması durduruldu!")
                
        except Exception as e:
            await update.message.reply_text(f"❌ Tarama hatası: {str(e)}")

    async def _scan_market(self, chat_id: int):
        """Binance'deki tüm coinleri tara ve fırsatları bul"""
        try:
            while self.scan_active:
                try:
                    current_time = time.time()
                    if (self.last_scan_time and 
                        current_time - self.last_scan_time < 300):  # 5 dakika
                        await asyncio.sleep(1)
                        continue

                    all_symbols = await self.market_scanner.get_all_symbols()
                    if not all_symbols:
                        print("⚠️ Sembol listesi boş, tekrar deneniyor...")
                        await asyncio.sleep(5)
                        continue

                    total_symbols = len(all_symbols)
                    scanned_count = 0
                    opportunities = []

                    print(f"\n🔍 Toplam {total_symbols} coin taranıyor...")

                    # Her 10 coini paralel tara
                    for i in range(0, total_symbols, 10):
                        batch = all_symbols[i:i+10]
                        tasks = []
                        
                        for symbol in batch:
                            tasks.append(self._scan_single_coin(symbol))
                        
                        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                        
                        for result in batch_results:
                            if isinstance(result, dict) and result.get('signal'):
                                opportunities.append(result)
                        
                        scanned_count += len(batch)
                        if scanned_count % 50 == 0:
                            print(f"⏳ İşlenen: {scanned_count}/{total_symbols} ({(scanned_count/total_symbols*100):.1f}%)")
                        
                        await asyncio.sleep(0.5)

                    print(f"\n📊 Tarama Özeti:")
                    print(f"• Taranan: {scanned_count}/{total_symbols}")
                    print(f"• Bulunan Fırsatlar: {len(opportunities)}")
                    print(f"• Geçen Süre: {time.time() - current_time:.1f} saniye")

                    # Fırsatları toplu mesaj olarak gönder
                    if opportunities:
                        # Her 5 fırsatı bir mesajda birleştir
                        batch_size = 5
                        for i in range(0, len(opportunities), batch_size):
                            batch_opps = opportunities[i:i+batch_size]
                            
                            # Mesajları birleştir
                            combined_message = f"🎯 {len(batch_opps)} Yeni Fırsat!\n\n"
                            for opp in batch_opps:
                                combined_message += f"-------------------\n{opp['message']}\n"
                            
                            try:
                                # Uzun mesajları böl (Telegram limiti 4096 karakter)
                                if len(combined_message) > 4000:
                                    parts = [combined_message[i:i+4000] for i in range(0, len(combined_message), 4000)]
                                    for part in parts:
                                        await self.application.bot.send_message(
                                            chat_id=chat_id,
                                            text=part
                                        )
                                        await asyncio.sleep(3)  # 3 saniye bekle
                                else:
                                    await self.application.bot.send_message(
                                        chat_id=chat_id,
                                        text=combined_message
                                    )
                                    await asyncio.sleep(3)  # 3 saniye bekle
                                
                            except Exception as e:
                                print(f"📤 Mesaj gönderme hatası: {str(e)}")
                                await asyncio.sleep(5)  # Hata durumunda 5 saniye bekle
                                continue

                    self.last_scan_time = current_time
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"🚫 Tarama döngüsü hatası: {str(e)}")
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            print("⛔️ Tarama görevi iptal edildi")
        except Exception as e:
            print(f"💥 Ana tarama hatası: {str(e)}")

    async def _scan_single_coin(self, symbol: str) -> Dict:
        """Tek bir coin için fırsat analizi"""
        try:
            # Coin verilerini al
            ticker = await self.market_scanner.get_ticker(symbol)
            if not ticker:
                return {}

            # Minimum hacim kontrolü (1M USDT)
            if ticker.get('quoteVolume', 0) < 1000000:
                return {}

            # OHLCV verilerini al
            df = await self.market_scanner.get_ohlcv(symbol)
            if df is None or df.empty:
                return {}

            # Teknik analiz
            analysis = self._calculate_indicators(df)
            
            # Fırsat analizi
            opportunity = await self._analyze_trading_opportunity(symbol, ticker, analysis)
            
            if opportunity and opportunity.get('signal'):
                print(f"✨ Fırsat bulundu: {symbol}")
                return opportunity

            return {}

        except Exception as e:
            print(f"❌ Coin analiz hatası {symbol}: {str(e)}")
            return {}

    async def _analyze_market_status(self) -> Dict:
        """Genel piyasa durumunu analiz et"""
        try:
            # BTC durumunu al
            btc_data = await self.market_scanner.get_ticker("BTC/USDT")
            btc_ohlcv = await self.market_scanner.get_ohlcv("BTC/USDT")
            btc_analysis = self._calculate_indicators(btc_ohlcv)
            
            # Piyasa stres seviyesini hesapla
            stress_level = "DÜŞÜK 🟢"
            if btc_analysis['rsi'] > 75 or btc_analysis['rsi'] < 25:
                stress_level = "YÜKSEK 🔴"
            elif btc_analysis['rsi'] > 65 or btc_analysis['rsi'] < 35:
                stress_level = "ORTA 🟡"
            
            # Trend analizi
            trend = "YATAY ↔️"
            if btc_analysis['ema20'] > btc_analysis['ema50'] * 1.02:
                trend = "GÜÇLÜ YÜKSELİŞ ⤴️"
            elif btc_analysis['ema20'] > btc_analysis['ema50']:
                trend = "YÜKSELİŞ ↗️"
            elif btc_analysis['ema20'] < btc_analysis['ema50'] * 0.98:
                trend = "GÜÇLÜ DÜŞÜŞ ⤵️"
            elif btc_analysis['ema20'] < btc_analysis['ema50']:
                trend = "DÜŞÜŞ ↘️"
            
            # Hacim trendi
            volume_trend = "NORMAL 📊"
            if btc_analysis['volume_change'] > 50:
                volume_trend = "ÇOK YÜKSEK 📈"
            elif btc_analysis['volume_change'] > 20:
                volume_trend = "YÜKSEK 📈"
            elif btc_analysis['volume_change'] < -50:
                volume_trend = "ÇOK DÜŞÜK 📉"
            elif btc_analysis['volume_change'] < -20:
                volume_trend = "DÜŞÜK 📉"
            
            return {
                'btc_price': btc_data['last'],
                'btc_change': btc_data['percentage'],
                'btc_rsi': btc_analysis['rsi'],
                'stress_level': stress_level,
                'trend': trend,
                'volume_trend': volume_trend,
                'dominant_direction': "ALIŞ 💚" if btc_analysis['macd'] > btc_analysis['macd_signal'] else "SATIŞ ❤️",
                'fear_greed': "AÇGÖZLÜLÜK" if btc_analysis['rsi'] > 60 else "KORKU" if btc_analysis['rsi'] < 40 else "NÖTR",
                'summary': self._generate_market_summary(btc_analysis),
                'recommendation': self._generate_recommendation(btc_analysis),
                'risk_level': "YÜKSEK 🔴" if stress_level == "YÜKSEK 🔴" else "ORTA 🟡" if stress_level == "ORTA 🟡" else "DÜŞÜK 🟢"
            }
            
        except Exception as e:
            print(f"Piyasa analiz hatası: {str(e)}")
            return {}

    async def _analyze_coin(self, symbol: str, data: Dict) -> Dict:
        """Coin'i detaylı analiz et"""
        try:
            result = {
                'momentum': "GÜÇLÜ ALIŞ 💚" if data['rsi'] < 30 and data['change'] > 0 else
                           "GÜÇLÜ SATIŞ ❤️" if data['rsi'] > 70 and data['change'] < 0 else
                           "ALIŞ 💚" if data['rsi'] < 40 and data['change'] > 0 else
                           "SATIŞ ❤️" if data['rsi'] > 60 and data['change'] < 0 else
                           "NÖTR ⚪️",
                'news': await self._get_coin_news(symbol),
                'social_sentiment': await self._get_social_sentiment(symbol),
                'technical_summary': self._generate_technical_summary(data),
                'warning': self._generate_warning(data)
            }
            return result
            
        except Exception as e:
            print(f"Coin analiz hatası {symbol}: {str(e)}")
            return {}

    def _generate_market_comment(self, opportunities: Dict) -> str:
        """Genel pazar yorumu oluştur"""
        try:
            total_coins = (len(opportunities['strong_buy']) + 
                         len(opportunities['potential_buy']) + 
                         len(opportunities['breakout']))
            
            if total_coins > 15:
                return "🟢 Pazar oldukça güçlü görünüyor. Alım fırsatları bol."
            elif total_coins > 10:
                return "🟡 Pazar dengeli. Seçici olmakta fayda var."
            elif total_coins > 5:
                return "🟠 Pazar temkinli. Risk yönetimi önemli."
            else:
                return "🔴 Pazar zayıf. İşlemlerde çok dikkatli olun."
                
        except Exception as e:
            return "Pazar yorumu oluşturulamadı."

    async def watch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Coin izlemeye al"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text(
                    "❌ Symbol belirtilmedi!\n"
                    "Örnek: /watch BTC/USDT"
                )
                return
                
            symbol = args[0].upper()
            self.market_scanner.add_watched_symbol(symbol)
            await update.message.reply_text(f"✅ {symbol} izleme listesine eklendi!")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def unwatch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Coin izlemeden çıkar"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text(
                    "❌ Symbol belirtilmedi!\n"
                    "Örnek: /unwatch BTC/USDT"
                )
                return
                
            symbol = args[0].upper()
            self.market_scanner.remove_watched_symbol(symbol)
            await update.message.reply_text(f"✅ {symbol} izleme listesinden çıkarıldı!")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def scalp_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Scalping takibi başlat"""
        try:
            args = context.args
            if len(args) < 6:
                await update.message.reply_text(
                    "❌ Eksik parametre! Kullanım:\n"
                    "/scalp SYMBOL TYPE ENTRY SL TP LEVERAGE\n"
                    "Örnek: /scalp BTC/USDT LONG 45000 44900 45200 5"
                )
                return
                
            symbol = args[0].upper()
            position_type = args[1].upper()
            entry_price = float(args[2])
            stop_loss = float(args[3])
            take_profit = float(args[4])
            leverage = int(args[5])
            
            if position_type not in ['LONG', 'SHORT']:
                await update.message.reply_text("❌ Geçersiz pozisyon tipi! LONG veya SHORT kullanın.")
                return
                
            # Risk kontrolü
            risk_percent = abs((entry_price - stop_loss) / entry_price * 100 * leverage)
            if risk_percent > 5:  # Maximum %5 risk
                await update.message.reply_text(
                    f"⚠️ Yüksek risk uyarısı! Risk: %{risk_percent:.2f}\n"
                    "Stop-loss seviyenizi veya kaldıracınızı düşürün."
                )
                return
                
            # Scalping takibini başlat
            await update.message.reply_text(
                f"⚡️ {symbol} için scalping takibi başlatılıyor...\n"
                f"Giriş: ${entry_price:.2f}\n"
                f"Stop: ${stop_loss:.2f}\n"
                f"Hedef: ${take_profit:.2f}\n"
                f"Kaldıraç: {leverage}x"
            )
            
            asyncio.create_task(
                self.trade_monitor.start_scalping_monitor(
                    symbol=symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_type=position_type,
                    leverage=leverage,
                    chat_id=update.effective_chat.id,
                    bot=self.application
                )
            )
            
        except ValueError as e:
            await update.message.reply_text(f"❌ Geçersiz sayısal değer: {str(e)}")
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")
            print(f"Scalp komutu hatası: {str(e)}")

    async def price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Anlık fiyat kontrolü"""
        try:
            args = context.args
            if not args:
                await update.message.reply_text(
                    "❌ Symbol belirtilmedi!\n"
                    "Örnek: /price BTC/USDT"
                )
                return
                
            symbol = args[0].upper()
            
            # Binance'den anlık veri çek
            ticker = self.trade_monitor.exchange.fetch_ticker(symbol)
            ohlcv = self.trade_monitor.exchange.fetch_ohlcv(symbol, '1m', limit=1)
            
            # Son işlem bilgileri
            trades = self.trade_monitor.exchange.fetch_trades(symbol, limit=1)
            last_trade = trades[0] if trades else None
            
            message = f"""📊 {symbol} ANLIK VERİLER

💰 Son Fiyat: ${ticker['last']:.4f}
📈 24s Değişim: %{ticker['percentage']:.2f}
💎 24s Hacim: ${ticker['quoteVolume']:,.0f}

📈 Son Mum (1d):
• Açılış: ${ohlcv[0][1]:.4f}
• Yüksek: ${ohlcv[0][2]:.4f}
• Düşük: ${ohlcv[0][3]:.4f}
• Kapanış: ${ohlcv[0][4]:.4f}
• Hacim: {ohlcv[0][5]:.2f}

⚡️ Son İşlem:
• Fiyat: ${last_trade['price']:.4f}
• Miktar: {last_trade['amount']:.4f}
• Yön: {last_trade['side'].upper()}
• Zaman: {datetime.fromtimestamp(last_trade['timestamp']/1000).strftime('%H:%M:%S')}

🔄 Güncelleme: {datetime.now().strftime('%H:%M:%S')}"""

            await update.message.reply_text(message)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kripto haberleri göster"""
        try:
            progress_message = await update.message.reply_text(
                "📰 Haberler toplanıyor...\n"
                "Bu işlem birkaç saniye sürebilir."
            )
            
            try:
                news_data = await self.news_tracker.fetch_news()
                if news_data:
                    message = await self.news_tracker.format_news_message(news_data)
                    await progress_message.delete()
                    
                    # Uzun mesajları böl
                    if len(message) > 4096:
                        chunks = [message[i:i+4096] for i in range(0, len(message), 4096)]
                        for chunk in chunks:
                            await update.message.reply_text(
                                chunk, 
                                disable_web_page_preview=True
                            )
                    else:
                        await update.message.reply_text(
                            message,
                            disable_web_page_preview=True
                        )
                else:
                    await progress_message.edit_text(
                        "❌ Haber verisi alınamadı!\n"
                        "Lütfen birkaç dakika sonra tekrar deneyin."
                    )
                    
            except Exception as e:
                await progress_message.edit_text(
                    f"❌ Haber verisi işlenirken hata oluştu: {str(e)}\n"
                    "Lütfen birkaç dakika sonra tekrar deneyin."
                )
                
        except Exception as e:
            await update.message.reply_text(
                "❌ Beklenmeyen bir hata oluştu.\n"
                "Lütfen birkaç dakika sonra tekrar deneyin."
            )

    async def auto_scan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Otomatik taramayı başlat/durdur"""
        try:
            if not self.auto_scan_active:
                self.auto_scan_active = True
                await update.message.reply_text(
                    "🟢 Otomatik tarama başlatıldı!\n"
                    "• Her 5 dakikada bir piyasa taranacak\n"
                    "• Sadece güçlü sinyaller bildirilecek\n"
                    "• Durdurmak için: /autoscan"
                )
                self.auto_scan_task = asyncio.create_task(self._auto_scan_loop(update.effective_chat.id))
            else:
                self.auto_scan_active = False
                if self.auto_scan_task:
                    self.auto_scan_task.cancel()
                await update.message.reply_text("🔴 Otomatik tarama durduruldu!")
                
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def _auto_scan_loop(self, chat_id: int):
        """Sürekli tarama döngüsü"""
        try:
            while self.auto_scan_active:
                opportunities = await self.market_scanner.scan_opportunities()
                current_time = datetime.now()
                new_signals = []
                
                # Tüm fırsat tiplerini kontrol et
                for opp_type in ['strong_buy', 'breakout', 'oversold', 'trend_following']:
                    if opp_type in opportunities:
                        for opp in opportunities[opp_type]:
                            symbol = opp['symbol']
                            
                            # Bekleme süresini kontrol et (15 dakika = 900 saniye)
                            if symbol in self.signal_cooldown:
                                time_diff = (current_time - self.signal_cooldown[symbol]).total_seconds()
                                if time_diff < 900:  # 15 dakika
                                    continue
                            
                            trend = self.market_scanner._analyze_trend_direction(opp['analysis'], {'last': opp['price']})
                            
                            # Güven skorunu kontrol et
                            if trend['confidence'] >= 60:
                                signal_key = f"{symbol}_{current_time.strftime('%Y%m%d_%H')}"
                                if signal_key not in self.last_signals:
                                    new_signals.append({
                                        'symbol': symbol,
                                        'data': opp,
                                        'trend': trend,
                                        'type': opp_type
                                    })
                                    self.last_signals.add(signal_key)
                                    self.signal_cooldown[symbol] = current_time
                
                # Yeni sinyalleri bildir
                if new_signals:
                    message = "🔔 YENİ FIRSATLAR BULUNDU!\n\n"
                    
                    for signal in new_signals:
                        opp = signal['data']
                        trend = signal['trend']
                        
                        # Sinyal tipine göre emoji seç
                        type_emoji = {
                            'strong_buy': '💚',
                            'breakout': '⚡️',
                            'oversold': '📉',
                            'trend_following': '📈'
                        }.get(signal['type'], '🎯')
                        
                        message += f"""{type_emoji} {opp['symbol']}
• Fiyat: ${opp['price']:.4f}
• 24s Değişim: %{opp['change_24h']:.1f}
• RSI: {opp['analysis']['rsi']:.1f}
• Hacim: ${opp['volume']:,.0f}

📊 15dk SINYAL:
• Yön: {trend['suggestion']}
• Güven: %{trend['confidence']}
• Hedef: ${trend['target']:.4f}
• Stop: ${trend['stop_loss']:.4f}
• Risk/Ödül: {trend['risk_reward']:.2f}

📝 YORUM: {', '.join(trend['reason'])}
\n"""
                    
                    # Mesajı bölümlere ayır (Telegram limiti için)
                    if len(message) > 4096:
                        chunks = [message[i:i+4096] for i in range(0, len(message), 4096)]
                        for chunk in chunks:
                            await self.application.send_message(
                                chat_id=chat_id,
                                text=chunk,
                                parse_mode='HTML'
                            )
                    else:
                        await self.application.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode='HTML'
                        )
                
                # Eski sinyalleri temizle (24 saat önceki)
                old_time = current_time - timedelta(hours=24)
                self.last_signals = {
                    signal for signal in self.last_signals 
                    if datetime.strptime(signal.split('_')[1], '%Y%m%d_%H') > old_time
                }
                
                # 3 dakika bekle
                await asyncio.sleep(180)
                
        except asyncio.CancelledError:
            print("Otomatik tarama durduruldu")
        except Exception as e:
            print(f"Otomatik tarama hatası: {str(e)}")
            self.auto_scan_active = False

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Buton tıklamalarını işle"""
        query = update.callback_query
        await query.answer()

        action, symbol = query.data.split('_')
        chat_id = update.effective_chat.id
        
        if action == "watch":
            task_key = f"{chat_id}_{symbol}"
            if task_key in self.watch_tasks:
                # Takibi durdur
                self.watch_tasks[task_key].cancel()
                del self.watch_tasks[task_key]
                self.active_symbols.remove(symbol)
                if chat_id in self.watched_coins and symbol in self.watched_coins[chat_id]:
                    del self.watched_coins[chat_id][symbol]
                await query.edit_message_text(f"🔴 {symbol} takipten çıkarıldı!")

        elif action == "analyze":
            try:
                # Son verileri al
                ohlcv = await self.market_scanner.exchange.fetch_ohlcv(symbol, '15m', limit=100)
                ticker = await self.market_scanner.exchange.fetch_ticker(symbol)
                
                # DataFrame oluştur
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Teknik analiz yap
                analysis = self._calculate_indicators(df)
                
                # Destek ve direnç seviyeleri
                supports = self.calculate_support_levels(df)
                resistances = self.calculate_resistance_levels(df)
                
                # Detaylı analiz mesajı
                analysis_msg = f"""📊 {symbol} DETAYLI ANALİZ

💰 FİYAT BİLGİLERİ:
• Mevcut: ${ticker['last']:.4f}
• 24s Değişim: %{ticker['percentage']:.1f}
• 24s Hacim: ${ticker['quoteVolume']:,.0f}

📊 TEKNİK GÖSTERGELER:
• RSI (14): {analysis['rsi']:.1f}
• MACD: {analysis['macd']:.4f}
• Signal: {analysis['macd_signal']:.4f}
• EMA20: ${analysis['ema20']:.4f}
• EMA50: ${analysis['ema50']:.4f}
• VWAP: ${analysis['vwap']:.4f}

🎯 ÖNEMLİ SEVİYELER:
• Direnç 3: ${resistances[2]:.4f}
• Direnç 2: ${resistances[1]:.4f}
• Direnç 1: ${resistances[0]:.4f}
• Destek 1: ${supports[0]:.4f}
• Destek 2: ${supports[1]:.4f}
• Destek 3: ${supports[2]:.4f}

📊 MOMENTUM:
• Trend Yönü: {'Yükselen 📈' if analysis['ema20'] > analysis['ema50'] else 'Düşen 📉'}
• RSI Durumu: {self.get_rsi_status(analysis['rsi'])}
• Hacim Trendi: {'Artıyor 📈' if analysis['volume_change'] > 0 else 'Azalıyor 📉'}

⚡️ İŞLEM ÖNERİSİ:
{self.get_trading_suggestion(analysis, ticker['last'], supports, resistances)}

⏰ {datetime.now().strftime('%H:%M:%S')}"""

                keyboard = [[
                    InlineKeyboardButton("🔄 Analizi Güncelle", callback_data=f"analyze_{symbol}"),
                    InlineKeyboardButton("📈 Long", callback_data=f"long_{symbol}"),
                    InlineKeyboardButton("📉 Short", callback_data=f"short_{symbol}")
                ]]
                
                await query.edit_message_text(
                    text=analysis_msg,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            except Exception as e:
                await query.edit_message_text(
                    text=f"❌ Analiz hatası: {str(e)}",
                    reply_markup=None
                )

    def calculate_support_levels(self, df: pd.DataFrame) -> List[float]:
        """Destek seviyelerini hesapla"""
        try:
            lows = df['low'].values
            supports = []
            
            # Pivot noktaları bul
            for i in range(1, len(lows)-1):
                if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                    supports.append(lows[i])
            
            # Son 3 önemli destek seviyesini döndür
            supports = sorted(set(supports), reverse=True)[:3]
            return supports if len(supports) == 3 else [df['low'].min()] * 3
            
        except Exception as e:
            print(f"Destek hesaplama hatası: {str(e)}")
            return [0, 0, 0]

    def calculate_resistance_levels(self, df: pd.DataFrame) -> List[float]:
        """Direnç seviyelerini hesapla"""
        try:
            highs = df['high'].values
            resistances = []
            
            # Pivot noktaları bul
            for i in range(1, len(highs)-1):
                if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                    resistances.append(highs[i])
            
            # Son 3 önemli direnç seviyesini döndür
            resistances = sorted(set(resistances))[:3]
            return resistances if len(resistances) == 3 else [df['high'].max()] * 3
            
        except Exception as e:
            print(f"Direnç hesaplama hatası: {str(e)}")
            return [0, 0, 0]

    def get_rsi_status(self, rsi: float) -> str:
        """RSI durumunu yorumla"""
        if rsi > 70:
            return "Aşırı Alım ⚠️"
        elif rsi < 30:
            return "Aşırı Satış 🔥"
        elif rsi > 60:
            return "Güçlü 💪"
        elif rsi < 40:
            return "Zayıf 📉"
        else:
            return "Nötr ⚖️"

    def get_trading_suggestion(self, analysis: Dict, current_price: float, 
                             supports: List[float], resistances: List[float]) -> str:
        """İşlem önerisi oluştur"""
        try:
            suggestion = ""
            
            # Trend analizi
            trend = "yükselen" if analysis['ema20'] > analysis['ema50'] else "düşen"
            
            # RSI analizi
            rsi_signal = (
                "aşırı satış" if analysis['rsi'] < 30 
                else "aşırı alım" if analysis['rsi'] > 70 
                else "nötr"
            )
            
            # MACD analizi
            macd_signal = "pozitif" if analysis['macd'] > analysis['macd_signal'] else "negatif"
            
            # Destek/Direnç analizi
            nearest_support = min([s for s in supports if s < current_price], default=supports[0])
            nearest_resistance = min([r for r in resistances if r > current_price], default=resistances[0])
            
            risk_reward = (nearest_resistance - current_price) / (current_price - nearest_support)
            
            if trend == "yükselen" and rsi_signal != "aşırı alım" and macd_signal == "pozitif":
                suggestion = f"""💚 LONG POZİSYON FIRSATI
• Stop-Loss: ${nearest_support:.4f}
• Hedef: ${nearest_resistance:.4f}
• Risk/Ödül: {risk_reward:.2f}
• Trend yükselen ve momentum güçlü"""
                
            elif trend == "düşen" and rsi_signal != "aşırı satış" and macd_signal == "negatif":
                suggestion = f"""❤️ SHORT POZİSYON FIRSATI
• Stop-Loss: ${nearest_resistance:.4f}
• Hedef: ${nearest_support:.4f}
• Risk/Ödül: {risk_reward:.2f}
• Trend düşen ve momentum zayıf"""

            return suggestion
            
        except Exception as e:
            return f"Öneri oluşturma hatası: {str(e)}"

    async def track_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Belirli bir coini veya tüm coinleri takip et"""
        try:
            chat_id = update.effective_chat.id
            message_parts = update.message.text.split()
            
            # Eğer coin belirtilmişse (örn: /track BTCUSDT)
            if len(message_parts) > 1:
                symbol = message_parts[1].upper()
                # BTCUSDT formatını BTC/USDT formatına çevir
                if symbol.endswith('USDT'):
                    symbol = f"{symbol[:-4]}/USDT"
                
                # Coin zaten takip ediliyor mu kontrol et
                task_key = f"{chat_id}_{symbol}"
                if task_key in self.watch_tasks:
                    # Takibi durdur
                    self.watch_tasks[task_key].cancel()
                    del self.watch_tasks[task_key]
                    await update.message.reply_text(f"🛑 {symbol} takibi durduruldu!")
                    return
                
                # Coin'in geçerli olduğunu kontrol et
                ticker = await self.market_scanner.get_ticker(symbol)
                if not ticker:
                    await update.message.reply_text(f"❌ {symbol} geçerli bir coin değil!")
                    return
                
                # Takibi başlat
                current_price = ticker['last']
                self.watch_tasks[task_key] = asyncio.create_task(
                    self._watch_coin(symbol, chat_id, current_price)
                )
                
                await update.message.reply_text(
                    f"🔄 {symbol} takip ediliyor!\n"
                    f"• Güncel Fiyat: ${current_price:,.4f}\n"
                    f"• Hacim: ${ticker['quoteVolume']:,.0f}\n"
                    "Durdurmak için aynı komutu tekrar yazın."
                )
            
            # Coin belirtilmemişse tüm coinleri takip et
            else:
                if self.track_active:
                    self.track_active = False
                    if self.track_task:
                        self.track_task.cancel()
                    await update.message.reply_text("🛑 Tüm coinlerin takibi durduruldu!")
                    return
                
                self.track_active = True
                await update.message.reply_text(
                    "🔄 Tüm coinler takip ediliyor!\n"
                    "Önemli fiyat hareketlerinde bildirim alacaksınız.\n"
                    "Durdurmak için tekrar /track yazın."
                )
                
                self.track_task = asyncio.create_task(self._track_all_coins(chat_id))
            
        except Exception as e:
            await update.message.reply_text(f"❌ Track hatası: {str(e)}")

    async def _watch_coin(self, symbol: str, chat_id: int, entry_price: float):
        """Coin takibi ve sinyal üretimi"""
        try:
            print(f"🔍 {symbol} takibi başladı...")
            last_notification_time = 0
            last_signal_time = 0
            signal_cooldown = 3600  # Sinyaller arası minimum süre (1 saat)
            
            while True:
                try:
                    # Fiyat ve OHLCV verilerini al
                    ticker = await self.market_scanner.get_ticker(symbol)
                    df = await self.market_scanner.get_ohlcv(symbol)
                    
                    if not ticker or df is None or df.empty:
                        await asyncio.sleep(10)
                        continue

                    current_price = ticker['last']
                    volume = ticker['quoteVolume']
                    current_time = time.time()
                    
                    # Teknik analiz yap
                    analysis = self._calculate_indicators(df)
                    
                    # Fiyat değişimi kontrolü
                    price_change = ((current_price - entry_price) / entry_price) * 100
                    
                    # Önemli seviyeler
                    next_support = max([s for s in analysis.get('support_levels', []) if s < current_price], default=current_price * 0.985)
                    next_resistance = min([r for r in analysis.get('resistance_levels', []) if r > current_price], default=current_price * 1.015)
                    
                    # Sinyal kontrolleri
                    rsi = analysis.get('rsi', 50)
                    macd = analysis.get('macd', {})
                    bb = analysis.get('bb', {})
                    vwap = analysis.get('vwap', current_price)
                    
                    # LONG Sinyali
                    long_signal = (
                        rsi < 35 and
                        macd.get('macd', 0) > macd.get('signal', 0) and
                        current_price > vwap and
                        current_price > bb.get('lower', 0) and
                        current_price < next_resistance * 0.98
                    )
                    
                    # SHORT Sinyali
                    short_signal = (
                        rsi > 65 and
                        macd.get('macd', 0) < macd.get('signal', 0) and
                        current_price < vwap and
                        current_price < bb.get('upper', 0) and
                        current_price > next_support * 1.02
                    )
                    
                    # Sinyal mesajı oluştur
                    if (long_signal or short_signal) and (current_time - last_signal_time > signal_cooldown):
                        signal_type = "LONG" if long_signal else "SHORT"
                        emoji = "💚" if long_signal else "❤️"
                        target = next_resistance if long_signal else next_support
                        stop = next_support if long_signal else next_resistance
                        
                        # Risk yönetimi
                        risk_ratio = abs(target - current_price) / abs(current_price - stop)
                        suggested_leverage = min(3, round(risk_ratio))
                        
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"""⚡️ {symbol} {signal_type} SİNYALİ {emoji}

💰 Fiyat Seviyeleri:
• Giriş: ${current_price:.4f}
• Hedef: ${target:.4f} ({((target-current_price)/current_price*100):.1f}%)
• Stop: ${stop:.4f} ({((stop-current_price)/current_price*100):.1f}%)

📊 Teknik Durum:
• RSI: {rsi:.1f}
• MACD: {"Pozitif" if macd.get('histogram', 0) > 0 else "Negatif"}
• VWAP: ${vwap:.4f}
• Hacim: ${volume:,.0f}

⚠️ Risk Yönetimi:
• Önerilen Kaldıraç: {suggested_leverage}x
• Risk/Ödül: {risk_ratio:.2f}
• İzole Marjin Kullanın!
• Stop-Loss Zorunlu!

🎯 Strateji:
• Giriş: ${current_price:.4f} civarı
• Kâr Al: ${target:.4f}
• Zarar Kes: ${stop:.4f}
• Pozisyon: Bakiyenin %10'u

⚠️ Önemli:
• İzole marjin kullanın
• Stop-loss emirlerinizi girin
• Kaldıracı düşük tutun
• FOMO yapmayın!"""
                        )
                        last_signal_time = current_time
                    
                    # Rutin durum güncellemesi (5 dakikada bir)
                    if current_time - last_notification_time >= 300:
                        change_emoji = "📈" if price_change > 0 else "📉"
                        
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"""🔔 {symbol} Durum {change_emoji}

• Fiyat: ${current_price:,.4f}
• Değişim: %{price_change:.1f}
• RSI: {rsi:.1f}
• Hacim: ${volume:,.0f}

• Destek: ${next_support:.4f}
• Direnç: ${next_resistance:.4f}

/analyze_{symbol.replace('/', '')} için detaylı analiz"""
                        )
                        last_notification_time = current_time
                        entry_price = current_price

                    await asyncio.sleep(10)

                except Exception as e:
                    print(f"❌ {symbol} takip hatası: {str(e)}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            print(f"⛔️ {symbol} takibi iptal edildi")
        except Exception as e:
            print(f"💥 {symbol} genel takip hatası: {str(e)}")

    async def _track_all_coins(self, chat_id: int):
        """Tüm coinleri takip et"""
        try:
            while self.track_active:
                try:
                    # Tüm sembolleri al
                    all_symbols = await self.market_scanner.get_all_symbols()
                    if not all_symbols:
                        await asyncio.sleep(5)
                        continue

                    print(f"🔍 {len(all_symbols)} coin takip ediliyor...")

                    for symbol in all_symbols:
                        try:
                            # Son fiyatı al
                            ticker = await self.market_scanner.get_ticker(symbol)
                            if not ticker:
                                continue

                            current_price = ticker['last']
                            
                            # Önceki fiyatı kontrol et
                            prev_price = self.tracked_prices.get(symbol)
                            if prev_price is None:
                                self.tracked_prices[symbol] = current_price
                                continue

                            # Fiyat değişimini hesapla
                            price_change = ((current_price - prev_price) / prev_price) * 100

                            # Önemli fiyat hareketlerini bildir
                            # Major coinler için daha düşük eşik değeri
                            threshold = 2 if symbol in ['BTC/USDT', 'ETH/USDT'] else 5
                            
                            if abs(price_change) >= threshold:
                                change_type = "YÜKSELİŞ 📈" if price_change > 0 else "DÜŞÜŞ 📉"
                                volume = ticker.get('quoteVolume', 0)
                                
                                # Major coinler için özel format
                                if symbol in ['BTC/USDT', 'ETH/USDT']:
                                    message = f"""🚨 {symbol} {change_type}

• Fiyat: ${current_price:,.2f}
• Değişim: %{price_change:.1f}
• 24s Hacim: ${volume:,.0f}

/analyze_{symbol.replace('/', '')} için detaylı analiz"""
                                else:
                                    message = f"""⚡️ Önemli {change_type}: {symbol}

• Fiyat: ${current_price:.4f}
• Değişim: %{price_change:.1f}
• Hacim: ${volume:,.0f}

/analyze_{symbol.replace('/', '')} için detaylı analiz"""

                                await self.application.send_message(
                                    chat_id=chat_id,
                                    text=message,
                                    parse_mode='HTML'
                                )
                                
                                # Fiyatı güncelle
                                self.tracked_prices[symbol] = current_price

                            # Her 100 coinde bir debug mesajı
                            if len(self.tracked_prices) % 100 == 0:
                                print(f"⏳ {len(self.tracked_prices)} coin takip ediliyor...")

                            await asyncio.sleep(0.1)  # Rate limit için bekle

                        except Exception as e:
                            print(f"❌ Coin takip hatası {symbol}: {str(e)}")
                            continue

                    await asyncio.sleep(10)  # Her 10 saniyede bir tekrar kontrol et

                except Exception as e:
                    print(f"🚫 Takip döngüsü hatası: {str(e)}")
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            print("⛔️ Takip görevi iptal edildi")
        except Exception as e:
            print(f"💥 Ana takip hatası: {str(e)}")
        finally:
            self.tracked_prices.clear()

    async def start_coin_tracking(self, update: Update, symbol: str, chat_id: int):
        """Coin takibini başlat"""
        try:
            # Major coinleri kontrol et
            major_coins = {'BTC/USDT', 'ETH/USDT', 'BNB/USDT'}
            if symbol in major_coins:
                await update.message.reply_text(
                    f"⚠️ {symbol} otomatik bildirimler kapalıdır.\n"
                    "Sadece manuel kontrol yapabilirsiniz."
                )
                return
                
            # Coini takibe al
            if chat_id not in self.watched_coins:
                self.watched_coins[chat_id] = {}
                
            # Coin verilerini al
            ticker = await self.market_scanner.get_ticker(symbol)
            if not ticker:
                await update.message.reply_text(f"❌ {symbol} verileri alınamadı!")
                return
                
            # Analiz yap
            df = await self.market_scanner.get_ohlcv(symbol)
            if df is None:
                await update.message.reply_text(f"❌ {symbol} OHLCV verileri alınamadı!")
                return
                
            analysis = self._calculate_indicators(df)
            trade_signal = await self._analyze_trading_opportunity(symbol, ticker, analysis)
            
            # Takip bilgilerini kaydet
            self.watched_coins[chat_id][symbol] = {
                'last_alert': datetime.now(),
                'entry_price': ticker['last'],
                'target': trade_signal.get('target', 0),
                'stop_loss': trade_signal.get('stop_loss', 0)
            }
            
            # Bilgilendirme mesajı
            await update.message.reply_text(
                f"✅ {symbol} takibe alındı!\n\n"
                f"• Mevcut Fiyat: ${ticker['last']:.4f}\n"
                f"• 24s Değişim: %{ticker['percentage']:.1f}\n"
                + (trade_signal.get('message', '') if trade_signal else '')
            )
            
            # Takip görevini başlat
            task_key = f"{chat_id}_{symbol}"
            if task_key not in self.watch_tasks:
                self.watch_tasks[task_key] = asyncio.create_task(
                    self._watch_coin(symbol, chat_id, ticker['last'])
                )
                
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {str(e)}")

    async def handle_coin_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kullanıcıdan gelen coin mesajlarını işle"""
        try:
            # Mesajı al ve temizle
            symbol = update.message.text.upper().strip()
            chat_id = update.effective_chat.id
            
            # Eğer USDT eki yoksa ekle
            if '/' not in symbol:
                symbol = f"{symbol}/USDT"
            
            # Coini takibe al
            await self.start_coin_tracking(update, symbol, chat_id)
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Hata: {str(e)}\n\n"
                "Lütfen geçerli bir coin sembolü girin.\n"
                "Örnek: BTC veya BTC/USDT"
            )

    async def start(self):
        """Bot'u başlat"""
        try:
            print("🤖 Bot başlatılıyor...")
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            
            print("✅ Bot başlatıldı!")
            
            # Bot'u sürekli çalışır durumda tut
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"❌ Bot başlatma hatası: {str(e)}")
            raise

    async def stop(self):
        """Bot'u durdur"""
        try:
            print("\n👋 Bot kapatılıyor...")
            
            # Aktif görevleri iptal et
            if self.scan_task:
                self.scan_task.cancel()
            if self.track_task:
                self.track_task.cancel()
            if self.monitoring_task:
                self.monitoring_task.cancel()
            
            # Watch görevlerini iptal et
            for task in self.watch_tasks.values():
                task.cancel()
            self.watch_tasks.clear()
            
            # Önce updater'ı durdur
            if self.application.updater and self.application.updater.running:
                await self.application.updater.stop()
            
            # Sonra bot'u durdur
            if self.application.running:
                await self.application.stop()
                await self.application.shutdown()
            
            print("✅ Bot kapatıldı!")
            
        except Exception as e:
            print(f"❌ Bot kapatma hatası: {str(e)}")
            raise

    def run(self):
        """Bot'u asenkron olarak çalıştır"""
        try:
            # Event loop oluştur
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Bot'u başlat ve sürekli çalışır durumda tut
            loop.run_until_complete(self.start())
            
        except KeyboardInterrupt:
            print("\n⚠️ Klavye kesintisi algılandı...")
            loop.run_until_complete(self.stop())
        except Exception as e:
            print(f"❌ Bot çalıştırma hatası: {str(e)}")
            loop.run_until_complete(self.stop())
        finally:
            loop.close()

    async def analyze_signal(self, symbol: str, df: pd.DataFrame) -> Dict:
        """Teknik analiz yap ve sinyal üret"""
        try:
            # RSI
            rsi = RSIIndicator(df['close'], window=14)
            current_rsi = float(rsi.rsi().iloc[-1])
            
            # EMA
            ema20 = float(EMAIndicator(df['close'], window=20).ema_indicator().iloc[-1])
            ema50 = float(EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1])
            
            # MACD
            macd = MACD(df['close'])
            current_macd = float(macd.macd().iloc[-1])
            current_signal = float(macd.macd_signal().iloc[-1])
            
            # VWAP
            vwap = float(VolumeWeightedAveragePrice(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                volume=df['volume']
            ).volume_weighted_average_price().iloc[-1])
            
            # Hacim değişimi
            recent_vol = float(df['volume'].iloc[-3:].mean())
            prev_vol = float(df['volume'].iloc[-6:-3].mean())
            volume_change = ((recent_vol - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0.0
            
            # Fiyat değişimi
            price_change = float(((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100))
            
            # Trend analizi
            trend = "YUKARI" if ema20 > ema50 else "AŞAĞI"
            momentum = "GÜÇLÜ" if abs(price_change) > 2 and abs(volume_change) > 50 else "NORMAL"
            
            return {
                'rsi': current_rsi,
                'ema20': ema20,
                'ema50': ema50,
                'macd': current_macd,
                'macd_signal': current_signal,
                'vwap': vwap,
                'volume_change': volume_change,
                'price_change': price_change,
                'current_price': float(df['close'].iloc[-1]),
                'trend': trend,
                'momentum': momentum
            }
            
        except Exception as e:
            print(f"Analiz hatası {symbol}: {str(e)}")
            return None

    async def _analyze_trading_opportunity(self, symbol: str, data: Dict, analysis: Dict) -> Dict:
        """Gelişmiş alım-satım fırsatı analizi ve balina takibi"""
        try:
            current_price = data['last']
            volume = data.get('quoteVolume', 0)
            
            # Balina analizi - Güvenli veri kontrolü
            ask_volume = float(data.get('askVolume', 0) or 0)
            bid_volume = float(data.get('bidVolume', 0) or 0)
            trade_count = int(data.get('count', 0) or 0)
            price_change = float(data.get('priceChangePercent', 0) or 0)
            
            # Balina koşulları güvenli kontrol
            whale_conditions = {
                'volume_spike': volume > 5000000,  # 5M USDT üzeri işlem hacmi
                'large_trades': trade_count > 1000,  # Son 24s'te yüksek işlem sayısı
                'price_impact': abs(price_change) > 2,  # %2'den fazla fiyat değişimi
                'buy_volume': ask_volume > bid_volume if (ask_volume and bid_volume) else False,
                'sell_volume': bid_volume > ask_volume if (ask_volume and bid_volume) else False
            }
            
            # Balina aktivitesi skoru (0-5 arası)
            whale_score = sum([
                volume > 5000000,  # Hacim kontrolü
                trade_count > 1000,  # İşlem sayısı
                abs(price_change) > 2,  # Fiyat etkisi
                ask_volume > bid_volume * 1.5 if (ask_volume and bid_volume) else False,  # Güçlü alış
                bid_volume > ask_volume * 1.5 if (ask_volume and bid_volume) else False   # Güçlü satış
            ])
            
            # Teknik göstergeler
            rsi = analysis.get('rsi', 50)
            macd = analysis.get('macd', {})
            bb = analysis.get('bb', {})
            vwap = analysis.get('vwap', current_price)
            stoch_rsi = analysis.get('stoch_rsi', {})
            trend = analysis.get('trend', {})
            
            # LONG (Alış) Fırsatı için kriterler
            long_conditions = [
                rsi < 40,  # RSI aşırı satım
                macd.get('histogram', 0) > 0,  # MACD pozitif
                current_price < bb.get('middle', 0),  # BB orta bandı altında
                volume > 1000000,  # Minimum hacim
                stoch_rsi.get('k', 50) < 20,  # Stoch RSI aşırı satım
                current_price > vwap * 0.995,  # VWAP yakını
                bb.get('squeeze', False),  # BB sıkışması
                trend.get('momentum', 'NEUTRAL') == 'UP',  # Yukarı momentum
                whale_conditions['buy_volume'],  # Balina alış baskısı
                whale_score >= 3  # Güçlü balina aktivitesi
            ]
            
            # SHORT (Satış) Fırsatı için kriterler
            short_conditions = [
                rsi > 60,  # RSI aşırı alım
                macd.get('histogram', 0) < 0,  # MACD negatif
                current_price > bb.get('middle', 0),  # BB orta bandı üstünde
                volume > 1000000,  # Minimum hacim
                stoch_rsi.get('k', 50) > 80,  # Stoch RSI aşırı alım
                current_price < vwap * 1.005,  # VWAP yakını
                bb.get('squeeze', False),  # BB sıkışması
                trend.get('momentum', 'NEUTRAL') == 'DOWN',  # Aşağı momentum
                whale_conditions['sell_volume'],  # Balina satış baskısı
                whale_score >= 3  # Güçlü balina aktivitesi
            ]
            
            # En az 6 kriterin sağlanması gerekiyor (balina kriterleri eklendi)
            long_signal = sum(long_conditions) >= 6
            short_signal = sum(short_conditions) >= 6

            result = {
                'signal': None,
                'entry': current_price,
                'target': 0.0,
                'stop_loss': 0.0,
                'message': ''
            }

            if long_signal or short_signal:
                signal_type = "LONG" if long_signal else "SHORT"
                emoji = "💚" if long_signal else "❤️"
                
                # Destek/Direnç seviyeleri
                next_support = max([s for s in analysis.get('support_levels', [current_price * 0.985]) if s < current_price], default=current_price * 0.985)
                next_resistance = min([r for r in analysis.get('resistance_levels', [current_price * 1.015]) if r > current_price], default=current_price * 1.015)
                
                target = next_resistance if long_signal else next_support
                stop = next_support if long_signal else next_resistance
                
                # Gelişmiş Risk Yönetimi
                risk_ratio = abs(target - current_price) / abs(current_price - stop)
                risk_score = min(5, round(risk_ratio * 2))  # Risk skoru (1-5)
                
                # Risk skoruna göre pozisyon büyüklüğü
                position_sizes = {
                    1: "Bakiyenin %1'i",
                    2: "Bakiyenin %2'si",
                    3: "Bakiyenin %3'ü",
                    4: "Bakiyenin %4'ü",
                    5: "Bakiyenin %5'i"
                }
                
                # Risk skoruna göre kaldıraç önerisi
                leverage_sizes = {
                    1: 2,  # Çok düşük risk
                    2: 2,  # Düşük risk
                    3: 2,  # Orta risk
                    4: 1,  # Yüksek risk
                    5: 1   # Çok yüksek risk
                }
                
                suggested_position = position_sizes.get(risk_score, "Bakiyenin %1'i")
                suggested_leverage = leverage_sizes.get(risk_score, 1)
                
                # Risk uyarı mesajı
                risk_warning = "🟢 Düşük Risk" if risk_score <= 2 else "🟡 Orta Risk" if risk_score <= 4 else "🔴 Yüksek Risk"
                
                # Balina durumu mesajı
                whale_status = f"""🐋 Balina Aktivitesi (Skor: {whale_score}/5):
• Büyük Hacim: {"✅" if whale_conditions['volume_spike'] else "❌"}
• Yoğun İşlem: {"✅" if whale_conditions['large_trades'] else "❌"}
• Fiyat Etkisi: {"✅" if whale_conditions['price_impact'] else "❌"}
• Alış Baskısı: {"✅" if whale_conditions['buy_volume'] else "❌"}
• Satış Baskısı: {"✅" if whale_conditions['sell_volume'] else "❌"}"""
                
                result.update({
                    'signal': signal_type,
                    'entry': current_price,
                    'target': target,
                    'stop_loss': stop,
                    'message': f"""🎯 {symbol} {signal_type} FIRSATI {emoji}

💰 Fiyat Seviyeleri:
• Giriş: ${current_price:.4f}
• Hedef: ${target:.4f} ({((target-current_price)/current_price*100):.1f}%)
• Stop: ${stop:.4f} ({((stop-current_price)/current_price*100):.1f}%)

{whale_status}

📊 Teknik Durum:
• RSI: {rsi:.1f}
• Stoch RSI: {stoch_rsi.get('k', 0):.1f}
• MACD: {"Pozitif" if macd.get('histogram', 0) > 0 else "Negatif"}
• VWAP: ${vwap:.4f}
• Hacim: ${volume:,.0f}
• BB Sıkışma: {"Var ✅" if bb.get('squeeze', False) else "Yok ❌"}
• Momentum: {trend.get('momentum', 'NEUTRAL')}

⚠️ Risk Yönetimi:
• Risk Seviyesi: {risk_warning}
• Önerilen Pozisyon: {suggested_position}
• Önerilen Kaldıraç: {suggested_leverage}x
• Risk/Ödül: {risk_ratio:.2f}

🎯 Güvenli Giriş Stratejisi:
• Test Pozisyonu: Bakiyenin %1'i ile başlayın
• Giriş Bölgesi: ${current_price:.4f} civarı
• Hedef Bölgesi: ${target:.4f}
• Stop-Loss: ${stop:.4f} (Zorunlu!)

⚠️ Önemli Güvenlik Notları:
• İzole marjin kullanın
• Stop-loss emirlerinizi MUTLAKA girin
• Önce küçük pozisyonla test edin
• Kâr hedefine ulaşınca %50 çıkın
• Trend değişiminde hemen çıkın
• FOMO yapmayın!"""
                })

            return result

        except Exception as e:
            print(f"Trade analiz hatası {symbol}: {str(e)}")
            return {}

    def _get_market_status(self, analysis: Dict) -> str:
        """Piyasa durumunu yorumla"""
        if analysis['rsi'] > 70:
            return "Aşırı Alım Bölgesi ⚠️ - Short fırsatı olabilir"
        elif analysis['rsi'] < 30:
            return "Aşırı Satış Bölgesi 🔥 - Long fırsatı olabilir"
        elif analysis['macd'] > analysis['macd_signal']:
            return "Yükseliş Trendi 📈 - Long pozisyonlar avantajlı"
        elif analysis['macd'] < analysis['macd_signal']:
            return "Düşüş Trendi 📉 - Short pozisyonlar avantajlı"
        else:
            return "Nötr ⚖️ - Net sinyal bekleniyor"

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """Gelişmiş teknik gösterge hesaplamaları"""
        try:
            # Daha uzun veri penceresi için son 200 mum
            df = df.tail(200).copy()
            
            # RSI hesaplama (Wilder's RSI)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            # MACD hesaplama
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            histogram = macd - signal

            # Bollinger Bands
            sma20 = df['close'].rolling(window=20).mean()
            std20 = df['close'].rolling(window=20).std()
            bb_upper = sma20 + (std20 * 2)
            bb_middle = sma20
            bb_lower = sma20 - (std20 * 2)
            
            # Bollinger Band Genişliği
            bb_width = (bb_upper - bb_lower) / bb_middle
            bb_squeeze = bb_width < bb_width.rolling(window=20).mean()

            # VWAP hesaplama
            df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

            # Stochastic RSI
            rsi_k = 14  # RSI periyodu
            stoch_k = 3  # Stochastic K periyodu
            stoch_d = 3  # Stochastic D periyodu
            stoch_rsi = (rsi - rsi.rolling(window=stoch_k).min()) / \
                       (rsi.rolling(window=stoch_k).max() - rsi.rolling(window=stoch_k).min())
            stoch_rsi_k = stoch_rsi.rolling(window=stoch_k).mean() * 100
            stoch_rsi_d = stoch_rsi_k.rolling(window=stoch_d).mean()

            # Pivot Noktaları (son 20 mum)
            pivot_window = 20
            high_max = df['high'].rolling(window=pivot_window, center=True).max()
            low_min = df['low'].rolling(window=pivot_window, center=True).min()
            
            # Destek ve Direnç Seviyeleri
            current_price = df['close'].iloc[-1]
            supports = []
            resistances = []
            
            # Pivot noktalarından destek/direnç
            for i in range(-30, -5):
                if df['low'].iloc[i] == low_min.iloc[i]:
                    supports.append(df['low'].iloc[i])
                if df['high'].iloc[i] == high_max.iloc[i]:
                    resistances.append(df['high'].iloc[i])
            
            # Bollinger bantlarını ekle
            supports.extend([bb_lower.iloc[-1], sma20.iloc[-1] * 0.985])
            resistances.extend([bb_upper.iloc[-1], sma20.iloc[-1] * 1.015])
            
            # Benzersiz ve sıralı destek/direnç seviyeleri
            supports = sorted(list(set(supports)))
            resistances = sorted(list(set(resistances)))

            return {
                'rsi': float(rsi.iloc[-1]),
                'stoch_rsi': {
                    'k': float(stoch_rsi_k.iloc[-1]),
                    'd': float(stoch_rsi_d.iloc[-1])
                },
                'macd': {
                    'macd': float(macd.iloc[-1]),
                    'signal': float(signal.iloc[-1]),
                    'histogram': float(histogram.iloc[-1])
                },
                'bb': {
                    'upper': float(bb_upper.iloc[-1]),
                    'middle': float(bb_middle.iloc[-1]),
                    'lower': float(bb_lower.iloc[-1]),
                    'width': float(bb_width.iloc[-1]),
                    'squeeze': bool(bb_squeeze.iloc[-1])
                },
                'vwap': float(df['vwap'].iloc[-1]),
                'current_close': float(df['close'].iloc[-1]),
                'support_levels': [float(s) for s in supports if s < current_price],
                'resistance_levels': [float(r) for r in resistances if r > current_price],
                'trend': {
                    'short': 'UP' if current_price > sma20.iloc[-1] else 'DOWN',
                    'squeeze': bool(bb_squeeze.iloc[-1]),
                    'momentum': 'UP' if histogram.iloc[-1] > histogram.iloc[-2] else 'DOWN'
                }
            }

        except Exception as e:
            print(f"❌ Gösterge hesaplama hatası: {str(e)}")
            return {
                'rsi': 50,
                'stoch_rsi': {'k': 50, 'd': 50},
                'macd': {'macd': 0, 'signal': 0, 'histogram': 0},
                'bb': {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0, 'squeeze': False},
                'vwap': 0,
                'current_close': 0,
                'support_levels': [],
                'resistance_levels': [],
                'trend': {'short': 'NEUTRAL', 'squeeze': False, 'momentum': 'NEUTRAL'}
            }

    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Belirli bir coin için detaylı analiz yap"""
        try:
            # Komuttan sembolü al (örn: /analyze_BTCUSDT -> BTC/USDT)
            command = update.message.text.split('_')[1]
            symbol = f"{command[:-4]}/{command[-4:]}" if command.endswith('USDT') else None
            
            if not symbol:
                await update.message.reply_text("❌ Geçersiz sembol formatı!")
                return

            await update.message.reply_text(f"🔄 {symbol} analiz ediliyor...")

            # Market verilerini al
            ticker = await self.market_scanner.get_ticker(symbol)
            if not ticker:
                await update.message.reply_text(f"❌ {symbol} verileri alınamadı!")
                return

            # OHLCV verilerini al
            df = await self.market_scanner.get_ohlcv(symbol)
            if df is None or df.empty:
                await update.message.reply_text(f"❌ {symbol} için OHLCV verileri alınamadı!")
                return

            # Teknik analiz
            analysis = self._calculate_indicators(df)
            
            # Detaylı analiz mesajı oluştur
            current_price = ticker['last']
            volume = ticker['quoteVolume']
            
            rsi = analysis['rsi']
            macd = analysis['macd']
            bb = analysis['bb']

            # RSI durumu
            rsi_status = "Aşırı Satım! 📉" if rsi < 30 else "Aşırı Alım! 📈" if rsi > 70 else "Nötr ⚖️"
            
            # MACD sinyali
            macd_signal = "Alış 🟢" if macd['histogram'] > 0 else "Satış 🔴"
            
            # Bollinger durumu
            bb_status = "Üst Band Üstünde 📈" if current_price > bb['upper'] else \
                       "Alt Band Altında 📉" if current_price < bb['lower'] else \
                       "Bandlar Arasında ↔️"

            analysis_message = f"""📊 {symbol} Detaylı Analiz

💰 Fiyat: ${current_price:,.4f}
📈 24s Hacim: ${volume:,.0f}

📌 Teknik Göstergeler:
• RSI ({rsi:.1f}): {rsi_status}
• MACD: {macd_signal}
• Bollinger: {bb_status}

🎯 Destek/Direnç:
• Üst Band: ${bb['upper']:,.4f}
• Orta Band: ${bb['middle']:,.4f}
• Alt Band: ${bb['lower']:,.4f}

⚡️ Sinyal:
• RSI: {'AL' if rsi < 30 else 'SAT' if rsi > 70 else 'BEKLE'}
• MACD: {'AL' if macd['histogram'] > 0 else 'SAT'}
• Bollinger: {'SAT' if current_price > bb['upper'] else 'AL' if current_price < bb['lower'] else 'BEKLE'}

⏰ {datetime.now().strftime('%H:%M:%S')}"""

            await update.message.reply_text(analysis_message)

        except Exception as e:
            error_msg = f"❌ Analiz hatası: {str(e)}"
            print(error_msg)
            await update.message.reply_text(error_msg)

    def _find_support_levels(self, df: pd.DataFrame, window: int = 20) -> List[float]:
        """Destek seviyelerini bul"""
        try:
            lows = df['low'].values
            local_mins = argrelextrema(lows, np.less, order=window)[0]
            support_levels = sorted([lows[i] for i in local_mins], reverse=True)
            return [level for level in support_levels if level < df['close'].iloc[-1]]
        except:
            return []

    def _find_resistance_levels(self, df: pd.DataFrame, window: int = 20) -> List[float]:
        """Direnç seviyelerini bul"""
        try:
            highs = df['high'].values
            local_maxs = argrelextrema(highs, np.greater, order=window)[0]
            resistance_levels = sorted([highs[i] for i in local_maxs])
            return [level for level in resistance_levels if level > df['close'].iloc[-1]]
        except:
            return []

    def _determine_trend(self, df: pd.DataFrame) -> str:
        """Trend analizi"""
        try:
            close = df['close'].iloc[-1]
            ema20 = EMAIndicator(df['close'], window=20).ema_indicator().iloc[-1]
            ema50 = EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
            ema200 = EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]

            if close > ema20 > ema50 > ema200:
                return "GÜÇLÜ YÜKSELİŞ 📈"
            elif close > ema20 > ema50:
                return "YÜKSELİŞ ↗️"
            elif close < ema20 < ema50 < ema200:
                return "GÜÇLÜ DÜŞÜŞ 📉"
            elif close < ema20 < ema50:
                return "DÜŞÜŞ ↘️"
            else:
                return "YATAY ↔️"
        except:
            return "BELİRSİZ"

    def _detect_formation(self, df: pd.DataFrame) -> str:
        """Temel formasyonları tespit et"""
        try:
            closes = df['close'].values[-30:]  # Son 30 mum
            highs = df['high'].values[-30:]
            lows = df['low'].values[-30:]

            # Çift Dip Kontrolü
            if (lows[-1] > lows[-2] and 
                min(lows[-5:-2]) < lows[-1] and 
                min(lows[-5:-2]) < lows[-2]):
                return "ÇİFT DİP 🔄"

            # Çift Tepe Kontrolü
            if (highs[-1] < highs[-2] and 
                max(highs[-5:-2]) > highs[-1] and 
                max(highs[-5:-2]) > highs[-2]):
                return "ÇİFT TEPE ⚠️"

            return "BELİRGİN FORMASYON YOK"
        except:
            return "FORMASYON ANALİZİ YAPILAMADI"

    def _calculate_volatility(self, df: pd.DataFrame) -> str:
        """Volatilite analizi"""
        try:
            returns = df['close'].pct_change()
            volatility = returns.std() * np.sqrt(len(returns))
            
            if volatility > 0.05:
                return "YÜKSEK VOLATİLİTE ⚠️"
            elif volatility > 0.02:
                return "ORTA VOLATİLİTE ⚡️"
            else:
                return "DÜŞÜK VOLATİLİTE 🟢"
        except:
            return "VOLATİLİTE HESAPLANAMADI"

    def _generate_market_summary(self, analysis: Dict) -> str:
        """Piyasa özeti oluştur"""
        if analysis['rsi'] > 70:
            return "Piyasa aşırı alım bölgesinde, dikkatli olunmalı"
        elif analysis['rsi'] < 30:
            return "Piyasa aşırı satım bölgesinde, fırsatlar olabilir"
        elif analysis['macd'] > analysis['macd_signal']:
            return "MACD pozitif, yükseliş trendi güçlenebilir"
        elif analysis['macd'] < analysis['macd_signal']:
            return "MACD negatif, düşüş trendi devam edebilir"
        else:
            return "Piyasa dengeli, nötr bölgede hareket ediyor"

    def _generate_recommendation(self, analysis: Dict) -> str:
        """Strateji önerisi oluştur"""
        if analysis['rsi'] > 70 and analysis['macd'] < analysis['macd_signal']:
            return "Kar realizasyonu düşünülebilir, yeni alımlar için beklemede kalın"
        elif analysis['rsi'] < 30 and analysis['macd'] > analysis['macd_signal']:
            return "Kademeli alım fırsatı, stop-loss ile pozisyon açılabilir"
        elif analysis['ema20'] > analysis['ema50']:
            return "Trend yukarı yönlü, düşüşler alım fırsatı olabilir"
        elif analysis['ema20'] < analysis['ema50']:
            return "Trend aşağı yönlü, yükselişler satış fırsatı olabilir"
        else:
            return "Temkinli hareket edilmeli, trend netleşene kadar beklenebilir"

    def _generate_technical_summary(self, data: Dict) -> str:
        """Teknik analiz özeti oluştur"""
        if data['rsi'] > 70:
            return "Aşırı alım ⚠️"
        elif data['rsi'] < 30:
            return "Aşırı satım 🔍"
        elif data['volume_change'] > 50:
            return "Yüksek hacim artışı 📈"
        elif data['price_change'] > 5:
            return "Güçlü yükseliş ⤴️"
        elif data['price_change'] < -5:
            return "Sert düşüş ⤵️"
        else:
            return "Normal seyir ↔️"

    def _generate_warning(self, data: Dict) -> str:
        """Uyarı mesajı oluştur"""
        warnings = []
        if data['rsi'] > 75:
            warnings.append("Aşırı alım seviyesi")
        if data['rsi'] < 25:
            warnings.append("Aşırı satım seviyesi")
        if abs(data['price_change']) > 10:
            warnings.append("Yüksek volatilite")
        if data['volume_change'] > 100:
            warnings.append("Anormal hacim artışı")
        return " & ".join(warnings) if warnings else ""

    async def _get_coin_news(self, symbol: str) -> str:
        """Coin ile ilgili haberleri getir"""
        # TODO: Haber API entegrasyonu
        return ""

    async def _get_social_sentiment(self, symbol: str) -> str:
        """Sosyal medya duyarlılığını getir"""
        # TODO: Sosyal medya API entegrasyonu
        return ""

    async def _fetch_news(self, url: str) -> str:
        """Belirtilen URL'den haberleri çek"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
        except Exception as e:
            print(f"Haber çekme hatası: {str(e)}")
        return None

    def _parse_coindesk(self, html: str) -> List[Dict]:
        """CoinDesk haberlerini parse et"""
        news = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            articles = soup.find_all('article', limit=3)
            
            for article in articles:
                title = article.find('h4')
                if title:
                    news.append({
                        'title': title.text.strip(),
                        'source': 'CoinDesk'
                    })
        except Exception as e:
            print(f"CoinDesk parse hatası: {str(e)}")
        return news

    def _parse_cointelegraph(self, html: str) -> List[Dict]:
        """CoinTelegraph haberlerini parse et"""
        news = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            articles = soup.find_all('article', limit=3)
            
            for article in articles:
                title = article.find('span', class_='post-card-inline__title')
                if title:
                    news.append({
                        'title': title.text.strip(),
                        'source': 'CoinTelegraph'
                    })
        except Exception as e:
            print(f"CoinTelegraph parse hatası: {str(e)}")
        return news

    def _parse_investing(self, html: str) -> List[Dict]:
        """Investing.com haberlerini parse et"""
        news = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            articles = soup.find_all('article', class_='js-article-item', limit=3)
            
            for article in articles:
                title = article.find('a', class_='title')
                if title:
                    news.append({
                        'title': title.text.strip(),
                        'source': 'Investing.com'
                    })
        except Exception as e:
            print(f"Investing.com parse hatası: {str(e)}")
        return news

    def _analyze_sentiment(self, title: str) -> int:
        """Haber başlığından duygu analizi yap"""
        positive_words = {'yüksel', 'artış', 'rally', 'surge', 'gain', 'bull', 'up', 'pozitif', 'başarı'}
        negative_words = {'düşüş', 'crash', 'dump', 'bear', 'down', 'negatif', 'risk', 'kayıp'}
        
        title = title.lower()
        pos_count = sum(1 for word in positive_words if word in title)
        neg_count = sum(1 for word in negative_words if word in title)
        
        return pos_count - neg_count

    async def _analyze_news(self, symbol: str) -> str:
        """Haberleri analiz et ve yorumla"""
        try:
            # Coin ismini temizle
            coin_name = symbol.split('/')[0]
            
            all_news = []
            sentiment_total = 0
            
            # Tüm kaynaklardan haberleri çek
            for source, url_template in self.news_sources.items():
                url = url_template.format(coin_name)
                html = await self._fetch_news(url)
                
                if html:
                    if source == 'coindesk':
                        news = self._parse_coindesk(html)
                    elif source == 'cointelegraph':
                        news = self._parse_cointelegraph(html)
                    else:  # investing
                        news = self._parse_investing(html)
                        
                    all_news.extend(news)
                    
                    # Duygu analizi
                    for item in news:
                        sentiment_total += self._analyze_sentiment(item['title'])
            
            # Sonucu yorumla
            if not all_news:
                return "Önemli bir haber yok"
                
            avg_sentiment = sentiment_total / len(all_news)
            
            if avg_sentiment > 1:
                return "Pozitif - Yükseliş beklentisi"
            elif avg_sentiment < -1:
                return "Negatif - Düşüş beklentisi"
            else:
                return "Nötr - Yatay seyir"
                
        except Exception as e:
            print(f"Haber analizi hatası: {str(e)}")
            return "Haber analizi yapılamadı"

    async def check_target_hit(self, symbol: str, current_price: float, chat_id: int):
        """Hedef fiyat kontrolü"""
        try:
            if chat_id in self.watched_coins and symbol in self.watched_coins[chat_id]:
                coin_data = self.watched_coins[chat_id][symbol]
                
                if 'target' in coin_data:
                    target = coin_data['target']
                    entry = coin_data['entry_price']
                    
                    # LONG pozisyon hedef kontrolü
                    if entry < target and current_price >= target:
                        await self.application.send_message(
                            chat_id=chat_id,
                            text=f"""🎯 HEDEF BAŞARI: {symbol}

• Giriş: ${entry:.4f}
• Hedef: ${target:.4f}
• Mevcut: ${current_price:.4f}
• Kar: %{((current_price/entry - 1) * 100):.1f}

✅ Kar alma düşünülebilir!"""
                        )
                        
                    # SHORT pozisyon hedef kontrolü
                    elif entry > target and current_price <= target:
                        await self.application.send_message(
                            chat_id=chat_id,
                            text=f"""🎯 HEDEF BAŞARI: {symbol}

• Giriş: ${entry:.4f}
• Hedef: ${target:.4f}
• Mevcut: ${current_price:.4f}
• Kar: %{((entry/current_price - 1) * 100):.1f}

✅ Kar alma düşünülebilir!"""
                        )
                        
        except Exception as e:
            print(f"Hedef kontrol hatası {symbol}: {str(e)}")

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
    
    bot = TelegramBot(token=TOKEN)
    
    async def main():
        try:
            await bot.start()
        except KeyboardInterrupt:
            print("\n👋 Bot kullanıcı tarafından durduruldu")
        except Exception as e:
            print(f"❌ Ana program hatası: {e}")
        finally:
            await bot.stop()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
