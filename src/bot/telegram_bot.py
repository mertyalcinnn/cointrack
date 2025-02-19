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
import logging
import json
from .modules.market_analyzer import MarketAnalyzer
from .modules.message_formatter import MessageFormatter
from .modules.handlers.scan_handler import ScanHandler
from .modules.handlers.track_handler import TrackHandler
from .modules.utils.logger import setup_logger

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
        """Initialize the bot with API keys and configuration"""
        # Initialize logger
        self.logger = setup_logger('CoinScanner')
        
        # Initialize components
        self.application = Application.builder().token(token).build()
        self.analyzer = MarketAnalyzer(self.logger)
        self.formatter = MessageFormatter()
        
        # Bot state
        self.last_opportunities = []
        
        # Track handler'ı önce oluştur
        self.track_handler = TrackHandler(self.logger)
        
        # Scan handler'a track handler'ı geçir
        self.scan_handler = ScanHandler(self.logger, self.track_handler)
        
        # Handler'ları kaydet
        self.application.add_handler(CommandHandler("scan", self.scan_handler.handle))
        self.application.add_handler(CommandHandler("track", self.track_handler.handle))
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("list", self.list_tracked_command))
        
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
        
    def _setup_handlers(self):
        """Telegram komut işleyicilerini ayarla"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("scan", self.scan_handler.handle))
        self.application.add_handler(CommandHandler("track", self.track_handler.handle))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("list", self.list_tracked_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Text handler'ı en sona ekleyin
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.handle_coin_input
            )
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot komutları hakkında bilgi ver"""
        help_text = """🤖 Coin Scanner Bot - Komutlar

📊 TEMEL KOMUTLAR:
/start - Botu başlat
/help - Bu yardım mesajını göster
/scan - Fırsat taraması başlat
/stop - Aktif taramayı durdur

📈 TAKİP KOMUTLARI:
/track <numara> - Listedeki coini takibe al
Örnek: /track 1 (listedeki 1 numaralı coini takip et)

/untrack <sembol> - Coini takipten çıkar
Örnek: /untrack BTCUSDT

/list - Takip edilen coinleri listele

⚡️ KULLANIM:
1. /scan komutu ile fırsat taraması başlat
2. Listeden beğendiğin coinin numarasını seç
3. /track <numara> komutu ile takibe al
4. /list ile takip ettiğin coinleri kontrol et
5. /untrack ile takibi sonlandır

❗️ ÖNEMLİ: Önce /scan komutu ile tarama yapın, sonra listeden coin seçip /track komutu ile takibe alın."""

        await update.message.reply_text(help_text)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Başlangıç mesajını göster"""
        # Kullanıcının chat ID'sini kaydet
        user_chat_id = update.effective_chat.id
        self.user_chat_ids.add(user_chat_id)
        
        welcome_text = """🚀 Kripto Sinyal Botuna Hoş Geldiniz!

Bu bot size:
• Otomatik piyasa taraması
• Coin bazlı takip sistemi
• 15 dakikalık al-sat sinyalleri
• Teknik analiz
• Haber takibi
sunar.

Kullanım:
1. Coin takibi için:
   • /track BTC yazın
   • veya direkt BTC yazın
   
2. Piyasa taraması için:
   • /scan yazın
   
3. Yardım için:
   • /help yazın

