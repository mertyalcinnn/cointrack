"""
AI Analiz komutu için gerekli fonksiyonlar
"""
import logging
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.bot.ai_integration import format_ai_analysis
from src.analysis.ai_analyzer import AIAnalyzer

async def cmd_aianalysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Herhangi bir coini AI ile analiz et"""
    try:
        args = context.args
        
        # Argüman kontrolü
        if not args:
            await update.message.reply_text(
                "❌ Lütfen analiz edilecek bir coin belirtin!\n"
                "Örnek: /aianalysis BTCUSDT veya /aianalysis BTC"
            )
            return
        
        # Sembol temizleme ve formatlama
        symbol = args[0].upper().strip()
        if not symbol.endswith('USDT') and not any(symbol.endswith(suffix) for suffix in ['BTC', 'ETH']):
            symbol += 'USDT'  # Varsayılan olarak USDT ekle
        
        # Kullanıcıya bilgi ver
        msg = await update.message.reply_text(
            f"🧠 {symbol} için derin analiz yapılıyor...\n"
            f"Bu teknik analiz ve temel verileri birleştiren kapsamlı bir analizdir.\n"
            f"⏳ Lütfen bekleyin (1-2 dakika sürebilir)..."
        )
        
        # Ticker verisi al - DÜZELTME: Exchange'in türüne göre doğru şekilde al
        ticker_info = None
        try:
            # self.exchange açıkça ccxt_async olmalı; yoksa bu hata oluşur
            if hasattr(self.exchange, 'fetch_ticker'):
                # Eğer asenkron CCXT'yse doğru şekilde kullan
                if hasattr(self.exchange, '__module__') and self.exchange.__module__.startswith('ccxt.async_support'):
                    ticker_info = await self.exchange.fetch_ticker(symbol)
                else:
                    # Senkron CCXT - await kullanma
                    ticker_info = self.exchange.fetch_ticker(symbol)
            else:
                self.logger.error(f"Exchange fetch_ticker metodu bulunamadı")
                await msg.edit_text(f"❌ {symbol} verileri için geçerli bir exchange bulunamadı.")
                return
        except Exception as ticker_error:
            self.logger.error(f"Ticker verisi alınamadı: {ticker_error}")
            await msg.edit_text(f"❌ {symbol} verileri alınamadı. Sembolü kontrol edin.")
            return
        
        if not ticker_info:
            await msg.edit_text(f"❌ {symbol} fiyat verisi bulunamadı. Geçerli bir sembol olduğundan emin olun.")
            return
        
        # Fiyat ve hacim bilgilerini çıkar
        current_price = ticker_info['last']
        volume = ticker_info['quoteVolume']
        
        # AI Analyzer modülünü çağır
        if not hasattr(self, 'ai_analyzer'):
            self.ai_analyzer = AIAnalyzer(self.logger)
        
        # Teknik analiz yap
        technical_data = await self.analyzer.analyze_opportunity(symbol, current_price, volume, "4h")
        if not technical_data:
            await msg.edit_text(f"❌ {symbol} için teknik analiz yapılamadı.")
            return
            
        # AI analiz
        ai_result = await self.ai_analyzer.analyze_opportunity(symbol, technical_data)
        
        # Sonuçları formatla ve gönder
        message = format_ai_analysis(self, symbol, technical_data, ai_result)
        
        # İşlem butonları ekle
        keyboard = [
            [InlineKeyboardButton("📈 Grafik Göster", callback_data=f"chart_{symbol}_4h")],
            [InlineKeyboardButton("🔔 Fiyat Alarmı", callback_data=f"alert_{symbol}_{current_price}")],
            [InlineKeyboardButton("📊 Takibe Al", callback_data=f"track_{symbol}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await msg.edit_text(message, parse_mode='Markdown', reply_markup=reply_markup, disable_web_page_preview=True)
        
    except Exception as e:
        if hasattr(self, 'logger'):
            self.logger.error(f"AI analiz komutu hatası: {e}")
            self.logger.error(traceback.format_exc())
        else:
            logging.error(f"AI analiz komutu hatası: {e}")
            logging.error(traceback.format_exc())
            
        await update.message.reply_text(f"❌ Analiz sırasında bir hata oluştu: {str(e)}")
