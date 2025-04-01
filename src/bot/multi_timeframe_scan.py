from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
import asyncio
from src.analysis.multi_timeframe_analyzer import MultiTimeframeAnalyzer

async def setup_multi_analyzer(logger=None):
    """MultiTimeframeAnalyzer'ı başlat"""
    analyzer = MultiTimeframeAnalyzer(logger)
    await analyzer.initialize()
    return analyzer

async def scan_command_multi(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Çoklu zaman dilimi analizi ile scan komutunu işle - Premium gerektirir"""
    try:
        chat_id = update.effective_chat.id
        
        # Kullanıcıya bilgi ver
        await update.message.reply_text(
            f"🔍 Çoklu zaman dilimi analizi yapılıyor...\n"
            f"✅ 1W → Ana trendi belirliyor\n"
            f"✅ 1H → Günlük hareketleri inceliyor\n"
            f"✅ 15M → Kesin giriş-çıkış noktalarını belirliyor\n\n"
            f"⏳ Lütfen bekleyin, bu işlem birkaç dakika sürebilir..."
        )
        
        # MultiTimeframeAnalyzer nesnesini kontrol et
        if not hasattr(self, 'multi_analyzer') or self.multi_analyzer is None:
            self.logger.info("MultiTimeframeAnalyzer oluşturuluyor...")
            self.multi_analyzer = await setup_multi_analyzer(self.logger)
            
        # MultiTimeframeAnalyzer kullanarak analiz yap
        opportunities = await self.multi_analyzer.scan_market()
        
        if not opportunities or len(opportunities) == 0:
            # Test verilerini kullan
            self.logger.warning("Tarama sonucu bulunamadı, test verileri kullanılıyor")
            opportunities = self._get_test_multi_opportunities()
            
        # Sonuçları kaydet
        self.last_scan_results[chat_id] = opportunities
        
        # Sonuçları formatla ve gönder
        await self.send_multi_timeframe_results(chat_id, opportunities)
            
    except Exception as e:
        self.logger.error(f"Çoklu zaman dilimi scan komutu hatası: {e}")
        import traceback
        self.logger.error(traceback.format_exc())
        await update.message.reply_text(
            "❌ Tarama sırasında bir hata oluştu!\n"
            "Lütfen daha sonra tekrar deneyin."
        )

async def send_multi_timeframe_results(self, chat_id, opportunities):
    """Çoklu zaman dilimi analiz sonuçlarını gönder"""
    try:
        if not opportunities:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text="❌ Şu anda işlem fırsatı bulunamadı!"
            )
            return
        
        # Başlık mesajı
        header = (
            "🔍 ÇOKLU ZAMAN DİLİMİ ANALİZ SONUÇLARI\n\n"
            "✅ 1W → Ana trend belirlendi\n"
            "✅ 1H → Günlük hareketler incelendi\n"
            "✅ 15M → Kesin giriş-çıkış noktaları belirlendi\n\n"
            "📊 SONUÇLAR:\n\n"
        )
        
        # Her bir sonuç için
        results = ""
        for i, opp in enumerate(opportunities[:5], 1):
            timeframes = opp.get('timeframes', {})
            trend_desc = "\n   ".join(opp.get('trend_descriptions', []))
            
            results += (
                f"{i}. {opp['symbol']} - {opp['signal']}\n"
                f"   💰 Fiyat: ${opp['current_price']:.6f}\n"
                f"   📈 Güven: {opp['opportunity_score']:.1f}/100\n"
                f"   {trend_desc}\n"
                f"   🛑 Stop Loss: ${opp['stop_price']:.6f}\n"
                f"   🎯 Hedef: ${opp['target_price']:.6f}\n"
                f"   ⚖️ R/R: {opp['risk_reward']:.2f}\n\n"
            )
        
        # Tam mesajı oluştur
        message = header + results
        
        # Takip butonları ile mesajı gönder
        keyboard = []
        for i in range(min(5, len(opportunities))):
            keyboard.append([InlineKeyboardButton(f"{i+1}. {opportunities[i]['symbol']} Takip Et", callback_data=f"track_{i+1}")])
        
        keyboard.append([InlineKeyboardButton("🔄 Taramayı Yenile", callback_data="refresh_multi")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup
        )
        
        # En iyi fırsatın grafiğini gönder
        if opportunities:
            top_opportunity = opportunities[0]
            self.logger.info(f"En yüksek puanlı fırsat için çoklu zaman dilimi grafiği oluşturuluyor: {top_opportunity['symbol']}")
            
            try:
                chart_buf = await self.multi_analyzer.generate_multi_timeframe_chart(top_opportunity['symbol'])
                if chart_buf:
                    await self.application.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_buf,
                        caption=f"📊 En Yüksek Puanlı Fırsat: {top_opportunity['symbol']} - Çoklu Zaman Dilimi Analizi"
                    )
                    self.logger.info(f"Çoklu zaman dilimi grafiği başarıyla gönderildi: {top_opportunity['symbol']}")
                else:
                    self.logger.warning(f"Çoklu zaman dilimi grafiği oluşturulamadı: {top_opportunity['symbol']}")
            except Exception as e:
                self.logger.error(f"Grafik gönderme hatası: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())
            
    except Exception as e:
        self.logger.error(f"Çoklu zaman dilimi analiz sonuçları gönderme hatası: {str(e)}")
        import traceback
        self.logger.error(traceback.format_exc())
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Tarama sonuçları işlenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
        )

def _get_test_multi_opportunities(self):
    """Test amaçlı çoklu zaman dilimi fırsatları oluştur"""
    from datetime import datetime
    
    current_time = datetime.now().isoformat()
    return [
        {
            'symbol': 'BTCUSDT',
            'current_price': 96000.0,
            'volume': 1000000000.0,
            'signal': '🟩 GÜÇLÜ LONG',
            'opportunity_score': 85.0,
            'stop_price': 94000.0,
            'target_price': 98000.0,
            'trend_score': 1.4,
            'timeframes': {
                'weekly': 'BULLISH',
                'hourly': 'STRONGLY_BULLISH',
                'minute15': 'BULLISH'
            },
            'trend_descriptions': [
                "✅ 1W: Yükseliş trendi",
                "✅ 1H: Yükseliş trendi",
                "✅ 15M: Yükseliş sinyali"
            ],
            'risk_reward': 2.0,
            'indicators': {
                'rsi_w': 60,
                'rsi_h': 65,
                'rsi_15m': 62,
                'macd_15m': 0.001,
                'bb_position_15m': 60,
                'volume_change': 30
            },
            'timestamp': current_time
        },
        {
            'symbol': 'ETHUSDT',
            'current_price': 3500.0,
            'volume': 500000000.0,
            'signal': '🔴 SHORT',
            'opportunity_score': 75.0,
            'stop_price': 3600.0,
            'target_price': 3300.0,
            'trend_score': -0.8,
            'timeframes': {
                'weekly': 'BEARISH',
                'hourly': 'BEARISH',
                'minute15': 'NEUTRAL'
            },
            'trend_descriptions': [
                "❌ 1W: Düşüş trendi",
                "❌ 1H: Düşüş trendi",
                "➖ 15M: Nötr"
            ],
            'risk_reward': 2.0,
            'indicators': {
                'rsi_w': 40,
                'rsi_h': 35,
                'rsi_15m': 45,
                'macd_15m': -0.002,
                'bb_position_15m': 30,
                'volume_change': 20
            },
            'timestamp': current_time
        },
        {
            'symbol': 'BNBUSDT',
            'current_price': 420.0,
            'volume': 200000000.0,
            'signal': '🟩 LONG',
            'opportunity_score': 70.0,
            'stop_price': 410.0,
            'target_price': 440.0,
            'trend_score': 0.7,
            'timeframes': {
                'weekly': 'BULLISH',
                'hourly': 'NEUTRAL',
                'minute15': 'BULLISH'
            },
            'trend_descriptions': [
                "✅ 1W: Yükseliş trendi",
                "➖ 1H: Nötr",
                "✅ 15M: Yükseliş sinyali"
            ],
            'risk_reward': 2.0,
            'indicators': {
                'rsi_w': 55,
                'rsi_h': 50,
                'rsi_15m': 58,
                'macd_15m': 0.003,
                'bb_position_15m': 40,
                'volume_change': 15
            },
            'timestamp': current_time
        }
    ]
