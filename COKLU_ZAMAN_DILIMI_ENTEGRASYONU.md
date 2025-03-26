# Çoklu Zaman Dilimi Analizi Entegrasyonu

Bu doküman, kripto sinyal botunuza çoklu zaman dilimi analizi özelliğini entegre etmeniz için adım adım talimatlar içerir.

## 1. Modül Dosyalarını Birleştirme

İlk olarak, parça parça yazılmış MultiTimeframeAnalyzer modülünü birleştirmeniz gerekiyor:

```bash
# Ana dizinde çalıştır
python3 combine_multi_timeframe_modules.py
```

Bu komut, `src/analysis/multi_timeframe_analyzer_part*.py` dosyalarını birleştirerek, tam bir `src/analysis/multi_timeframe_analyzer.py` dosyası oluşturacaktır.

## 2. Telegram Bot Entegrasyonu

Çoklu zaman dilimi analizini botunuza entegre etmek için `telegram_bot.py` dosyanızda aşağıdaki değişiklikleri yapın:

### 2.1. Import Ekleyin

Dosyanın üst kısmına, diğer importların yanına aşağıdaki import satırını ekleyin:

```python
from src.bot.multi_timeframe_handler import MultiTimeframeHandler
```

### 2.2. `__init__` Metodunu Güncelleyin

`TelegramBot` sınıfının `__init__` metoduna aşağıdaki kodu ekleyin:

```python
def __init__(self, token: str):
    # ... mevcut kod ...
    
    # MultiTimeframeHandler'ı başlat
    self.multi_handler = MultiTimeframeHandler(logger=self.logger, bot_instance=self)
    
    # ... mevcut kodun geri kalanı ...
```

### 2.3. `start` Metodunu Güncelleyin

`start` metoduna, bot başlatma işleminin bir parçası olarak aşağıdaki kodu ekleyin:

```python
async def start(self):
    # ... mevcut kod ...
    
    # Bot başlatılıyor
    await self.application.initialize()
    
    # MultiTimeframeHandler'ı başlat
    await self.multi_handler.initialize()
    
    # Diğer başlatma işlemleri
    await self.application.start()
    # ... diğer kod ...
```

### 2.4. `register_handlers` Metodunu Güncelleyin

`register_handlers` metoduna aşağıdaki kodu ekleyin:

```python
def register_handlers(self):
    # ... mevcut kod ...
    
    # MultiTimeframeHandler'ın komutlarını kaydet
    await self.multi_handler.register_handlers(self.application)
    
    # ... mevcut kodun geri kalanı ...
```

### 2.5. `handle_callback_query` Metodunu Güncelleyin

`handle_callback_query` metodunda, callback veri tiplerini işleyen kısma aşağıdaki kodu ekleyin:

```python
async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... mevcut kod ...
    
    # Mevcut callback işleyiciler
    if callback_data.startswith("track_"):
        # ... mevcut kod ...
    elif callback_data.startswith("stoptrack_"):
        # ... mevcut kod ...
    elif callback_data.startswith("refresh_"):
        # ... mevcut kod ...
        
    # Çoklu zaman dilimi analizi için callback işleyici
    elif callback_data == "refresh_multi":
        await self.multi_handler.refresh_multi_callback(update, context)
        
    # ... mevcut kodun geri kalanı ...
```

## 3. Test Etme

Bu değişiklikleri yaptıktan sonra, botunuzu yeniden başlatın ve aşağıdaki komutla test edin:

```
/multiscan
```

veya belirli bir coin için:

```
/multiscan BTCUSDT
```

Bu komut, seçilen coin veya popüler coinler için çoklu zaman dilimi analizi yapacak ve sonuçları gösterecektir.

## 4. Özellikler

Bu entegrasyon ile botunuz şu özelliklere sahip olacaktır:

- **1W (Haftalık)** grafikleri kullanarak ana trendi belirleme
- **1H (Saatlik)** grafikleri kullanarak günlük hareketleri analiz etme
- **15M (15 Dakikalık)** grafikleri kullanarak giriş-çıkış noktalarını belirleme
- Üç zaman diliminin uyumunu kontrol ederek daha güvenilir sinyaller oluşturma
- Çoklu zaman dilimli teknik grafik gösterimi

## Not

Bu özellik premium kullanıcılar için sınırlandırılmıştır. Normal kullanıcılar deneme süresi başlatmaları için yönlendirilecektir.
