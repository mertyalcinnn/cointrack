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
    level=logging.INFO,  # INFO yerine DEBUG kullanın
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
    'position_size_usd': 10,    # Her işlem için pozisyon büyüklüğü ($)
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

def setup_binance():
    try:
        exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
                'recvWindow': 60000  # Daha uzun bir pencere süresi
            }
        })
        logger.debug("Binance API bağlantısı oluşturuldu")
        
        # Futures hesabının tam detayını görmek için
        try:
            # Farklı bir bakiye sorgulama yöntemi deneyin
            futures_balance = exchange.fapiPrivateGetBalance()
            print("Ham futures bakiye verisi:", futures_balance)
            
            # USDT bakiyesini bul
            usdt_balance = 0
            for asset in futures_balance:
                if asset['asset'] == 'USDT':
                    usdt_balance = float(asset['availableBalance'])
                    break
                    
            if usdt_balance > 0:
                logger.info(f"Binance Futures USDT bakiyesi: {usdt_balance}")
                print(f"✅ Futures USDT bakiyesi: {usdt_balance}")
                
                if usdt_balance < CONFIG['position_size_usd']:
                    logger.warning(f"Futures bakiyesi ({usdt_balance} USDT) işlem için yetersiz! En az {CONFIG['position_size_usd']} USDT gerekli.")
                    print(f"⚠️ DİKKAT: Futures bakiyeniz ({usdt_balance} USDT) işlem için yetersiz!")
            else:
                logger.warning("Futures hesabında kullanılabilir USDT bakiyesi bulunamadı!")
                print("❌ Futures hesabında USDT bakiyesi bulunamadı!")
                
            return exchange
            
        except Exception as e:
            logger.error(f"Futures bakiyesi alınırken hata: {e}")
            print(f"⚠️ Futures bakiyesi alınırken hata: {e}")
            
            # Alternatif yöntem ile deneyin
            try:
                balance = exchange.fetch_balance()
                print("Standart balances:", balance.keys())
                
                if 'info' in balance:
                    print("Balance info:", balance['info'])
                
                if 'USDT' in balance:
                    logger.info(f"Binance API bağlantısı başarılı. USDT bakiyesi: {balance['USDT']['free']}")
                    print(f"✅ USDT bakiyesi: {balance['USDT']['free']}")
                else:
                    logger.warning("USDT bakiyesi bulunamadı! Mevcut para birimleri:")
                    print("❌ USDT bakiyesi bulunamadı!")
                    
                    # Tüm para birimlerini kontrol et
                    for currency, value in balance.items():
                        if isinstance(value, dict) and 'free' in value and float(value['free']) > 0:
                            print(f"- {currency}: {value['free']}")
            except Exception as sub_e:
                logger.error(f"Alternatif bakiye kontrolünde hata: {sub_e}")
            
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
        {{
            "trend": "UP/DOWN/SIDEWAYS",
            "prediction": "açıklama",
            "recommendation": "BUY/HOLD/SELL",
            "confidence": 75
        }}

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
# Kaldıraç seviyesini belirle
def determine_leverage(ai_score):
    if ai_score > 85:
        return min(10, CONFIG['max_leverage'])
    elif ai_score > 75:
        return min(7, CONFIG['max_leverage'])
    elif ai_score > 65:
        return min(5, CONFIG['max_leverage'])
    else:
        return 3

