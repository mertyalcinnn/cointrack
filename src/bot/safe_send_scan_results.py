async def send_scan_results(self, chat_id, opportunities, scan_type):
    """Tarama sonuçlarını gönder - basit ve hataya dayanıklı versiyon"""
    try:
        if not opportunities:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Şu anda {scan_type} türünde işlem fırsatı bulunamadı!"
            )
            return

        # BASIT VE GÜVENLI MESAJ FORMATI
        message = "🔍 **İŞLEM FIRSATLARI** 🔍\n\n"
        
        for i, opp in enumerate(opportunities[:5], 1):
            try:
                symbol = opp.get('symbol', f'COIN-{i}')
                signal = opp.get('signal', '⚪ BEKLE')
                
                # Basit format - hata yapabilecek hiçbir işlem yok
                message += f"{i}. {symbol} - {signal}\n\n"
            except Exception as item_err:
                self.logger.error(f"Öğe {i} formatlanırken hata: {str(item_err)}")
        
        # Mesajı gönder
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
        # En iyi fırsatın grafiğini göndermeyi dene
        if opportunities:
            top_opportunity = opportunities[0]
            try:
                symbol = top_opportunity.get('symbol', '')
                if symbol and hasattr(self, 'analyzer') and hasattr(self.analyzer, 'generate_chart'):
                    chart_buf = await self.analyzer.generate_chart(symbol, "15m")
                    if chart_buf:
                        await self.application.bot.send_photo(
                            chat_id=chat_id,
                            photo=chart_buf,
                            caption=f"📊 {symbol} - {scan_type.upper()} Analizi"
                        )
            except Exception as chart_err:
                self.logger.error(f"Grafik gönderme hatası: {str(chart_err)}")
                
    except Exception as e:
        self.logger.error(f"Tarama sonuçları gönderilirken hata: {str(e)}")
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Tarama sonuçları işlenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
        )
