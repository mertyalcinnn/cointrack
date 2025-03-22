from telegram import Update
from telegram.ext import ContextTypes
from ..data.binance_client import BinanceClient
from ..analysis.market import MarketAnalyzer
from ..utils.formatter import MessageFormatter
import time

class ScanHandler:
    def __init__(self, logger, track_handler):
        self.logger = logger
        self.client = BinanceClient()
        self.analyzer = MarketAnalyzer(logger)
        self.formatter = MessageFormatter()
        self.track_handler = track_handler

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            chat_id = update.effective_chat.id
            interval = self._get_interval(context.args)
            if not interval:
                await self._send_usage_message(update)
                return

            progress_message = await update.message.reply_text(
                f"🔍 {interval} taraması başlatıldı...\n"
                f"⏳ Veriler alınıyor..."
            )
            
            start_time = time.time()
            
            # Market verilerini al
            ticker_data = await self.client.get_ticker()
            if not ticker_data:
                await progress_message.edit_text("❌ Market verileri alınamadı!")
                return
                
            await progress_message.edit_text(
                f"📊 Market verileri alındı!\n"
                f"⏳ Coinler analiz ediliyor..."
            )
            
            # Fırsatları analiz et - Güvenli analiz ekle
            opportunities = await self._analyze_market_safely(ticker_data, interval)
            
            if not opportunities:
                await progress_message.edit_text("❌ Fırsat bulunamadı!")
                return
            
            scan_duration = time.time() - start_time
            
            # Önemli: Fırsatları track handler'a aktar
            self.track_handler.update_opportunities(chat_id, opportunities)
            
            # İlk mesajı güncelle
            await progress_message.edit_text(
                f"✅ Tarama tamamlandı!\n"
                f"📊 {len(opportunities)} fırsat bulundu.\n"
                f"⏳ Sonuçlar hazırlanıyor..."
            )
            
            # Fırsatları listele
            messages = self._format_opportunities(opportunities, interval)
            for i, message in enumerate(messages, 1):
                numbered_message = f"Fırsat #{i}:\n{message}"
                await update.message.reply_text(numbered_message)
            
            # Özet ve kullanım mesajı
            summary = (
                f"📈 TARAMA ÖZET ({interval})\n\n"
                f"🔍 Taranan Coin: {len(ticker_data)}\n"
                f"✨ Bulunan Fırsat: {len(opportunities)}\n"
                f"⭐ En Yüksek Skor: {opportunities[0]['opportunity_score']:.1f}\n"
                f"⏱ Tarama Süresi: {scan_duration:.1f}s\n\n"
                f"🎯 Coin takip etmek için:\n"
                f"/track <numara> komutunu kullanın\n"
                f"Örnek: /track 1"
            )
            await update.message.reply_text(summary)

        except Exception as e:
            self.logger.error(f"Scan error: {e}")
            await update.message.reply_text(f"❌ Tarama hatası: {str(e)}")

    async def _analyze_market_safely(self, ticker_data, interval):
        """Hata kontrolü ile market analizi yapar"""
        try:
            # Önce normal analizi dene
            opportunities = await self.analyzer.analyze_market(ticker_data, interval)
            
            # Güvenli sonuçları filtrele
            safe_opportunities = []
            for opp in opportunities:
                try:
                    # Temel verileri kontrol et
                    required_fields = ['symbol', 'price', 'opportunity_score', 'signal']
                    if not all(field in opp for field in required_fields):
                        self.logger.warning(f"Eksik alan: {opp.get('symbol', 'Bilinmeyen')}")
                        continue
                    
                    # Support ve resistance değerlerini düzelt
                    self._ensure_support_resistance(opp)
                    
                    # Güvenli fırsatları ekle
                    safe_opportunities.append(opp)
                except Exception as e:
                    self.logger.error(f"Fırsat hazırlama hatası ({opp.get('symbol', 'Bilinmeyen')}): {e}")
                    continue
            
            # Skorlarına göre fırsatları sırala
            if safe_opportunities:
                safe_opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)
            
            return safe_opportunities
            
        except Exception as e:
            self.logger.error(f"Güvenli analiz hatası: {e}")
            # Yedek: Basit analiz yöntemi
            try:
                return await self.analyzer.analyze_market_simple(ticker_data, interval)
            except Exception as e2:
                self.logger.error(f"Basit analiz de başarısız: {e2}")
                return []

    def _ensure_support_resistance(self, opportunity):
        """Support ve resistance değerlerini kontrol et ve eksik ise ekle"""
        try:
            # Mevcut fiyatı al
            price = opportunity.get('price', 0)
            if not price:
                price = opportunity.get('current_price', 0)
            
            # Eğer fiyat yoksa veya geçersizse, işlem yapma
            if not price or price <= 0:
                opportunity['price'] = 1.0  # Geçici varsayılan değer
                price = 1.0
            
            # Support/Resistance değerlerini kontrol et
            for i in range(1, 4):
                support_key = f'support{i}'
                resistance_key = f'resistance{i}'
                
                # Support değeri eksik veya hatalıysa düzelt
                try:
                    support_value = opportunity.get(support_key)
                    if support_value is None or support_value <= 0 or isinstance(support_value, str):
                        opportunity[support_key] = price * (1 - 0.01 * i)
                except (TypeError, ValueError):
                    opportunity[support_key] = price * (1 - 0.01 * i)
                
                # Resistance değeri eksik veya hatalıysa düzelt
                try:
                    resistance_value = opportunity.get(resistance_key)
                    if resistance_value is None or resistance_value <= 0 or isinstance(resistance_value, str):
                        opportunity[resistance_key] = price * (1 + 0.01 * i)
                except (TypeError, ValueError):
                    opportunity[resistance_key] = price * (1 + 0.01 * i)
            
            # Signal kontrolü
            signal = opportunity.get('signal', '')
            if isinstance(signal, str) == False:
                signal = 'BELİRSİZ'
                opportunity['signal'] = signal
            
            # Stop price ve target price değerlerini kontrol et
            try:
                stop_price = opportunity.get('stop_price')
                if stop_price is None or stop_price <= 0 or isinstance(stop_price, str):
                    if 'LONG' in signal:
                        opportunity['stop_price'] = price * 0.98
                    elif 'SHORT' in signal:
                        opportunity['stop_price'] = price * 1.02
                    else:
                        opportunity['stop_price'] = price * 0.98
            except (TypeError, ValueError):
                opportunity['stop_price'] = price * 0.98
            
            try:
                target_price = opportunity.get('target_price')
                if target_price is None or target_price <= 0 or isinstance(target_price, str):
                    if 'LONG' in signal:
                        opportunity['target_price'] = price * 1.03
                    elif 'SHORT' in signal:
                        opportunity['target_price'] = price * 0.97
                    else:
                        opportunity['target_price'] = price * 1.02
            except (TypeError, ValueError):
                opportunity['target_price'] = price * 1.02
            
            # Risk/Reward oranını hesapla
            try:
                risk_reward = opportunity.get('risk_reward')
                if risk_reward is None or risk_reward <= 0 or isinstance(risk_reward, str):
                    risk = abs(price - opportunity['stop_price'])
                    reward = abs(price - opportunity['target_price'])
                    opportunity['risk_reward'] = reward / max(risk, 0.0001)
            except (TypeError, ValueError, ZeroDivisionError):
                opportunity['risk_reward'] = 1.0
                
        except Exception as e:
            self.logger.error(f"_ensure_support_resistance hatası: {e}")
            # Temel değerleri zorunlu olarak ekle
            opportunity['support1'] = price * 0.99 if price else 0.99
            opportunity['support2'] = price * 0.98 if price else 0.98
            opportunity['support3'] = price * 0.97 if price else 0.97
            opportunity['resistance1'] = price * 1.01 if price else 1.01
            opportunity['resistance2'] = price * 1.02 if price else 1.02
            opportunity['resistance3'] = price * 1.03 if price else 1.03
            opportunity['stop_price'] = price * 0.98 if price else 0.98
            opportunity['target_price'] = price * 1.02 if price else 1.02
            opportunity['risk_reward'] = 1.0

    def _format_opportunities(self, opportunities: list, interval: str) -> list:
        """Fırsatları formatla"""
        messages = []
        for opp in opportunities:
            try:
                # Gerekli alanları kontrol et
                if not all(k in opp for k in ['symbol', 'price', 'signal', 'opportunity_score']):
                    self.logger.warning(f"Eksik temel alanlar: {opp.get('symbol', 'Bilinmeyen')}")
                    continue
                
                # EMA Sinyalleri - güvenli erişim
                ema20 = opp.get('ema20', 0)
                ema50 = opp.get('ema50', 0)
                if ema20 and ema50:
                    ema_signal = "📈 YUKARI" if ema20 > ema50 else "📉 AŞAĞI"
                    ema_cross = abs(ema20 - ema50) / (ema50 if ema50 != 0 else 1) * 100
                else:
                    ema_signal = "⚪ BELİRSİZ"
                    ema_cross = 0
                
                # Bollinger Bands Analizi - güvenli erişim
                try:
                    price = opp.get('price', 0)
                    bb_lower = opp.get('bb_lower', price * 0.98)
                    bb_upper = opp.get('bb_upper', price * 1.02)
                    
                    # NaN veya None kontrolü
                    if not bb_lower or not bb_upper or bb_lower == bb_upper:
                        bb_position = 50  # Varsayılan orta değer
                    else:
                        bb_position = (price - bb_lower) / (bb_upper - bb_lower) * 100
                        # Negatif veya aşırı büyük değerleri kısıtla
                        bb_position = max(0, min(100, bb_position))
                except Exception as bb_error:
                    self.logger.error(f"BB pozisyon hesaplama hatası ({opp['symbol']}): {bb_error}")
                    bb_position = 50  # Hata durumunda varsayılan değer
                
                bb_signal = self._get_bb_signal(bb_position)
                
                # Support/Resistance değerlerini sağla
                self._ensure_support_resistance(opp)
                
                # Stop Loss ve Take Profit bilgileri
                stop_loss = opp.get('stop_price', 0)
                take_profit = opp.get('target_price', 0)
                risk_reward = opp.get('risk_reward', 0)
                
                # Değerler 0 ise veya None ise, varsayılan değerler kullan
                if not stop_loss or stop_loss == 0:
                    if "LONG" in opp['signal']:
                        stop_loss = opp['price'] * 0.98
                    elif "SHORT" in opp['signal']:
                        stop_loss = opp['price'] * 1.02
                    else:
                        stop_loss = opp['price'] * 0.99
                    
                if not take_profit or take_profit == 0:
                    if "LONG" in opp['signal']:
                        take_profit = opp['price'] * 1.03
                    elif "SHORT" in opp['signal']:
                        take_profit = opp['price'] * 0.97
                    else:
                        take_profit = opp['price'] * 1.01
                    
                if not risk_reward or risk_reward == 0:
                    risk = abs(opp['price'] - stop_loss)
                    reward = abs(opp['price'] - take_profit)
                    risk_reward = reward / (risk if risk > 0 else 1) * 1.0
                
                # Mesaj oluşturma - eksik olabilecek alanları kontrol et
                symbol = opp.get('symbol', 'BİLİNMEYEN')
                price = opp.get('price', 0)
                rsi = opp.get('rsi', 50)
                trend = opp.get('trend', 'BELİRSİZ')
                volume = opp.get('volume', 0)
                macd = opp.get('macd', 0)
                signal = opp.get('signal', 'BELİRSİZ')
                score = opp.get('opportunity_score', 0)
                volume_surge = opp.get('volume_surge', False)
                
                message = (
                    f"🪙 {symbol}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"💵 Fiyat: ${price:.4f}\n"
                    f"📊 RSI: {rsi:.1f}\n"
                    f"📈 Trend: {trend}\n"
                    f"⚡ Hacim: ${volume:,.0f}\n"
                    f"📊 Hacim Artışı: {'✅' if volume_surge else '❌'}\n\n"
                    f"📊 TEKNİK ANALİZ:\n"
                    f"• EMA Trend: {ema_signal} ({ema_cross:.1f}%)\n"
                    f"• BB Pozisyon: {bb_signal} ({bb_position:.1f}%)\n"
                    f"• MACD: {macd:.4f}\n"
                    f"• RSI: {rsi:.1f}\n\n"
                    f"🎯 Sinyal: {signal}\n"
                    f"🛑 Stop Loss: ${stop_loss:.4f}\n"
                    f"✨ Take Profit: ${take_profit:.4f}\n"
                    f"⚖️ Risk/Ödül: {risk_reward:.2f}\n"
                    f"⭐ Fırsat Puanı: {score:.1f}/100\n"
                    f"━━━━━━━━━━━━━━━━"
                )
                messages.append(message)
            except Exception as format_error:
                self.logger.error(f"Mesaj formatı hatası ({opp.get('symbol', 'Bilinmeyen')}): {format_error}")
                continue
                
        return messages

    def _get_bb_signal(self, bb_position: float) -> str:
        """Bollinger Bands sinyali belirle"""
        if bb_position <= 0:
            return "💚 GÜÇLÜ ALIM"
        elif bb_position <= 20:
            return "💛 ALIM"
        elif bb_position >= 100:
            return "🔴 GÜÇLÜ SATIŞ"
        elif bb_position >= 80:
            return "🟡 SATIŞ"
        else:
            return "⚪ NÖTR"

    def _get_interval(self, args):
        """Tarama aralığını belirle"""
        if not args:
            return "4h"
        arg = args[0].lower()
        return {
            "scan15": "15m",
            "scan4": "4h"
        }.get(arg)

    async def _send_usage_message(self, update):
        """Kullanım mesajını gönder"""
        await update.message.reply_text(
            "❌ Geçersiz komut!\n"
            "Kullanım:\n"
            "/scan - 4 saatlik tarama\n"
            "/scan scan15 - 15 dakikalık tarama\n"
            "/scan scan4 - 4 saatlik tarama"
        )

    async def _get_opportunities(self, interval):
        ticker_data = await self.client.get_ticker()
        if not ticker_data:
            return []
        return await self.analyzer.analyze_market(ticker_data, interval)

    async def _send_opportunities(self, update, opportunities, interval):
        messages = self.formatter.format_opportunities(opportunities, interval)
        for message in messages:
            await update.message.reply_text(message)

    async def scan_market(self, interval="4h"):
        """Belirtilen aralıkta piyasayı tarar ve fırsatları döndürür"""
        try:
            # Market verilerini al
            ticker_data = await self.client.get_ticker()
            if not ticker_data:
                self.logger.warning("Market verileri alınamadı!")
                return []
                
            # Fırsatları güvenli şekilde analiz et
            opportunities = await self._analyze_market_safely(ticker_data, interval)
            
            if not opportunities:
                self.logger.warning("Fırsat bulunamadı!")
                return []
                
            return opportunities
        except Exception as e:
            self.logger.error(f"Scan market hatası: {str(e)}")
            return [] 