"""
AI entegrasyonu için gerekli fonksiyonlar
"""

from src.analysis.ai_analyzer import AIAnalyzer
import logging
import traceback
import ccxt.async_support as ccxt_async  # Asenkron CCXT kullanıyoruz

async def analyze_single_coin_with_ai(self, chat_id, symbol, msg, ai_analyzer=None):
    """Tek bir coini AI ile analiz eder"""
    try:
        # AI Analyzer oluştur (eğer verilmemişse)
        if not ai_analyzer:
            self.ai_analyzer = AIAnalyzer(self.logger)
            ai_analyzer = self.ai_analyzer
        else:
            self.ai_analyzer = ai_analyzer
            
        # Ticker verisi al - asenkron CCXT kullanarak
        try:
            exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot'
                }
            })
            
            # Asenkron exchange için await kullanmalıyız
            ticker_data = await exchange.fetch_ticker(symbol)
            current_price = float(ticker_data['last'])
            volume = float(ticker_data['quoteVolume'])
            
            # Asenkron exchange'i kapat (önemli)
            await exchange.close()
            
        except Exception as ticker_error:
            if hasattr(self, 'logger'):
                self.logger.error(f"Ticker verisi alınamadı: {ticker_error}")
            else:
                logging.error(f"Ticker verisi alınamadı: {ticker_error}")
                
            await msg.edit_text(f"❌ {symbol} için fiyat verisi alınamadı! Sembolü kontrol edin.")
            return
            
        # Teknik analiz yap - doğru parametre sayısıyla çağır
        technical_data = await self.analyzer.analyze_opportunity(symbol, current_price, volume, "4h")
        if not technical_data:
            await msg.edit_text(f"❌ {symbol} için teknik analiz yapılamadı! Sembolü kontrol edin.")
            return
            
        # AI analizi yap
        ai_result = await ai_analyzer.analyze_opportunity(symbol, technical_data)
        
        # Sonuçları formatla ve gönder
        message = format_ai_analysis(self, symbol, technical_data, ai_result)
        await msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
        
    except Exception as e:
        if hasattr(self, 'logger'):
            self.logger.error(f"Tek coin AI analizi hatası: {str(e)}")
            self.logger.error(traceback.format_exc())
        else:
            logging.error(f"Tek coin AI analizi hatası: {str(e)}")
            logging.error(traceback.format_exc())
            
        await msg.edit_text(f"❌ {symbol} için AI analiz yapılırken hata oluştu: {str(e)}")

async def analyze_scan_results_with_ai(self, chat_id, msg, ai_analyzer=None):
    """Son tarama sonuçlarını AI ile analiz eder"""
    try:
        # AI Analyzer oluştur (eğer verilmemişse)
        if not ai_analyzer:
            self.ai_analyzer = AIAnalyzer(self.logger)
            ai_analyzer = self.ai_analyzer
        else:
            self.ai_analyzer = ai_analyzer
            
        if chat_id not in self.last_scan_results or not self.last_scan_results[chat_id]:
            await msg.edit_text(
                "❌ Önce /scan veya /multiscan komutu ile piyasayı taramalısınız!"
            )
            return
            
        # Son tarama sonuçlarını al
        opportunities = self.last_scan_results[chat_id]
        
        # Tarama sonuçlarını AI ile analiz et
        await msg.edit_text(
            "🧠 Tarama sonuçları AI ile analiz ediliyor...\n"
            "En iyi 5 fırsat inceleniyor...\n"
            "⏳ Lütfen bekleyin..."
        )
        
        # Fırsatların gerekli tüm verileri içerdiğinden emin ol
        for opp in opportunities:
            # Gerekli alanları kontrol et ve düzelt
            if 'price' in opp and 'current_price' not in opp:
                opp['current_price'] = opp['price']
            if 'symbol' not in opp:
                continue  # Symbol yoksa analiz edemeyiz
        
        ai_results = await ai_analyzer.analyze_multiple_coins(opportunities)
        
        # Sonuçları formatla ve gönder
        message = format_multiple_ai_analysis(self, ai_results)
        await msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
        
    except Exception as e:
        if hasattr(self, 'logger'):
            self.logger.error(f"Çoklu coin AI analizi hatası: {str(e)}")
            self.logger.error(traceback.format_exc())
        else:
            logging.error(f"Çoklu coin AI analizi hatası: {str(e)}")
            logging.error(traceback.format_exc())
            
        await msg.edit_text("❌ AI analiz yapılırken bir hata oluştu.")

