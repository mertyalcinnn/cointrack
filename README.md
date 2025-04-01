# Crypto Signal Bot

Gelişmiş kripto para analiz, sinyal ve otomatik işlem botu.

## Özellikler

- Çoklu veri kaynağı entegrasyonu
- Duygu analizi
- Teknik analiz
- Telegram bot entegrasyonu
- Web dashboard
- **Otomatik Kaldıraçlı İşlem Sistemi** (Binance Vadeli İşlemler)

## Kurulum

```bash
# Virtual environment oluşturma
python3 -m venv venv
source venv/bin/activate

# Gerekli kütüphanelerin kurulumu
pip install -r requirements.txt
```

## Otomatik Kaldıraçlı İşlem Sistemi

Bu projede yer alan otomatik kaldıraçlı işlem sistemi, Binance vadeli işlemler piyasasında yapay zeka destekli analizler kullanarak alım-satım yapabilir.

**Özellikler:**
- Claude AI entegrasyonu ile temel analiz yapar
- RSI, MACD, EMA gibi göstergeler ile teknik analiz yapar
- Otomatik kaldıraç ayarı (max 10x) ile işlem açar
- Risk yönetimi (stop-loss & take-profit) ile güvenli işlem yapar
- Telegram entegrasyonu ile mobil bildirimler gönderir

**Kullanım:**

Manuel olarak başlatmak için:
```bash
python autotrader.py
```

Telegram bot üzerinden başlatmak için:
```
/autoscan - Otomatik işlem sistemini başlatır
/stopautoscan - Otomatik işlem sistemini durdurur
```

Detaylı bilgi için [AUTOTRADER_SETUP_GUIDE.md](AUTOTRADER_SETUP_GUIDE.md) kılavuzunu inceleyin.
