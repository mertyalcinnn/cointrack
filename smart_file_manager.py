#!/usr/bin/env python3
# chmod +x smart_file_manager.py  # Bu komutu çalıştırarak scripti çalıştırılabilir hale getirebilirsiniz
"""
Akıllı Dosya Yönetim Aracı

Bu script, özellikle büyük kod dosyaları için geliştirilmiş bir dosya yönetim aracıdır.
Dosyaları sınıf, metod veya mantıksal yapılara göre akıllıca bölerek yönetim kolaylığı sağlar.

Özellikleri:
- Dosyayı parçalara bölme (sınıf veya fonksiyon sınırlarını koruyarak)
- Parçaları birleştirme
- Parçaları tamir etme (indent hatalarını otomatik düzeltme)
- Parçalı çalışma modu (büyük dosyaları düzenlemek için)

Kullanımı:
    python smart_file_manager.py split <dosya_yolu> [--parts <parça_sayısı>] [--smart]
    python smart_file_manager.py merge <ana_dosya_yolu> <parça_dizini>
    python smart_file_manager.py fix <dosya_yolu>
"""

import sys
import os
import re
import shutil
import glob
import argparse
import tempfile
from datetime import datetime

def fix_indentation(file_path):
    """
    Dosyadaki indentation hatalarını düzeltir
    
    Args:
        file_path (str): Düzeltilecek dosyanın yolu
    
    Returns:
        bool: Başarı durumu
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Python dosyasını geçici bir dosyaya yazıp, Python'a düzelttirelim
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.py')
        temp_file.close()
        
        with open(temp_file.name, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # black veya yapf gibi kod formatlayıcıları kullanabilirsiniz
        # Burada basit bir yaklaşım kullanıyoruz
        try:
            import black
            try:
                black.format_file_in_place(
                    temp_file.name, 
                    fast=False, 
                    mode=black.FileMode()
                )
                with open(temp_file.name, 'r', encoding='utf-8') as f:
                    formatted_content = f.read()
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(formatted_content)
                
                print(f"✓ {file_path} dosyası black ile düzeltildi.")
                return True
            except Exception as e:
                print(f"Black ile düzeltme yapılamadı: {e}")
        except ImportError:
            print("Black paketini bulamadım, manuel düzeltme deniyorum...")
        
        # Manuel düzeltme yöntemi
        # Python'ın sözdizimini kontrol edelim
        import py_compile
        try:
            py_compile.compile(temp_file.name, doraise=True)
            print(f"✓ {file_path} dosyasında sözdizimi hatası bulunamadı.")
        except py_compile.PyCompileError as e:
            print(f"⚠️ Dosyada sözdizimi hatası var: {e}")
            # Buraya daha gelişmiş düzeltme algoritmaları eklenebilir
            return False
        
        return True
    except Exception as e:
        print(f"Hata: {e}")
        return False
    finally:
        # Geçici dosyayı temizle
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)

def find_class_boundaries(content):
    """
    Python dosyasındaki sınıf tanımlarını bulur
    
    Args:
        content (str): Dosya içeriği
    
    Returns:
        list: [(sınıf_adı, başlangıç_satırı, bitiş_satırı), ...] biçiminde liste
    """
    lines = content.split('\n')
    class_pattern = re.compile(r'^\s*class\s+(\w+)')
    
    classes = []
    current_class = None
    start_line = None
    
    for i, line in enumerate(lines):
        match = class_pattern.match(line)
        
        if match and not current_class:  # Yeni sınıf başlangıcı
            current_class = match.group(1)
            start_line = i
        elif match and current_class:  # Yeni sınıf, önceki bitti
            classes.append((current_class, start_line, i - 1))
            current_class = match.group(1)
            start_line = i
        elif i == len(lines) - 1 and current_class:  # Dosya sonu
            classes.append((current_class, start_line, i))
    
    return classes

def find_function_boundaries(content):
    """
    Python dosyasındaki fonksiyon tanımlarını bulur (sınıfın dışında)
    
    Args:
        content (str): Dosya içeriği
    
    Returns:
        list: [(fonksiyon_adı, başlangıç_satırı, bitiş_satırı), ...] biçiminde liste
    """
    lines = content.split('\n')
    function_pattern = re.compile(r'^\s*def\s+(\w+)')
    class_pattern = re.compile(r'^\s*class\s+(\w+)')
    
    functions = []
    current_function = None
    start_line = None
    in_class = False
    
    for i, line in enumerate(lines):
        class_match = class_pattern.match(line)
        if class_match:
            in_class = True
            continue
        
        if in_class and line.strip() == '':
            in_class = False  # Sınıf tanımı bitti (basit yaklaşım)
        
        if in_class:
            continue  # Sınıf içindeki metodları atla
        
        match = function_pattern.match(line)
        
        if match and not current_function:  # Yeni fonksiyon başlangıcı
            current_function = match.group(1)
            start_line = i
        elif match and current_function:  # Yeni fonksiyon, önceki bitti
            functions.append((current_function, start_line, i - 1))
            current_function = match.group(1)
            start_line = i
        elif (i == len(lines) - 1 or class_pattern.match(lines[i+1] if i+1 < len(lines) else '')) and current_function:
            # Dosya sonu veya yeni sınıf başlangıcı
            functions.append((current_function, start_line, i))
            current_function = None
    
    return functions

def split_file_smart(file_path, num_parts=None):
    """
    Dosyayı sınıf ve fonksiyon sınırlarını koruyarak akıllı bir şekilde böler
    
    Args:
        file_path (str): Bölünecek dosyanın yolu
        num_parts (int, optional): İstenilen parça sayısı
    
    Returns:
        bool: İşlem başarılı mı
    """
    if not os.path.exists(file_path):
        print(f"Hata: {file_path} bulunamadı.")
        return False
    
    # Dosya adını ve uzantısını ayır
    base_name = os.path.basename(file_path)
    file_name, file_ext = os.path.splitext(base_name)
    dir_path = os.path.dirname(file_path)
    
    # Dosya içeriğini oku
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    total_lines = len(lines)
    
    # Sınıf ve fonksiyon sınırlarını bul
    classes = find_class_boundaries(content)
    functions = find_function_boundaries(content)
    
    # İçe aktarma (import) kısmını bul
    imports_end = 0
    for i, line in enumerate(lines):
        if line.startswith(('import ', 'from ')) or line.strip() == '':
            imports_end = i
        elif not line.startswith(('#', '"', "'")) and line.strip():
            break
    
    # Bölümleri oluştur
    sections = []
    
    # İçe aktarma kısmını ekle
    if imports_end > 0:
        sections.append(('imports', 0, imports_end))
    
    # Sınıf dışındaki fonksiyonları ekle
    for name, start, end in functions:
        sections.append((f"function_{name}", start, end))
    
    # Sınıfları ekle
    for name, start, end in classes:
        sections.append((f"class_{name}", start, end))
    
    # Kalan kısımları ekle
    last_end = max([end for _, _, end in sections]) if sections else 0
    if last_end < total_lines - 1:
        sections.append(('remaining', last_end + 1, total_lines - 1))
    
    # Sections'ları sırala
    sections.sort(key=lambda x: x[1])
    
    # İstenen parça sayısı belirtilmişse, sections'ları grupla
    if num_parts and num_parts > 0:
        grouped_sections = []
        sections_per_part = max(1, len(sections) // num_parts)
        
        for i in range(0, len(sections), sections_per_part):
            group = sections[i:i+sections_per_part]
            if group:
                name = f"part{len(grouped_sections)+1}"
                start = group[0][1]
                end = group[-1][2]
                grouped_sections.append((name, start, end))
        
        sections = grouped_sections
    
    # Sections'ları dosyalara yaz
    for i, (name, start, end) in enumerate(sections):
        part_file_name = f"{file_name}_{name}{file_ext}"
        part_file_path = os.path.join(dir_path, part_file_name)
        
        with open(part_file_path, 'w', encoding='utf-8') as f:
            f.writelines(line + '\n' for line in lines[start:end+1])
        
        print(f"Parça {i+1}/{len(sections)} oluşturuldu: {part_file_name} ({end - start + 1} satır)")
    
    # İndex dosyası oluştur
    index_file_path = os.path.join(dir_path, f"{file_name}_index.txt")
    with open(index_file_path, 'w', encoding='utf-8') as f:
        f.write(f"Orijinal dosya: {file_path}\n")
        f.write(f"Bölünme tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Toplam satır sayısı: {total_lines}\n\n")
        f.write("Parçalar:\n")
        
        for i, (name, start, end) in enumerate(sections):
            part_file_name = f"{file_name}_{name}{file_ext}"
            f.write(f"{i+1}. {part_file_name} (Satır {start+1}-{end+1})\n")
    
    print(f"\n✓ Bölme işlemi tamamlandı. Toplam {len(sections)} parça oluşturuldu.")
    print(f"İndex dosyası: {index_file_path}")
    return True

def split_file_by_size(file_path, num_parts):
    """
    Dosyayı belirtilen parça sayısına göre böler
    
    Args:
        file_path (str): Bölünecek dosyanın yolu
        num_parts (int): Parça sayısı
    
    Returns:
        bool: İşlem başarılı mı
    """
    if not os.path.exists(file_path):
        print(f"Hata: {file_path} bulunamadı.")
        return False
    
    try:
        num_parts = int(num_parts)
        if num_parts < 1:
            print("Hata: Parça sayısı pozitif bir tamsayı olmalıdır.")
            return False
    except ValueError:
        print("Hata: Parça sayısı bir sayı olmalıdır.")
        return False
    
    # Dosya adını ve uzantısını ayır
    base_name = os.path.basename(file_path)
    file_name, file_ext = os.path.splitext(base_name)
    dir_path = os.path.dirname(file_path)
    
    # Dosyayı oku ve satır sayısını hesapla
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    total_lines = len(lines)
    lines_per_part = total_lines // num_parts
    
    print(f"Dosya: {file_path}")
    print(f"Toplam satır sayısı: {total_lines}")
    print(f"Parça sayısı: {num_parts}")
    print(f"Her parçada yaklaşık {lines_per_part} satır")
    
    # Dosyayı parçalara böl ve yaz
    for i in range(num_parts):
        start_line = i * lines_per_part
        end_line = (i + 1) * lines_per_part if i < num_parts - 1 else total_lines
        
        # Parça dosyası adını oluştur: example_part1.py, example_part2.py, ...
        part_file_name = f"{file_name}_part{i+1}{file_ext}"
        part_file_path = os.path.join(dir_path, part_file_name)
        
        with open(part_file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines[start_line:end_line])
        
        print(f"Parça {i+1}/{num_parts} oluşturuldu: {part_file_name} ({end_line - start_line} satır)")
    
    print(f"\n✓ Bölme işlemi tamamlandı. Toplam {num_parts} parça oluşturuldu.")
    return True

def merge_files(main_file_path, parts_dir=None):
    """
    Parça dosyalarını birleştirerek ana dosyayı oluşturur
    
    Args:
        main_file_path (str): Oluşturulacak ana dosyanın yolu
        parts_dir (str, optional): Parça dosyalarının bulunduğu dizin
    
    Returns:
        bool: İşlem başarılı mı
    """
    # Ana dosya adını ve uzantısını ayır
    base_name = os.path.basename(main_file_path)
    file_name, file_ext = os.path.splitext(base_name)
    
    # Parça dosyalarının dizinini belirle
    if not parts_dir:
        parts_dir = os.path.dirname(main_file_path)
    
    # İndex dosyasını kontrol et
    index_file_path = os.path.join(parts_dir, f"{file_name}_index.txt")
    parts_order = []
    
    if os.path.exists(index_file_path):
        print(f"İndex dosyası bulundu: {index_file_path}")
        # İndex dosyasından parça sırasını oku
        with open(index_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith(('#', 'Orijinal', 'Bölünme', 'Toplam', 'Parçalar:')):
                    continue
                match = re.search(r'(\d+)\. (.*?) \(', line)
                if match:
                    part_num = int(match.group(1))
                    part_file = match.group(2)
                    parts_order.append((part_num, os.path.join(parts_dir, part_file)))
    
    # Eğer index dosyası yoksa veya okunamazsa, dosya adından pattern oluştur
    if not parts_order:
        print("İndex dosyası bulunamadı, dosya adı kalıbına göre parçalar aranıyor...")
        # Bu regex dosya adının başında file_name_ ile başlayan ve sonunda file_ext ile biten tüm dosyaları bulur
        parts_pattern = os.path.join(parts_dir, f"{file_name}_*{file_ext}")
        part_files = glob.glob(parts_pattern)
        
        # Parça numarasına göre sırala
        number_pattern = re.compile(r'part(\d+)')
        
        for file_path in part_files:
            file_basename = os.path.basename(file_path)
            match = number_pattern.search(file_basename)
            if match:
                part_num = int(match.group(1))
                parts_order.append((part_num, file_path))
            else:
                # Eğer part numarası bulunamazsa, alfabetik sıraya göre ekle
                # Bu import, class, function gibi bölümleri doğru sırada birleştirmek için
                order_value = 0
                if "imports" in file_basename:
                    order_value = -1  # İmportlar en başta olsun
                elif "class" in file_basename:
                    order_value = 100 + ord(file_basename[0])  # Sınıflar sonra
                elif "function" in file_basename:
                    order_value = 200 + ord(file_basename[0])  # Fonksiyonlar en sonda
                else:
                    order_value = 300 + ord(file_basename[0])  # Diğerleri
                
                parts_order.append((order_value, file_path))
    
    # Parçaları sırala
    parts_order.sort(key=lambda x: x[0])
    
    if not parts_order:
        print(f"Hata: '{file_name}_*{file_ext}' kalıbına uyan parça dosyası bulunamadı.")
        return False
    
    print(f"Birleştirilecek dosya sayısı: {len(parts_order)}")
    for i, (part_num, file_path) in enumerate(parts_order):
        print(f"Parça {i+1}: {os.path.basename(file_path)}")
    
    # Parçaları birleştir
    with open(main_file_path, 'w', encoding='utf-8') as outfile:
        for _, file_path in parts_order:
            with open(file_path, 'r', encoding='utf-8') as infile:
                content = infile.read()
                outfile.write(content)
                # Dosya sonunda yeni satır yoksa ekle
                if content and not content.endswith('\n'):
                    outfile.write('\n')
    
    print(f"\n✓ Birleştirme işlemi tamamlandı: {main_file_path}")
    
    # Dosyayı formatlayarak düzelt
    print("Birleştirilmiş dosyayı düzeltme denetimi yapılıyor...")
    fix_indentation(main_file_path)
    
    return True

def main():
    parser = argparse.ArgumentParser(description='Akıllı Dosya Yönetim Aracı')
    subparsers = parser.add_subparsers(dest='command', help='Komut')
    
    # split komutu
    split_parser = subparsers.add_parser('split', help='Dosyayı parçalara böl')
    split_parser.add_argument('file_path', help='Bölünecek dosyanın yolu')
    split_parser.add_argument('--parts', type=int, help='Parça sayısı')
    split_parser.add_argument('--smart', action='store_true', help='Akıllı bölme (sınıf ve fonksiyon yapılarını koru)')
    
    # merge komutu
    merge_parser = subparsers.add_parser('merge', help='Parçaları birleştir')
    merge_parser.add_argument('main_file', help='Oluşturulacak ana dosyanın yolu')
    merge_parser.add_argument('parts_dir', nargs='?', help='Parça dosyalarının dizini (belirtilmezse ana dosya dizini kullanılır)')
    
    # fix komutu
    fix_parser = subparsers.add_parser('fix', help='Dosyayı düzelt (indentation hatalarını gider)')
    fix_parser.add_argument('file_path', help='Düzeltilecek dosyanın yolu')
    
    args = parser.parse_args()
    
    if args.command == 'split':
        if args.smart:
            split_file_smart(args.file_path, args.parts)
        else:
            split_file_by_size(args.file_path, args.parts or 2)
    elif args.command == 'merge':
        merge_files(args.main_file, args.parts_dir)
    elif args.command == 'fix':
        fix_indentation(args.file_path)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