def format_ai_analysis(self, symbol, technical_data, ai_result):
    """Geliştirilmiş AI analiz sonucu formatı"""
    try:
        # Puanlar ve temel veriler
        tech_score = technical_data.get('opportunity_score', 0)
        fund_score = ai_result.get('fundamental_score', 0)
        total_score = (tech_score + fund_score) / 2
        current_price = technical_data.get('current_price', 0)
        
        # Tavsiye formatı
        recommendation = ai_result.get('recommendation', 'BEKLE')
        rec_emoji = "🟢" if recommendation == "AL" else "🔴" if recommendation == "SAT" else "⚪"
        rec_text = f"{rec_emoji} {recommendation}"
        
        # Fiyat bilgileri
        price_change = technical_data.get('price_change_24h', 0)
        change_emoji = "🔼" if price_change > 0 else "🔽"
        change_text = f"{change_emoji} %{abs(price_change):.2f}" if price_change != 0 else "➡️ %0.00"
        
        # Teknik göstergeler
        rsi = technical_data.get('rsi', 0)
        macd = technical_data.get('macd', 0)
        ema20 = technical_data.get('ema20', 0)
        trend = technical_data.get('trend', '?')
        trend_emoji = "📈" if trend == "YUKARI" else "📉" if trend == "AŞAĞI" else "➡️"
        
        # Giriş ve hedefler
        if recommendation == "AL":
            entry_price = current_price
            stop_loss = current_price * 0.95  # %5 altında
            target1 = current_price * 1.10    # %10 üstünde
            target2 = current_price * 1.20    # %20 üstünde
            risk_reward = 2.0
        elif recommendation == "SAT":
            entry_price = current_price
            stop_loss = current_price * 1.05  # %5 üstünde
            target1 = current_price * 0.90    # %10 altında
            target2 = current_price * 0.80    # %20 altında
            risk_reward = 2.0
        else:  # BEKLE
            entry_price = current_price
            stop_loss = current_price * 0.93  # %7 altında
            target1 = current_price * 1.10    # %10 üstünde
            target2 = None
            risk_reward = 1.43
        
        # Destek/direnç seviyelerini kullan (eğer varsa)
        if 'support_levels' in technical_data and technical_data['support_levels']:
            support_levels = technical_data['support_levels']
            closest_support = max([s for s in support_levels if s < current_price], default=stop_loss)
            stop_loss = closest_support
        
        if 'resistance_levels' in technical_data and technical_data['resistance_levels']:
            resistance_levels = technical_data['resistance_levels']
            if recommendation == "AL":
                upper_resistances = [r for r in resistance_levels if r > current_price]
                if upper_resistances:
                    target1 = min(upper_resistances, default=target1)
                    if len(upper_resistances) > 1:
                        target2_candidates = [r for r in upper_resistances if r > target1]
                        if target2_candidates:
                            target2 = min(target2_candidates, default=target2)
        
        # AI analiz metni
        analysis_text = ai_result.get('analysis', '')
        
        # Temel noktalar çıkar (en fazla 5 tane)
        analysis_points = []
        if analysis_text:
            # Paragraf veya maddeleri bölmek için
            paragraphs = [p.strip() for p in analysis_text.split('\n') if p.strip()]
            for p in paragraphs[:10]:  # İlk 10 paragrafı kontrol et
                if len(p) > 30 and not p.startswith('#') and not p.startswith('Puan:'):
                    # Cümleyi kısalt
                    if len(p) > 120:
                        p = p[:117] + "..."
                    analysis_points.append(p)
                    if len(analysis_points) >= 5:
                        break
        
        # Hedef ve stop-loss değişim yüzdeleri
        stop_pct = abs((stop_loss / current_price - 1) * 100)
        target1_pct = abs((target1 / current_price - 1) * 100)
        target2_pct = abs(((target2 or current_price * 1.2) / current_price - 1) * 100)
        
        # Formatlanmış çıktı oluştur
        message = (
            f"🔍 {symbol} DETAYLI ANALİZ RAPORU\n\n"
            
            f"💰 **FİYAT BİLGİLERİ**\n"
            f"● Güncel Fiyat: ${current_price:.6f}\n"
            f"● 24s Değişim: {change_text}\n"
            f"● Trend: {trend_emoji} {trend}\n\n"
            
            f"⭐ **ANALİZ SKORU: {total_score:.1f}/100**\n"
            f"● Teknik Analiz: {tech_score:.1f}/100\n"
            f"● Temel Analiz: {fund_score:.1f}/100\n\n"
            
            f"🎯 **İŞLEM TAVSİYESİ: {rec_text}**\n"
            f"● Giriş Fiyatı: ${entry_price:.6f}\n"
            f"● Stop Loss: ${stop_loss:.6f} (%{stop_pct:.1f})\n"
            f"● Hedef 1: ${target1:.6f} (%{target1_pct:.1f})\n"
        )
        
        # Eğer Hedef 2 varsa ekle
        if target2:
            message += f"● Hedef 2: ${target2:.6f} (%{target2_pct:.1f})\n"
        
        # Risk/Ödül oranı
        message += f"● Risk/Ödül: {risk_reward:.1f}\n\n"
        
        # Teknik göstergeler
        message += (
            f"📊 **TEKNİK GÖSTERGELER**\n"
            f"● RSI: {rsi:.1f}" + (" (Aşırı Alım)" if rsi > 70 else " (Aşırı Satım)" if rsi < 30 else "") + "\n"
            f"● MACD: {macd:.6f}" + (" (Pozitif)" if macd > 0 else " (Negatif)") + "\n"
            f"● EMA 20: ${ema20:.6f}\n\n"
        )
        
        # AI analiz noktaları
        message += f"📝 **TEMEL ANALİZ NOKTALARI**\n"
        if analysis_points:
            for i, point in enumerate(analysis_points, 1):
                message += f"{i}. {point}\n"
        else:
            message += "● Yeterli temel analiz verisi bulunamadı\n"

        # Dipnot ekle
        message += "\n⚠️ **Bu analiz yatırım tavsiyesi değildir. Her zaman kendi araştırmanızı yapın.**"
        
        return message
        
    except Exception as e:
        if hasattr(self, 'logger'):
            self.logger.error(f"AI sonuç formatlama hatası: {e}")
        else:
            logging.error(f"AI sonuç formatlama hatası: {e}")
            
        return "❌ Sonuç formatlanırken bir hata oluştu!"

