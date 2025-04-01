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
                        levels_msg += "🟢 DESTEK SEVİYE