# İşlem fırsatı analiz et
def analyze_opportunity(exchange, symbol):
    # AI analizi al
    logger.debug(f"AI analizi başlatılıyor: {symbol}")
    ai_result = get_ai_analysis(exchange, symbol)
    
    if not ai_result:
        logger.debug(f"{symbol} için AI analizi alınamadı")
        return None
    
    logger.debug(f"AI Analiz Sonucu ({symbol}): {ai_result}")
    
    # Teknik sinyalleri al
    logger.debug(f"Teknik analiz başlatılıyor: {symbol}")
    tech_signals = get_technical_signals(exchange, symbol)
    logger.debug(f"Teknik Analiz Sonucu ({symbol}): {tech_signals}")
    
    # AI tavsiyesini dönüştür
    if ai_result['recommendation'] == 'BUY':
        ai_recommendation = 'AL'
    elif ai_result['recommendation'] == 'SELL':
        ai_recommendation = 'SAT'
    else:
        ai_recommendation = 'BEKLE'
    
    logger.debug(f"{symbol} AI Tavsiyesi: {ai_recommendation}")
    
    # Toplam skoru hesapla
    ai_score = ai_result['confidence']
    tech_score = 0
    
    if tech_signals['overall'] == 'STRONG_LONG':
        tech_score = 30
    elif tech_signals['overall'] == 'LONG':
        tech_score = 20
    elif tech_signals['overall'] == 'STRONG_SHORT':
        tech_score = -30
    elif tech_signals['overall'] == 'SHORT':
        tech_score = -20
    
    logger.debug(f"{symbol} Tech Skor: {tech_score}, AI Skor: {ai_score}")
    
    # İşlem yönünü belirle
    if tech_signals['overall'] in ['LONG', 'STRONG_LONG'] and ai_recommendation == 'AL':
        direction = 'LONG'
        score = ai_score + abs(tech_score)
        logger.debug(f"{symbol} LONG sinyali bulundu. Toplam skor: {score}")
    elif tech_signals['overall'] in ['SHORT', 'STRONG_SHORT'] and ai_recommendation == 'SAT':
        direction = 'SHORT'
        score = ai_score + abs(tech_score)
        logger.debug(f"{symbol} SHORT sinyali bulundu. Toplam skor: {score}")
    else:
        # Uyumsuz sinyaller
        logger.debug(f"{symbol} için uyumsuz sinyaller: Teknik={tech_signals['overall']}, AI={ai_recommendation}")
        return None
    
    # Min skor kontrolü
    if score < CONFIG['min_ai_score']:
        logger.debug(f"{symbol} toplam skoru ({score}) minimum skor eşiğinin ({CONFIG['min_ai_score']}) altında")
        return None
        
    return {
        'symbol': symbol,
        'direction': direction,
        'ai_recommendation': ai_recommendation,
        'ai_confidence': ai_score,
        'tech_signal': tech_signals['overall'],
        'total_score': score,
        'timestamp': datetime.now().isoformat()
    }

