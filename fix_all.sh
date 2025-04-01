#!/bin/bash
# chmod +x fix_all.sh  # Bu komutu çalıştırarak scripti çalıştırılabilir hale getirebilirsiniz
# Bu script, AI Analyzer dosyasındaki hatayı düzeltmek için hazırlanmıştır

# Renk tanımları
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===== Crypto Signal Bot Hata Düzeltme Aracı =====${NC}"
echo -e "${YELLOW}Bu script, ai_analyzer.py dosyasındaki indentation hatasını düzeltir.${NC}"
echo ""

# Dosyanın varlığını kontrol et
if [ ! -f "src/analysis/ai_analyzer.py" ]; then
    echo -e "${RED}HATA: src/analysis/ai_analyzer.py dosyası bulunamadı!${NC}"
    echo "Script'in doğru dizinde çalıştırıldığından emin olun."
    exit 1
fi

# Yedek oluştur
echo "Orijinal dosya yedekleniyor..."
cp src/analysis/ai_analyzer.py src/analysis/ai_analyzer.py.backup
echo -e "${GREEN}✓ Yedek oluşturuldu: src/analysis/ai_analyzer.py.backup${NC}"
echo ""

# Çözüm yöntemini seç
echo -e "${YELLOW}Lütfen kullanmak istediğiniz çözüm yöntemini seçin:${NC}"
echo "1) Hızlı ve Basit Çözüm (direct_fix.py)"
echo "2) Orta Seviye Çözüm (quick_fix.py)"
echo "3) Gelişmiş Çözüm (fix_ai_analyzer.py)"
echo "4) Tüm yöntemleri dene (birisi çalışana kadar)"
echo ""
read -p "Seçiminiz (1-4): " choice

case $choice in
    1)
        echo "Hızlı ve Basit Çözüm uygulanıyor..."
        python3 direct_fix.py
        ;;
    2)
        echo "Orta Seviye Çözüm uygulanıyor..."
        python3 quick_fix.py
        ;;
    3)
        echo "Gelişmiş Çözüm uygulanıyor..."
        python3 fix_ai_analyzer.py
        ;;
    4)
        echo "Tüm yöntemler deneniyor..."
        echo -e "${YELLOW}1. Hızlı ve Basit Çözüm...${NC}"
        if python3 direct_fix.py; then
            echo -e "${GREEN}✓ Hızlı çözüm başarılı!${NC}"
        else
            echo -e "${YELLOW}Hızlı çözüm başarısız, orta seviye çözüm deneniyor...${NC}"
            if python3 quick_fix.py; then
                echo -e "${GREEN}✓ Orta seviye çözüm başarılı!${NC}"
            else
                echo -e "${YELLOW}Orta seviye çözüm başarısız, gelişmiş çözüm deneniyor...${NC}"
                if python3 fix_ai_analyzer.py; then
                    echo -e "${GREEN}✓ Gelişmiş çözüm başarılı!${NC}"
                else
                    echo -e "${RED}❌ Tüm çözüm yöntemleri başarısız oldu!${NC}"
                    echo "Lütfen README_HATA_COZUMU.md dosyasını okuyun ve manuel düzeltme yapın."
                    exit 1
                fi
            fi
        fi
        ;;
    *)
        echo -e "${RED}Geçersiz seçim!${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${YELLOW}Düzeltilen dosyayı test ediyoruz...${NC}"

# Python sözdizimi kontrolü
if python3 -m py_compile src/analysis/ai_analyzer.py 2>/dev/null; then
    echo -e "${GREEN}✓ Python sözdizimi kontrolü başarılı!${NC}"
    echo -e "${GREEN}✓ ai_analyzer.py dosyası başarıyla düzeltildi!${NC}"
    
    echo ""
    echo -e "${BLUE}Bir sonraki adımlar:${NC}"
    echo "1. Telegram botunu çalıştırmayı deneyin:"
    echo "   python3 -m src.bot.telegram_bot"
    echo ""
    echo "2. Hala sorun yaşıyorsanız, README_HATA_COZUMU.md dosyasını inceleyin."
    echo ""
    echo -e "${YELLOW}Not: Herhangi bir sorun olursa, yedek dosyayı geri yükleyebilirsiniz:${NC}"
    echo "mv src/analysis/ai_analyzer.py.backup src/analysis/ai_analyzer.py"
else
    echo -e "${RED}❌ Düzeltme sonrası hala sözdizimi hatası var!${NC}"
    echo "Orijinal dosya geri yükleniyor..."
    cp src/analysis/ai_analyzer.py.backup src/analysis/ai_analyzer.py
    echo -e "${YELLOW}Lütfen README_HATA_COZUMU.md dosyasını okuyun ve manuel düzeltme yapın.${NC}"
    exit 1
fi
