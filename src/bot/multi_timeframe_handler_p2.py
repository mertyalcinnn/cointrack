            if not is_premium:
                await query.edit_message_text(
                    "🔒 Bu özellik sadece premium kullanıcılar için kullanılabilir.\n"
                    "Premium özelliklerini denemek için /trial komutunu kullanabilirsiniz.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎁 Deneme Süresi Başlat", callback_data="start_trial")]
                    ])
                )
                return
            
            # Analizi yenile
            await query.edit_message_text(
                "🔄 Çoklu zaman dilimi analizi yenileniyor...\n"
                "Lütfen bekleyin...",
                reply_markup=None
            )
            
            results = await self.analyzer.scan_market([symbol] if symbol else None)
            
            if results:
                # Cache'i güncelle
                cache_key = symbol if symbol else "all_symbols"
                self.analysis_cache[cache_key] = results
                self.last_analysis_time[cache_key] = time.time()
                
                # Sonuçları formatla
                message_text = self._format_multi_results(results)
                
                # Refresh butonu ekle
                keyboard = [
                    [InlineKeyboardButton("🔄 Yenile", callback_data="refresh_multi")],
                    [InlineKeyboardButton("📊 Tüm Grafik", callback_data=f"full_chart_{results[0]['symbol']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Mesajı güncelle
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # Grafik için yeni bir mesaj gönder
                top_opportunity = results[0]
                chart_buf = await self.analyzer.generate_multi_timeframe_chart(top_opportunity["symbol"])
                if chart_buf:
                    # Grafik için açıklama metni oluştur
                    chart_caption = self._create_chart_caption(top_opportunity)
                    
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=chart_buf,
                        caption=chart_caption,
                        parse_mode='HTML'
                    )
            else:
                scan_type = f"{symbol} çoklu zaman dilimi" if symbol else "çoklu zaman dilimi"
                await query.edit_message_text(
                    f"❌ {scan_type.capitalize()} analizi için uygun fırsat bulunamadı!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Tekrar Dene", callback_data="refresh_multi")]
                    ])
                )
            
        except Exception as e:
            self.logger.error(f"Refresh multi callback hatası: {str(e)}")
            await query.answer("Yenileme sırasında bir hata oluştu!")
            
            # Hata durumunda basit bir mesaj güncelleme
            try:
                await query.edit_message_text(
                    f"{query.message.text}\n\n⚠️ Yenileme sırasında bir hata oluştu. Lütfen daha sonra tekrar deneyin.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Tekrar Dene", callback_data="refresh_multi")]
                    ]),
                    parse_mode='Markdown'
                )
            except:
                pass