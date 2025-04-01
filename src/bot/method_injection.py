"""
Bu script, TelegramBot sınıfına yeni metotlar ekler
"""

import logging
import traceback
from src.analysis.ai_analyzer import AIAnalyzer
from .telegram_bot import TelegramBot

# TelegramBot sınıfına metotları ekle
async def _analyze_single_coin_with_ai(self, chat_id, symbol, msg, ai_analyzer=None):
    """Tek bir coini AI ile analiz eder"""
    try:
        # AI Analyzer oluştur (eğer verilmemişse)
        if not ai_analyzer:
            ai_analyzer = AIAnalyzer(self.logger)
            
        # Önce teknik analiz yap
        technical_data = await self.analyzer.analyze_opportunity(symbol, "4h")
        if not technical_data:
            await msg.edit_text(f"❌ {symbol} için teknik analiz yapılamadı! Sembolü kontrol edin.")
            return
            
        # AI analizi yap
        ai_result = await ai_analyzer.analyze_opportunity(symbol, technical_data)
        
        # Sonuçları formatla ve gönder
        message = self._format_ai_analysis(symbol, technical_data, ai_result)
        await msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
        
    except Exception as e:
        self.logger.error(f"Tek coin AI analizi hatası: {str(e)}")
        self.logger.error(traceback.format_exc())
        await msg.edit_text(f"❌ {symbol} için AI analiz yapılırken hata oluştu: {str(e)}")

async def _analyze_scan_results_with_ai(self, chat_id, msg, ai_analyzer=None):
    """Son tarama sonuçlarını AI ile analiz eder"""
    try:
        # AI Analyzer oluştur (eğer verilmemişse)
        if not ai_analyzer:
            ai_analyzer = AIAnalyzer(self.logger)
            
        if chat_id not in self.last_scan_results or not self.last_scan_results[chat_id]:
            await msg.edit_text(
                "❌ Önce /scan veya /multiscan komutu ile piyasayı taramalısınız!"
            )
            return
            
        # Son tarama sonuçlarını al
        opportunities = self.last_scan_results[chat_id]
        
        # Tarama sonuçlarını AI ile analiz et
        await msg.edit_text(
            "🧠 Tarama sonuçları GPT ile analiz ediliyor...\n"
            "En iyi 5 fırsat inceleniyor...\n"
            "⏳ Lütfen bekleyin..."
        )
        
        ai_results = await ai_analyzer.analyze_multiple_coins(opportunities)
        
        # Sonuçları formatla ve gönder
        message = self._format_multiple_ai_analysis(ai_results)
        await msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
        
    except Exception as e:
        self.logger.error(f"Çoklu coin AI analizi hatası: {str(e)}")
        self.logger.error(traceback.format_exc())
        await msg.edit_text("❌ AI analiz yapılırken bir hata oluştu.")

def _format_ai_analysis(self, symbol, technical_data, ai_result):
    """AI analiz sonucunu mesaja dönüştür"""
    try:
        tech_score = technical_data.get('opportunity_score', 0)
        fund_score = ai_result.get('fundamental_score', 0)
        total_score = (tech_score + fund_score) / 2
        
        recommendation = "⚪ BEKLE"
        if ai_result.get('recommendation') == "AL" and technical_data.get('signal', '').find('LONG') >= 0:
            recommendation = "🟢 GÜÇLÜ AL"
        elif ai_result.get('recommendation') == "AL":
            recommendation = "🟢 AL"
        elif ai_result.get('recommendation') == "SAT" and technical_data.get('signal', '').find('SHORT') >= 0:
            recommendation = "🔴 GÜÇLÜ SAT"
        elif ai_result.get('recommendation') == "SAT":
            recommendation = "🔴 SAT"
        
        message = (
            f"🧠 **{symbol} DERIN ANALIZ SONUÇLARI** 🧠\n\n"
            f"📊 **Teknik Puan:** {tech_score:.1f}/100\n"
            f"📚 **Temel Puan:** {fund_score:.1f}/100\n"
            f"⭐ **Toplam Puan:** {total_score:.1f}/100\n\n"
            f"🎯 **Tavsiye:** {recommendation}\n\n"
            f"💰 **Fiyat:** ${technical_data.get('current_price', 0):.6f}\n"
            f"📈 **Trend:** {technical_data.get('trend', 'NEUTRAL')}\n\n"
            f"📝 **GPT ANALİZİ:**\n"
            f"{ai_result.get('analysis', 'Analiz bulunamadı.')[:800]}...\n\n"
            f"⚠️ *Bu analiz yatırım tavsiyesi değildir.*"
        )
        
        return message
    
    except Exception as e:
        self.logger.error(f"AI sonuç formatlama hatası: {e}")
        return "❌ Sonuç formatlanırken bir hata oluştu!"

def _format_multiple_ai_analysis(self, results):
    """Çoklu AI analiz sonucunu mesaja dönüştür"""
    try:
        message = "🧠 **GPT ILE DERIN ANALIZ SONUÇLARI** 🧠\n\n"
        
        # En iyi 5 sonucu göster
        for i, result in enumerate(results[:5], 1):
            symbol = result['symbol']
            tech_score = result.get('opportunity_score', 0)
            fund_score = result.get('fundamental_score', 0)
            total_score = result.get('total_score', 0)
            
            message += (
                f"{i}. **{symbol}** - {total_score:.1f}/100\n"
                f"   📊 Teknik: {tech_score:.1f} | 📚 Temel: {fund_score:.1f}\n"
                f"   💡 {result.get('ai_recommendation', 'BEKLE')}\n\n"
            )
        
        # Detaylı analiz komutu tavsiyesi
        message += (
            "📋 **KULLANIM:**\n"
            "• Detaylı AI analizi için: `/aianalysis BTCUSDT`\n\n"
            "⚠️ *Bu analizler yatırım tavsiyesi değildir.*"
        )
        
        return message
    
    except Exception as e:
        self.logger.error(f"Çoklu AI sonuç formatlama hatası: {e}")
        return "❌ Sonuçlar formatlanırken bir hata oluştu!"

# TelegramBot sınıfına metotları enjekte et
TelegramBot._analyze_single_coin_with_ai = _analyze_single_coin_with_ai
TelegramBot._analyze_scan_results_with_ai = _analyze_scan_results_with_ai
TelegramBot._format_ai_analysis = _format_ai_analysis
TelegramBot._format_multiple_ai_analysis = _format_multiple_ai_analysis

print("TelegramBot sınıfına AI analiz metotları başarıyla enjekte edildi.")
