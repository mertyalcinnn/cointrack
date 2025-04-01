import pandas as pd
import numpy as np
import ccxt
from openai import AsyncOpenAI
from bs4 import BeautifulSoup
import aiohttp
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from typing import Dict, Optional
from anthropic import Anthropic
from .price_analysis import PriceAnalyzer
from .whale_tracker import WhaleTracker
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice

class SignalAnalyzer:
    def __init__(self):
        """Initialize SignalAnalyzer"""
        load_dotenv()
        print("\n🔄 SignalAnalyzer başlatılıyor...")
        self.last_api_call = None
        self.min_delay = 60  # saniye cinsinden minimum bekleme süresi
        self.initialize_apis()
        self.price_analyzer = PriceAnalyzer()
        self.anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.last_signals = {}
        self.whale_tracker = WhaleTracker()
        print("✅ SignalAnalyzer başlatıldı!")

    def initialize_apis(self):
        """API'leri başlat"""
        self.openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.exchange = ccxt.binance()
        self.news_sources = [
            'https://cointelegraph.com',
            'https://coindesk.com',
            'https://cryptonews.com',
            'https://decrypt.co'
        ]
        
        # TradingView endpoints
        self.trading_view_intervals = {
            '15m': 'BINANCE:BTCUSDT|15',
            '1h': 'BINANCE:BTCUSDT|60',
            '4h': 'BINANCE:BTCUSDT|240',
            '1d': 'BINANCE:BTCUSDT|1D'
        }

    async def get_tradingview_analysis(self, symbol):
        """TradingView'dan teknik analiz verilerini çek"""
        try:
            print(f"\n📊 {symbol} için TradingView analizi yapılıyor...")
            symbol_formatted = f"BINANCE:{symbol.replace('/', '')}"
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json'
                }
                
                analysis = {}
                for interval, endpoint in self.trading_view_intervals.items():
                    endpoint = endpoint.replace('BTCUSDT', symbol.replace('/', ''))
                    try:
                        async with session.get(f'https://scanner.tradingview.com/crypto/scan?symbol={endpoint}', headers=headers) as response:
                            if response.status == 200:
                                data = await response.json()
                                analysis[interval] = data
                                print(f"✅ {interval} verisi alındı")
                    except Exception as e:
                        print(f"⚠️ TradingView {interval} hatası: {e}")
                        continue
                
                return analysis
        except Exception as e:
            print(f"❌ TradingView analiz hatası: {e}")
            return None

    async def get_technical_analysis(self, symbol, timeframe='15m'):
        """Teknik analiz verilerini hesapla"""
        try:
            print(f"\n📈 {symbol} için teknik analiz yapılıyor...")
            
            # OHLCV verilerini al
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=100)
            print("✅ OHLCV verileri alındı")
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # İndikatörleri hesapla
            print("🔄 İndikatörler hesaplanıyor...")
            
            # RSI hesaplama
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            # EMA hesaplama
            df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
            
            # MACD hesaplama
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            # Bollinger Bands
            df['BB_middle'] = df['close'].rolling(window=20).mean()
            df['BB_upper'] = df['BB_middle'] + 2 * df['close'].rolling(window=20).std()
            df['BB_lower'] = df['BB_middle'] - 2 * df['close'].rolling(window=20).std()
            
            print("✅ Teknik analiz tamamlandı")
            return df.tail(1).to_dict('records')[0]
        except Exception as e:
            print(f"❌ Teknik analiz hatası: {e}")
            return None
            
    async def get_market_sentiment(self, symbol):
        """Piyasa duyarlılığını analiz et"""
        print(f"\n📰 {symbol} için piyasa duyarlılığı analizi yapılıyor...")
        
        # Coin adını hazırla (BTC/USDT -> bitcoin)
        coin_name = symbol.split('/')[0].lower()
        if coin_name == 'btc':
            coin_name = 'bitcoin'
        elif coin_name == 'eth':
            coin_name = 'ethereum'

        news_texts = []
        price_mentions = []
        predictions = []
        sentiment_scores = []

        async with aiohttp.ClientSession() as session:
            for source in self.news_sources:
                try:
                    print(f"🔄 {source} kontrol ediliyor...")
                    async with session.get(source) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Başlıkları ve metinleri ara
                            for text in soup.find_all(['h1', 'h2', 'p']):
                                text_content = text.get_text().lower()
                                if coin_name in text_content:
                                    news_texts.append(text_content)
                                    
                                    # Fiyat tahminlerini ara
                                    if any(word in text_content for word in ['price', 'predict', 'forecast', 'target']):
                                        predictions.append(text_content)
                                    
                                    # Pozitif/negatif sentiment
                                    if any(word in text_content for word in ['bullish', 'surge', 'rise', 'up']):
                                        sentiment_scores.append(1)
                                    elif any(word in text_content for word in ['bearish', 'drop', 'fall', 'down']):
                                        sentiment_scores.append(-1)
                                    else:
                                        sentiment_scores.append(0)
                    print(f"✅ {source} tamamlandı")
                except Exception as e:
                    print(f"⚠️ Haber kaynağı hatası {source}: {e}")
                    continue

        # Sonuçları hazırla
        sentiment_data = {
            'news_count': len(news_texts),
            'latest_news': news_texts[-5:] if news_texts else [],  # Son 5 haber
            'price_predictions': predictions,
            'overall_sentiment': sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0,
            'raw_texts': news_texts
        }

        print(f"✅ {len(news_texts)} haber bulundu")
        return sentiment_data

    async def analyze_with_gpt(self, technical_data, sentiment_data, tradingview_data, symbol):
        """Teknik analiz temelinde sinyal üret"""
        print(f"\n📊 {symbol} için teknik analiz yapılıyor...")
        try:
        
            # RSI analizi
            rsi = technical_data.get('RSI', 50)
            macd = technical_data.get('MACD', 0)
            macd_signal = technical_data.get('MACD_Signal', 0)
            ema20 = technical_data.get('EMA20', 0)
            ema50 = technical_data.get('EMA50', 0)
            close = technical_data.get('close', 0)
            
            # Sinyal analizi
            signal_type = 'hold'
            risk_level = 5
            
            # RSI tabanlı analiz
            if rsi < 30:
                signal_type = 'buy'
                risk_level = max(3, risk_level - 2)
            elif rsi > 70:
                signal_type = 'sell'
                risk_level = min(8, risk_level + 2)
            
            # MACD tabanlı analiz
            if macd > macd_signal:
                if signal_type == 'hold':
                    signal_type = 'buy'
                risk_level = max(3, risk_level - 1)
            elif macd < macd_signal:
                if signal_type == 'hold':
                    signal_type = 'sell'
                risk_level = min(8, risk_level + 1)
            
            # EMA tabanlı analiz
            if ema20 > ema50:
                if signal_type == 'hold':
                    signal_type = 'buy'
            elif ema20 < ema50:
                if signal_type == 'hold':
                    signal_type = 'sell'
            
            # Hedef ve stop-loss hesaplama
            price_movement = 0.02  # %2'lik hedef hareket
            if signal_type == 'buy':
                targets = [round(close * (1 + price_movement), 2), 
                          round(close * (1 + price_movement * 2), 2)]
                stop_loss = round(close * (1 - price_movement), 2)
            elif signal_type == 'sell':
                targets = [round(close * (1 - price_movement), 2),
                          round(close * (1 - price_movement * 2), 2)]
                stop_loss = round(close * (1 + price_movement), 2)
            else:
                targets = []
                stop_loss = None
            
            # Piyasa duyarlılığını kontrol et
            sentiment_score = sentiment_data.get('overall_sentiment', 0)
            if abs(sentiment_score) > 0.5:
                risk_level = min(max(2, risk_level + int(sentiment_score * 2)), 9)
            
            analysis = {
                'signal_type': signal_type,
                'risk_level': risk_level,
                'targets': targets,
                'stop_loss': stop_loss,
                'analysis': f"Teknik analiz: RSI={rsi:.1f}, MACD Farkı={macd-macd_signal:.2f}, EMA Farkı={ema20-ema50:.2f}"
            }
            
            print("✅ Teknik analiz tamamlandı")
            return analysis
            
        except Exception as e:
            print(f"❌ Analiz hatası: {str(e)}")
            return {
                'signal_type': 'hold',
                'risk_level': 5,
                'targets': [],
                'stop_loss': None,
                'analysis': 'Teknik analiz hatası'
            }

    async def get_market_analysis(self, symbol: str) -> Dict:
        """Detaylı piyasa analizi"""
        try:
            # Fiyat ve teknik analiz
            data = await self.price_analyzer.get_price_data(symbol)
            if 'error' in data:
                raise Exception(data['error'])
            
            # Balina analizi
            whale_data = await self.whale_tracker.analyze_whale_activity(symbol)
            if 'error' in whale_data:
                print(f"Balina analizi hatası: {whale_data['error']}")
                whale_data = None
                
            # Multi-timeframe verilerinden 1h kullan
            timeframe_data = data['multi_timeframe']['1h']
            market_status = data['market_status']
            strategies = data['trading_strategies']
            volume_profile = data['volume_profile']
            fib_levels = data['fibonacci_levels']
            orderbook = data['orderbook']
            
            # Kaldıraç önerisi hesapla
            leverage_suggestion = self._calculate_leverage_suggestion(
                timeframe_data['volatility'],
                timeframe_data['technical']['rsi'],
                market_status
            )
            
            analysis_text = f"""💰 {symbol} Detaylı Analiz

💵 Fiyat: ${timeframe_data['close']:,.2f}
📊 Değişim: %{timeframe_data['price_change']:.2f}
📈 Volatilite: %{timeframe_data['volatility']:.2f}

🎯 Kaldıraç Önerisi: {leverage_suggestion['level']}x
ℹ️ Sebep: {leverage_suggestion['reason']}

⚠️ Risk Durumu:
• Volatilite: {market_status['volatility']}
• Hacim: {market_status['volume']}
• Trend Gücü: {market_status['strength']}/5

📊 Teknik Göstergeler (1H):
• RSI: {timeframe_data['technical']['rsi']:.2f}
• MACD: {'Pozitif' if timeframe_data['technical']['macd']['histogram'] > 0 else 'Negatif'}
• Stochastic: K({timeframe_data['technical']['stochastic']['k']:.1f}) D({timeframe_data['technical']['stochastic']['d']:.1f})

🎯 Önemli Seviyeler:
• POC: ${volume_profile['poc']['price_level']}
• Direnç: ${orderbook['resistance']}
• Destek: ${orderbook['support']}

📈 Fibonacci Seviyeleri:
• 0.618: ${fib_levels['level_0.618']}
• 0.5: ${fib_levels['level_0.5']}
• 0.382: ${fib_levels['level_0.382']}

💡 Önerilen Strateji: {strategies['recommended']['name'].upper()}
{self._format_strategy_signals(strategies['recommended']['details'])}

{self._get_trading_recommendation(timeframe_data, market_status, leverage_suggestion)}

⚠️ Risk Uyarısı: Kaldıraçlı işlemler yüksek risk içerir."""

            # Balina analizi ekle
            if whale_data and 'error' not in whale_data:
                whale_analysis = f"""
🐋 Balina Aktivitesi:
• Son 24s İşlem: {whale_data['whale_count']} balina
• Alım/Satım Oranı: {whale_data['buy_sell_ratio']:.2f}
• Baskı Yönü: {whale_data['pressure']['pressure']}
• Akümülasyon: {whale_data['accumulation']['trend']}

⚠️ Alarm Seviyesi: {whale_data['alert_level']['level']}
{chr(10).join('• ' + signal for signal in whale_data['alert_level']['signals'])}

🔍 Son Balina Hareketleri:"""
                
                for move in whale_data['recent_moves']:
                    whale_analysis += f"""
• {move['time']} - {move['side']} ${move['value']:,.0f}"""
                
                analysis_text += f"\n{whale_analysis}"
            
            return {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "analysis": analysis_text
            }
            
        except Exception as e:
            print(f"Analiz hatası ({symbol}): {str(e)}")
            return {
                "symbol": symbol,
                "error": str(e)
            }

    def _calculate_leverage_suggestion(self, volatility: float, rsi: float, market_status: Dict) -> Dict:
        """Kaldıraç önerisi hesapla"""
        if volatility > 5 or rsi > 75 or rsi < 25:
            return {
                'level': 2,
                'reason': '⚠️ Yüksek volatilite/aşırı alım-satım'
            }
        elif market_status['volatility'] == 'HIGH' or market_status['volume'] == 'HIGH':
            return {
                'level': 5,
                'reason': '📊 Yüksek piyasa aktivitesi'
            }
        elif market_status['strength'] >= 4:
            return {
                'level': 10,
                'reason': '✅ Güçlü trend'
            }
        else:
            return {
                'level': 3,
                'reason': '📈 Normal piyasa koşulları'
            }

    def _format_strategy_signals(self, strategy: Dict) -> str:
        """Strateji sinyallerini formatla"""
        if 'signals' not in strategy:
            return "Sinyal bulunamadı"
        return '\n'.join(f"• {signal}" for signal in strategy['signals'])

    def _get_trading_recommendation(self, timeframe_data: Dict, market_status: Dict, leverage: Dict) -> str:
        """İşlem önerisi oluştur"""
        if market_status['volatility'] == 'HIGH':
            return "⚠️ Yüksek volatilite! İşlem önerilmez."
        
        trend = market_status['trend']
        bb = timeframe_data['technical']['bollinger']
        
        if trend == 'BULLISH' and timeframe_data['technical']['rsi'] < 70:
            return f"""💚 LONG POZİSYON
• Kaldıraç: {leverage['level']}x
• Hedef 1: ${bb['upper']}
• Stop-loss: ${bb['lower']}
• Trend Yönü: 📈 Yükseliş"""
        
        elif trend == 'BEARISH' and timeframe_data['technical']['rsi'] > 30:
            return f"""❌ SHORT POZİSYON
• Kaldıraç: {leverage['level']}x
• Hedef 1: ${bb['lower']}
• Stop-loss: ${bb['upper']}
• Trend Yönü: �� Düşüş"""
        
        else:
            return "⏳ Trend belirsiz. İşlem önerilmez."

    def format_analysis_message(self, analysis: Dict) -> str:
        """
        Claude analizini Telegram mesajına dönüştürür
        """
        try:
            market_data = analysis['market_data']
            
            header = f"""🔍 {analysis['symbol']} Analiz

💰 Fiyat: ${market_data['current_price']:,.2f}
📊 Değişim: {market_data['price_change']:.2f}%
📈 Hacim Değişimi: {market_data.get('volume_change', 0):.2f}%

{'-' * 30}

"""
            # Claude'un analizini doğrudan ekle
            full_message = header + analysis['analysis']
            
            # Zaman damgası ekle
            full_message += f"\n\n⏰ {datetime.now().strftime('%H:%M:%S')}"
            
            return full_message

        except Exception as e:
            return f"❌ Analiz mesajı oluşturma hatası: {str(e)}"

    async def generate_signal(self, symbol: str) -> Optional[Dict]:
        """
        Sinyal oluştur ve analiz yap
        """
        try:
            # Market analizi al
            analysis = await self.get_market_analysis(symbol)
            
            # Sinyal oluştur
            signal = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'analysis': analysis
            }
            
            return signal
            
        except Exception as e:
            print(f"Sinyal oluşturma hatası ({symbol}): {str(e)}")
            return None

    async def analyze(self, symbol: str, df: pd.DataFrame) -> Dict:
        """Teknik analiz yap"""
        try:
            # RSI
            rsi = RSIIndicator(df['close'], window=14)
            current_rsi = float(rsi.rsi().iloc[-1])
            
            # EMA
            ema20 = float(EMAIndicator(df['close'], window=20).ema_indicator().iloc[-1])
            ema50 = float(EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1])
            
            # MACD
            macd = MACD(df['close'])
            current_macd = float(macd.macd().iloc[-1])
            current_signal = float(macd.macd_signal().iloc[-1])
            
            # VWAP
            vwap = float(VolumeWeightedAveragePrice(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                volume=df['volume']
            ).volume_weighted_average_price().iloc[-1])
            
            # Hacim değişimi
            recent_vol = float(df['volume'].iloc[-3:].mean())
            prev_vol = float(df['volume'].iloc[-6:-3].mean())
            volume_change = ((recent_vol - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0.0
            
            # Fiyat değişimi
            price_change = float(((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100))
            
            return {
                'rsi': current_rsi,
                'ema20': ema20,
                'ema50': ema50,
                'macd': current_macd,
                'macd_signal': current_signal,
                'vwap': vwap,
                'volume_change': volume_change,
                'price_change': price_change,
                'current_price': float(df['close'].iloc[-1])
            }
            
        except Exception as e:
            print(f"Analiz hatası {symbol}: {str(e)}")
            return None