# Pozisyon aç
def open_position(exchange, open_positions, opportunity):
    try:
        # Farklı yöntemlerle bakiyeyi kontrol et
        try:
            # Önce direkt FAPI endpoint'ini deneyelim
            futures_balance = exchange.fapiPrivateGetBalance()
            
            # USDT bakiyesini bul
            usdt_balance = 0
            for asset in futures_balance:
                if asset['asset'] == 'USDT':
                    usdt_balance = float(asset['availableBalance'])
                    break
                    
            print(f"Futures USDT bakiyesi (FAPI): {usdt_balance}")
            
            if usdt_balance >= CONFIG['position_size_usd']:
                print(f"✅ Yeterli bakiye mevcut: {usdt_balance} USDT")
            else:
                logger.error(f"Yetersiz bakiye: {usdt_balance} USDT. En az {CONFIG['position_size_usd']} USDT gerekli.")
                print(f"❌ Yetersiz bakiye: {usdt_balance} USDT. En az {CONFIG['position_size_usd']} USDT gerekli.")
                return None
                
        except Exception as e:
            logger.warning(f"FAPI bakiye kontrolünde hata: {e}, standart yöntem deneniyor...")
            
            # Standart yöntem ile deneyelim
            balance = exchange.fetch_balance()
            
            if 'USDT' in balance and float(balance['USDT']['free']) >= CONFIG['position_size_usd']:
                print(f"✅ Yeterli bakiye mevcut: {balance['USDT']['free']} USDT")
            else:
                free_usdt = balance['USDT']['free'] if 'USDT' in balance else 0
                logger.error(f"Yetersiz bakiye: {free_usdt} USDT. En az {CONFIG['position_size_usd']} USDT gerekli.")
                print(f"❌ Yetersiz bakiye: {free_usdt} USDT. En az {CONFIG['position_size_usd']} USDT gerekli.")
                return None
        
        # Fonksiyonun geri kalanı aynı kalır...
        
        # Sembol için geçerli piyasa fiyatını al
        ticker = exchange.fetch_ticker(opportunity['symbol'])
        current_price = ticker['last']
        
        # Volatiliteyi hesapla (ATR - Average True Range)
        ohlcv = exchange.fetch_ohlcv(opportunity['symbol'], '1d', limit=14)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['tr1'] = abs(df['high'] - df['low'])
        df['tr2'] = abs(df['high'] - df['close'].shift())
        df['tr3'] = abs(df['low'] - df['close'].shift())
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        atr = df['tr'].mean()
        
        # Kaldıraç seviyesini belirle (skorla birlikte volatiliteyi de dikkate al)
        base_leverage = determine_leverage(opportunity['ai_confidence'])
        volatility_factor = 1 - (atr / current_price) * 10  # Yüksek volatilite = Düşük faktör
        volatility_factor = max(0.5, min(1.5, volatility_factor))  # 0.5 ile 1.5 arasında sınırla
        adjusted_leverage = max(1, min(base_leverage * volatility_factor, CONFIG['max_leverage']))
        adjusted_leverage = int(adjusted_leverage)  # Tam sayıya yuvarla
        
        # Kaldıracı ayarla
        try:
            exchange.set_leverage(adjusted_leverage, opportunity['symbol'])
            logger.info(f"{opportunity['symbol']} için kaldıraç {adjusted_leverage}x olarak ayarlandı")
            print(f"⚖️ Kaldıraç: {adjusted_leverage}x (Volatilite faktörü: {volatility_factor:.2f})")
        except Exception as e:
            logger.error(f"Kaldıraç ayarlanamadı: {e}")
            print(f"❌ Kaldıraç ayarlanamadı: {e}")
            return None
        
        # Margin tipini ayarla
        try:
            exchange.set_margin_mode('cross', opportunity['symbol'])
            logger.info(f"{opportunity['symbol']} için margin modu 'cross' olarak ayarlandı")
        except Exception as e:
            if "No need to change margin type" in str(e):
                logger.info(f"{opportunity['symbol']} için margin modu zaten 'cross'")
            else:
                logger.error(f"Margin modu ayarlanamadı: {e}")
        
        # Pozisyon büyüklüğünü hesapla
        amount = CONFIG['position_size_usd'] / current_price
        
        # Piyasa koşullarına göre pozisyon büyüklüğünü ayarla
        if opportunity['total_score'] > 90:  # Çok güçlü sinyal
            position_size_multiplier = 1.2
        elif opportunity['total_score'] > 80:  # Güçlü sinyal
            position_size_multiplier = 1.0
        else:  # Normal sinyal
            position_size_multiplier = 0.8
            
        amount = amount * position_size_multiplier
        
        # Market bilgilerini al ve miktarı precision'a göre yuvarla
        try:
            market_info = exchange.market(opportunity['symbol'])
            precision = market_info['precision']['amount'] if 'precision' in market_info and 'amount' in market_info['precision'] else 8
            amount = float(round(amount, precision))
        except Exception as e:
            logger.warning(f"Market bilgisi alınamadı, varsayılan precision kullanılacak: {e}")
            amount = float(round(amount, 6))
        
        # İşlem yönünü belirle
        side = 'buy' if opportunity['direction'] == 'LONG' else 'sell'
        
        # Volatilite tabanlı TP/SL hesaplama
        # Yüksek volatilitede daha geniş, düşük volatilitede daha dar stop loss
        risk_reward_ratio = 3.0  # Risk/Ödül oranı
        
        # ATR'ye dayanarak stop loss ve take profit mesafelerini ayarla
        if side == 'buy':
            stop_loss_distance = atr * 1.5  # Stop loss ATR'nin 1.5 katı
            take_profit_distance = stop_loss_distance * risk_reward_ratio
            stop_loss_price = current_price - stop_loss_distance
            take_profit_price = current_price + take_profit_distance
        else:
            stop_loss_distance = atr * 1.5
            take_profit_distance = stop_loss_distance * risk_reward_ratio
            stop_loss_price = current_price + stop_loss_distance
            take_profit_price = current_price - take_profit_distance
        
        logger.info(f"İşlem parametreleri: Sembol={opportunity['symbol']}, Yön={side}, Miktar={amount}, Fiyat={current_price}, TP={take_profit_price}, SL={stop_loss_price}")
        
        print(f"\n🔄 İşlem açılıyor: {opportunity['symbol']} ({side.upper()})")
        print(f"💰 Miktar: {amount} ({CONFIG['position_size_usd']*position_size_multiplier:.2f} USD)")
        print(f"💵 Giriş Fiyatı: {current_price}")
        print(f"🎯 Kar Hedefi: {take_profit_price:.6f}")
        print(f"🛑 Stop Loss: {stop_loss_price:.6f}")
        print(f"📊 Risk/Ödül: 1:{risk_reward_ratio}")
        
        # İşlemi aç
        try:
            order = exchange.create_market_order(
                symbol=opportunity['symbol'],
                side=side,
                amount=amount,
                params={}
            )
            
            logger.info(f"Market emri gönderildi: {order['id']}")
        except Exception as e:
            logger.error(f"Market emri gönderilemedi: {e}")
            print(f"❌ İşlem açılamadı: {e}")
            return None
        
        # Pozisyon bilgilerini kaydet
        position = {
            'symbol': opportunity['symbol'],
            'id': order['id'],
            'side': side,
            'amount': amount,
            'entry_price': current_price,
            'take_profit': take_profit_price,
            'stop_loss': stop_loss_price,
            'leverage': adjusted_leverage,
            'opened_at': datetime.now().isoformat(),
            'opportunity': opportunity
        }
        
        open_positions.append(position)
        
        # İşlem geçmişini güncelle
        trade_history = load_trade_history()
        trade_history.append({
            'action': 'OPEN',
            'position': position,
            'timestamp': datetime.now().isoformat()
        })
        save_trade_history(trade_history)
        
        logger.info(f"Pozisyon açıldı: {opportunity['symbol']} {side.upper()} - Kaldıraç: {adjusted_leverage}x - Giriş: {current_price} - TP: {take_profit_price} - SL: {stop_loss_price}")
        print(f"✅ Pozisyon açıldı: {opportunity['symbol']} {side.upper()}")
        
        # Telegram bildirimini gönder
        send_telegram_message(
            f"🚀 *POZİSYON AÇILDI*\n\n"
            f"💰 Sembol: {opportunity['symbol']}\n"
            f"📈 Yön: {side.upper()}\n"
            f"⚖️ Kaldıraç: {adjusted_leverage}x\n"
            f"💵 Giriş Fiyatı: ${current_price:.6f}\n"
            f"🎯 Kar Hedefi: ${take_profit_price:.6f}\n"
            f"🛑 Stop Loss: ${stop_loss_price:.6f}\n\n"
            f"⭐ AI Skoru: {opportunity['ai_confidence']}\n"
            f"📊 Teknik Sinyal: {opportunity['tech_signal']}\n"
            f"📰 Haber Duyarlılığı: {opportunity['news_sentiment']:.2f}\n"
        )
        
        return position
    except Exception as e:
        logger.error(f"Pozisyon açılamadı: {e}")
        print(f"❌ Pozisyon açılamadı: {e}")
        return None