⚠️ Not: Tüm sinyaller bilgilendirme amaçlıdır.
Yatırım tavsiyesi değildir."""

        await update.message.reply_text(welcome_text)

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
        """Fırsat taraması başlat"""
        try:
            interval = "4h" if not context.args else (
                "15m" if context.args[0].lower() == "scan15" else
                "4h" if context.args[0].lower() == "scan4" else None
            )
            
            if interval is None:
                await update.message.reply_text(
                    "❌ Geçersiz komut!\n"
                    "Kullanım:\n"
                    "/scan - 4 saatlik tarama\n"
                    "/scan scan15 - 15 dakikalık tarama\n"
                    "/scan scan4 - 4 saatlik tarama"
                )
                return

            await update.message.reply_text(f"🔍 {interval} taraması başlatıldı...")
            
            opportunities = await self.analyzer.get_opportunities(interval)
            if not opportunities:
                await update.message.reply_text("❌ Fırsat bulunamadı!")
                return
                
            messages = self.formatter.format_opportunities(opportunities, interval)
            for message in messages:
                await update.message.reply_text(message)
            
            self.last_opportunities = opportunities
            
        except Exception as e:
            await update.message.reply_text(f"❌ Tarama hatası: {str(e)}")

    async def _scan_market(self, chat_id: int):
        """Piyasa taraması ve en iyi 10 fırsatı analiz et"""
        try:
            await self._log("🔍 Piyasa taraması başlatılıyor...", "info", True, chat_id)
            
            # Piyasa verilerini çek
            market_data = await self._get_market_data()
            if not market_data:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Piyasa verileri alınamadı!"
                )
                return

            # Debug mesajı
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"📊 Toplam {len(market_data)} USDT çifti taranıyor..."
            )

            opportunities = []
            min_volume = 100000  # 100K USDT'ye düşürüldü
            min_price_change = 0.1  # %0.1'e düşürüldü

            processed_pairs = 0
            found_opportunities = 0

            for symbol, data in market_data.items():
                try:
                    processed_pairs += 1
                    
                    # Veri dönüşümü
                    volume = float(data['quoteVolume'])
                    price_change = float(data.get('priceChangePercent', 0))
                    current_price = float(data['lastPrice'])
                    high = float(data['highPrice'])
                    low = float(data['lowPrice'])
                    
                    # Minimum hacim kontrolü
                    if volume >= min_volume:
                        # Debug log
                        await self._log(
                            f"Fırsat: {symbol} - Hacim: ${volume:,.0f} - Değişim: %{price_change:.2f}",
                            "debug"
                        )
                        
                        # Volatilite hesaplama
                        volatility = ((high - low) / low * 100) if low > 0 else 0
                        
                        # Momentum hesaplama
                        price_momentum = ((current_price - low) / low * 100) if low > 0 else 0
                        
                        # Hacim momentum
                        volume_momentum = volume / min_volume
                        
                        # RSI sinyali
                        rsi_signal = "AŞIRI ALIM" if price_momentum > 70 else "AŞIRI SATIM" if price_momentum < 30 else "NÖTR"
                        
                        # Volatilite sinyali
                        volatility_signal = "YÜKSEK" if volatility > 5 else "DÜŞÜK" if volatility < 1 else "NÖTR"
                        
                        # Hacim profili
                        volume_profile = "ÇOK YÜKSEK" if volume_momentum > 3 else "YÜKSEK" if volume_momentum > 1.5 else "NORMAL"
                        
                        # Totaller
                        total1 = max(0, volume_momentum * abs(price_momentum))
                        total2 = max(0, volatility * volume_momentum)
                        total3 = max(0, (abs(price_change) + volatility) * volume_momentum)
                        
                        # İşlem sinyalleri
                        long_signal = (
                            price_change > 0 and
                            current_price > low and
                            volatility > 1 and
                            volume_momentum > 1
                        )
                        
                        short_signal = (
                            price_change < 0 and
                            current_price < high and
                            volatility > 1 and
                            volume_momentum > 1
                        )
                        
                        # Risk seviyesi
                        risk_level = min(5, max(1, int((volatility / 3 + volume_momentum / 1.5 + abs(price_momentum) / 15))))
                        
                        # Pozisyon büyüklüğü
                        position_size = min(5, max(1, int((volume_momentum * 1.5 + abs(price_momentum) / 8 + volatility / 3) / 3)))
                        
                        # Skor hesaplama
                        volume_score = min(100, max(0, volume_momentum * 15))
                        volatility_score = min(100, max(0, volatility * 5))
                        momentum_score = min(100, max(0, abs(price_momentum) * 3))
                        
                        total_score = (
                            volume_score * 0.4 +
                            volatility_score * 0.3 +
                            momentum_score * 0.3
                        )
                        
                        # Fırsatı listeye ekle
                        opportunities.append({
                            'symbol': symbol,
                            'price': current_price,
                            'volume': volume,
                            'change': price_change,
                            'high': high,
                            'low': low,
                            'volatility': volatility,
                            'price_momentum': price_momentum,
                            'volume_momentum': volume_momentum,
                            'total1': total1,
                            'total2': total2,
                            'total3': total3,
                            'long_signal': long_signal,
                            'short_signal': short_signal,
                            'risk_level': risk_level,
                            'position_size': position_size,
                            'rsi_signal': rsi_signal,
                            'volatility_signal': volatility_signal,
                            'volume_profile': volume_profile,
                            'score': total_score
                        })
                        found_opportunities += 1
                        
                except Exception as e:
                    await self._log(f"{symbol} için hesaplama hatası: {str(e)}", "error")
                    continue

            # Debug mesajı
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 {len(opportunities)} fırsat analiz edildi."
            )

            # En iyi 10'u seç
            opportunities.sort(key=lambda x: x['score'], reverse=True)
            top_10 = opportunities[:10]

            if not top_10:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Kriterlere uygun fırsat bulunamadı!"
                )
                return

            # Sonuçları gönder
            message = "🎯 KRIPTO FIRSAT TARAYICI\n"
            message += "━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            for idx, opp in enumerate(top_10, 1):
                signal_emoji = "🟢" if opp['long_signal'] else "🔴" if opp['short_signal'] else "⚪"
                risk_emoji = "🔥" * opp['risk_level']
                position_stars = "⭐" * opp['position_size']
                
                message += f"#{idx} {signal_emoji} {opp['symbol']}\n"
                message += f"━━━━━━━━━━━━━━━━━━━━━\n"
                message += f"💰 Fiyat: ${opp['price']:.4f}\n"
                message += f"📊 24s Değişim: %{opp['change']:.2f}\n"
                message += f"📈 24s Hacim: ${opp['volume']:,.0f}\n"
                message += f"📐 Volatilite: %{opp['volatility']:.2f}\n\n"
                
                message += f"📊 TEKNIK GÖSTERGELER:\n"
                message += f"• Momentum: %{opp['price_momentum']:.2f}\n"
                message += f"• RSI Durumu: {opp['rsi_signal']}\n"
                message += f"• Volatilite: {opp['volatility_signal']}\n"
                message += f"• Hacim Profili: {opp['volume_profile']}\n\n"
                
                message += f"💫 TOTALLER:\n"
                message += f"• T1 (Momentum): {opp['total1']:.1f}\n"
                message += f"• T2 (Volatilite): {opp['total2']:.1f}\n"
                message += f"• T3 (Genel Güç): {opp['total3']:.1f}\n\n"
                
                message += f"🎯 15 DAKİKALIK SINYAL:\n"
                if opp['long_signal']:
                    message += "LONG ⬆️\n"
                    message += f"• Giriş: ${opp['price']:.4f}\n"
                    message += f"• Hedef: ${opp['price'] * 1.02:.4f}\n"
                    message += f"• Stop: ${opp['price'] * 0.99:.4f}\n"
                elif opp['short_signal']:
                    message += "SHORT ⬇️\n"
                    message += f"• Giriş: ${opp['price']:.4f}\n"
                    message += f"• Hedef: ${opp['price'] * 0.98:.4f}\n"
                    message += f"• Stop: ${opp['price'] * 1.01:.4f}\n"
                else:
                    message += "BEKLE ⏳\n"
                    message += "• Sinyal bekleniyor...\n"
                
                message += f"\n🎲 RİSK SEVİYESİ: {risk_emoji}\n"
                message += f"💪 POZİSYON BÜYÜKLÜĞÜ: {position_stars}\n"
                message += f"⭐ FIRSAT SKORU: {opp['score']:.1f}/100\n"
                message += "\n━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Mesajı bölerek gönder
            if len(message) > 4000:
                chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for chunk in chunks:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=chunk
                    )
            else:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message
                )

            # Özet mesajı
            summary = (
                "📈 PIYASA ÖZETI:\n"
                f"• Taranan Coin Sayısı: {len(market_data)}\n"
                f"• Bulunan Fırsat Sayısı: {len(opportunities)}\n"
                f"• LONG Sinyali: {sum(1 for x in top_10 if x['long_signal'])}\n"
                f"• SHORT Sinyali: {sum(1 for x in top_10 if x['short_signal'])}\n"
                f"• Ortalama Volatilite: {sum(x['volatility'] for x in top_10) / len(top_10):.2f}%\n"
                "\n🔍 Bir sonraki tarama için /scan komutunu kullanın."
            )
            
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=summary
            )

        except Exception as e:
            await self._log(f"Tarama hatası: {str(e)}", "error")
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Tarama sırasında bir hata oluştu: {str(e)}"
            )
        finally:
            self.is_scanning = False

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
        """Coin takip komutunu işle"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen takip edilecek coini belirtin.\n"
                    "Örnek: /track 1 (listedeki 1 numaralı coin için)"
                )
                return

            chat_id = update.message.chat_id
            selection = int(context.args[0])

            if not hasattr(self, 'last_opportunities') or not self.last_opportunities:
                await update.message.reply_text("❌ Önce /scan komutu ile tarama yapın!")
                return

            if selection < 1 or selection > len(self.last_opportunities):
                await update.message.reply_text("❌ Geçersiz seçim! Lütfen listeden geçerli bir numara seçin.")
                return

            coin_data = self.last_opportunities[selection - 1]
            symbol = coin_data['symbol']

            # Zaten takip ediliyor mu kontrol et
            if chat_id in self.tracked_coins and symbol in self.tracked_coins[chat_id]:
                await update.message.reply_text(f"⚠️ {symbol} zaten takip ediliyor!")
                return

            # Takip verilerini kaydet
            if chat_id not in self.tracked_coins:
                self.tracked_coins[chat_id] = {}
            
            self.tracked_coins[chat_id][symbol] = {
                'entry_price': coin_data['price'],
                'target_price': coin_data['price'] * 1.02 if coin_data['long_signal'] else coin_data['price'] * 0.98,
                'stop_price': coin_data['price'] * 0.99 if coin_data['long_signal'] else coin_data['price'] * 1.01,
                'is_long': coin_data['long_signal'],
                'start_time': time.time(),
                'last_alert': time.time()
            }

            # Takip görevini başlat
            if chat_id not in self.track_tasks:
                self.track_tasks[chat_id] = {}
            
            self.track_tasks[chat_id][symbol] = asyncio.create_task(
                self._track_coin(chat_id, symbol)
            )

            await update.message.reply_text(
                f"✅ {symbol} takibe alındı!\n\n"
                f"📈 Giriş Fiyatı: ${coin_data['price']:.4f}\n"
                f"🎯 Hedef: ${self.tracked_coins[chat_id][symbol]['target_price']:.4f}\n"
                f"🛑 Stop: ${self.tracked_coins[chat_id][symbol]['stop_price']:.4f}\n"
                f"📊 Yön: {'LONG 📈' if coin_data['long_signal'] else 'SHORT 📉'}"
            )

        except Exception as e:
            await self._log(f"Track komutu hatası: {str(e)}", "error")
            await update.message.reply_text("❌ Takip başlatılırken bir hata oluştu!")

    async def _track_coin(self, chat_id: int, symbol: str):
        """Coin takip görevi"""
        try:
            while True:
                # Her 30 saniyede bir kontrol et
                await asyncio.sleep(30)
                
                if chat_id not in self.tracked_coins or symbol not in self.tracked_coins[chat_id]:
                    break

                coin_data = self.tracked_coins[chat_id][symbol]
                current_price = await self._get_current_price(symbol)
                
                if not current_price:
                    continue

                # Hedef ve stop kontrolü
                if coin_data['is_long']:
                    if current_price >= coin_data['target_price']:
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"🎯 {symbol} HEDEF BAŞARILI!\n\n"
                                 f"Giriş: ${coin_data['entry_price']:.4f}\n"
                                 f"Hedef: ${coin_data['target_price']:.4f}\n"
                                 f"Mevcut: ${current_price:.4f}\n"
                                 f"Kar: %{((current_price/coin_data['entry_price'])-1)*100:.2f}\n\n"
                                 f"✅ Karı realize etmeniz önerilir!"
                        )
                        await self.untrack_coin(chat_id, symbol)
                        break
                    
                    elif current_price <= coin_data['stop_price']:
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ {symbol} STOP SEVİYESİNDE!\n\n"
                                 f"Giriş: ${coin_data['entry_price']:.4f}\n"
                                 f"Stop: ${coin_data['stop_price']:.4f}\n"
                                 f"Mevcut: ${current_price:.4f}\n"
                                 f"Zarar: %{((current_price/coin_data['entry_price'])-1)*100:.2f}\n\n"
                                 f"❌ Zararı durdurmak için çıkmanız önerilir!"
                        )
                        await self._untrack_coin(chat_id, symbol)
                        break
                else:  # SHORT pozisyon
                    if current_price <= coin_data['target_price']:
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"🎯 {symbol} HEDEF BAŞARILI!\n\n"
                                 f"Giriş: ${coin_data['entry_price']:.4f}\n"
                                 f"Hedef: ${coin_data['target_price']:.4f}\n"
                                 f"Mevcut: ${current_price:.4f}\n"
                                 f"Kar: %{((coin_data['entry_price']/current_price)-1)*100:.2f}\n\n"
                                 f"✅ Karı realize etmeniz önerilir!"
                        )
                        await self._untrack_coin(chat_id, symbol)
                        break
                    
                    elif current_price >= coin_data['stop_price']:
                        await self.application.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ {symbol} STOP SEVİYESİNDE!\n\n"
                                 f"Giriş: ${coin_data['entry_price']:.4f}\n"
                                 f"Stop: ${coin_data['stop_price']:.4f}\n"
                                 f"Mevcut: ${current_price:.4f}\n"
                                 f"Zarar: %{((coin_data['entry_price']/current_price)-1)*100:.2f}\n\n"
                                 f"❌ Zararı durdurmak için çıkmanız önerilir!"
                        )
                        await self._untrack_coin(chat_id, symbol)
                        break

        except Exception as e:
            await self._log(f"Coin takip hatası ({symbol}): {str(e)}", "error")

    async def _get_current_price(self, symbol: str) -> float:
        """Anlık fiyat getir"""
        try:
            self.logger.debug(f"🔍 {symbol} için anlık fiyat alınıyor...")
            async with aiohttp.ClientSession() as session:
                async with session.get(f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}') as response:
                    if response.status == 200:
                        data = await response.json()
                        price = float(data['price'])
                        self.logger.debug(f"✅ {symbol} fiyatı: ${price}")
                        return price
            self.logger.error(f"❌ {symbol} fiyatı alınamadı!")
            return None
        except Exception as e:
            self.logger.error(f"❌ Fiyat çekme hatası ({symbol}): {e}")
            return None

    async def _untrack_coin(self, chat_id: int, symbol: str):
        """Coin takibini sonlandır"""
        try:
            if chat_id in self.tracked_coins and symbol in self.tracked_coins[chat_id]:
                del self.tracked_coins[chat_id][symbol]
            
            if chat_id in self.track_tasks and symbol in self.track_tasks[chat_id]:
                self.track_tasks[chat_id][symbol].cancel()
                del self.track_tasks[chat_id][symbol]
                
        except Exception as e:
            await self._log(f"Takip sonlandırma hatası ({symbol}): {str(e)}", "error")

    async def untrack_command(self, update, context):
        """Takibi sonlandırma komutunu işle"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "❌ Lütfen takibi sonlandırılacak coini belirtin.\n"
                    "Örnek: /untrack BTCUSDT"
                )
                return

            chat_id = update.message.chat_id
            symbol = context.args[0].upper()

            if chat_id not in self.tracked_coins or symbol not in self.tracked_coins[chat_id]:
                await update.message.reply_text(f"❌ {symbol} takip edilmiyor!")
                return

            await self._untrack_coin(chat_id, symbol)
            await update.message.reply_text(f"✅ {symbol} takibi sonlandırıldı!")

        except Exception as e:
            await self._log(f"Untrack komutu hatası: {str(e)}", "error")
            await update.message.reply_text("❌ Takip sonlandırılırken bir hata oluştu!")

    async def list_tracked_command(self, update, context):
        """Takip edilen coinleri listele"""
        try:
            chat_id = update.message.chat_id
            
            if chat_id not in self.tracked_coins or not self.tracked_coins[chat_id]:
                await update.message.reply_text("📝 Takip edilen coin bulunmuyor!")
                return

            message = "📊 TAKİP EDİLEN COİNLER:\n\n"
            
            for symbol, data in self.tracked_coins[chat_id].items():
                current_price = await self._get_current_price(symbol)
                if current_price:
                    profit = ((current_price/data['entry_price'])-1)*100 if data['is_long'] else ((data['entry_price']/current_price)-1)*100
                    
                    message += (
                        f"💎 {symbol}\n"
                        f"📈 Yön: {'LONG' if data['is_long'] else 'SHORT'}\n"
                        f"💰 Giriş: ${data['entry_price']:.4f}\n"
                        f"📊 Mevcut: ${current_price:.4f}\n"
                        f"💫 Kar/Zarar: %{profit:.2f}\n"
                        f"🎯 Hedef: ${data['target_price']:.4f}\n"
                        f"🛑 Stop: ${data['stop_price']:.4f}\n\n"
                    )

            await update.message.reply_text(message)

        except Exception as e:
            await self._log(f"List tracked komutu hatası: {str(e)}", "error")
            await update.message.reply_text("❌ Liste alınırken bir hata oluştu!")

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
        """Run the bot"""
        print("🤖 Bot başlatılıyor...")
        self.application.run_polling(drop_pending_updates=True)

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

    async def _get_market_data(self, interval: str = "4h") -> list:
        """Market verilerini getir ve detaylı analiz yap"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.binance.com/api/v3/ticker/24hr') as response:
                    if response.status != 200:
                        return []
                        
                    data = await response.json()
                    
                    # USDT çiftlerini filtrele
                    usdt_pairs = [
                        item for item in data 
                        if item['symbol'].endswith('USDT') 
                        and not item['symbol'].startswith('USDC')
                        and float(item['quoteVolume']) > 1000000  # Minimum hacmi artırdık
                        and item['symbol'] not in self.excluded_coins
                    ]
                    
                    opportunities = []
                    for pair in usdt_pairs:
                        try:
                            symbol = pair['symbol']
                            
                            # Kline verilerini al
                            klines = await self._get_klines_data(symbol, interval)
                            if not klines:
                                continue
                            
                            # Anlık fiyatı al
                            current_price = float(pair['lastPrice'])
                            volume = float(pair['quoteVolume'])
                            
                            # Fırsat analizi yap
                            analysis = await self._analyze_opportunity(symbol, current_price, volume, interval)
                            if analysis and analysis['opportunity_score'] > 75:  # Minimum skoru artırdık
                                opportunities.append(analysis)
                            
                        except Exception as e:
                            continue
                    
                    # Skorlarına göre sırala ve en iyi 10 tanesini al
                    opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
                    return opportunities[:10]
                    
        except Exception as e:
            return []

    async def _log(self, message: str, level: str = "info", notify_user: bool = False, chat_id: Optional[int] = None):
        """Log message and optionally notify user"""
        try:
            # Log seviyesine göre mesajı logla
            if level == "debug":
                self.logger.debug(message)
            elif level == "info":
                self.logger.info(message)
            elif level == "warning":
                self.logger.warning(message)
            elif level == "error":
                self.logger.error(message)
                
            # Kullanıcıya bildirim gönder
            if notify_user and chat_id:
                emoji_map = {
                    "debug": "🔍",
                    "info": "ℹ️",
                    "warning": "⚠️",
                    "error": "❌"
                }
                emoji = emoji_map.get(level, "ℹ️")
                
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=f"{emoji} {message}"
                    )
                except Exception as e:
                    self.logger.error(f"Kullanıcı bildirimi gönderilemedi: {str(e)}")
                    
        except Exception as e:
            # Loglama sırasında hata oluşursa
            print(f"Loglama hatası: {str(e)}")
            if notify_user and chat_id:
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Sistem hatası: {str(e)}"
                    )
                except:
                    pass  # Son çare olarak hatayı sessizce geç

    async def _start_command(self, update, context):
        """Handle /start command"""
        welcome_message = (
            "🚀 *Kripto Para Fırsat Tarayıcısına Hoş Geldiniz!*\n\n"
            "Bu bot, kripto para piyasasındaki en iyi alım-satım fırsatlarını bulmanıza yardımcı olur.\n\n"
            "📊 *Kullanılabilir Komutlar:*\n"
            "• /scan - Piyasa taraması başlat\n"
            "• /help - Detaylı yardım menüsü\n"
            "• /stop - Aktif taramayı durdur\n\n"
            "🔍 *Tarayıcı Nasıl Çalışır?*\n"
            "1. Binance borsasındaki tüm USDT çiftlerini analiz eder\n"
            "2. Hacim, volatilite ve momentum verilerini inceler\n"
            "3. En iyi 10 fırsatı seçer ve detaylı rapor sunar\n\n"
            "📈 *Her Coin İçin Sunulan Bilgiler:*\n"
            "• Güncel fiyat ve 24 saatlik değişim\n"
            "• İşlem hacmi ve volatilite analizi\n"
            "• RSI ve momentum göstergeleri\n"
            "• Risk seviyesi ve pozisyon önerileri\n"
            "• LONG/SHORT sinyalleri ve hedef fiyatlar\n\n"
            "⚡️ *Özel Özellikler:*\n"
            "• T1: Momentum gücü göstergesi\n"
            "• T2: Volatilite etkisi analizi\n"
            "• T3: Genel güç endeksi\n\n"
            "Detaylı bilgi için /help komutunu kullanın."
        )
        
        try:
            await update.message.reply_text(welcome_message, parse_mode='Markdown')
            await self._log(f"Yeni kullanıcı başladı: {update.effective_user.id}", "info")
        except Exception as e:
            await self._log(f"Start komutu hatası: {str(e)}", "error")

    async def _help_command(self, update, context):
        """Handle /help command"""
        help_message = (
            "📚 *DETAYLI KULLANIM KILAVUZU*\n\n"
            "*1. Temel Komutlar:*\n"
            "• /scan - Yeni bir piyasa taraması başlatır\n"
            "• /stop - Aktif taramayı durdurur\n"
            "• /help - Bu yardım menüsünü gösterir\n\n"
            
            "*2. Tarama Sonuçlarını Okuma:*\n"
            "🟢 LONG Sinyali:\n"
            "• Yükselen momentum\n"
            "• Artan işlem hacmi\n"
            "• Pozitif fiyat değişimi\n\n"
            
            "🔴 SHORT Sinyali:\n"
            "• Düşen momentum\n"
            "• Artan işlem hacmi\n"
            "• Negatif fiyat değişimi\n\n"
            
            "*3. Risk Seviyeleri:*\n"
            "🔥 - Çok Düşük Risk\n"
            "🔥🔥 - Düşük Risk\n"
            "🔥🔥🔥 - Orta Risk\n"
            "🔥🔥🔥🔥 - Yüksek Risk\n"
            "🔥🔥🔥🔥🔥 - Çok Yüksek Risk\n\n"
            
            "*4. Pozisyon Büyüklüğü:*\n"
            "⭐ - Çok Küçük (%1-2)\n"
            "⭐⭐ - Küçük (%2-5)\n"
            "⭐⭐⭐ - Orta (%5-10)\n"
            "⭐⭐⭐⭐ - Büyük (%10-15)\n"
            "⭐⭐⭐⭐⭐ - Çok Büyük (%15-20)\n\n"
            
            "*5. Teknik Göstergeler:*\n"
            "• *RSI Durumu:*\n"
            "  - AŞIRI ALIM: Satış fırsatı\n"
            "  - AŞIRI SATIM: Alım fırsatı\n"
            "  - NÖTR: Bekle ve izle\n\n"
            
            "• *Volatilite:*\n"
            "  - YÜKSEK: Riskli ama potansiyel yüksek\n"
            "  - DÜŞÜK: Daha güvenli, potansiyel düşük\n"
            "  - NÖTR: Normal piyasa koşulları\n\n"
            
            "• *Hacim Profili:*\n"
            "  - ÇOK YÜKSEK: Güçlü piyasa ilgisi\n"
            "  - YÜKSEK: Artan ilgi\n"
            "  - NORMAL: Standart işlem hacmi\n\n"
            
            "*6. TOTAL Göstergeleri:*\n"
            "• T1 (Momentum): Fiyat hareketinin gücü\n"
            "• T2 (Volatilite): Fiyat dalgalanması etkisi\n"
            "• T3 (Genel Güç): Toplam piyasa etkisi\n\n"
            
            "*7. Önerilen Kullanım:*\n"
            "1. Düzenli olarak /scan komutunu kullanın\n"
            "2. Risk seviyesine göre pozisyon alın\n"
            "3. Stop-loss seviyelerine dikkat edin\n"
            "4. Birden fazla göstergeyi birlikte değerlendirin\n\n"
            
            "⚠️ *Önemli Notlar:*\n"
            "• Bu bir öneri sistemidir, kesin alım-satım sinyali değildir\n"
            "• Her zaman kendi araştırmanızı yapın\n"
            "• Risk yönetimi kurallarına uyun\n"
            "• Kaybedebileceğinizden fazlasını riske atmayın"
        )
        
        try:
            await update.message.reply_text(help_message, parse_mode='Markdown')
            await self._log(f"Yardım menüsü gösterildi: {update.effective_user.id}", "info")
        except Exception as e:
            await self._log(f"Help komutu hatası: {str(e)}", "error")

    async def _scan_command(self, update, context):
        """Handle /scan command"""
        try:
            if self.is_scanning:
                await update.message.reply_text("⚠️ Tarama zaten devam ediyor!")
                return
                
            await update.message.reply_text(
                "🔍 Piyasa taraması başlatılıyor...\n"
                "⏳ Bu işlem birkaç dakika sürebilir."
            )
            
            self.is_scanning = True
            self.scan_task = asyncio.create_task(
                self._scan_market(update.message.chat_id)
            )
            self.scan_task.add_done_callback(self._scan_completed)
            
            await self._log(f"Tarama başlatıldı: {update.effective_user.id}", "info")
            
        except Exception as e:
            await self._log(f"Scan komutu hatası: {str(e)}", "error")
            await update.message.reply_text(
                "❌ Tarama başlatılırken bir hata oluştu.\n"
                "Lütfen daha sonra tekrar deneyin."
            )
            self.is_scanning = False

    async def stop_command(self, update, context):
        """Handle /stop command"""
        try:
            if self.is_scanning:
                self.is_scanning = False
                if self.scan_task and not self.scan_task.done():
                    self.scan_task.cancel()
                    try:
                        await self.scan_task
                    except asyncio.CancelledError:
                        pass
                
                await update.message.reply_text("🛑 Tarama durduruldu.")
                await self._log(f"Tarama durduruldu: {update.effective_user.id}", "info")
            else:
                await update.message.reply_text("ℹ️ Aktif tarama bulunmuyor.")
                
        except Exception as e:
            await self._log(f"Stop komutu hatası: {str(e)}", "error")
            await update.message.reply_text("❌ Tarama durdurulurken bir hata oluştu.")

    def _scan_completed(self, task):
        """Callback for when scan task completes"""
        self.is_scanning = False
        try:
            task.result()
        except asyncio.CancelledError:
            self.logger.info("Tarama iptal edildi")
        except Exception as e:
            self.logger.error(f"Tarama sırasında hata oluştu: {str(e)}")

    async def _get_klines_data(self, symbol: str, interval: str) -> list:
        """Belirli bir zaman dilimi için kline verilerini getir"""
        try:
            self.logger.debug(f"🔄 {symbol} için {interval} kline verileri alınıyor...")
            
            # Interval kontrolü
            valid_intervals = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']
            if interval not in valid_intervals:
                self.logger.error(f"❌ Geçersiz interval: {interval}")
                return None
                
            async with aiohttp.ClientSession() as session:
                url = 'https://api.binance.com/api/v3/klines'
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'limit': 100
                }
                
                self.logger.debug(f"📡 API isteği: {url}?symbol={symbol}&interval={interval}&limit=100")
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            self.logger.debug(f"✅ {symbol} için {len(data)} kline verisi alındı")
                            return data
                        else:
                            self.logger.error(f"❌ {symbol} için veri bulunamadı")
                            return None
                    else:
                        response_text = await response.text()
                        self.logger.error(f"❌ API Hatası: Status {response.status}, Response: {response_text}")
                        return None
                    
        except aiohttp.ClientError as e:
            self.logger.error(f"❌ Bağlantı hatası ({symbol}): {e}")
            return None
        except Exception as e:
            self.logger.error(f"❌ Beklenmeyen hata ({symbol}): {e}")
            return None

    async def _analyze_opportunity(self, symbol: str, current_price: float, volume: float, interval: str = "4h") -> dict:
        """Fırsat analizi yap"""
        try:
            # Kline verilerini al
            klines = await self._get_klines_data(symbol, interval)
            if not klines or len(klines) < 100:  # En az 100 veri noktası gerekli
                return None

            # Verileri numpy dizilerine dönüştür
            closes = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])
            highs = np.array([float(k[2]) for k in klines])
            lows = np.array([float(k[3]) for k in klines])

            # RSI hesapla
            rsi = self._calculate_rsi(closes)
            
            # MACD hesapla
            macd_line, signal_line, hist = self._calculate_macd(closes)
            
            # Bollinger Bands hesapla
            upper, middle, lower = self._calculate_bollinger_bands(closes)
            
            # Hacim analizi
            avg_volume = np.mean(volumes[-20:])
            volume_surge = volume > (avg_volume * 1.5)
            
            # Trend analizi
            ema20 = self._calculate_ema(closes, 20)
            ema50 = self._calculate_ema(closes, 50)
            trend = "YUKARI" if ema20[-1] > ema50[-1] else "AŞAĞI"
            
            # Destek/Direnç seviyeleri
            support = float(np.min(lows[-20:]))
            resistance = float(np.max(highs[-20:]))
            
            # Fırsat puanı hesapla (0-100)
            score = 0
            
            # RSI bazlı puan (0-20)
            if rsi < 30:  # Aşırı satım
                score += 20
            elif rsi > 70:  # Aşırı alım
                score += 5
            else:
                score += 10
                
            # MACD bazlı puan (0-20)
            if hist > 0 and hist > signal_line:  # Pozitif ve artıyor
                score += 20
            elif hist < 0 and hist < signal_line:  # Negatif ve azalıyor
                score += 5
            
            # Bollinger Bands bazlı puan (0-20)
            bb_position = (current_price - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
            if bb_position < 0.2:  # Alt banda yakın
                score += 20
            elif bb_position > 0.8:  # Üst banda yakın
                score += 5
            
            # Hacim bazlı puan (0-20)
            if volume_surge:
                score += 20
            else:
                score += min(20, (volume / avg_volume) * 10)
                
            # Trend bazlı puan (0-20)
            if trend == "YUKARI":
                score += 20
            else:
                score += 5
                
            return {
                'symbol': symbol,
                'price': current_price,
                'volume': volume,
                'rsi': float(rsi),
                'macd': float(hist),
                'bb_position': float(bb_position),
                'trend': trend,
                'support': support,
                'resistance': resistance,
                'volume_surge': volume_surge,
                'opportunity_score': float(score),
                'interval': interval,
                'signal': "🟢 AL" if score > 80 else "🟡 İZLE" if score > 60 else "🔴 BEKLE"
            }
            
        except Exception as e:
            self.logger.error(f"Analiz hatası ({symbol}): {e}")
            return None

    def _calculate_rsi(self, prices: np.ndarray, period: int = 14) -> float:
        """RSI hesapla"""
        deltas = np.diff(prices)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum()/period
        down = -seed[seed < 0].sum()/period
        rs = up/down if down != 0 else 0
        rsi = np.zeros_like(prices)
        rsi[:period] = 100. - 100./(1.+rs)

        for i in range(period, len(prices)):
            delta = deltas[i-1]
            if delta > 0:
                upval = delta
                downval = 0.
            else:
                upval = 0.
                downval = -delta

            up = (up*(period-1) + upval)/period
            down = (down*(period-1) + downval)/period
            rs = up/down if down != 0 else 0
            rsi[i] = 100. - 100./(1.+rs)

        return rsi[-1]

    def _calculate_macd(self, prices: np.ndarray) -> tuple:
        """MACD hesapla"""
        # Numpy array'i pandas Series'e çevir
        prices_pd = pd.Series(prices)
        
        # MACD hesapla
        exp1 = prices_pd.ewm(span=12, adjust=False).mean()
        exp2 = prices_pd.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        
        # Son değerleri al
        return float(macd.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])

    def _calculate_bollinger_bands(self, prices: np.ndarray, period: int = 20) -> tuple:
        """Bollinger Bands hesapla"""
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        return upper, sma, lower

    def _calculate_ema(self, prices: np.ndarray, period: int) -> np.ndarray:
        """EMA hesapla"""
        # Numpy array'i pandas Series'e çevir
        prices_pd = pd.Series(prices)
        
        # EMA hesapla ve numpy array'e geri çevir
        ema = prices_pd.ewm(span=period, adjust=False).mean()
        return ema.to_numpy()

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
