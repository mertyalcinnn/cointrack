import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Telegram Bot Token
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Diğer konfigürasyon değişkenleri
POLLING_INTERVAL = 900  # 15 dakika
ACTIVE_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'] 