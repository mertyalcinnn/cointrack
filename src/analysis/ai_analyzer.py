from anthropic import Anthropic, AnthropicError
import asyncio
import logging
from typing import Dict, List, Any
import os
import json
import traceback
from datetime import datetime
import re

# Web araştırma entegrasyonu
try:
    from src.web_research import WebResearcher
except ImportError:
    WebResearcher = None

class AIAnalyzer:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('AIAnalyzer')
        
        # .env'yi yeniden yükle
        from dotenv import load_dotenv
        from pathlib import Path
        
        # .env dosyasının yolunu bul
        env_path = Path(__file__).parent.parent.parent / '.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)
        
        # API anahtarını al
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            self.logger.warning("ANTHROPIC_API_KEY bulunamadı. .env dosyasında tanımlandığından emin olun.")
            raise ValueError("ANTHROPIC_API_KEY bulunamadı. Lütfen .env dosyanıza bir API anahtarı ekleyin.")
        
        self.logger.info(f"Anthropic API bağlantısı kuruluyor... (API anahtarı: {self.api_key[:8]}...)")
        
        # Web araştırma modülünü başlat
        self.web_researcher = None
        
        try:
            self.client = Anthropic(api_key=self.api_key)
            self.max_tokens = 2000
            self.cache_dir = "cache/ai_analysis"
            self.cache_duration = 86400  # 24 saat (saniye cinsinden)
            
            # Cache dizinini oluştur
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception as e:
            self.logger.error(f"Anthropic istemcisi oluşturulurken hata: {e}")
            raise
    
    def generate_ai_prompt(self, symbol: str, technical_data: Dict, web_research_data: Dict = None) -> str:
        """
        AI analizi için prompt oluştur
        """
        # Temel teknik bilgileri ekle
        current_price = technical_data.get('current_price', 0)
        rsi = technical_data.get('rsi', 0)
        macd = technical_data.get('macd', 0)
        ema20 = technical_data.get('ema20', 0)
        ema50 = technical_data.get('ema50', 0)
        ema200 = technical_data.get('ema200', 0) if 'ema200' in technical_data else None
        bb_position = technical_data.get('bb_position', 50)  # Varsayılan değer
        volume = technical_data.get('volume', 0)
        trend = technical_data.get('trend', 'Belirsiz')
        signal = technical_data.get('signal', '')
        
        # Stop-loss ve hedef bilgileri
        stop_price = technical_data.get('stop_price', current_price * 0.95)
        target_price = technical_data.get('target_price', current_price * 1.05)
        risk_reward = technical_data.get('risk_reward', (target_price - current_price) / (current_price - stop_price) if stop_price != current_price else 0)
        
        # Destek ve direnç seviyeleri
        support_levels = technical_data.get('support_levels', [])
        resistance_levels = technical_data.get('resistance_levels', [])
        
        # Prompt oluştur
        prompt = f"""
        {symbol} için kısa ve özlü bir teknik ve temel analiz yap. 
        
        Teknik Göstergeler:
        - Fiyat: ${current_price:.6f}
        - RSI: {rsi:.1f}
        - MACD: {macd:.6f}
        - EMA20: ${ema20:.6f}
        - EMA50: ${ema50:.6f}
        {f'- EMA200: ${ema200:.6f}' if ema200 else ''}
        - Bollinger Band Pozisyonu: %{bb_position:.1f}
        - 24s Hacim: ${volume:,.0f}
        - Trend: {trend}
        - Sinyal: {signal}
        
        Stop-loss: ${stop_price:.6f}
        Hedef: ${target_price:.6f}
        Risk/Ödül: {risk_reward:.2f}
        
        Konuşma tarzında değil, madde madde kısa ve kesin yargılarla yanıt ver. Max 300 karakter kullan.
        
        Şu başlıkları yanıtında mutlaka içer (her başlık için 1-2 cümle yeterli):
        
        1. Güncel Durum
        2. AL/SAT/BEKLE tavsiyesi (net ifade et)
        3. Destek ve direnç seviyeleri
        4. Kısa vadeli beklenti
        5. Risk düzeyi
        """
        
        return prompt
        
    def _format_technical_data(self, data: Dict) -> str:
        """
        Teknik verileri formatla
        """
        return "\\n".join([
            f"- {key}: {value}"
            for key, value in data.items()
        ])
        
    def _format_research_data(self, data: Dict) -> str:
        """
        Araştırma verilerini formatla
        """
        return "\\n".join([
            f"- {key}: {value}"
            for key, value in data.items()
        ])
        
    async def analyze_opportunity(self, symbol: str, technical_data: Dict) -> Dict:
        """
        Belirli bir coin için AI analizi yap
        """
        try:
            # Web araştırması yap - eğer WebResearcher mevcutsa
            web_research_data = {}
            if self.web_researcher:
                try:
                    web_research_data = await self.web_researcher.research_coin(symbol)
                except Exception as e:
                    self.logger.error(f"Web araştırması hatası: {e}")
            
            # Prompt oluştur
            prompt = self.generate_ai_prompt(symbol, technical_data, web_research_data)
            
            # AI'dan yanıt al (Anthropic API'yi doğru şekilde çağır)
            try:
                # Burada await kullanmıyoruz çünkü Anthropic API'nin newer versiyonunda bu method senkron
                response = self.client.messages.create(
                    model="claude-3-7-sonnet-20250219",  # Claude 3.7 Sonnet modeli kullan
                    max_tokens=500,  # Az token kullanmak için limit
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                
                # Yanıtı işle
                analysis_text = response.content[0].text
            except Exception as api_error:
                self.logger.error(f"Anthropic API hatası: {str(api_error)}")
                # Hata durumunda basit bir analiz metni oluştur
                analysis_text = f"Teknik analize göre {symbol} için alım-satım kararı vermek için daha fazla veri gerekli."
            
            # Sonuçları oluştur
            result = {
                "symbol": symbol,
                "analysis": analysis_text,
                "recommendation": self._extract_recommendation(analysis_text),
                "fundamental_score": self._calculate_fundamental_score(analysis_text),
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"AI analizi hatası: {str(e)}")
            return {
                "symbol": symbol,
                "analysis": f"Analiz sırasında hata oluştu: {str(e)}",
                "recommendation": "BEKLE",
                "fundamental_score": 0,
                "timestamp": datetime.now().isoformat()
            }
    
    async def analyze_multiple_coins(self, opportunities: List[Dict]) -> List[Dict]:
        """
        Birden fazla coin için AI analizi yap
        Tarama sonuçlarına dayanarak detaylı analiz yapar
        """
        try:
            self.logger.info(f"Çoklu coin AI analizi başlatılıyor... {len(opportunities)} coin")
            
            results = []
            # En iyi 5 fırsatı analiz et
            top_opportunities = sorted(
                opportunities, 
                key=lambda x: x.get('opportunity_score', 0),
                reverse=True
            )[:5]
            
            for opportunity in top_opportunities:
                symbol = opportunity.get('symbol')
                if not symbol:
                    continue
                    
                self.logger.info(f"AI analizi yapılıyor: {symbol}")
                
                # AI analizi yap
                technical_data = opportunity.copy()
                ai_result = await self.analyze_opportunity(symbol, technical_data)
                
                # Sonuçları birleştir
                result = opportunity.copy()
                result.update({
                    "ai_analysis": ai_result.get('analysis', ''),
                    "ai_recommendation": ai_result.get('recommendation', 'BEKLE'),
                    "fundamental_score": ai_result.get('fundamental_score', 0),
                    "total_score": (opportunity.get('opportunity_score', 0) + 
                                   ai_result.get('fundamental_score', 0)) / 2,
                    "analyzed_at": datetime.now().isoformat()
                })
                
                results.append(result)
                
            self.logger.info(f"Çoklu coin AI analizi tamamlandı: {len(results)} sonuç")
            return results
            
        except Exception as e:
            self.logger.error(f"Çoklu coin AI analizi hatası: {str(e)}")
            traceback.print_exc()
            # Basit sonuçları döndür
            return [{
                "symbol": opp.get('symbol', 'UNKNOWN'),
                "ai_analysis": f"Analiz sırasında hata oluştu",
                "ai_recommendation": "BEKLE",
                "fundamental_score": 0,
                "total_score": opp.get('opportunity_score', 0) / 2,
                "analyzed_at": datetime.now().isoformat()
            } for opp in opportunities[:5]]
    
    def _extract_recommendation(self, analysis_text: str) -> str:
        """
        AI analiz metninden tavsiye çıkar
        """
        # Basit kural tabanlı çıkarım
        analysis_lower = analysis_text.lower()
        
        # Olumlu ifadeler
        positive_patterns = ["güçlü al", "al sinyali", "yükseliş bekleniyor", "long pozisyon", "alım fırsatı"]
        negative_patterns = ["sat sinyali", "düşüş bekleniyor", "short pozisyon", "satış fırsatı", "riskli"]
        
        # Skor hesapla
        positive_score = sum(1 for pattern in positive_patterns if pattern in analysis_lower)
        negative_score = sum(1 for pattern in negative_patterns if pattern in analysis_lower)
        
        # Tavsiye oluştur
        if positive_score > negative_score + 1:
            return "AL"
        elif negative_score > positive_score + 1:
            return "SAT"
        else:
            return "BEKLE"
    
    def _calculate_fundamental_score(self, analysis_text: str) -> float:
        """
        AI analiz metninden temel puan hesapla (0-100 arası)
        """
        # Basit kural tabanlı puanlama
        analysis_lower = analysis_text.lower()
        
        # Olumlu faktörler
        positive_factors = [
            "güçlü temel", "yüksek potansiyel", "büyüme", "yenilikçi", "güçlü ekip",
            "iyi yönetim", "geniş kullanım", "gerçek dünya", "ortaklık", "entegrasyon"
        ]
        
        # Olumsuz faktörler
        negative_factors = [
            "zayıf temel", "düşük potansiyel", "düşüş", "kopya", "zayıf ekip",
            "kötü yönetim", "az kullanım", "spekülasyon", "risk", "rekabet"
        ]
        
        # Temel puan hesapla
        positive_score = sum(3 for factor in positive_factors if factor in analysis_lower) 
        negative_score = sum(3 for factor in negative_factors if factor in analysis_lower)
        
        # Baz puan (50) üzerine ekle veya çıkar
        base_score = 50
        final_score = base_score + positive_score - negative_score
        
        # 0-100 aralığında sınırla
        return max(0, min(100, final_score))