# Pozisyon kapat
def close_position(exchange, open_positions, position, reason):
    try:
        # Ters işlem yönü
        close_side = 'sell' if position['side'] == 'buy' else 'buy'
        
        # Pozisyonu kapat
        order = exchange.create_market_order(
            symbol=position['symbol'],
            side=close_side,
            amount=position['amount'],
            params={}
        )
        
        # Güncel fiyatı al
        ticker = exchange.fetch_ticker(position['symbol'])
        exit_price = ticker['last']
        
        # PnL hesapla
        if position['side'] == 'buy':
            pnl = (exit_price - position['entry_price']) * position['amount'] * position['leverage']
        else:
            pnl = (position['entry_price'] - exit_price) * position['amount'] * position['leverage']
        
        # Kapatma bilgilerini kaydet
        close_data = {
            'exit_price': exit_price,
            'pnl': pnl,
            'closed_at': datetime.now().isoformat(),
            'reason': reason
        }
        
        # Pozisyon listesini güncelle
        for i, p in enumerate(open_positions):
            if p['id'] == position['id']:
                open_positions.pop(i)
                break
        
        # İşlem geçmişini güncelle
        trade_history = load_trade_history()
        trade_history.append({
            'action': 'CLOSE',
            'position': {**position, **close_data},
            'timestamp': datetime.now().isoformat()
        })
        save_trade_history(trade_history)
        
        logger.info(f"Pozisyon kapatıldı: {position['symbol']} - Çıkış: {exit_price} - PnL: ${pnl:.2f} - Neden: {reason}")
        
        # Telegram bildirimini gönder
        kar_zarar_emoji = "💰" if pnl >= 0 else "💴"
        send_telegram_message(
            f"{kar_zarar_emoji} *POZİSYON KAPATILDI*\n\n"
            f"💰 Sembol: {position['symbol']}\n"
            f"📈 Yön: {position['side'].upper()}\n"
            f"💵 Giriş Fiyatı: ${position['entry_price']:.6f}\n"
            f"💵 Çıkış Fiyatı: ${exit_price:.6f}\n"
            f"{kar_zarar_emoji} {'KÂR' if pnl >= 0 else 'ZARAR'}: ${abs(pnl):.2f}\n\n"
            f"🚫 Neden: {reason}\n"
        )
        
        return {**position, **close_data}
    except Exception as e:
        logger.error(f"Pozisyon kapatılamadı: {e}")
        return None

