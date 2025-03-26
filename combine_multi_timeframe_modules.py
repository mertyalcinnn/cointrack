#!/usr/bin/env python3
"""
Bu script, parça halinde yazılmış MultiTimeframeAnalyzer parçalarını birleştirir
"""
import os
import glob

# Parçaları içeren dosyaları bul
part_files = sorted(glob.glob("src/analysis/multi_timeframe_analyzer_part*.py"))
print(f"Found {len(part_files)} part files: {part_files}")

# Birleştirilmiş içeriği oluştur
combined_content = ""

# Dosya başına genel import satırları
imports = """import asyncio
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from io import BytesIO
import ccxt
import mplfinance as mpf
from typing import List, Dict, Optional, Any, Tuple

"""

# Sınıf başlangıcı
class_start = """class MultiTimeframeAnalyzer:
    \"\"\"
    Üç farklı zaman dilimini (1W, 1H, 15M) kullanarak kapsamlı teknik analiz yapan sınıf.
    \"\"\"
    
"""

combined_content += imports + class_start

# Her parçayı oku ve metot içeriklerini ekle
for part_file in part_files:
    with open(part_file, 'r') as f:
        content = f.read()
        
        # Sınıf içindeki metotları çıkar (ilk kelime boşluk+def olanlar)
        lines = content.split('\n')
        method_lines = []
        in_method = False
        
        for line in lines:
            # Yeni bir metot mu başlıyor?
            if line.startswith('    def ') or line.startswith('    async def '):
                in_method = True
                method_lines.append(line)
            # Metot içindeyiz, devam ediyoruz
            elif in_method and (line.startswith('        ') or line.strip() == ''):
                method_lines.append(line)
            # Metot içinde değiliz ve boş satır değil - yeni içerik
            elif not in_method and line.strip() != '':
                # Sınıf tanımı veya import - bunları atla
                if not (line.startswith('class ') or line.startswith('import ') or line.startswith('from ')):
                    in_method = True
                    method_lines.append(line)
        
        # Metotları birleştirilmiş içeriğe ekle
        if method_lines:
            combined_content += '\n'.join(method_lines) + '\n\n'

# Son birleştirilmiş dosyayı oluştur
output_file = "src/analysis/multi_timeframe_analyzer.py"
with open(output_file, 'w') as f:
    f.write(combined_content)

print(f"Combined MultiTimeframeAnalyzer written to {output_file}")
