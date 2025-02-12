import ccxt
from typing import Dict, Optional
from datetime import datetime
import asyncio
import numpy as np
from dataclasses import dataclass
import pandas as pd

@dataclass
class TradePosition:
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_type: str  # 'LONG' veya 'SHORT'
    leverage: int
    entry_time: datetime
    monitoring: bool = True

class TradeMonitor:
    def __init__(self):
        self.exchange = ccxt.binance()
        self.active_positions: Dict[str, TradePosition] = {}
        self.alert_thresholds = {
            'profit_alert': 1.5,    
            'loss_alert': -0.8,     
            'trend_change': 0.5,    
            'volume_spike': 2.0     
        }
        self.scalping_thresholds = {
            'quick_profit': 0.5,    # %0.5 hızlı kar
            'quick_loss': -0.3,     # %-0.3 hızlı zarar
            'trend_change': 0.2,    # %0.2 trend değişimi
            'volume_alert': 1.5     # Normal hacmin 1.5 katı
        }
        self.timeframes = {
            'scalping': '1m',      # 1 dakikalık
            'quick': '3m',         # 3 dakikalık
            'normal': '5m'         # 5 dakikalık
        }
        
    async def _send_alert(self, chat_id: int, bot, message: str, is_urgent: bool = False):
        """Uyarı gönder"""
        try:
            # Acil durumlarda bildirim sesi açık, normal durumda kapalı
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML',
                disable_notification=not is_urgent  # Acil durumda ses açık
            )
        except Exception as e:
            print(f"Uyarı gönderme hatası: {str(e)}")

    async def _check_position_status(self, 
                                   position: TradePosition, 
                                   current_price: float,
                                   pnl: float,
                                   chat_id: int,
                                   bot) -> None:
        """Pozisyon durumunu kontrol et"""
        try:
            alerts = []
            should_exit = False
            is_urgent = False
            
            # Stop-Loss kontrolü
            if (position.position_type == 'LONG' and current_price <= position.stop_loss) or \
               (position.position_type == 'SHORT' and current_price >= position.stop_loss):
                alerts.append("🚨 ACİL ÇIKIŞ - STOP LOSS!")
                should_exit = True
                is_urgent = True
            
            # Take-Profit kontrolü
            elif (position.position_type == 'LONG' and current_price >= position.take_profit) or \
                 (position.position_type == 'SHORT' and current_price <= position.take_profit):
                alerts.append("🎯 HEDEF BAŞARILI - KAR AL!")
                should_exit = True
                is_urgent = True
            
            # Kar/Zarar uyarıları
            elif pnl >= self.alert_thresholds['profit_alert']:
                alerts.append(f"💰 KAR FIRSAT: %{pnl:.2f} KAZANÇ!")
                is_urgent = True
            elif pnl <= self.alert_thresholds['loss_alert']:
                alerts.append(f"⚠️ ZARAR UYARISI: %{pnl:.2f} KAYIP!")
                is_urgent = True
            
            # Trend değişimi kontrolü
            price_change = ((current_price - position.entry_price) / position.entry_price) * 100
            if abs(price_change) >= self.alert_thresholds['trend_change']:
                trend = "YÜKSELİŞ" if price_change > 0 else "DÜŞÜŞ"
                alerts.append(f"📊 TREND DEĞİŞİMİ: {trend}!")
            
            # Uyarı varsa bildir
            if alerts:
                message = f"""⚠️ {position.symbol} POZİSYON UYARISI ⚠️

{chr(10).join(alerts)}

💰 Anlık Fiyat: ${current_price:.2f}
📊 Kar/Zarar: %{pnl:.2f}

🎯 Giriş: ${position.entry_price:.2f}
🛑 Stop: ${position.stop_loss:.2f}
✨ Hedef: ${position.take_profit:.2f}
⚡️ Kaldıraç: {position.leverage}x"""

                await self._send_alert(chat_id, bot, message, is_urgent)
            
            # Çıkış sinyali varsa pozisyonu sonlandır
            if should_exit:
                position.monitoring = False
                
        except Exception as e:
            print(f"Durum kontrolü hatası: {str(e)}")

    async def start_trade_monitoring(self, 
                                   symbol: str, 
                                   entry_price: float,
                                   stop_loss: float,
                                   take_profit: float,
                                   position_type: str,
                                   leverage: int,
                                   chat_id: int,
                                   bot) -> None:
        """İşlem takibini başlat"""
        try:
            position = TradePosition(
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_type=position_type,
                leverage=leverage,
                entry_time=datetime.now()
            )
            
            self.active_positions[symbol] = position
            
            # Başlangıç mesajı
            start_message = f"""🎯 İŞLEM TAKİBİ BAŞLADI

{symbol} {position_type}
💰 Giriş: ${entry_price:.2f}
🛑 Stop: ${stop_loss:.2f}
🎯 Hedef: ${take_profit:.2f}
⚡️ Kaldıraç: {leverage}x

⏱️ 15 dakika boyunca takip edilecek...
⚠️ Önemli değişimlerde bildirim alacaksınız!"""

            await self._send_alert(chat_id, bot, start_message)
            
            # 15 dakika boyunca takip et
            monitoring_start = datetime.now()
            while (datetime.now() - monitoring_start).seconds < 900 and position.monitoring:
                try:
                    ticker = self.exchange.fetch_ticker(symbol)
                    current_price = ticker['last']
                    pnl = self._calculate_pnl(position, current_price)
                    
                    await self._check_position_status(
                        position, current_price, pnl, chat_id, bot
                    )
                    
                    await asyncio.sleep(10)
                    
                except Exception as e:
                    print(f"Monitoring hatası: {str(e)}")
                    await asyncio.sleep(5)
            
            # Takip süresi bitti
            if position.monitoring:
                await self._send_final_report(position, current_price, pnl, chat_id, bot)
            
        except Exception as e:
            print(f"Trade monitoring hatası: {str(e)}")
            await self._send_alert(
                chat_id, 
                bot, 
                f"❌ İşlem takibi başlatılamadı: {str(e)}",
                True
            )

    def _calculate_pnl(self, position: TradePosition, current_price: float) -> float:
        """Kar/Zarar hesapla"""
        try:
            price_change = ((current_price - position.entry_price) / position.entry_price) * 100
            if position.position_type == 'LONG':
                return price_change * position.leverage
            else:  # SHORT
                return -price_change * position.leverage
        except Exception as e:
            print(f"PNL hesaplama hatası: {str(e)}")
            return 0.0

    async def _send_final_report(self, 
                               position: TradePosition, 
                               current_price: float,
                               pnl: float,
                               chat_id: int,
                               bot) -> None:
        """Final raporu gönder"""
        try:
            duration = (datetime.now() - position.entry_time).seconds // 60
            
            report = f"""📊 {position.symbol} İşlem Raporu

⏱️ Süre: {duration} dakika
💰 Son Fiyat: ${current_price:.2f}
📈 PNL: %{pnl:.2f}

🎯 Giriş: ${position.entry_price:.2f}
🛑 Stop-Loss: ${position.stop_loss:.2f}
✨ Hedef: ${position.take_profit:.2f}
⚡️ Kaldıraç: {position.leverage}x

{'🎯 Hedef fiyata ulaşıldı!' if current_price >= position.take_profit else ''}
{'⚠️ Stop-Loss seviyesine ulaşıldı!' if current_price <= position.stop_loss else ''}"""

            await bot.send_message(chat_id=chat_id, text=report)
            
        except Exception as e:
            print(f"Rapor gönderme hatası: {str(e)}")

    async def start_scalping_monitor(self, 
                                   symbol: str, 
                                   entry_price: float,
                                   stop_loss: float,
                                   take_profit: float,
                                   position_type: str,
                                   leverage: int,
                                   chat_id: int,
                                   bot) -> None:
        """15 dakikalık scalping takibi başlat"""
        try:
            position = TradePosition(
                symbol=symbol,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_type=position_type,
                leverage=leverage,
                entry_time=datetime.now()
            )
            
            self.active_positions[symbol] = position
            
            start_message = f"""⚡️ SCALPING TAKİBİ BAŞLADI

{symbol} {position_type}
💰 Giriş: ${entry_price:.4f}
🛑 Stop: ${stop_loss:.4f}
🎯 Hedef: ${take_profit:.4f}
⚡️ Kaldıraç: {leverage}x

⏱️ 15 dakikalık hızlı işlem modu
📊 1 dakikalık grafik takibi
⚠️ Hızlı kar/zarar uyarıları aktif"""

            await self._send_alert(chat_id, bot, start_message)
            
            # 15 dakika boyunca sık kontrol
            monitoring_start = datetime.now()
            last_candle_time = None
            
            while (datetime.now() - monitoring_start).seconds < 900 and position.monitoring:
                try:
                    # 1 dakikalık mum verilerini al
                    candles = self.exchange.fetch_ohlcv(
                        symbol, 
                        timeframe=self.timeframes['scalping'],
                        limit=3
                    )
                    
                    current_candle_time = candles[-1][0]
                    current_price = candles[-1][4]  # Kapanış fiyatı
                    
                    # Yeni mum oluştuysa analiz yap
                    if current_candle_time != last_candle_time:
                        last_candle_time = current_candle_time
                        
                        # Scalping analizi
                        analysis = self._analyze_scalping_candles(candles, position_type)
                        
                        # PNL hesapla
                        pnl = self._calculate_pnl(position, current_price)
                        
                        # Durum kontrolü
                        await self._check_scalping_status(
                            position,
                            current_price,
                            pnl,
                            analysis,
                            chat_id,
                            bot
                        )
                    
                    await asyncio.sleep(2)  # 2 saniyede bir kontrol
                    
                except Exception as e:
                    print(f"Scalping takip hatası: {str(e)}")
                    await asyncio.sleep(2)
            
            # Süre bitti
            if position.monitoring:
                await self._send_scalping_report(position, current_price, chat_id, bot)
            
        except Exception as e:
            print(f"Scalping başlatma hatası: {str(e)}")
            await self._send_alert(chat_id, bot, f"❌ Scalping takibi başlatılamadı: {str(e)}", True)

    def _analyze_scalping_candles(self, candles: list, position_type: str) -> Dict:
        """Scalping mum analizi"""
        try:
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Momentum hesapla
            momentum = (df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1] * 100
            
            # Hacim analizi
            volume_change = (df['volume'].iloc[-1] - df['volume'].iloc[-2]) / df['volume'].iloc[-2] * 100
            
            # Sinyal kontrolü
            signals = []
            
            if position_type == 'LONG':
                if momentum > 0.1:
                    signals.append("Yükseliş momentumu devam ediyor")
                elif momentum < -0.1:
                    signals.append("⚠️ Momentum kaybı")
                    
                if volume_change > 50:
                    signals.append("💪 Güçlü alım hacmi")
                elif volume_change < -50:
                    signals.append("⚠️ Hacim düşüşü")
                    
            else:  # SHORT
                if momentum < -0.1:
                    signals.append("Düşüş momentumu devam ediyor")
                elif momentum > 0.1:
                    signals.append("⚠️ Momentum kaybı")
                    
                if volume_change > 50:
                    signals.append("💪 Güçlü satış hacmi")
                elif volume_change < -50:
                    signals.append("⚠️ Hacim düşüşü")
            
            return {
                'momentum': momentum,
                'volume_change': volume_change,
                'signals': signals
            }
            
        except Exception as e:
            return {'error': str(e)}

    async def _check_scalping_status(self,
                                   position: TradePosition,
                                   current_price: float,
                                   pnl: float,
                                   analysis: Dict,
                                   chat_id: int,
                                   bot) -> None:
        """Scalping durum kontrolü"""
        try:
            alerts = []
            should_exit = False
            is_urgent = False
            
            # Stop-Loss kontrolü
            if (position.position_type == 'LONG' and current_price <= position.stop_loss) or \
               (position.position_type == 'SHORT' and current_price >= position.stop_loss):
                alerts.append("🚨 STOP-LOSS! HEMEN ÇIKIŞ YAPIN!")
                should_exit = True
                is_urgent = True
            
            # Take-Profit kontrolü
            elif (position.position_type == 'LONG' and current_price >= position.take_profit) or \
                 (position.position_type == 'SHORT' and current_price <= position.take_profit):
                alerts.append("🎯 HEDEF BAŞARILI! KAR ALIN!")
                should_exit = True
                is_urgent = True
            
            # Hızlı kar/zarar kontrolleri
            elif pnl >= self.scalping_thresholds['quick_profit']:
                alerts.append(f"💰 HIZLI KAR FIRSAT: %{pnl:.2f}")
                is_urgent = True
            elif pnl <= self.scalping_thresholds['quick_loss']:
                alerts.append(f"⚠️ HIZLI ZARAR UYARISI: %{pnl:.2f}")
                is_urgent = True
            
            # Analiz sinyallerini ekle
            if 'signals' in analysis:
                alerts.extend(analysis['signals'])
            
            # Uyarı varsa bildir
            if alerts:
                message = f"""⚡️ {position.symbol} SCALPING UYARISI

{chr(10).join(alerts)}

💰 Fiyat: ${current_price:.4f}
📊 PNL: %{pnl:.2f}
📈 Momentum: %{analysis.get('momentum', 0):.2f}
📊 Hacim Değişimi: %{analysis.get('volume_change', 0):.2f}

🎯 Giriş: ${position.entry_price:.4f}
🛑 Stop: ${position.stop_loss:.4f}
✨ Hedef: ${position.take_profit:.4f}"""

                await self._send_alert(chat_id, bot, message, is_urgent)
            
            if should_exit:
                position.monitoring = False
                
        except Exception as e:
            print(f"Scalping durum kontrolü hatası: {str(e)}")

    async def _send_scalping_report(self, 
                                   position: TradePosition, 
                                   current_price: float,
                                   chat_id: int,
                                   bot) -> None:
        """Scalping raporu gönder"""
        try:
            duration = (datetime.now() - position.entry_time).seconds // 60
            
            report = f"""📊 {position.symbol} Scalping Raporu

⏱️ Süre: {duration} dakika
💰 Son Fiyat: ${current_price:.2f}
📈 PNL: %{self._calculate_pnl(position, current_price):.2f}

🎯 Giriş: ${position.entry_price:.2f}
🛑 Stop-Loss: ${position.stop_loss:.2f}
✨ Hedef: ${position.take_profit:.2f}
⚡️ Kaldıraç: {position.leverage}x"""

            await bot.send_message(chat_id=chat_id, text=report)
            
        except Exception as e:
            print(f"Scalping rapor gönderme hatası: {str(e)}") 