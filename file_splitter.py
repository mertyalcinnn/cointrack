#!/usr/bin/env python3
# chmod +x file_splitter.py  # Bu komutu çalıştırarak scripti çalıştırılabilir hale getirebilirsiniz
"""
Dosya Bölme ve Birleştirme Aracı

Bu script büyük dosyaları parçalara bölebilir ve bölünmüş dosyaları tekrar birleştirebilir.
Özellikle boyut sınırlamaları olan sistemlerde veya büyük dosyaları düzenlemek için kullanışlıdır.

Kullanımı:
    Bölme:     python file_splitter.py split <dosya_yolu> <maks_satır_sayısı>
    Birleştirme: python file_splitter.py merge <bölünmüş_dosya_prefix>
"""

import sys
import os
import glob
import re

def split_file(file_path, max_lines):
    """
    Bir dosyayı belirtilen satır sayısına göre parçalara böler.
    
    Args:
        file_path (str): Bölünecek dosyanın yolu
        max_lines (int): Her parçadaki maksimum satır sayısı
    """
    if not os.path.exists(file_path):
        print(f"Hata: {file_path} bulunamadı.")
        return False
    
    try:
        max_lines = int(max_lines)
        if max_lines < 1:
            print("Hata: Satır sayısı pozitif bir tamsayı olmalıdır.")
            return False
    except ValueError:
        print("Hata: Satır sayısı bir sayı olmalıdır.")
        return False
    
    # Dosya adını ve uzantısını ayır
    base_name = os.path.basename(file_path)
    file_name, file_ext = os.path.splitext(base_name)
    dir_path = os.path.dirname(file_path)
    
    # Dosyayı oku ve satır sayısını hesapla
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    total_lines = len(lines)
    num_parts = (total_lines + max_lines - 1) // max_lines  # Yukarı yuvarlama
    
    print(f"Dosya: {file_path}")
    print(f"Toplam satır sayısı: {total_lines}")
    print(f"Her parçada maksimum {max_lines} satır")
    print(f"Oluşturulacak parça sayısı: {num_parts}")
    
    # Dosyayı parçalara böl ve yaz
    for i in range(num_parts):
        start_line = i * max_lines
        end_line = min((i + 1) * max_lines, total_lines)
        
        # Parça dosyası adını oluştur: example_part1.py, example_part2.py, ...
        part_file_name = f"{file_name}_part{i+1}{file_ext}"
        part_file_path = os.path.join(dir_path, part_file_name)
        
        with open(part_file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines[start_line:end_line])
        
        print(f"Parça {i+1}/{num_parts} oluşturuldu: {part_file_name} ({end_line - start_line} satır)")
    
    print(f"\n✓ Bölme işlemi tamamlandı. Toplam {num_parts} parça oluşturuldu.")
    return True

def merge_files(file_prefix):
    """
    Bölünmüş dosyaları birleştirir.
    
    Args:
        file_prefix (str): Parça dosyalarının ortak prefix'i 
                          (örn: "/dosya/yolu/example_part" -> "/dosya/yolu/example_part1.py" gibi dosyaları arar)
    """
    # Prefix'i dosya yolu ve isim parçalarına ayır
    dir_path = os.path.dirname(file_prefix)
    if not dir_path:
        dir_path = '.'
    
    base_prefix = os.path.basename(file_prefix)
    
    # Regex kalıbı oluştur - örn: "example_part1.py", "example_part2.py" gibi
    pattern = re.compile(f"{re.escape(base_prefix)}(\\d+)(\\..+)?$")
    
    # Eşleşen dosyaları bul
    part_files = []
    for file in os.listdir(dir_path):
        match = pattern.match(file)
        if match:
            part_number = int(match.group(1))
            file_extension = match.group(2) or ""
            part_files.append((part_number, os.path.join(dir_path, file), file_extension))
    
    if not part_files:
        print(f"Hata: '{file_prefix}' ile başlayan parça dosyası bulunamadı.")
        return False
    
    # Parça numarasına göre sırala
    part_files.sort(key=lambda x: x[0])
    
    print(f"Birleştirilecek dosya sayısı: {len(part_files)}")
    for part_num, file_path, _ in part_files:
        print(f"Parça {part_num}: {os.path.basename(file_path)}")
    
    # İlk dosyanın uzantısını al
    _, _, file_extension = part_files[0]
    
    # Birleştirilmiş dosya adını oluştur
    merged_file_path = f"{file_prefix}_merged{file_extension}"
    
    # Tüm parça dosyalarını birleştir
    with open(merged_file_path, 'w', encoding='utf-8') as outfile:
        for _, file_path, _ in part_files:
            with open(file_path, 'r', encoding='utf-8') as infile:
                outfile.write(infile.read())
    
    print(f"\n✓ Birleştirme işlemi tamamlandı: {merged_file_path}")
    return True

def print_usage():
    """Kullanım bilgisini gösterir"""
    print("Kullanım:")
    print("  Bölme:       python file_splitter.py split <dosya_yolu> <maks_satır_sayısı>")
    print("  Birleştirme: python file_splitter.py merge <bölünmüş_dosya_prefix>")
    print("\nÖrnekler:")
    print("  python file_splitter.py split büyük_dosya.py 1000")
    print("  python file_splitter.py merge büyük_dosya_part")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "split" and len(sys.argv) == 4:
        split_file(sys.argv[2], sys.argv[3])
    elif command == "merge" and len(sys.argv) == 3:
        merge_files(sys.argv[2])
    else:
        print("Hata: Geçersiz komut veya eksik parametreler.")
        print_usage()
        sys.exit(1)