def format_multiple_ai_analysis(self, results):
    """Geliştirilmiş çoklu AI analiz sonucu formatı"""
    try:
        message = "🧠 AI ANALİZ SONUÇLARI | EN İYİ FIRSATLAR 🧠\n\n"
        
        # En iyi 5 sonucu göster
        for i, result in enumerate(results[:5], 1):
            symbol = result['symbol']
            tech_score = result.get('opportunity_score', 0)
            fund_score = result.get('fundamental_score', 0)
            total_score = (tech_score + fund_score) / 2 if 'total_score' not in result else result.get('total_score', 0)
            
            # Tavsiye emojisi ve anlaşılır isim
            rec = result.get('ai_recommendation', 'BEKLE')
            rec_emoji = "🟢" if rec == "AL" else "🔴" if rec == "SAT" else "⚪"
            
            # Mevcut fiyat bilgisi
            current_price = result.get('current_price', 0)
            price_str = f"${current_price:.6f}" if current_price < 1 else f"${current_price:.2f}"
            
            # Giriş fiyatı ve hedefler hesapla
            entry_price = current_price
            if rec == "AL":
                stop_loss = current_price * 0.95  # %5 altında
                target = current_price * 1.15     # %15 üstünde
                risk_reward = 3.0                 # 3:1 risk/ödül
            elif rec == "SAT":
                stop_loss = current_price * 1.05  # %5 üstünde
                target = current_price * 0.85     # %15 altında
                risk_reward = 3.0                 # 3:1 risk/ödül
            else:  # BEKLE
                stop_loss = current_price * 0.93  # %7 altında
                target = current_price * 1.10     # %10 üstünde
                risk_reward = 1.43                # 1.43:1 risk/ödül
            
            # Tavsiye gerekçesi
            reason = ""
            if 'ai_analysis' in result:
                # AI analizinden daha iyi bir neden çıkarmaya çalış
                if hasattr(self, 'ai_analyzer') and hasattr(self.ai_analyzer, '_extract_recommendation_reason'):
                    reason = self.ai_analyzer._extract_recommendation_reason(result['ai_analysis'], rec)
                
                # Hedef ve stop-loss değerlerini çıkarmaya çalış
                if hasattr(self, 'ai_analyzer') and hasattr(self.ai_analyzer, '_extract_targets'):
                    targets = self.ai_analyzer._extract_targets(result['ai_analysis'], current_price, rec)
                    if 'stop' in targets:
                        try:
                            stop_loss = float(targets['stop'].replace('$', ''))
                        except:
                            pass
                    if 'target' in targets:
                        try:
                            target = float(targets['target'].replace('$', ''))
                        except:
                            pass
            
            # Nedenimiz yoksa varsayılan nedenler oluştur
            if not reason:
                if rec == "AL":
                    reason = "Teknik göstergeler pozitif ve temel veriler güçlü destek sağlıyor"
                elif rec == "SAT":
                    reason = "Negatif fiyat momentumu ve yüksek değerleme"
                else:
                    reason = "Karışık sinyaller, net trend oluşumunu bekleyin"
            
            # Stop ve hedefleri formatla
            stop_str = f"${stop_loss:.6f}" if stop_loss < 1 else f"${stop_loss:.2f}"
            target_str = f"${target:.6f}" if target < 1 else f"${target:.2f}"
            
            # Stop ve hedef % değişimleri
            stop_pct = abs((stop_loss/current_price-1)*100)
            target_pct = abs((target/current_price-1)*100)
                    
            # Coin başına özel özet oluştur
            message += (
                f"{i}. {symbol} - {total_score:.1f}/100 {rec_emoji}\n"
                f"   💰 Fiyat: {price_str} | 📊 Teknik: {tech_score:.1f} | 📚 Temel: {fund_score:.1f}\n"
                f"   🎯 Hedef: {target_str} (%{target_pct:.1f}) | 🛑 Stop: {stop_str} (%{stop_pct:.1f}) | ⚖️ R/R: {risk_reward:.1f}\n"
                f"   💡 {rec}: {reason[:100]}\n\n"
            )
        
        # Kullanıcı seçebilsin
        coins_list = ", ".join([result['symbol'] for result in results[:5]])
        
        message += (
            "📋 İŞLEM BİLGİLERİ:\n"
            "● Yukarıdaki coinlerden birini analiz et: /aianalysis SEMBOL\n"
            "● Herhangi bir coini analiz et: /aianalysis COINADI\n"
            f"● Hızlı analiz örnekleri: /aianalysis {results[0]['symbol']} veya /aianalysis BTC\n\n"
            "⚠️ Risk yönetimi için her zaman stop-loss kullanın. Analizler yatırım tavsiyesi değildir."
        )
        
        return message
        
    except Exception as e:
        if hasattr(self, 'logger'):
            self.logger.error(f"Çoklu AI sonuç formatlama hatası: {e}")
        else:
            logging.error(f"Çoklu AI sonuç formatlama hatası: {e}")
            
        return "❌ Sonuçlar formatlanırken bir hata oluştu!"