# Pozisyonları kontrol et
def check_positions(exchange, open_positions):
    for position in list(open_positions):
        try:
            # Güncel fiyatı al
            ticker = exchange.fetch_ticker(position['symbol'])
            current_price = ticker['last']
            
            # Pozisyon yaşını kontrol et
            opened_at = datetime.fromisoformat(position['opened_at'])
            position_age = (datetime.now() - opened_at).total_seconds()
            
            # Kar hedefine ulaşıldı mı?
            if (position['side'] == 'buy' and current_price >= position['take_profit']) or \
               (position['side'] == 'sell' and current_price <= position['take_profit']):
                close_position(exchange, open_positions, position, "Kar hedefine ulaşıldı")
            
            # Zarar limitine ulaşıldı mı?
            elif (position['side'] == 'buy' and current_price <= position['stop_loss']) or \
                 (position['side'] == 'sell' and current_price >= position['stop_loss']):
                close_position(exchange, open_positions, position, "Zarar limitine ulaşıldı")
            
            # Maksimum pozisyon yaşını aştı mı?
            elif position_age > CONFIG['max_position_age']:
                close_position(exchange, open_positions, position, "Maksimum süre aşıldı")
                
        except Exception as e:
            logger.error(f"Pozisyon kontrolü sırasında hata: {e}")

