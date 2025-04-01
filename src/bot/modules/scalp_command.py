import logging
from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime

# Scalp komutu için yardımcı fonksiyonlar
async def cmd_scalp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scalping sinyallerini göster (15m ve 1h grafiklerin birleşimi)"""
    try:
        chat_id = update.effective_chat.id
        
        # Parametreleri kontrol et
        symbol = None
        if context.args and len(context.args) > 0:
            symbol = context.args[0].upper()
            if not symbol.endswith('USDT'):
                symbol += 'USDT'
            # CCXT formatına çevir
            if '/' not in symbol:
                symbol_ccxt = f"{symbol[:-4]}/USDT"
            else:
                symbol_ccxt = symbol
        
        # Başlama mesajı gönder
        msg = await update.message.reply_text(
            "🔍 Kısa vadeli ticaret fırsatları aranıyor...\n"
            "Bu analiz 15 dakikalık ve 1 saatlik grafikleri birlikte kullanır.\n"
            "⏳ Lütfen bekleyin..."
        )
        
        # Tek coin analizi veya genel tarama
        if symbol:
            # Tek bir coin'i analiz et
            result = await self.dual_analyzer.analyze_dual_timeframe(symbol_ccxt)
            
            if not result:
                await msg.edit_text(
                    f"❌ {symbol} için analiz yapılamadı! Sembolü kontrol edin."
                )
                return
            
            # Sonucu formatla ve gönder
            message = _format_scalp_result(result)
            await msg.edit_text(message)
            
            # Grafik gönder
            chart_buf = await self.analyzer.generate_chart(symbol.replace('/', ''), "15m")
            if chart_buf:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=chart_buf,
                    caption=f"📊 {symbol} 15m Grafiği"
                )
        else:
            # Tüm sembolleri taramak çok zaman alacağından, sadece popüler coinleri analiz et
            popular_coins = [
                "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", 
                "ADA/USDT", "DOGE/USDT", "DOT/USDT", "AVAX/USDT", "LINK/USDT",
                "MATIC/USDT", "ATOM/USDT", "UNI/USDT", "LTC/USDT", "NEAR/USDT"
            ]
            
            # Tüm coinleri analiz et
            opportunities = await self.dual_analyzer.scan_market(popular_coins)
            
            if not opportunities:
                await msg.edit_text(
                    "❌ Şu anda kısa vadeli işlem fırsatı bulunamadı!\n"
                    "Lütfen daha sonra tekrar deneyin veya belirli bir coin belirtin: /scalp BTCUSDT"
                )
                return
            
            # Sonuçları sakla
            self.last_scan_results[chat_id] = opportunities
            
            # Sonuçları formatla ve gönder
            message = _format_scalp_opportunities(opportunities)
            await msg.edit_text(message)
            
            # En iyi fırsatın grafiğini gönder
            if len(opportunities) > 0:
                top_symbol = opportunities[0]['symbol'].replace('/', '')
                chart_buf = await self.analyzer.generate_chart(top_symbol, "15m")
                if chart_buf:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_buf,
                        caption=f"📊 {top_symbol} 15m Grafiği (En İyi Fırsat)"
                    )
    
    except Exception as e:
        self.logger.error(f"Scalp komutu hatası: {str(e)}")
        await update.message.reply_text(
            f"❌ Kısa vadeli işlem analizi sırasında bir hata oluştu: {str(e)}"
        )

def _format_scalp_result(result):
    """Tek bir scalping sonucunu formatla"""
    message = f"⚡ **KISA VADELİ İŞLEM ANALİZİ** ⚡\n\n"
    message += f"🪙 {result['symbol']} - {result['position']}\n"
    message += f"💰 Fiyat: ${result['current_price']:.6f}\n"
    message += f"⭐ Fırsat Puanı: {result['opportunity_score']:.1f}/100\n"
    message += f"📊 Güven: %{result['confidence']:.1f}\n\n"
    
    # Trend ve sinyal bilgilerini ekle
    message += f"⏱️ **1h Trend:** {result['1h_trend']}\n"
    message += f"📈 **15m Sinyal:** {result['15m_signal']}\n\n"
    
    # Teknik göstergeler
    message += f"📊 **Teknik Göstergeler:**\n"
    message += f"• 1h RSI: {result['rsi_1h']:.1f}\n"
    message += f"• 15m RSI: {result['rsi_15m']:.1f}\n"
    message += f"• 15m MACD: {result['macd_15m']:.6f}\n"
    message += f"• BB Pozisyon: %{result['bb_position_15m']:.1f}\n\n"
    
    # İşlem bilgileri
    message += f"🚦 **İşlem Bilgileri:**\n"
    message += f"• Giriş Fiyatı: ${result['current_price']:.6f}\n"
    message += f"• Stop Loss: ${result['stop_loss']:.6f} (%{abs((result['stop_loss'] - result['current_price']) / result['current_price'] * 100):.2f})\n"
    message += f"• Take Profit: ${result['take_profit']:.6f} (%{abs((result['take_profit'] - result['current_price']) / result['current_price'] * 100):.2f})\n"
    message += f"• Risk/Ödül: {result['risk_reward']:.2f}\n\n"
    
    # Analiz nedenleri
    message += f"📝 **Analiz Nedenleri:**\n"
    for reason in result['reasons']:
        message += f"• {reason}\n"
    
    message += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    return message

def _format_scalp_opportunities(opportunities):
    """Scalping fırsatlarını formatla"""
    message = f"⚡ **KISA VADELİ İŞLEM FIRSATLARI** ⚡\n\n"
    message += f"📈 15 dakikalık ve 1 saatlik grafiklerin birleşimi ile oluşturulan sinyaller.\n"
    message += f"⏱️ Tahmini işlem süresi: 15 dakika - 1 saat\n"
    message += f"💹 Hedef kâr: %1-%2 (kaldıraç kullanımına göre 5-10$)\n\n"
    
    for i, result in enumerate(opportunities):
        message += f"**{i+1}. {result['symbol']} - {result['position']}**\n"
        message += f"💰 Fiyat: ${result['current_price']:.6f}\n"
        message += f"⭐ Puan: {result['opportunity_score']:.1f}/100\n"
        
        # Teknik göstergeler (kısa özet)
        message += f"📊 RSI: 1h-{result['rsi_1h']:.0f}/15m-{result['rsi_15m']:.0f}\n"
        
        # Risk yönetimi
        message += f"🛑 Stop: ${result['stop_loss']:.6f} (%{abs((result['stop_loss'] - result['current_price']) / result['current_price'] * 100):.1f})\n"
        message += f"🎯 Hedef: ${result['take_profit']:.6f} (%{abs((result['take_profit'] - result['current_price']) / result['current_price'] * 100):.1f})\n"
        
        # Ana neden
        main_reason = result['reasons'][0] if result['reasons'] else ""
        message += f"💡 {main_reason}\n\n"
    
    # Kullanım ipuçları
    message += f"**Kullanım İpuçları:**\n"
    message += f"• 15dk ve 1s grafiklerdeki uyumlu sinyaller daha güvenilirdir\n"
    message += f"• Her zaman stop-loss kullanın (maksimum %1-%1.5 risk)\n"
    message += f"• Kâr hedefinize ulaştığınızda çıkın (açgözlü olmayın)\n"
    message += f"• Belirli bir coini analiz etmek için: /scalp BTCUSDT\n"
    
    message += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    return message
