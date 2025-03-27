#!/usr/bin/env python3
"""
Multi Timeframe Handler modül parçalarını birleştiren script
"""

import os

def combine_handler_files():
    # Parça dosyalarını tanımla
    base_path = "src/bot"
    part1_file = f"{base_path}/multi_timeframe_handler.py"
    part2_file = f"{base_path}/multi_timeframe_handler_p2.py"
    output_file = f"{base_path}/multi_timeframe_handler_new.py"
    
    # Dosyaların varlığını kontrol et
    if not os.path.exists(part1_file):
        print(f"Birinci parça dosyası bulunamadı: {part1_file}")
        return False
        
    if not os.path.exists(part2_file):
        print(f"İkinci parça dosyası bulunamadı: {part2_file}")
        return False
    
    # Dosyaları oku
    with open(part1_file, 'r') as f1:
        content1 = f1.read().rstrip()
    
    with open(part2_file, 'r') as f2:
        content2 = f2.read()
    
    # İçerikleri birleştir
    combined_content = content1 + "\n" + content2
    
    # Yeni dosyayı yaz
    with open(output_file, 'w') as f_out:
        f_out.write(combined_content)
    
    print(f"Handler dosyası başarıyla birleştirildi: {output_file}")
    
    # Başarıyla birleştirildiyse eski dosyayı yeni dosyayla değiştir
    os.replace(output_file, part1_file)
    print(f"Yeni dosya orijinal konuma taşındı: {part1_file}")
    
    return True

if __name__ == "__main__":
    if combine_handler_files():
        print("İşlem başarılı!")
    else:
        print("İşlem başarısız!")