# Piyasayı tara ve işlem yap
def scan_market(exchange, open_positions):
    try:
        logger.info("Piyasa taraması başlatılıyor")
        print("\n🔍 Piyasa taraması başlatılıyor...")
        
        # Tüm futures sembollerini al
        markets = exchange.load_markets()
        
        # Sadece USDT çiftlerini filtrele
        usdt_pairs = [symbol for symbol in markets.keys() if ':USDT' in symbol]
        logger.info(f"Toplam {len(usdt_pairs)} USDT çifti bulundu")
        print(f"📊 Toplam {len(usdt_pairs)} USDT çifti bulundu")
        
        # İşlem hacmine göre en yüksek coinleri bul
        volumes = {}
        for symbol in usdt_pairs[:50]:  # İlk 50 çifti kontrol et (hız için)
            try:
                ticker = exchange.fetch_ticker(symbol)
                volumes[symbol] = ticker['quoteVolume'] if 'quoteVolume' in ticker else 0
            except Exception as e:
                logger.error(f"{symbol} ticker bilgisi alınamadı: {e}")
        
        # İşlem hacmine göre sırala
        sorted_by_volume = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        top_symbols = [symbol for symbol, _ in sorted_by_volume[:20]]  # En yüksek hacimli 20 çift
        
        logger.info(f"En yüksek hacimli 20 sembol: {top_symbols}")
        print(f"📈 En yüksek hacimli 20 sembol analiz edilecek")
        
        # İşlem fırsatları
        opportunities = []
        
        # Her bir sembol için işlem fırsatı analiz et
        for symbol in top_symbols:
            print(f"🔍 {symbol} analiz ediliyor...")
            
            # Teknik analiz
            tech_signals = get_technical_signals(exchange, symbol)
            
            # AI analizi
            ai_result = get_ai_analysis(exchange, symbol)
            
            # Haber analizi
            news_sentiment = get_news_sentiment(symbol.split('/')[0].replace(':USDT', ''))
            
            # Fırsat puanlaması
            if ai_result and tech_signals:
                # AI tavsiyesini dönüştür
                if ai_result['recommendation'] == 'BUY':
                    ai_recommendation = 'AL'
                elif ai_result['recommendation'] == 'SELL':
                    ai_recommendation = 'SAT'
                else:
                    ai_recommendation = 'BEKLE'
                
                # Toplam skoru hesapla
                ai_score = ai_result['confidence']
                tech_score = 0
                
                if tech_signals['overall'] == 'STRONG_LONG':
                    tech_score = 30
                elif tech_signals['overall'] == 'LONG':
                    tech_score = 20
                elif tech_signals['overall'] == 'STRONG_SHORT':
                    tech_score = -30
                elif tech_signals['overall'] == 'SHORT':
                    tech_score = -20
                
                # Haber puanı ekle
                news_score = news_sentiment * 10  # -10 ile +10 arasında değer
                
                # İşlem yönünü belirle
                if tech_signals['overall'] in ['LONG', 'STRONG_LONG'] and ai_recommendation == 'AL' and news_sentiment > 0:
                    direction = 'LONG'
                    score = ai_score + abs(tech_score) + news_score
                    logger.debug(f"{symbol} LONG sinyali bulundu. Toplam skor: {score}")
                    print(f"✅ {symbol} için LONG sinyali tespit edildi. Skor: {score}")
                elif tech_signals['overall'] in ['SHORT', 'STRONG_SHORT'] and ai_recommendation == 'SAT' and news_sentiment < 0:
                    direction = 'SHORT'
                    score = ai_score + abs(tech_score) + abs(news_score)
                    logger.debug(f"{symbol} SHORT sinyali bulundu. Toplam skor: {score}")
                    print(f"✅ {symbol} için SHORT sinyali tespit edildi. Skor: {score}")
                else:
                    # Uyumsuz sinyaller
                    logger.debug(f"{symbol} için uyumsuz sinyaller: Teknik={tech_signals['overall']}, AI={ai_recommendation}, Haber={news_sentiment}")
                    print(f"❌ {symbol} için uyumsuz sinyaller")
                    continue
                
                # Min skor kontrolü
                if score < CONFIG['min_ai_score']:
                    logger.debug(f"{symbol} toplam skoru ({score}) minimum skor eşiğinin ({CONFIG['min_ai_score']}) altında")
                    print(f"❌ {symbol} skoru yetersiz: {score} < {CONFIG['min_ai_score']}")
                    continue
                    
                opportunities.append({
                    'symbol': symbol,
                    'direction': direction,
                    'ai_recommendation': ai_recommendation,
                    'ai_confidence': ai_score,
                    'tech_signal': tech_signals['overall'],
                    'news_sentiment': news_sentiment,
                    'total_score': score,
                    'timestamp': datetime.now().isoformat()
                })
                
        # Fırsatları skora göre sırala
        opportunities.sort(key=lambda x: x['total_score'], reverse=True)
        logger.info(f"Toplam {len(opportunities)} fırsat bulundu")
        print(f"\n📊 Toplam {len(opportunities)} fırsat bulundu")
        
        # En iyi fırsatları göster
        if opportunities:
            print("\n🏆 En iyi fırsatlar:")
            for i, opp in enumerate(opportunities[:5]):
                print(f"  {i+1}. {opp['symbol']} - Yön: {opp['direction']} - Skor: {opp['total_score']:.1f}")
                print(f"     AI: {opp['ai_confidence']:.1f}, Teknik: {opp['tech_signal']}, Haber: {opp['news_sentiment']:.2f}")
        
        # Açık pozisyon sayısını kontrol et
        if len(open_positions) < CONFIG['max_positions'] and opportunities:
            # Zaten açık olan sembolleri kontrol et
            open_symbols = [p['symbol'] for p in open_positions]
            for opportunity in opportunities:
                if opportunity['symbol'] not in open_symbols:
                    logger.debug(f"Pozisyon açma kriterleri karşılandı: {opportunity['symbol']}")
                    print(f"\n🔄 Pozisyon açılıyor: {opportunity['symbol']} ({opportunity['direction']})")
                    open_position(exchange, open_positions, opportunity)
                    break  # Her döngüde sadece bir pozisyon aç
                else:
                    logger.debug(f"{opportunity['symbol']} için zaten açık pozisyon var")
        else:
            if len(open_positions) >= CONFIG['max_positions']:
                logger.debug(f"Maksimum pozisyon sayısına ulaşıldı: {len(open_positions)}/{CONFIG['max_positions']}")
                print(f"⚠️ Maksimum pozisyon sayısına ulaşıldı: {len(open_positions)}/{CONFIG['max_positions']}")
            elif not opportunities:
                logger.debug("Uygun işlem fırsatı bulunamadı")
                print("❌ Uygun işlem fırsatı bulunamadı")
    
    except Exception as e:
        logger.error(f"Piyasa tarama sırasında hata: {e}")
        print(f"❌ Piyasa tarama hatası: {e}")
        import traceback
        logger.error(traceback.format_exc())
