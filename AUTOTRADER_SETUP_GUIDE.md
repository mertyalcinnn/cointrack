# Otomatik Kaldıraçlı İşlem Sistemi Kurulum Kılavuzu

Otomatik kaldıraçlı işlem sistemi (AutoTrader), AI analizlerini kullanarak Binance vadeli işlemler piyasasında otomatik al-sat yapan bir sistemdir. Bu sistem, AI analizlerini kullanarak en iyi işlem fırsatlarını tespit eder ve belirlenen risk/ödül oranlarına göre pozisyon açıp kapatır. Ayrıca Telegram entegrasyonu sayesinde mobil cihazlarınıza anında bildirimler gönderir.

## Özellikleri

* **AI Destekli Analiz**: Claude AI kullanarak temel analiz skorları üretir
* **Teknik Analiz**: RSI, MACD, EMA20, EMA50 kullanarak teknik sinyaller oluşturur
* **Kaldıraçlı İşlem**: Otomatik kaldıraç ayarı (maksimum 10x)
* **Risk Yönetimi**: Maksimum 4$ zarar, minimum 10$ kar hedefi
* **Çoklu İşlem**: Aynı anda 3 pozisyona kadar takip edebilme
* **İşlem Geçmişi**: Tüm işlemler JSON formatında kaydedilir
* **Telegram Entegrasyonu**: Pozisyon açılış/kapanış bilgileri anında telefonunuza bildirilir

## Kurulum

### 1. Gerekli Kütüphaneler

Otomatik işlem sistemini kullanmak için aşağıdaki kütüphaneleri yüklemeniz gerekmektedir:

```bash
pip install ccxt pandas python-dotenv asyncio python-telegram-bot
```

### 2. API Anahtarları

Binance API anahtarlarınızı `.env` dosyasına ekleyin:

```
BINANCE_API_KEY=sizin_api_anahtarınız
BINANCE_API_SECRET=sizin_api_gizli_anahtarınız
ANTHROPIC_API_KEY=sizin_claude_api_anahtarınız
TELEGRAM_BOT_TOKEN=sizin_telegram_bot_tokeniniz
```

Telegram bot token'ı oluşturmak için:
1. Telegram'da [@BotFather](https://t.me/BotFather) ile konuşun
2. `/newbot` komutunu gönderin ve talimatları izleyin
3. Size verilen API token'ı `.env` dosyasına ekleyin

### 3. Sistem Yapılandırması

Aşağıdaki parametreleri kendi risk profilinize göre ayarlayabilirsiniz (kodun içinde):
* `profit_target_usd`: Kar hedefi ($ cinsinden) - Varsayılan: 10$
* `max_loss_usd`: Maksimum zarar limiti ($ cinsinden) - Varsayılan: 4$
* `position_size_usd`: Her işlem için pozisyon büyüklüğü - Varsayılan: 50$
* `max_leverage`: Maksimum kaldıraç - Varsayılan: 10x
* `min_ai_score`: İşlem açmak için gereken minimum AI skoru - Varsayılan: 70

## Çalıştırma

Sistemi doğrudan başlatmak için aşağıdaki komutu kullanın:

```bash
python autotrader.py
```

Telegram botu üzerinden başlatmak için:

1. Önce Telegram botunu başlatın:
```bash
python run.py
```

2. Telegram'da botunuza şu komutu gönderin:
```
/autoscan
```

3. Durdurmak için:
```
/stopautoscan
```

## Nasıl Çalışır?

1. Sistem 5 dakikada bir piyasayı tarar
2. En yüksek puanlı 3 fırsat içinden işleme uygun olanları seçer
3. AI ve teknik analiz sonuçları uyumlu ise (örn. LONG sinyali ve AL önerisi) işlem açar
4. Her döngüde açık pozisyonlar kontrol edilir
5. Kar hedefine ulaşıldığında veya zarar limitine gelindiğinde pozisyonlar otomatik kapatılır

## Güvenlik Önlemleri

* Sistem sadece belirlenen pozisyon büyüklüğünü kullanır (varsayılan: 50$)
* Her işlem için stop-loss ve take-profit seviyeleri hesaplanır
* Maksimum 3 eşzamanlı işlem açılabilir
* Yetersiz bakiye durumunda işlem açılmaz

## İzleme ve Raporlama

Tüm işlemler hem konsola yazdırılır hem de `autotrader.log` dosyasına kaydedilir. Ayrıca, tüm işlem geçmişi `trade_history.json` dosyasında tutulur.

## Uyarı

Bu sistem finansal tavsiye değildir. Kripto para piyasaları yüksek risk içerir ve kaldıraçlı işlemler bu riski daha da artırır. Sistemi kullanmadan önce risk anlayışınızı değerlendirin ve yalnızca kaybetmeyi göze alabileceğiniz miktarla işlem yapın.

## İşlem Stratejisi Detayları

### Giriş Stratejisi

İşlem girişleri şu kriterlere göre yapılır:
1. AI skoru en az 70 olmalı
2. Teknik sinyali AI önerisiyle uyumlu olmalı:
   * LONG pozisyonlar için: Teknik sinyal "LONG" veya "STRONG_LONG" VE AI önerisi "AL"
   * SHORT pozisyonlar için: Teknik sinyal "SHORT" veya "STRONG_SHORT" VE AI önerisi "SAT"
3. Toplam skor en yüksek olan 3 fırsat değerlendirilir

### Kaldıraç Ayarı

Kaldıraç seviyesi, toplam skora göre dinamik olarak ayarlanır:
* Toplam skor > 85: 10x kaldıraç
* Toplam skor > 75: 7x kaldıraç
* Toplam skor > 65: 5x kaldıraç
* Toplam skor < 65: 3x kaldıraç

### Çıkış Stratejisi

Pozisyonlar şu durumlarda kapatılır:
1. Kar hedefine ulaşıldığında (10$ veya %6 fiyat hareketi)
2. Zarar limitine gelindiğinde (4$ veya %2 ters fiyat hareketi)
3. 24 saat içinde kar/zarar hedeflerine ulaşılmazsa pozisyon otomatik kapatılır
