from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, Application, CallbackContext
from telegram.error import BadRequest
import logging
from typing import List, Dict, Optional, Any, Tuple
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.analysis.multi_timeframe_analyzer import MultiTimeframeAnalyzer
from datetime import datetime
import ccxt

class MultiTimeframeHandler:
    """
    Çoklu zaman dilimi analizi için Telegram bot entegrasyonu.
    Bu sınıf /multiscan komutunu ve ilgili callback işlevlerini yönetir.
    """
    
    def __init__(self, logger=None, bot_instance=None):
        """Initialize the handler with necessary components"""
        self.logger = logger or logging.getLogger('MultiTimeframeHandler')
        self.bot = bot_instance
        self.analyzer = MultiTimeframeAnalyzer(logger=self.logger)
        self.exchange = ccxt.binance()
        self.logger.info("MultiTimeframeHandler başlatıldı")
    
    async def initialize(self):
        """
        Handler'ı başlat
        """
        await self.analyzer.initialize()
    
    def register_handlers(self, application: Application):
        """Register command and callback handlers"""
        try:
            self.logger.info("MultiTimeframeHandler komutları kaydediliyor...")
            application.add_handler(CommandHandler("multiscan", self.multiscan_command))
            application.add_handler(CallbackQueryHandler(self.refresh_multi_callback, pattern="^refresh_multi"))
            self.logger.info("MultiTimeframeHandler komutları başarıyla kaydedildi")
        except Exception as e:
            self.logger.error(f"Handler kayıt hatası: {str(e)}")
    
    async def multiscan_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            message = update.effective_message
            
            # Argümanları kontrol et
            args = context.args
            symbol = None
            if args and len(args) > 0:
                symbol = args[0].upper().strip()
                if not symbol.endswith('USDT'):
                    symbol += 'USDT'
                wait_message = await message.reply_text(f"⏳ {symbol} için analiz yapılıyor...")
            else:
                wait_message = await message.reply_text("⏳ Market taranıyor...")

            try:
                # ccxt.binance() senkron API kullanıyor, await kullanmıyoruz
                tickers = self.exchange.fetch_tickers()
                
                # Sadece USDT çiftlerini filtrele
                ticker_data = []
                for symbol_name, ticker in tickers.items():
                    if symbol_name.endswith('USDT'):
                        try:
                            ticker_data.append({
                                'symbol': symbol_name,
                                'price': float(ticker['last']) if ticker['last'] else 0,
                                'volume': float(ticker['quoteVolume']) if ticker['quoteVolume'] else 0,
                                'change': float(ticker['percentage']) if ticker.get('percentage') else 0
                            })
                        except (KeyError, TypeError, ValueError) as e:
                            self.logger.warning(f"Ticker veri dönüşüm hatası {symbol_name}: {str(e)}")
                            continue
                            
            except Exception as e:
                self.logger.error(f"Ticker verisi alma hatası: {str(e)}")
                await wait_message.edit_text("❌ Market verisi alınamadı. Lütfen daha sonra tekrar deneyin.")
                return

            # Market analizi yap
            if symbol:
                # Tek sembol analizi
                symbol_data = next((t for t in ticker_data if t['symbol'] == symbol), None)
                if not symbol_data:
                    await wait_message.edit_text(f"❌ {symbol} için veri bulunamadı.")
                    return
                results = await self.analyzer.scan_market([symbol_data])
            else:
                # Genel tarama
                results = await self.analyzer.scan_market(ticker_data)

            if not results:
                await wait_message.edit_text("❌ Analiz sonucu bulunamadı.")
                return

            # Sonuçları formatla
            formatted_message = self._format_multi_results(results)
            
            # Yenileme butonu ekle
            refresh_button = InlineKeyboardButton(
                "🔄 Yenile",
                callback_data=f"refresh_multi{'_'+symbol if symbol else ''}"
            )
            
            # Mesajı gönder
            await wait_message.edit_text(
                formatted_message,
                reply_markup=InlineKeyboardMarkup([[refresh_button]]),
                parse_mode='HTML'
            )

        except Exception as e:
            self.logger.error(f"Multiscan hatası: {str(e)}")
            await update.effective_message.reply_text("❌ Bir hata oluştu. Lütfen daha sonra tekrar deneyin.")
    
    async def refresh_multi_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            query = update.callback_query
            await query.answer("Yenileniyor...")
            
            # Callback verilerini ayrıştır
            callback_data = query.data
            symbol = callback_data.split('_')[2] if len(callback_data.split('_')) > 2 else None
            
            try:
                # Ticker verilerini al
                tickers = self.exchange.fetch_tickers()
                
                # Sadece USDT çiftlerini filtrele
                ticker_data = []
                for symbol_name, ticker in tickers.items():
                    if symbol_name.endswith('USDT'):
                        try:
                            ticker_data.append({
                                'symbol': symbol_name,
                                'price': float(ticker['last']) if ticker['last'] else 0,
                                'volume': float(ticker['quoteVolume']) if ticker['quoteVolume'] else 0,
                                'change': float(ticker['percentage']) if ticker.get('percentage') else 0
                            })
                        except (KeyError, TypeError, ValueError) as e:
                            self.logger.warning(f"Ticker veri dönüşüm hatası {symbol_name}: {str(e)}")
                            continue
                            
            except Exception as e:
                self.logger.error(f"Ticker verisi alma hatası: {str(e)}")
                await query.edit_message_text("❌ Market verisi alınamadı. Lütfen daha sonra tekrar deneyin.")
                return

            # Market analizi yap
            if symbol:
                symbol_data = next((t for t in ticker_data if t['symbol'] == symbol), None)
                if not symbol_data:
                    await query.edit_message_text(f"❌ {symbol} için veri bulunamadı.")
                    return
                results = await self.analyzer.scan_market([symbol_data])
            else:
                results = await self.analyzer.scan_market(ticker_data)
            
            if not results:
                await query.edit_message_text("❌ Analiz sonucu bulunamadı.")
                return

            # Sonuçları formatla
            formatted_message = self._format_multi_results(results)
            
            # Yenileme butonu
            refresh_button = InlineKeyboardButton(
                "🔄 Yenile",
                callback_data=query.data
            )
            
            # Mesajı güncelle
            await query.edit_message_text(
                formatted_message,
                reply_markup=InlineKeyboardMarkup([[refresh_button]]),
                parse_mode='HTML'
            )

        except Exception as e:
            self.logger.error(f"Refresh hatası: {str(e)}")
            await query.edit_message_text("❌ Yenileme sırasında bir hata oluştu.")
    
    def _format_multi_results(self, results: List[Dict]) -> str:
        """Çoklu zaman dilimi analiz sonuçlarını formatla"""
        try:
            if not results:
                return "❌ Sonuç bulunamadı."

            # Sonuçları LONG ve SHORT olarak ayır
            long_results = [r for r in results if r.get('signal') == 'LONG']
            short_results = [r for r in results if r.get('signal') == 'SHORT']

            # Log sonuçları
            self.logger.info(f"Toplam {len(results)} sonuç, {len(long_results)} LONG, {len(short_results)} SHORT")

            message_parts = []
            
            # Başlık
            total = len(long_results) + len(short_results)
            message_parts.append(f"📊 <b>Çoklu Zaman Dilimi Analizi</b> ({total} fırsat)\n")
            message_parts.append(f"<i>LONG: {len(long_results)} | SHORT: {len(short_results)}</i>\n")
            
            # LONG fırsatları
            if long_results:
                message_parts.append("\n🟢 <b>LONG Fırsatları:</b>")
                for r in long_results:
                    trend_emoji = self._trend_emoji(r.get('trend', 'NEUTRAL'))
                    risk_reward = r.get('risk_reward_ratio', 'N/A')
                    opportunity_score = r.get('opportunity_score', 0)
                    
                    message_parts.append(
                        f"\n<code>{r['symbol']}</code> {trend_emoji} "
                        f"Fiyat: {r.get('price', 'N/A')} | "
                        f"RSI: {r.get('rsi', 'N/A')} | "
                        f"R/R: {risk_reward} | "
                        f"Skor: {opportunity_score}"
                    )
            
            # SHORT fırsatları
            if short_results:
                message_parts.append("\n\n🔴 <b>SHORT Fırsatları:</b>")
                for r in short_results:
                    trend_emoji = self._trend_emoji(r.get('trend', 'NEUTRAL'))
                    risk_reward = r.get('risk_reward_ratio', 'N/A')
                    opportunity_score = r.get('opportunity_score', 0)
                    
                    message_parts.append(
                        f"\n<code>{r['symbol']}</code> {trend_emoji} "
                        f"Fiyat: {r.get('price', 'N/A')} | "
                        f"RSI: {r.get('rsi', 'N/A')} | "
                        f"R/R: {risk_reward} | "
                        f"Skor: {opportunity_score}"
                    )
            
            # Kullanım bilgisi
            message_parts.append(
                "\n\n📍 <b>KULLANIM:</b>\n"
                "• Detaylı analiz: /multiscan BTCUSDT\n"
                "• Tüm market: /multiscan\n"
                "\n⚠️ Bu analizler yatırım tavsiyesi değildir."
            )

            return "\n".join(message_parts)

        except Exception as e:
            self.logger.error(f"Format hatası: {str(e)}")
            return "❌ Sonuçlar formatlanırken bir hata oluştu."

    def _trend_emoji(self, trend):
        """Trend durumuna göre emoji döndürür"""
        if trend == "STRONGLY_BULLISH":
            return "🟢🟢"
        elif trend == "BULLISH":
            return "🟢"
        elif trend == "STRONGLY_BEARISH":
            return "🔴🔴"
        elif trend == "BEARISH":
            return "🔴"
        elif trend == "NEUTRAL":
            return "⚪"
        else:
            return "❓"