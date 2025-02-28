"""
Binance Alım-Satım İşlemleri
"""
import os
import logging
import time
import hmac
import hashlib
import requests
import json
from urllib.parse import urlencode
from datetime import datetime
from typing import Dict, List, Optional, Union, Any
from decimal import Decimal, ROUND_DOWN
import ccxt
from dotenv import load_dotenv

# Logger ayarlamaları
logger = logging.getLogger(__name__)

class BinanceTrader:
    """
    Binance alım-satım işlemlerini yönetir.
    """
    def __init__(self):
        """Binance trader sınıfını başlat."""
        # .env dosyasından API anahtarlarını yükle
        load_dotenv()
        
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.testnet = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Binance API anahtarları .env dosyasında bulunamadı!")
        
        logger.info(f"Binance Trader başlatıldı. Testnet: {self.testnet}")
        
        # Testnet veya gerçek API URL'sini belirle
        if self.testnet:
            self.base_url = os.getenv('BINANCE_TESTNET_API_URL', 'https://testnet.binance.vision/api')
        else:
            self.base_url = 'https://api.binance.com/api'
        
        # CCXT kütüphanesini kullanarak exchange bağlantısını kur
        self.exchange = ccxt.binance({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
                'testnet': self.testnet
            }
        })
        
        if self.testnet:
            self.exchange.set_sandbox_mode(True)
        
        # Minimum miktarları ve fiyat hassasiyetini saklamak için
        self.symbol_info_cache = {}
        self.refresh_market_info()
    
    def refresh_market_info(self):
        """Sembol bilgilerini yenile"""
        try:
            markets = self.exchange.load_markets(True)  # Force reload
            logger.info(f"{len(markets)} piyasa bilgisi yüklendi")
            self.symbol_info_cache = markets
        except Exception as e:
            logger.error(f"Piyasa bilgisi yüklenirken hata: {str(e)}")
    
    def _get_symbol_precision(self, symbol: str) -> tuple:
        """Sembol için hassasiyet değerlerini al"""
        if symbol not in self.symbol_info_cache:
            logger.warning(f"{symbol} için bilgi bulunamadı, piyasa bilgilerini yenileniyor...")
            self.refresh_market_info()
        
        if symbol not in self.symbol_info_cache:
            logger.error(f"{symbol} için bilgi bulunamadı!")
            # Varsayılan değerler döndür
            return (8, 8, 5.0)
        
        market = self.symbol_info_cache[symbol]
        
        # Fiyat hassasiyeti
        price_precision = market['precision']['price']
        
        # Miktar hassasiyeti
        amount_precision = market['precision']['amount']
        
        # Minimum miktar
        min_amount = float(market['limits']['amount']['min']) if 'limits' in market and 'amount' in market['limits'] and 'min' in market['limits']['amount'] else 5.0
        
        return (price_precision, amount_precision, min_amount)
    
    def _round_step_size(self, quantity: float, step_size: float) -> float:
        """Verilen adım boyutuna göre miktarı yuvarla"""
        return float(Decimal(str(quantity)).quantize(Decimal(str(step_size)), rounding=ROUND_DOWN))
    
    async def get_account_info(self) -> Dict:
        """Hesap bilgilerini al"""
        try:
            account = await self.exchange.fetch_balance()
            return {
                'total': account['total'],
                'free': account['free'],
                'used': account['used']
            }
        except Exception as e:
            logger.error(f"Hesap bilgisi alınırken hata: {str(e)}")
            return {}
    
    async def get_symbol_price(self, symbol: str) -> float:
        """Belirli bir sembol için güncel fiyatı al"""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            logger.error(f"{symbol} fiyatı alınırken hata: {str(e)}")
            return 0.0
    
    async def buy_market(self, symbol: str, amount: float) -> Dict:
        """
        Market fiyatından satın alma işlemi
        
        Args:
            symbol: BTC/USDT gibi alınacak sembol
            amount: USDT cinsinden alınacak miktar
            
        Returns:
            İşlem detayları
        """
        try:
            # Sembol bilgilerini al
            price_precision, amount_precision, min_amount = self._get_symbol_precision(symbol)
            
            # Güncel fiyatı al ve USDT miktarını çevirme
            current_price = await self.get_symbol_price(symbol)
            
            if current_price <= 0:
                logger.error(f"{symbol} için geçerli fiyat alınamadı")
                return {'success': False, 'error': 'Geçerli fiyat alınamadı'}
            
            # USDT miktarını coin miktarına çevir
            coin_amount = amount / current_price
            
            # Minimum miktar kontrolü
            if coin_amount < min_amount:
                logger.warning(f"{symbol} için miktar çok küçük: {coin_amount} < {min_amount}")
                return {'success': False, 'error': f'Minimum miktar {min_amount} olmalıdır'}
            
            # Hassasiyet ayarı
            coin_amount = self._round_step_size(coin_amount, 10 ** -amount_precision)
            
            logger.info(f"Market alımı: {symbol}, miktar: {coin_amount}")
            
            # Market emri ver
            result = await self.exchange.create_market_buy_order(symbol, coin_amount)
            
            return {
                'success': True,
                'order_id': result['id'],
                'symbol': symbol,
                'type': 'market',
                'side': 'buy',
                'amount': coin_amount,
                'value': amount,
                'price': current_price,
                'status': result['status'],
                'timestamp': result['timestamp']
            }
            
        except Exception as e:
            logger.error(f"Market alım hatası {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def sell_market(self, symbol: str, amount: float) -> Dict:
        """
        Market fiyatından satış işlemi
        
        Args:
            symbol: BTC/USDT gibi satılacak sembol
            amount: Coin cinsinden satılacak miktar
            
        Returns:
            İşlem detayları
        """
        try:
            # Sembol bilgilerini al
            price_precision, amount_precision, min_amount = self._get_symbol_precision(symbol)
            
            # Minimum miktar kontrolü
            if amount < min_amount:
                logger.warning(f"{symbol} için miktar çok küçük: {amount} < {min_amount}")
                return {'success': False, 'error': f'Minimum miktar {min_amount} olmalıdır'}
            
            # Hassasiyet ayarı
            amount = self._round_step_size(amount, 10 ** -amount_precision)
            
            logger.info(f"Market satış: {symbol}, miktar: {amount}")
            
            # Market emri ver
            result = await self.exchange.create_market_sell_order(symbol, amount)
            
            # Güncel fiyatı al
            current_price = await self.get_symbol_price(symbol)
            
            return {
                'success': True,
                'order_id': result['id'],
                'symbol': symbol,
                'type': 'market',
                'side': 'sell',
                'amount': amount,
                'value': amount * current_price,
                'price': current_price,
                'status': result['status'],
                'timestamp': result['timestamp']
            }
            
        except Exception as e:
            logger.error(f"Market satış hatası {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def buy_limit(self, symbol: str, amount: float, price: float) -> Dict:
        """
        Limit fiyatından satın alma işlemi
        
        Args:
            symbol: BTC/USDT gibi alınacak sembol
            amount: USDT cinsinden alınacak miktar
            price: Limit fiyatı
            
        Returns:
            İşlem detayları
        """
        try:
            # Sembol bilgilerini al
            price_precision, amount_precision, min_amount = self._get_symbol_precision(symbol)
            
            # USDT miktarını coin miktarına çevir
            coin_amount = amount / price
            
            # Minimum miktar kontrolü
            if coin_amount < min_amount:
                logger.warning(f"{symbol} için miktar çok küçük: {coin_amount} < {min_amount}")
                return {'success': False, 'error': f'Minimum miktar {min_amount} olmalıdır'}
            
            # Hassasiyet ayarları
            coin_amount = self._round_step_size(coin_amount, 10 ** -amount_precision)
            price = self._round_step_size(price, 10 ** -price_precision)
            
            logger.info(f"Limit alım: {symbol}, miktar: {coin_amount}, fiyat: {price}")
            
            # Limit emri ver
            result = await self.exchange.create_limit_buy_order(symbol, coin_amount, price)
            
            return {
                'success': True,
                'order_id': result['id'],
                'symbol': symbol,
                'type': 'limit',
                'side': 'buy',
                'amount': coin_amount,
                'value': amount,
                'price': price,
                'status': result['status'],
                'timestamp': result['timestamp']
            }
            
        except Exception as e:
            logger.error(f"Limit alım hatası {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def sell_limit(self, symbol: str, amount: float, price: float) -> Dict:
        """
        Limit fiyatından satış işlemi
        
        Args:
            symbol: BTC/USDT gibi satılacak sembol
            amount: Coin cinsinden satılacak miktar
            price: Limit fiyatı
            
        Returns:
            İşlem detayları
        """
        try:
            # Sembol bilgilerini al
            price_precision, amount_precision, min_amount = self._get_symbol_precision(symbol)
            
            # Minimum miktar kontrolü
            if amount < min_amount:
                logger.warning(f"{symbol} için miktar çok küçük: {amount} < {min_amount}")
                return {'success': False, 'error': f'Minimum miktar {min_amount} olmalıdır'}
            
            # Hassasiyet ayarları
            amount = self._round_step_size(amount, 10 ** -amount_precision)
            price = self._round_step_size(price, 10 ** -price_precision)
            
            logger.info(f"Limit satış: {symbol}, miktar: {amount}, fiyat: {price}")
            
            # Limit emri ver
            result = await self.exchange.create_limit_sell_order(symbol, amount, price)
            
            return {
                'success': True,
                'order_id': result['id'],
                'symbol': symbol,
                'type': 'limit',
                'side': 'sell',
                'amount': amount,
                'value': amount * price,
                'price': price,
                'status': result['status'],
                'timestamp': result['timestamp']
            }
            
        except Exception as e:
            logger.error(f"Limit satış hatası {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """
        Emir iptali
        
        Args:
            symbol: BTC/USDT gibi sembol
            order_id: İptal edilecek emir ID'si
            
        Returns:
            İşlem detayları
        """
        try:
            logger.info(f"Emir iptal: {symbol}, emir ID: {order_id}")
            
            result = await self.exchange.cancel_order(order_id, symbol)
            
            return {
                'success': True,
                'order_id': result['id'],
                'symbol': symbol,
                'status': result['status'],
                'timestamp': result['timestamp']
            }
            
        except Exception as e:
            logger.error(f"Emir iptal hatası {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """
        Açık emirleri al
        
        Args:
            symbol: BTC/USDT gibi sembol, None ise tüm semboller
            
        Returns:
            Açık emirler listesi
        """
        try:
            logger.info(f"Açık emirleri alınıyor: {symbol if symbol else 'Tüm semboller'}")
            
            result = await self.exchange.fetch_open_orders(symbol=symbol)
            
            return result
            
        except Exception as e:
            logger.error(f"Açık emirler alınırken hata: {str(e)}")
            return []
    
    async def get_order_status(self, symbol: str, order_id: str) -> Dict:
        """
        Emir durumunu sorgula
        
        Args:
            symbol: BTC/USDT gibi sembol
            order_id: Sorgulanacak emir ID'si
            
        Returns:
            Emir detayları
        """
        try:
            logger.info(f"Emir durumu sorgulanıyor: {symbol}, emir ID: {order_id}")
            
            result = await self.exchange.fetch_order(order_id, symbol)
            
            return {
                'success': True,
                'order_id': result['id'],
                'symbol': symbol,
                'type': result['type'],
                'side': result['side'],
                'amount': result['amount'],
                'filled': result['filled'],
                'remaining': result['remaining'],
                'price': result['price'],
                'status': result['status'],
                'timestamp': result['timestamp']
            }
            
        except Exception as e:
            logger.error(f"Emir durumu sorgulanırken hata: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    async def get_order_history(self, symbol: str = None, limit: int = 20) -> List[Dict]:
        """
        Emir geçmişini al
        
        Args:
            symbol: BTC/USDT gibi sembol, None ise tüm semboller
            limit: Maksimum kayıt sayısı
            
        Returns:
            Emir geçmişi listesi
        """
        try:
            logger.info(f"Emir geçmişi alınıyor: {symbol if symbol else 'Tüm semboller'}, limit: {limit}")
            
            orders = await self.exchange.fetch_closed_orders(symbol=symbol, limit=limit)
            
            return orders
            
        except Exception as e:
            logger.error(f"Emir geçmişi alınırken hata: {str(e)}")
            return []
    
    async def get_coin_balances(self, min_value: float = 1.0) -> Dict:
        """
        Sadece belirli bir değerin üzerindeki coin bakiyelerini al
        
        Args:
            min_value: Minimum USDT değeri
            
        Returns:
            Coin bakiyeleri
        """
        try:
            logger.info(f"Coin bakiyeleri alınıyor (min {min_value} USDT)")
            
            account = await self.exchange.fetch_balance()
            result = {}
            
            for currency, balance in account['total'].items():
                if balance <= 0:
                    continue
                
                try:
                    # USDT değerini hesapla
                    if currency == 'USDT':
                        value = balance
                    else:
                        try:
                            ticker = await self.exchange.fetch_ticker(f"{currency}/USDT")
                            value = balance * ticker['last']
                        except:
                            # USDT çifti yoksa BTC üzerinden hesapla
                            ticker_btc = await self.exchange.fetch_ticker(f"{currency}/BTC")
                            ticker_btc_usdt = await self.exchange.fetch_ticker("BTC/USDT")
                            value = balance * ticker_btc['last'] * ticker_btc_usdt['last']
                    
                    # Minimum değer kontrolü
                    if value >= min_value:
                        result[currency] = {
                            'total': balance,
                            'free': account['free'].get(currency, 0),
                            'used': account['used'].get(currency, 0),
                            'value_usdt': value
                        }
                except Exception as e:
                    logger.warning(f"{currency} değeri hesaplanırken hata: {str(e)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Coin bakiyeleri alınırken hata: {str(e)}")
            return {}

# Test fonksiyonu
async def test_trader():
    trader = BinanceTrader()
    
    # Hesap bilgilerini al
    account_info = await trader.get_account_info()
    print("Hesap Bilgileri:", json.dumps(account_info, indent=2))
    
    # Bitcoin fiyatını al
    btc_price = await trader.get_symbol_price("BTC/USDT")
    print(f"Bitcoin Fiyatı: ${btc_price}")
    
    # Bakiyeleri al
    balances = await trader.get_coin_balances()
    print("Coin Bakiyeleri:", json.dumps(balances, indent=2))
    
    # Test alım-satım işlemleri (testnet ile gerçekleştirilebilir)
    if trader.testnet:
        # Market alım emri
        buy_result = await trader.buy_market("BTC/USDT", 15)  # 15 USDT ile BTC al
        print("Market Alım Sonucu:", json.dumps(buy_result, indent=2))
        
        if buy_result.get('success', False):
            # 10 saniye bekle
            time.sleep(10)
            
            # Alınan BTC'yi sat
            coin_amount = buy_result.get('amount', 0)
            sell_result = await trader.sell_market("BTC/USDT", coin_amount)
            print("Market Satış Sonucu:", json.dumps(sell_result, indent=2))

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_trader())
