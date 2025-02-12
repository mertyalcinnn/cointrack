import requests
from datetime import datetime, timedelta
import logging
import json
import os
import random
import numpy as np

# Logger ayarlama
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CoinGeckoAPI:
    def __init__(self):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.cache_dir = "cache"
        self.cache_duration = 900  # 15 dakika
        self.demo_mode = True  # Varsayılan olarak demo modu açık

        # Demo mod için başlangıç fiyatları
        self.demo_prices = {
            'bitcoin': 96525,
            'ethereum': 2250,
            'binancecoin': 315,
            'ripple': 0.52,
            'cardano': 0.48
        }

        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

        logger.debug("CoinGeckoAPI başlatıldı.")

    def _get_demo_price_data(self, coin_id: str = "bitcoin", days: int = 1):
        """Demo modda fiyat geçmişi oluşturur."""
        logger.debug(f"Demo fiyat geçmişi üretiliyor: Coin={coin_id}, Days={days}")
        base_price = self.demo_prices.get(coin_id, 100)
        hours = days * 24
        return self._generate_realistic_price_movement(base_price, hours)

    def _get_demo_current_data(self, coin_id: str = "bitcoin"):
        """Demo modda güncel fiyat verisi oluşturur."""
        logger.debug(f"Demo güncel veri üretiliyor: Coin={coin_id}")
        base_price = self.demo_prices.get(coin_id, 100)
        change = random.uniform(-2, 2)  # -2% ile +2% arası değişim

        return {
            "current_price": round(base_price * (1 + change / 100), 2),
            "price_change_24h": round(change, 2),
            "last_updated": datetime.now().isoformat()
        }

    def get_price_history(self, coin_id: str = "bitcoin", days: int = 1):
        """Belirli bir coin için fiyat geçmişini alır"""
        logger.debug(f"Fiyat geçmişi alınıyor: Coin ID={coin_id}, Days={days}")
        if self.demo_mode:
            logger.info(f"Demo modda çalışıyor - {coin_id} için yapay veri üretiliyor")
            return self._get_demo_price_data(coin_id, days)

        try:
            endpoint = f"{self.base_url}/coins/{coin_id}/market_chart"
            params = {"vs_currency": "usd", "days": str(days), "interval": "hourly"}
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return [{"timestamp": datetime.fromtimestamp(ts / 1000).isoformat(), "price": price} for ts, price in data.get("prices", [])]
        except Exception as e:
            logger.error(f"get_price_history sırasında hata oluştu: {e}")
            return []

    def get_current_data(self, coin_id: str = "bitcoin"):
        """Coin'in güncel verilerini alır"""
        logger.debug(f"Güncel veri alınıyor: Coin ID={coin_id}")
        if self.demo_mode:
            logger.info(f"Demo modda çalışıyor - {coin_id} için yapay veri üretiliyor")
            return self._get_demo_current_data(coin_id)

        try:
            endpoint = f"{self.base_url}/simple/price"
            params = {"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"}
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get(coin_id, {})
            return {
                "current_price": data.get("usd", 0),
                "price_change_24h": data.get("usd_24h_change", 0),
                "last_updated": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"get_current_data sırasında hata oluştu: {e}")
            return {}

    def _generate_realistic_price_movement(self, base_price: float, hours: int, volatility: float = 0.02):
        """Gerçekçi fiyat hareketleri üret"""
        logger.debug(f"Fiyat hareketi üretiliyor: Base Price={base_price}, Hours={hours}, Volatility={volatility}")
        data = []
        current_price = base_price
        trend = random.uniform(-0.1, 0.1)

        for i in range(hours):
            timestamp = datetime.now() - timedelta(hours=hours - i)
            noise = np.random.normal(0, volatility)
            movement = trend / hours + noise
            current_price *= (1 + movement)
            if i % 4 == 0:
                trend += random.uniform(-0.02, 0.02)

            data.append({"timestamp": timestamp.isoformat(), "price": round(current_price, 2)})

        return data

# Örnek Kullanım
def test_api():
    api = CoinGeckoAPI()
    print("Bitcoin Güncel Fiyat:", api.get_current_data("bitcoin"))
    print("Bitcoin Fiyat Geçmişi:", api.get_price_history("bitcoin", days=1)[:5])

test_api()