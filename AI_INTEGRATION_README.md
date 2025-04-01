# AI Analiz Entegrasyonu Kullanım Kılavuzu

## Genel Bakış

Bu entegrasyon, teknik analiz sonuçlarınızı Claude AI ile destekleyerek daha kapsamlı bir kripto para analizi sunmaktadır. Sistem, teknik göstergeleri kullanarak yaptığı analizlere ek olarak temel verileri, haberleri ve topluluk bilgilerini de değerlendirip daha bütünsel bir yaklaşım sunmaktadır.

## Kurulum

1. Anthropic API anahtarı almanız gerekmektedir. [Anthropic API websitesinden](https://console.anthropic.com/) bir anahtar edinebilirsiniz.

2. API anahtarınızı `.env` dosyasına ekleyin:
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
   ```

3. Tüm gerekliliklerin yüklü olduğundan emin olun:
   ```
   pip install anthropic==0.5.0
   ```

## Kullanım

Telegram botunuzda iki yeni komut eklenmiştir:

### 1. `/aianalysis SEMBOL`

Belirtilen sembol için detaylı bir teknik ve temel analiz sunar. Örneğin:
```
/aianalysis BTCUSDT
```

### 2. Mevcut tarama sonuçlarını AI ile analiz etme

Herhangi bir sembol belirtmeden kullanıldığında, son tarama sonuçlarındaki en iyi 5 fırsatı AI analizi ile değerlendirip sunar:
```
/aianalysis
```

## Nasıl Çalışır?

1. Sistem önce teknik analiz yapar veya mevcut tarama sonuçlarını kullanır
2. Bu teknik verileri Anthropic API'ye gönderir
3. Claude AI mevcut teknik veriler ışığında, kripto paranın temel özelliklerini, haberlerini ve topluluk bilgilerini değerlendirerek bir analiz sunar
4. Sonuçlar formatlanıp kullanıcıya gönderilir

## Özellikler

- **Teknik + Temel Analiz**: Her iki analiz yöntemini bir araya getirerek daha kapsamlı bir değerlendirme sunar
- **100 üzerinden puanlama**: Hem teknik hem de temel analiz 100 üzerinden puanlanır, toplam puan ikisinin ortalamasıdır
- **Detaylı analiz raporu**: Claude AI'nin sunduğu detaylı ve gerekçelendirilmiş rapor
- **Önbellek mekanizması**: Aynı sembol için sürekli API çağrısı yapmamak için 24 saatlik önbellek sistemi

## Not

- AI analizi gerçek zamanlı piyasa verileriyle güncellenemez, Claude'un son eğitim verilerini yansıtır
- Yatırım tavsiyesi niteliğinde değildir, sadece bilgilendirme amaçlıdır
- Analiz sonuçları Claude'un bilgi kesim tarihine (son eğitim tarihi) göre sınırlıdır
