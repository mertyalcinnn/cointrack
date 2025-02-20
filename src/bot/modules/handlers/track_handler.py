from telegram import Update
from telegram.ext import ContextTypes
from ..analysis.market import MarketAnalyzer
from datetime import datetime, timedelta
import asyncio
import time
from enum import Enum
from typing import Dict, Optional

class PositionStatus(Enum):
    STRONG_HOLD = "💎 GÜÇLÜ TUT"
    HOLD = "✋ TUT"
    TAKE_PROFIT = "💰 KAR AL"
    CUT_LOSS = "✂️ ZARARDAN ÇIK"
    URGENT_EXIT = "🚨 ACİL ÇIK"

class TrackHandler:
    def __init__(self, logger):
        self.logger = logger
        self.last_opportunities = {}  # {chat_id: opportunities}
        self.analyzer = MarketAnalyzer(logger)
        self.tracked_coins = {}  # {chat_id: {symbol: {'entry_price': float, 'last_update': datetime, 'alerts': []}}}
        self.tracking_tasks = {}  # {chat_id: {symbol: Task}}
        self.position_history = {}  # {chat_id: {symbol: {'max_profit': float, 'max_loss': float}}}
        self.timeframe_alerts = {
            '15m': {'profit_target': 3, 'loss_limit': -2},  # 15dk için %3 kar, %2 zarar
            '4h': {'profit_target': 8, 'loss_limit': -5}    # 4s için %8 kar, %5 zarar
        }

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Track komutunu işle"""
        try:
            chat_id = update.effective_chat.id
            self.logger.debug(f"Track komutu çalıştı. Chat ID: {chat_id}")
            
            if not context.args:
                await update.message.reply_text(
                    "❌ Kullanım:\n"
                    "1️⃣ Tarama sonrası takip:\n"
                    "   /track <numara>\n"
                    "   Örnek: /track 1\n\n"
                    "2️⃣ Direkt coin takibi:\n"
                    "   /track <sembol>\n"
                    "   Örnek: /track BTCUSDT"
                )
                return

            for arg in context.args:
                arg = arg.upper()
                
                # Numara ile takip (scan sonrası)
                if arg.isdigit():
                    await self._handle_scan_tracking(update, arg, chat_id)
                # Sembol ile direkt takip
                else:
                    await self._handle_direct_tracking(update, arg, chat_id)

        except Exception as e:
            self.logger.error(f"Track komutu hatası: {e}")
            await update.message.reply_text(
                "❌ Hata oluştu! Lütfen tekrar deneyin."
            )

    async def _start_price_tracking(self, update: Update, chat_id: int, symbol: str, entry_price: float, timeframe: str = '4h'):
        """Fiyat takibini başlat"""
        if chat_id not in self.tracking_tasks:
            self.tracking_tasks[chat_id] = {}

        # Eğer bu sembol için zaten bir takip varsa, onu durdur
        if symbol in self.tracking_tasks[chat_id]:
            self.tracking_tasks[chat_id][symbol].cancel()

        # Yeni takip görevi oluştur
        task = asyncio.create_task(self._track_price(update, chat_id, symbol, entry_price, timeframe))
        self.tracking_tasks[chat_id][symbol] = task

    async def _track_price(self, update: Update, chat_id: int, symbol: str, entry_price: float, timeframe: str = '4h'):
        """Fiyat takip döngüsü"""
        try:
            # Pozisyon geçmişini başlat
            if chat_id not in self.position_history:
                self.position_history[chat_id] = {}
            if symbol not in self.position_history[chat_id]:
                self.position_history[chat_id][symbol] = {
                    'max_profit': 0,
                    'max_loss': 0
                }

            while True:
                current_analysis = await self.analyzer.analyze_single_coin(symbol)
                
                if current_analysis:
                    current_price = current_analysis['price']
                    price_change = ((current_price - entry_price) / entry_price) * 100
                    
                    # Maksimum kar/zarar güncelle
                    history = self.position_history[chat_id][symbol]
                    if price_change > history['max_profit']:
                        history['max_profit'] = price_change
                    if price_change < history['max_loss']:
                        history['max_loss'] = price_change

                    # Pozisyon durumu analizi
                    position_analysis = self._analyze_position_status(
                        price_change,
                        history['max_profit'],
                        history['max_loss'],
                        timeframe,
                        current_analysis['opportunity_score']
                    )
                    
                    # Ana mesaj
                    message = (
                        f"💰 {symbol} POZİSYON DURUMU\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"📈 Giriş: ${entry_price:.4f}\n"
                        f"📊 Güncel: ${current_price:.4f}\n"
                        f"⏱ Timeframe: {timeframe}\n\n"
                        
                        f"📊 KAR/ZARAR ANALİZİ:\n"
                        f"{'🟢' if price_change >= 0 else '🔴'} "
                        f"Anlık: {price_change:+.2f}%\n"
                        f"📈 En Yüksek: +{history['max_profit']:.2f}%\n"
                        f"📉 En Düşük: {history['max_loss']:.2f}%\n\n"
                        
                        f"🎯 POZİSYON DURUMU: {position_analysis['status'].value}\n"
                    )

                    # Analiz nedenleri
                    message += "\n📝 ANALİZ:\n"
                    for reason in position_analysis['reasons']:
                        message += f"• {reason}\n"

                    # Duygusal tavsiyeler
                    message += "\n💭 TAVSİYELER:\n"
                    for advice in position_analysis['emotional_advice']:
                        message += f"• {advice}\n"

                    # Teknik analiz
                    message += (
                        f"\n📊 TEKNİK GÖSTERGELER:\n"
                        f"• RSI: {current_analysis['rsi']:.1f}\n"
                        f"• MACD: {current_analysis['macd']:.4f}\n"
                        f"• Trend: {current_analysis['trend']}\n"
                        f"• Sinyal: {current_analysis['signal']}\n"
                    )

                    message += f"\n⏰ Son Güncelleme: {datetime.now().strftime('%H:%M:%S')}"

                    # Önemli değişimlerde uyarı ekle
                    if abs(price_change) >= 5 or position_analysis['status'] in [PositionStatus.TAKE_PROFIT, PositionStatus.URGENT_EXIT]:
                        message = f"⚠️ ÖNEMLİ UYARI ⚠️\n\n" + message

                    await update.message.reply_text(message)

                await asyncio.sleep(30)

        except asyncio.CancelledError:
            self.logger.info(f"Price tracking cancelled for {symbol}")
        except Exception as e:
            self.logger.error(f"Price tracking error for {symbol}: {e}")

    def _analyze_position_status(self, 
                               price_change: float,
                               max_profit: float,
                               max_loss: float,
                               timeframe: str,
                               technical_score: float) -> Dict:
        """Pozisyon durumunu analiz et"""
        
        alerts = self.timeframe_alerts.get(timeframe, self.timeframe_alerts['4h'])
        profit_target = alerts['profit_target']
        loss_limit = alerts['loss_limit']
        
        reasons = []
        emotional_advice = []
        
        # Kar/Zarar durumu analizi
        if price_change > 0:
            profit_percentage = (price_change / profit_target) * 100
            if price_change >= profit_target:
                status = PositionStatus.TAKE_PROFIT
                reasons.append(f"✨ Hedef kara ulaşıldı! (+{price_change:.2f}%)")
                emotional_advice.append("🎯 Kar realizasyonu önemlidir")
            elif price_change >= profit_target * 0.8:
                status = PositionStatus.TAKE_PROFIT
                reasons.append(f"📈 Kar hedefine yaklaşıldı (+{price_change:.2f}%)")
                emotional_advice.append("⚠️ Açgözlülük yapma, karını al")
            else:
                status = PositionStatus.HOLD
                reasons.append(f"📊 Kar devam ediyor (+{price_change:.2f}%)")
                emotional_advice.append("🎯 Trendi takip et")
        else:
            loss_percentage = (price_change / loss_limit) * 100
            if price_change <= loss_limit:
                status = PositionStatus.URGENT_EXIT
                reasons.append(f"🚨 Stop-loss seviyesi aşıldı! ({price_change:.2f}%)")
                emotional_advice.append("✂️ Daha büyük kayıpları önle, çık!")
            elif price_change <= loss_limit * 0.8:
                status = PositionStatus.CUT_LOSS
                reasons.append(f"⚠️ Stop-loss'a yaklaşılıyor ({price_change:.2f}%)")
                emotional_advice.append("🎯 Zararı kontrol et, çıkış planla")
            else:
                status = PositionStatus.HOLD
                reasons.append(f"📉 Sınırlı zarar ({price_change:.2f}%)")
                emotional_advice.append("💭 Paniğe kapılma, planına sadık kal")

        # Maksimum kar/zarar analizi
        if max_profit > 0:
            reasons.append(f"📊 Maksimum Kar: +{max_profit:.2f}%")
            if price_change < max_profit * 0.7:
                reasons.append("⚠️ Karın %30'undan fazlası kaybedildi!")
                emotional_advice.append("💡 Trend dönüşü olabilir, dikkatli ol")

        if max_loss < 0:
            reasons.append(f"📉 Maksimum Zarar: {max_loss:.2f}%")
            if price_change > max_loss * 0.5:
                reasons.append("✨ Toparlanma görülüyor!")
                emotional_advice.append("🎯 İyileşme devam ederse tut")

        return {
            'status': status,
            'reasons': reasons,
            'emotional_advice': emotional_advice
        }

    async def _handle_scan_tracking(self, update, number: str, chat_id: int):
        """Scan sonrası coin takibi"""
        opportunities = self.last_opportunities.get(chat_id, [])
        
        if not opportunities:
            await update.message.reply_text(
                "❌ Önce /scan komutu ile tarama yapmalısınız!\n"
                "1. /scan yazarak tarama yapın\n"
                "2. Sonra /track <numara> ile coin seçin"
            )
            return
            
        index = int(number) - 1
        if 0 <= index < len(opportunities):
            coin = opportunities[index]
            entry_price = coin['price']
            symbol = coin['symbol']
            
            # Timeframe'i belirle (varsayılan 4h)
            timeframe = '4h'  # Bu kısmı scan komutundan alabilirsiniz
            
            # Takip listesine ekle
            if chat_id not in self.tracked_coins:
                self.tracked_coins[chat_id] = {}
            
            self.tracked_coins[chat_id][symbol] = {
                'entry_price': entry_price,
                'last_update': datetime.now(),
                'alerts': []
            }
            
            # Fiyat takibini başlat
            await self._start_price_tracking(update, chat_id, symbol, entry_price, timeframe)
            
            await update.message.reply_text(
                f"✅ {symbol} takibe alındı!\n"
                f"💰 Giriş Fiyatı: ${entry_price:.4f}\n"
                f"⏰ Her 30 saniyede bir güncellenecek"
            )
        else:
            await update.message.reply_text(f"❌ Geçersiz coin numarası: {number}")

    async def _handle_direct_tracking(self, update, symbol: str, chat_id: int):
        """Direkt coin takibi"""
        try:
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
            
            analysis = await self.analyzer.analyze_single_coin(symbol)
            
            if analysis:
                entry_price = analysis['price']
                
                # Takip listesine ekle
                if chat_id not in self.tracked_coins:
                    self.tracked_coins[chat_id] = {}
                
                self.tracked_coins[chat_id][symbol] = {
                    'entry_price': entry_price,
                    'last_update': datetime.now(),
                    'alerts': []
                }
                
                # Fiyat takibini başlat
                await self._start_price_tracking(update, chat_id, symbol, entry_price)
                
                await update.message.reply_text(
                    f"✅ {symbol} takibe alındı!\n"
                    f"💰 Giriş Fiyatı: ${entry_price:.4f}\n"
                    f"⏰ Her 30 saniyede bir güncellenecek"
                )
            else:
                await update.message.reply_text(f"❌ {symbol} analiz edilemedi veya bulunamadı.")
                
        except Exception as e:
            await update.message.reply_text(f"❌ {symbol} takip edilemedi: {str(e)}")

    def update_opportunities(self, chat_id: int, opportunities: list):
        """Son fırsatları güncelle"""
        self.logger.debug(f"Fırsatlar güncelleniyor. Chat ID: {chat_id}, Fırsat sayısı: {len(opportunities)}")
        self.last_opportunities[chat_id] = opportunities.copy()
        self.logger.debug(f"Fırsatlar güncellendi. Mevcut fırsatlar: {len(self.last_opportunities[chat_id])}")

    async def get_tracked_coins(self, chat_id: int) -> list:
        """Takip edilen coinleri getir"""
        if chat_id in self.tracked_coins:
            return list(self.tracked_coins[chat_id].keys())
        return []

    async def remove_from_tracking(self, chat_id: int, symbol: str) -> bool:
        """Coini takipten çıkar"""
        if chat_id in self.tracked_coins and symbol in self.tracked_coins[chat_id]:
            del self.tracked_coins[chat_id][symbol]
            return True
        return False 