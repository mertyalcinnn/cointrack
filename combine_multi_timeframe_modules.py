#!/usr/bin/env python3
"""
Multi Timeframe Analyzer modüllerini birleştiren script
"""

import os
import glob

def combine_module_files():
    # Tüm parça dosyalarını bul
    base_path = "src/analysis"
    part_files = sorted(glob.glob(f"{base_path}/multi_timeframe_analyzer_part*.py"))
    
    if not part_files:
        print("Birleştirilecek dosya bulunamadı!")
        return False
    
    # Birleştirilmiş içerik
    combined_content = ""
    
    # Her parça dosyasını oku ve birleştir
    print(f"Toplam {len(part_files)} parça dosyası birleştiriliyor...")
    
    for i, part_file in enumerate(part_files):
        print(f"Dosya işleniyor: {part_file}")
        with open(part_file, 'r') as f:
            content = f.read()
            
            # İlk dosya için tüm içeriği al
            if i == 0:
                combined_content += content
            else:
                # Sonraki dosyalar için sınıf tanımlarını ve import kısımlarını atla
                lines = content.strip().split('\n')
                found_method = False
                for line in lines:
                    if line.startswith('    def ') or line.startswith('    async def '):
                        found_method = True
                    
                    if found_method:
                        combined_content += line + '\n'
    
    # Çıktı dosyasını yaz
    output_file = f"{base_path}/multi_timeframe_analyzer.py"
    with open(output_file, 'w') as f:
        f.write(combined_content)
    
    print(f"Birleştirme tamamlandı: {output_file}")
    return True

if __name__ == "__main__":
    if combine_module_files():
        print("İşlem başarılı!")
    else:
        print("İşlem başarısız!")
