#!/usr/bin/env python3
# chmod +x fix_ai_analyzer.py  # Bu komutu çalıştırarak scripti çalıştırılabilir hale getirebilirsiniz
"""
AI Analyzer Düzeltme Aracı

Bu script, src/analysis/ai_analyzer.py dosyasındaki indentation hatasını düzeltir.
"""

import os
import re
import sys

def fix_ai_analyzer():
    file_path = "src/analysis/ai_analyzer.py"
    
    if not os.path.exists(file_path):
        print(f"Hata: {file_path} dosyası bulunamadı!")
        return False
    
    # Dosyayı yedekle
    backup_path = f"{file_path}.bak"
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✓ Yedek oluşturuldu: {backup_path}")
    except Exception as e:
        print(f"Yedekleme hatası: {e}")
        return False
    
    # Yeni içeriği oluştur
    try:
        print("AI Analyzer dosyası düzeltiliyor...")
        
        # Antropic importları ve temel sınıf yapısını ekle
        fixed_content = """from anthropic import Anthropic, AnthropicError
import asyncio
import logging
from typing import Dict, List
import os
import json
import traceback
from datetime import datetime
import re

# Web araştırma entegrasyonu
from src.web_research import WebResearcher

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
"""

        # Orijinal dosyadan sınıf yöntemlerini çıkar
        # ve düzgün şekilde biçimlendir
        lines = content.split('\n')
        methods_content = ""
        method_started = False
        current_method = []
        
        for line in lines:
            if line.strip().startswith("def ") and not method_started:
                # Yeni method başlangıcı
                method_started = True
                current_method = [line]
            elif method_started:
                # Metod içindeyiz
                current_method.append(line)
                # Metodun sonuna geldiğimizi kontrol et
                if not line.strip() and not any(l.strip().startswith(("def ", "class ")) for l in current_method[-5:]):
                    # Metod bitmiş, sınıfa ekle
                    methods_content += "\n    " + "\n    ".join([l.strip() for l in current_method]) + "\n"
                    method_started = False
                    current_method = []
        
        # Sınıf metotlarını ekle
        fixed_content += methods_content
        
        # Dosyayı yaz
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        
        print(f"✓ {file_path} dosyası başarıyla düzeltildi!")
        
        # Python syntax kontrolü yap
        try:
            import py_compile
            py_compile.compile(file_path, doraise=True)
            print("✓ Python sözdizimi kontrolü başarılı!")
            return True
        except py_compile.PyCompileError as e:
            print(f"⚠️ Düzeltme sonrası hala sözdizimi hatası var: {e}")
            # Orijinal dosyayı geri yükle
            with open(backup_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            print("! Orijinal dosya geri yüklendi.")
            return False
        
    except Exception as e:
        print(f"Düzeltme hatası: {e}")
        # Hata durumunda orijinal dosyayı geri yükle
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            print("! Orijinal dosya geri yüklendi.")
        except:
            print("! Orijinal dosya geri yüklenemedi!")
        
        return False

def fix_manually():
    """Daha basit bir manuel düzeltme"""
    file_path = "src/analysis/ai_analyzer.py"
    print(f"Manuel düzeltme deneniyor: {file_path}")
    
    try:
        # Düzeltilmiş içerik - sadece temel yapı ve sorunlu metot
        fixed_content = """from anthropic import Anthropic, AnthropicError
import asyncio
import logging
from typing import Dict, List
import os
import json
import traceback
from datetime import datetime
import re

# Web araştırma entegrasyonu
from src.web_research import WebResearcher

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
    
    def generate_ai_prompt(self, symbol: str, technical_data: Dict, web_research_data: Dict) -> str:
        \"\"\"
        AI analizi için prompt oluştur
        \"\"\"
        prompt = f\"\"\"
        {symbol} için teknik ve temel analiz:
        
        Teknik Göstergeler:
        {self._format_technical_data(technical_data)}
        
        Piyasa Araştırması:
        {self._format_research_data(web_research_data)}
        
        Lütfen yukarıdaki verileri analiz ederek:
        1. Mevcut trend durumu
        2. Olası destek ve direnç seviyeleri
        3. Kısa vadeli (15dk-1s) ve orta vadeli (4s-1g) beklentiler
        4. Risk/ödül oranı ve stop/hedef önerileri
        5. Dikkat edilmesi gereken önemli noktalar
        
        başlıkları altında detaylı bir analiz yapınız.
        \"\"\"
        return prompt
    
    def _format_technical_data(self, data: Dict) -> str:
        \"\"\"
        Teknik verileri formatla
        \"\"\"
        return "\\n".join([
            f"- {key}: {value}"
            for key, value in data.items()
        ])
    
    def _format_research_data(self, data: Dict) -> str:
        \"\"\"
        Araştırma verilerini formatla
        \"\"\"
        return "\\n".join([
            f"- {key}: {value}"
            for key, value in data.items()
        ])
"""
        
        # Dosyayı yaz
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        
        print(f"✓ {file_path} dosyası temel yapısı düzeltildi.")
        return True
        
    except Exception as e:
        print(f"Manuel düzeltme hatası: {e}")
        return False

if __name__ == "__main__":
    print("AI Analyzer düzeltme aracı çalıştırılıyor...")
    
    if not fix_ai_analyzer():
        print("\nGelişmiş düzeltme başarısız oldu, temel düzeltme deneniyor...")
        if fix_manually():
            print("✓ Temel düzeltme başarılı!")
            print("\nUyarı: Düzeltilen dosya sadece temel yapıya sahip ve eksik metodlar içerebilir.")
            print("Lütfen manuel olarak kontrol edip tamamlayın.")
        else:
            print("❌ Tüm düzeltme denemeleri başarısız oldu!")
            sys.exit(1)
    
    print("\nAI Analyzer düzeltme işlemi tamamlandı!")
    print(f"Dosya: src/analysis/ai_analyzer.py")
