async def send_scan_results(self, chat_id, opportunities, scan_type):
    """Tarama sonuçlarını göndererek en iyi fırsatın gelişmiş grafiğini ekler."""
    try:
        if not opportunities:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Şu anda {scan_type} türünde işlem fırsatı bulunamadı!"
            )
            return

        # Sonuçları formatla
        try:
            message = self._format_scalp_opportunities(opportunities)
        except Exception as e:
            self.logger.error(f"Fırsat formatlarken hata: {str(e)}")
            # Basit bir mesaj formatı kullan
            message = "🔍 İŞLEM FIRSATLARI:\n\n"
            for i, opp in enumerate(opportunities[:5], 1):
                symbol = opp.get('symbol', 'UNKNOWN')
                signal = opp.get('signal', '⚪ BEKLE')
                message += f"{i}. {symbol} - {signal}\n\n"

        # Mesajı gönder
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
        # En iyi fırsatın grafiğini gönder
        if opportunities:
            top_opportunity = opportunities[0]  # En yüksek puanlı fırsat
            self.logger.info(f"En yüksek puanlı fırsat için gelişmiş grafik oluşturuluyor: {top_opportunity['symbol']}")
            
            # Grafiği oluşturmayı dene - bakımcı dostu hata kontrolü
            try:
                chart_buf = None
                
                # 1. Önce dual_analyzer.generate_enhanced_scalp_chart'ı dene
                if hasattr(self, 'dual_analyzer') and hasattr(self.dual_analyzer, 'generate_enhanced_scalp_chart'):
                    try:
                        chart_buf = await self.dual_analyzer.generate_enhanced_scalp_chart(top_opportunity['symbol'], top_opportunity)
                    except Exception as e:
                        self.logger.warning(f"dual_analyzer.generate_enhanced_scalp_chart hatası: {str(e)}")
                
                # 2. Yukarıdaki başarısız olursa, analyzer.generate_enhanced_scalp_chart'ı dene
                if not chart_buf and hasattr(self, 'analyzer') and hasattr(self.analyzer, 'generate_enhanced_scalp_chart'):
                    try:
                        chart_buf = await self.analyzer.generate_enhanced_scalp_chart(top_opportunity['symbol'], top_opportunity)
                    except Exception as e:
                        self.logger.warning(f"analyzer.generate_enhanced_scalp_chart hatası: {str(e)}")
                
                # 3. Yukarıdaki başarısız olursa, normal generate_chart metodunu dene
                if not chart_buf:
                    if hasattr(self, 'dual_analyzer') and hasattr(self.dual_analyzer, 'generate_chart'):
                        chart_buf = await self.dual_analyzer.generate_chart(top_opportunity['symbol'], "15m")
                    elif hasattr(self, 'analyzer') and hasattr(self.analyzer, 'generate_chart'):
                        chart_buf = await self.analyzer.generate_chart(top_opportunity['symbol'], "15m")
                
                # Eğer bir grafik oluşturabildiysen gönder
                if chart_buf:
                    await self.application.bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_buf,
                        caption=f"📊 En Yüksek Puanlı Fırsat: {top_opportunity['symbol']} - {scan_type.upper()} Analizi"
                    )
                    self.logger.info(f"Gelişmiş grafik başarıyla gönderildi: {top_opportunity['symbol']}")
                else:
                    self.logger.warning(f"Gelişmiş grafik oluşturulamadı: {top_opportunity['symbol']}")
                
            except Exception as e:
                self.logger.error(f"Grafik gönderme hatası: {str(e)}")
                import traceback
                self.logger.error(traceback.format_exc())
                    
        except Exception as e:
            self.logger.error(f"Tarama sonuçları gönderilirken hata: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Tarama sonuçları işlenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
            )
