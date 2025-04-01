#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Otomatik Kaldıraçlı İşlem Sistemi (AutoTrader)
AI ve teknik analiz verilerini kullanarak Binance vadeli işlemler piyasasında
otomatik olarak kaldıraçlı işlemler yapan modül.
"""

import os
import json
import time
import sys
import logging
import pandas as pd
import ccxt
import requests
from datetime import datetime
from dotenv import load_dotenv

# Telegram entegrasyonu için
try:
    import telegram
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("Telegram kütüphanesi bulunamadı, Telegram bildirimleri devre dışı.")

# Loglama ayarları
logging.basicConfig(
    level=logging.DEBUG,  # INFO yerine DEBUG kullanın
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("autotrader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AutoTrader")

# .env dosyasından API anahtarlarını yükle
load_dotenv()

# Yapılandırma parametreleri
CONFIG = {
    'position_size_usd': 50,    # Her işlem için pozisyon büyüklüğü ($)
    'profit_target_usd': 10,    # Kar hedefi ($)
    'max_loss_usd': 4,          # Maksimum zarar limiti ($)
    'max_positions': 3,         # Maksimum aynı anda açık pozisyon sayısı
    'max_leverage': 10,         # Maksimum kaldıraç
    'min_ai_score': 60,         # İşlem açmak için gereken minimum AI skoru
    'scan_interval': 300,       # Tarama aralığı (saniye)
    'max_position_age': 86400,  # Maksimum pozisyon yaşı (24 saat)
}

# Telegram bilgileri
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
telegram_bot = None

# Claude API
CLAUDE_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Telegram bot'unu ayarla
def setup_telegram():
    global telegram_bot
    if TELEGRAM_AVAILABLE and TELEGRAM_BOT_TOKEN:
        try:
            telegram_bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
            logger.info(f"Telegram bot yüklendi, chat_id: {TELEGRAM_CHAT_ID}")
            return True
        except Exception as e:
            logger.error(f"Telegram bot kurulum hatası: {e}")
    return False

# Telegram mesajı gönder (senkron versiyon)
def send_telegram_message(message):
    if telegram_bot and TELEGRAM_CHAT_ID:
        try:
            telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
            logger.info(f"Telegram mesajı gönderildi: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Telegram mesajı gönderme hatası: {e}")
    return False

# Binance API bağlantısı (Mainnet)
def setup_binance():
    try:
        exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'  # Vadeli işlemler piyasası
            }
        })
        logger.debug("Binance API bağlantısı oluşturuldu")
        
        # Bağlantıyı test et
        balance = exchange.fetch_balance()
        logger.info("Binance API bağlantısı başarılı")
        
        return exchange
    except Exception as e:
        logger.error(f"Binance API bağlantısı başarısız: {e}")
        return None

# İşlem geçmişi dosyası
TRADE_HISTORY_FILE = 'trade_history.json'

# İşlem geçmişini yükle
def load_trade_history():
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"İşlem geçmişi yüklenirken hata: {e}")
            return []
    return []

# İşlem geçmişini kaydet
def save_trade_history(history):
    try:
        with open(TRADE_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        logger.error(f"İşlem geçmişi kaydedilirken hata: {e}")

# Claude AI'dan analiz al
def get_ai_analysis(exchange, symbol, timeframe='1d'):
    if not CLAUDE_API_KEY:
        logger.error("ANTHROPIC_API_KEY bulunamadı, AI analizi yapılamıyor")
        return None
        
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01"
    }
    
    logger.debug(f"{symbol} için OHLCV verileri alınıyor")
    try:
        # OHLCV verileri al
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=30)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        logger.debug(f"{symbol} OHLCV verileri alındı, satır sayısı: {len(df)}")
        
        # AI için istek içeriği hazırla
        prompt = f"""
        Aşağıdaki kripto para verilerini analiz ederek yatırım tavsiyesi ver:
        
        Sembol: {symbol}
        Son 30 gün fiyat hareketleri:
        {df[['timestamp', 'close']].to_string(index=False)}
        
        Lütfen bu veriye dayanarak aşağıdaki bilgileri içeren bir analiz yap:
        1. Fiyat trendi (yükseliş, düşüş, yatay)
        2. Gelecek 24 saat için fiyat tahmini
        3. Tavsiye (AL, BEKLE, SAT)
        4. 0-100 arası güven skoru
        
        Yanıtı şu JSON formatta ver:
        {
          "trend": "UP/DOWN/SIDEWAYS",
          "prediction": "açıklama",
          "recommendation": "BUY/HOLD/SELL",
          "confidence": 75
        }
        
        Sadece JSON formatında yanıt ver, başka açıklama ekleme.
        """
        
        logger.debug(f"{symbol} için Claude AI isteği gönderiliyor")
        
        data = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1000,
            "temperature": 0,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=data
        )
        response.raise_for_status()
        
        # AI'dan gelen yanıtı al
        ai_response = response.json()
        content = ai_response['content'][0]['text']
        
        logger.debug(f"{symbol} için Claude AI yanıtı alındı: {content}")
        
        # JSON formatını çıkar
        import re
        json_str = re.search(r'{.*}', content, re.DOTALL)
        if json_str:
            result = json.loads(json_str.group())
            logger.debug(f"{symbol} AI analiz sonucu: {result}")
            return result
        else:
            logger.error(f"AI yanıtı JSON formatında değil: {content}")
            return None
    except Exception as e:
        logger.error(f"{symbol} için AI analizi alınamadı: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

# Teknik analiz sinyalleri oluştur
def get_technical_signals(exchange, symbol, timeframe='4h'):
    try:
        # OHLCV verileri al
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # EMA hesapla
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI hesapla
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD hesapla
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['signal']
        
        # Son satırı al
        last = df.iloc[-1]
        
        # Sinyalleri belirle
        signals = {
            'ema': 'NEUTRAL',
            'rsi': 'NEUTRAL',
            'macd': 'NEUTRAL',
            'overall': 'NEUTRAL'
        }
        
        # EMA sinyali
        if last['close'] > last['ema20'] and last['ema20'] > last['ema50']:
            signals['ema'] = 'STRONG_LONG'
        elif last['close'] > last['ema20']:
            signals['ema'] = 'LONG'
        elif last['close'] < last['ema20'] and last['ema20'] < last['ema50']:
            signals['ema'] = 'STRONG_SHORT'
        elif last['close'] < last['ema20']:
            signals['ema'] = 'SHORT'
        
        # RSI sinyali
        if last['rsi'] > 70:
            signals['rsi'] = 'SHORT'  # Aşırı alım
        elif last['rsi'] < 30:
            signals['rsi'] = 'LONG'   # Aşırı satım
        
        # MACD sinyali
        if last['macd'] > last['signal'] and last['macd_hist'] > 0:
            signals['macd'] = 'LONG'
        elif last['macd'] < last['signal'] and last['macd_hist'] < 0:
            signals['macd'] = 'SHORT'
        
        # Genel sinyal
        signal_values = {
            'STRONG_LONG': 2,
            'LONG': 1,
            'NEUTRAL': 0,
            'SHORT': -1,
            'STRONG_SHORT': -2
        }
        
        score = signal_values[signals['ema']] + signal_values[signals['rsi']] + signal_values[signals['macd']]
        
        if score >= 2:
            signals['overall'] = 'STRONG_LONG'
        elif score > 0:
            signals['overall'] = 'LONG'
        elif score <= -2:
            signals['overall'] = 'STRONG_SHORT'
        elif score < 0:
            signals['overall'] = 'SHORT'
        
        return signals
    except Exception as e:
        logger.error(f"Teknik analiz sinyalleri oluşturulamadı: {e}")
        return {'ema': 'NEUTRAL', 'rsi': 'NEUTRAL', 'macd': 'NEUTRAL', 'overall': 'NEUTRAL'}