# Ana fonksiyon
def get_news_sentiment(coin_name):
    """
    Belirli bir kripto para için internet haberlerini analiz eder ve
    duyarlılık skoru döndürür (-1 ile 1 arasında)
    """
    try:
        # Claude AI'dan haber analizi isteği
        if not CLAUDE_API_KEY:
            logger.error("ANTHROPIC_API_KEY bulunamadı, haber analizi yapılamıyor")
            return 0
            
        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        # Son haberleri almak için prompt
        prompt = f"""
        Son 24 saat içinde {coin_name} kripto para birimi hakkındaki haberleri analiz et. 
        Bu kripto para hakkındaki genel duyarlılık nedir? 
        
        Lütfen duyarlılık analizini -1 ile 1 arasında bir sayı olarak ver:
        -1: Çok negatif haber duyarlılığı
        0: Nötr duyarlılık veya karışık haberler
        1: Çok pozitif haber duyarlılığı
        
        Sadece bir sayı ver, başka açıklama ekleme.
        """
        
        data = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 100,
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
        content = ai_response['content'][0]['text'].strip()
        
        # Sayısal değeri çıkar
        try:
            sentiment = float(content)
            if sentiment < -1:
                sentiment = -1
            elif sentiment > 1:
                sentiment = 1
                
            logger.info(f"{coin_name} için haber duyarlılık skoru: {sentiment}")
            return sentiment
        except:
            logger.error(f"Haber duyarlılık skoru çıkarılamadı: {content}")
            return 0
            
    except Exception as e:
        logger.error(f"Haber duyarlılık analizi yapılamadı: {e}")
        return 0
def main():
    logger.info("Otomatik Kaldıraçlı İşlem Sistemi başlatılıyor")
    
    print("Telegram ayarları kontrol ediliyor...")
    telegram_ready = setup_telegram()
    if telegram_ready:
        print("Telegram bildirimleri aktif")
    else:
        print("Telegram bildirimleri devre dışı")
    
    # Binance bağlantısını kur
    print("Binance API bağlantısı kuruluyor...")
    exchange = setup_binance()
    if not exchange:
        error_msg = "Binance API bağlantısı kurulamadı, program sonlandırılıyor"
        logger.error(error_msg)
        print(error_msg)
        return
    
    # Başlangıç bildirimi
    start_msg = (
        "🚀 *Otomatik Kaldıraçlı İşlem Sistemi Başlatıldı*\n\n"
        "💰 Sistem şu anda piyasayı tarayarak işlem fırsatlarını arıyor.\n\n"
        "⚙️ Ayarlar:\n"
        f"- Maksimum Pozisyon Sayısı: {CONFIG['max_positions']}\n"
        f"- Pozisyon Büyüklüğü: ${CONFIG['position_size_usd']}\n"
        f"- Maksimum Kaldıraç: {CONFIG['max_leverage']}x\n"
        f"- Risk/Ödül: {CONFIG['max_loss_usd']}$ / {CONFIG['profit_target_usd']}$\n\n"
        "⏰ Her 5 dakikada bir piyasa taraması yapılacak ve uygun fırsatlar bulunduğunda otomatik işlemler açılacak.\n"
        "⚠️ Sistemi durdurmak için /stopautoscan komutunu kullanın."
    )
    
    send_telegram_message(start_msg)
    
    # Açık pozisyonlar listesi
    open_positions = []
    
    try:
# Ana döngü
        while True:
            print("\n" + "="*50)
            print(f"⏰ TARAMA BAŞLIYOR: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*50)
            
            # Pozisyonları kontrol et
            check_positions(exchange, open_positions)
            
            # Piyasayı tara
            scan_market(exchange, open_positions)
            
            # Bekleme süresi
            print(f"\n⏳ {CONFIG['scan_interval']} saniye bekleniyor...")
            logger.info(f"{CONFIG['scan_interval']} saniye bekleniyor...")
            time.sleep(CONFIG['scan_interval'])
    except KeyboardInterrupt:
        print("Program kullanıcı tarafından durduruldu.")
        logger.info("Program kullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"Program bir hata nedeniyle durdu: {e}")
        logger.error(f"Program bir hata nedeniyle durdu: {e}")
        import traceback
        error_msg = traceback.format_exc()
        logger.error(f"Hata detayları:\n{error_msg}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Beklenmeyen hata: {e}")
        print(f"Beklenmeyen hata: {e}")
