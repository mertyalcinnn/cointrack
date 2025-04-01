import aiohttp
from typing import Dict, List
from datetime import datetime
import asyncio
from binance.client import Client
from binance.exceptions import BinanceAPIException
from deep_translator import GoogleTranslator

class NewsTracker:
    def __init__(self):
        # Ücretsiz haber API'ları
        self.news_endpoints = {
            'crypto_compare': 'https://min-api.cryptocompare.com/data/v2/news/?lang=EN',
            'fear_greed': 'https://api.alternative.me/fng/'
        }
        # Binance API istemcisi
        self.binance_client = Client(
            'j1xKfAelSYZ6u49FleNOSOXURBjuv3wHN8tASQPbq7PJFBCWrZQKpwh9LomMY4Rg',
            'iCOpNf9jRxzqqAW7uWx694B7c5lYGupjdFqPV5BDjr4ktwqX8HsCzlRgP6hYhxlm'
        )
        self.translator = GoogleTranslator(source='en', target='tr')
        
        # Korku & Açgözlülük endeksi için Türkçe karşılıklar
        self.sentiment_tr = {
            'Extreme Fear': 'Aşırı Korku',
            'Fear': 'Korku',
            'Neutral': 'Nötr',
            'Greed': 'Açgözlülük',
            'Extreme Greed': 'Aşırı Açgözlülük'
        }

    async def translate_text(self, text: str) -> str:
        """Metni Türkçe'ye çevir"""
        try:
            return self.translator.translate(text)
        except Exception as e:
            print(f"Çeviri hatası: {str(e)}")
            return text

    async def fetch_news(self) -> Dict:
        """Kripto haberlerini ve Binance verilerini topla"""
        try:
            news_data = {
                'market_news': [],
                'market_sentiment': None,
                'binance_info': {
                    'price_alerts': [],
                    'top_gainers': [],
                    'top_losers': []
                }
            }
            
            # Binance'den önemli fiyat hareketlerini al
            try:
                # 24 saatlik fiyat değişimlerini al
                tickers = self.binance_client.get_ticker()
                
                # Sadece USDT çiftlerini filtrele
                usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
                
                # Hacme göre sırala
                volume_filtered = [
                    t for t in usdt_pairs 
                    if float(t['quoteVolume']) > 10000000  # 10M USD üzeri hacim
                ]
                
                # Yükselenler
                gainers = sorted(
                    volume_filtered,
                    key=lambda x: float(x['priceChangePercent']),
                    reverse=True
                )[:5]
                
                # Düşenler
                losers = sorted(
                    volume_filtered,
                    key=lambda x: float(x['priceChangePercent'])
                )[:5]
                
                news_data['binance_info']['top_gainers'] = gainers
                news_data['binance_info']['top_losers'] = losers
                
            except BinanceAPIException as e:
                print(f"Binance veri hatası: {str(e)}")

            # CryptoCompare haberleri
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(self.news_endpoints['crypto_compare']) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data and 'Data' in data:
                                for news in data['Data'][:5]:
                                    # Başlığı Türkçe'ye çevir
                                    translated_title = await self.translate_text(news.get('title', 'Başlık yok'))
                                    news_data['market_news'].append({
                                        'title': translated_title,
                                        'source': news.get('source', 'Kaynak belirtilmemiş'),
                                        'url': news.get('url', '#'),
                                        'time': datetime.fromtimestamp(news.get('published_on', 0)).strftime('%H:%M:%S')
                                    })
                except Exception as e:
                    print(f"CryptoCompare hata: {str(e)}")

                # Korku & Açgözlülük endeksi
                try:
                    async with session.get(self.news_endpoints['fear_greed']) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data and 'data' in data and data['data']:
                                value_class = data['data'][0].get('value_classification', 'Bilinmiyor')
                                news_data['market_sentiment'] = {
                                    'value': data['data'][0].get('value', 'N/A'),
                                    'value_classification': self.sentiment_tr.get(value_class, value_class)
                                }
                except Exception as e:
                    print(f"Fear & Greed hata: {str(e)}")

            return news_data

        except Exception as e:
            print(f"Genel haber toplama hatası: {str(e)}")
            return {
                'market_news': [],
                'market_sentiment': None,
                'binance_info': {
                    'price_alerts': [],
                    'top_gainers': [],
                    'top_losers': []
                }
            }

    async def format_news_message(self, news_data: Dict) -> str:
        """Haber verilerini mesaj formatına çevir"""
        try:
            message = "📰 KRİPTO HABER BÜLTENİ\n\n"

            # En Çok Yükselenler
            if news_data['binance_info']['top_gainers']:
                message += "📈 EN ÇOK YÜKSELENLER (24s):\n"
                for coin in news_data['binance_info']['top_gainers']:
                    message += f"""• {coin['symbol']}
  Yükseliş: %{float(coin['priceChangePercent']):.2f}
  Güncel Fiyat: ${float(coin['lastPrice']):.4f}
  İşlem Hacmi: ${float(coin['quoteVolume']):,.0f}\n"""
                message += "\n"

            # En Çok Düşenler
            if news_data['binance_info']['top_losers']:
                message += "📉 EN ÇOK DÜŞENLER (24s):\n"
                for coin in news_data['binance_info']['top_losers']:
                    message += f"""• {coin['symbol']}
  Düşüş: %{float(coin['priceChangePercent']):.2f}
  Güncel Fiyat: ${float(coin['lastPrice']):.4f}
  İşlem Hacmi: ${float(coin['quoteVolume']):,.0f}\n"""
                message += "\n"

            # Piyasa Duygusu
            if news_data.get('market_sentiment'):
                sentiment = news_data['market_sentiment']
                message += f"""📊 KORKU & AÇGÖZLÜLÜK ENDEKSİ
• Değer: {sentiment['value']}
• Durum: {sentiment['value_classification']}\n\n"""

            # Piyasa Haberleri
            if news_data.get('market_news'):
                message += "📈 KRİPTO HABERLERİ:\n"
                for news in news_data['market_news']:
                    message += f"""• {news['title']}
Kaynak: {news['source']}
Saat: {news['time']}
🔗 {news['url']}\n\n"""

            message += f"\n🔄 Son Güncelleme: {datetime.now().strftime('%H:%M:%S')}"
            return message

        except Exception as e:
            return f"❌ Haber formatlanırken hata oluştu: {str(e)}"

    def _is_important_news(self, title: str) -> bool:
        """Haberin önemini kontrol et"""
        important_keywords = [
            'binance', 'listing', 'hack', 'sec', 
            'regulation', 'bitcoin', 'ethereum',
            'breakout', 'crash', 'pump', 'dump'
        ]
        
        title_lower = title.lower()
        return any(keyword in title_lower for keyword in important_keywords) 