from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from enum import Enum
from anthropic import Anthropic
import os
from dotenv import load_dotenv
import json
import ccxt

class TrendType(Enum):
    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONGLY_BEARISH = "STRONGLY_BEARISH"

class TimePeriod(Enum):
    VERY_SHORT = ("VERY_SHORT", 4)   # 4 saat
    SHORT = ("SHORT", 24)            # 24 saat
    MEDIUM = ("MEDIUM", 168)         # 1 hafta
    LONG = ("LONG", 720)            # 1 ay
    VERY_LONG = ("VERY_LONG", 2160)  # 3 ay

    def __init__(self, name: str, hours: int):
        self.hours = hours

class PriceAnalyzer:
    def __init__(self):
        load_dotenv()
        self.anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.trends = {
            'SHORT': 24,  # 24 saat
            'MEDIUM': 168,  # 1 hafta
            'LONG': 720   # 1 ay
        }
        self.trend_thresholds = {
            'STRONGLY_BULLISH': {'price': 5, 'rsi': 70},
            'BULLISH': {'price': 1, 'rsi': 55},
            'STRONGLY_BEARISH': {'price': -5, 'rsi': 30},
            'BEARISH': {'price': -1, 'rsi': 45}
        }
        self.exchange = ccxt.binance()
        self.leverage_levels = {
            'LOW': 2,
            'MEDIUM': 5,
            'HIGH': 10,
            'EXTREME': 20
        }
        self.timeframes = ['15m', '1h', '4h', '1d']
    
    def _determine_trend(self, price_change: float, current_rsi: float) -> str:
        """
        Fiyat değişimi ve RSI değerine göre trend belirler
        """
        if price_change > self.trend_thresholds['STRONGLY_BULLISH']['price'] and current_rsi > self.trend_thresholds['STRONGLY_BULLISH']['rsi']:
            return TrendType.STRONGLY_BULLISH.value
        elif price_change > self.trend_thresholds['BULLISH']['price'] and current_rsi > self.trend_thresholds['BULLISH']['rsi']:
            return TrendType.BULLISH.value
        elif price_change < self.trend_thresholds['STRONGLY_BEARISH']['price'] and current_rsi < self.trend_thresholds['STRONGLY_BEARISH']['rsi']:
            return TrendType.STRONGLY_BEARISH.value
        elif price_change < self.trend_thresholds['BEARISH']['price'] and current_rsi < self.trend_thresholds['BEARISH']['rsi']:
            return TrendType.BEARISH.value
        return TrendType.NEUTRAL.value

    def _calculate_confidence(self, price_change: float, current_rsi: float, volatility: float) -> float:
        """
        Trend güven skorunu hesaplar
        """
        rsi_confidence = abs(current_rsi - 50) / 50
        price_confidence = min(abs(price_change) / 5, 1.0)
        volatility_factor = max(0, 1 - (volatility / 10))  # Yüksek volatilite düşük güven
        
        confidence = (rsi_confidence + price_confidence) * volatility_factor
        return min(confidence, 1.0)  # 0-1 arasında normalize et

    async def analyze_price_trend(self, price_data: List[Dict], period: str = 'SHORT') -> Dict:
        """Fiyat verilerini analiz eder ve gelişmiş trend bilgisi döner"""
        try:
            if not price_data or len(price_data) < 2:
                return {
                    'trend': TrendType.NEUTRAL.value,
                    'confidence': 0,
                    'price_change': 0,
                    'period': period
                }
            
            # DataFrame oluştur
            df = pd.DataFrame(price_data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            # Son period saatlik veriyi al
            hours = self.trends.get(period, self.trends['SHORT'])
            cutoff = datetime.now() - timedelta(hours=hours)
            df = df[df['timestamp'] > cutoff]
            
            # Temel hesaplamalar
            start_price = df['close'].iloc[0]
            end_price = df['close'].iloc[-1]
            price_change = ((end_price - start_price) / start_price) * 100
            
            # RSI hesaplama
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            
            # Volatilite hesaplama
            returns = df['close'].pct_change()
            volatility = returns.std() * np.sqrt(24) * 100
            
            # Trend belirleme
            trend = self._determine_trend(price_change, current_rsi)
            confidence = self._calculate_confidence(price_change, current_rsi, volatility)
            
            return {
                'trend': trend,
                'confidence': round(confidence, 2),
                'price_change': round(price_change, 2),
                'period': period,
                'rsi': round(current_rsi, 2),
                'volatility': round(volatility, 2),
                'current_price': round(end_price, 8),
                'volume': float(df['volume'].iloc[-1])
            }
            
        except Exception as e:
            print(f"Fiyat analiz hatası: {str(e)}")
            return {
                'trend': TrendType.NEUTRAL.value,
                'confidence': 0,
                'price_change': 0,
                'period': period
            }

    def detect_breakout(self, 
                       price_data: List[Dict],
                       threshold: float = 5.0) -> Optional[Dict]:
        """
        Fiyat kırılımlarını tespit eder
        """
        if not price_data or len(price_data) < 24:
            return None
            
        try:
            df = pd.DataFrame(price_data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            # Bollinger Bands
            df['MA20'] = df['price'].rolling(window=20).mean()
            df['SD20'] = df['price'].rolling(window=20).std()
            df['Upper'] = df['MA20'] + (df['SD20'] * 2)
            df['Lower'] = df['MA20'] - (df['SD20'] * 2)
            
            # Son fiyat kontrolü
            last_price = df.iloc[-1]['price']
            upper_band = df.iloc[-1]['Upper']
            lower_band = df.iloc[-1]['Lower']
            
            # Kırılım kontrolü
            if last_price > upper_band:
                change = ((last_price - upper_band) / upper_band) * 100
                if change >= threshold:
                    return {
                        'type': 'UPWARD_BREAKOUT',
                        'magnitude': round(change, 2),
                        'price': last_price,
                        'timestamp': datetime.now().isoformat()
                    }
            elif last_price < lower_band:
                change = ((lower_band - last_price) / lower_band) * 100
                if change >= threshold:
                    return {
                        'type': 'DOWNWARD_BREAKOUT',
                        'magnitude': round(change, 2),
                        'price': last_price,
                        'timestamp': datetime.now().isoformat()
                    }
            
            return None
            
        except Exception as e:
            print(f"Kırılım analizi hatası: {str(e)}")
            return None

    def analyze_market_sentiment(self, df: pd.DataFrame) -> Dict:
        """
        Piyasa duyarlılığını analiz eder
        """
        try:
            # RSI analizi
            delta = df['price'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]

            # Volatilite hesaplama
            returns = df['price'].pct_change()
            volatility = returns.std() * np.sqrt(24) * 100

            # MACD hesaplama
            exp1 = df['price'].ewm(span=12, adjust=False).mean()
            exp2 = df['price'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            macd_hist = macd - signal
            
            # Son fiyat değişimi
            price_change = ((df['price'].iloc[-1] - df['price'].iloc[0]) / df['price'].iloc[0]) * 100

            # Duyarlılık analizi
            sentiment_score = 0
            sentiment_factors = []

            # RSI bazlı duyarlılık
            if current_rsi > 70:
                sentiment_score -= 2
                sentiment_factors.append("Aşırı alım bölgesi")
            elif current_rsi < 30:
                sentiment_score += 2
                sentiment_factors.append("Aşırı satım bölgesi")
            elif current_rsi > 60:
                sentiment_score -= 1
                sentiment_factors.append("Yüksek RSI")
            elif current_rsi < 40:
                sentiment_score += 1
                sentiment_factors.append("Düşük RSI")

            # MACD bazlı duyarlılık
            if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0:
                sentiment_score += 2
                sentiment_factors.append("MACD yukarı kesişim")
            elif macd_hist.iloc[-1] < 0 and macd_hist.iloc[-2] >= 0:
                sentiment_score -= 2
                sentiment_factors.append("MACD aşağı kesişim")

            # Volatilite bazlı duyarlılık
            if volatility > 5:
                sentiment_factors.append("Yüksek volatilite")
            elif volatility < 2:
                sentiment_factors.append("Düşük volatilite")

            # Fiyat değişimi bazlı duyarlılık
            if price_change > 5:
                sentiment_score += 1
                sentiment_factors.append("Güçlü yükseliş")
            elif price_change < -5:
                sentiment_score -= 1
                sentiment_factors.append("Güçlü düşüş")

            # Duyarlılık seviyesi belirleme
            def get_sentiment_level(score):
                if score >= 3:
                    return "ÇOK OLUMLU"
                elif score >= 1:
                    return "OLUMLU"
                elif score <= -3:
                    return "ÇOK OLUMSUZ"
                elif score <= -1:
                    return "OLUMSUZ"
                else:
                    return "NÖTR"

            sentiment_level = get_sentiment_level(sentiment_score)

            return {
                "sentiment": {
                    "level": sentiment_level,
                    "score": sentiment_score,
                    "factors": sentiment_factors,
                    "details": {
                        "rsi": round(current_rsi, 2),
                        "volatility": round(volatility, 2),
                        "price_change": round(price_change, 2),
                        "macd": {
                            "value": round(macd.iloc[-1], 2),
                            "signal": round(signal.iloc[-1], 2),
                            "histogram": round(macd_hist.iloc[-1], 2)
                        }
                    }
                }
            }

        except Exception as e:
            print(f"Duyarlılık analizi hatası: {str(e)}")
            return {
                "sentiment": {
                    "level": "NÖTR",
                    "score": 0,
                    "factors": ["Analiz hatası"],
                    "details": {}
                }
            }

    async def get_market_analysis(self, symbol: str) -> Dict:
        """Piyasa analizi yapar"""
        try:
            # OHLCV verilerini al
            ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=96)  # Son 24 saat
            if not ohlcv or len(ohlcv) < 2:
                raise Exception(f"{symbol} için yeterli veri yok")

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Ticker verilerini al
            ticker = await self.exchange.fetch_ticker(symbol)
            if not ticker or 'last' not in ticker:
                raise Exception(f"{symbol} için fiyat verisi alınamadı")

            current_price = ticker['last']
            price_change = ticker.get('percentage', 0)
            volume = ticker.get('quoteVolume', 0)

            # Teknik analiz
            analysis = self._calculate_indicators(df)
            
            return {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'price': {
                    'current': current_price,
                    'change': price_change,
                    'high_24h': ticker.get('high', 0),
                    'low_24h': ticker.get('low', 0)
                },
                'volume': volume,
                'technical': analysis,
                'status': 'success'
            }

        except Exception as e:
            print(f"Piyasa analiz hatası {symbol}: {str(e)}")
            return {
                'symbol': symbol,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        """Teknik göstergeleri hesapla"""
        try:
            if df.empty or len(df) < 2:
                raise Exception("Yetersiz veri")

            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            # MACD
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9).mean()

            # Bollinger Bands
            sma = df['close'].rolling(window=20).mean()
            std = df['close'].rolling(window=20).std()
            upper_band = sma + (std * 2)
            lower_band = sma - (std * 2)

            # Volume Change
            recent_volume = df['volume'].iloc[-3:].mean()
            prev_volume = df['volume'].iloc[-6:-3].mean()
            volume_change = ((recent_volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0

            return {
                'rsi': float(rsi.iloc[-1]),
                'macd': {
                    'macd': float(macd.iloc[-1]),
                    'signal': float(signal.iloc[-1]),
                    'hist': float((macd - signal).iloc[-1])
                },
                'bb': {
                    'upper': float(upper_band.iloc[-1]),
                    'middle': float(sma.iloc[-1]),
                    'lower': float(lower_band.iloc[-1])
                },
                'volume_change': float(volume_change)
            }

        except Exception as e:
            print(f"Gösterge hesaplama hatası: {str(e)}")
            return {
                'rsi': 50,
                'macd': {'macd': 0, 'signal': 0, 'hist': 0},
                'bb': {'upper': 0, 'middle': 0, 'lower': 0},
                'volume_change': 0
            }

    def format_analysis_message(self, analysis: Dict) -> str:
        """
        Claude analizini Telegram mesajına dönüştürür
        """
        try:
            market_data = analysis['market_data']
            
            header = f"""🔍 {analysis['symbol']} Analiz

💰 Fiyat: ${market_data['current_price']:,.2f}
📊 Değişim: {market_data['price_change']:.2f}%
📈 Hacim Değişimi: {market_data['volume_change']:.2f}%

{'-' * 30}

"""
            # Claude'un analizini doğrudan ekle
            full_message = header + analysis['claude_analysis']
            
            # Zaman damgası ekle
            full_message += f"\n\n⏰ {datetime.now().strftime('%H:%M:%S')}"
            
            return full_message

        except Exception as e:
            return f"❌ Analiz mesajı oluşturma hatası: {str(e)}"

    async def get_price_data(self, symbol: str) -> Dict:
        try:
            # Çoklu zaman dilimi analizi
            multi_timeframe_data = {}
            for tf in self.timeframes:
                ohlcv = self.exchange.fetch_ohlcv(symbol, tf, limit=100)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                multi_timeframe_data[tf] = self._analyze_timeframe(df, tf)

            # Funding rate (sadece perpetual futures için)
            try:
                funding_rate = self.exchange.fetch_funding_rate(symbol)
            except:
                funding_rate = None

            # Orderbook analizi
            order_book = self.exchange.fetch_order_book(symbol)
            orderbook_analysis = self._analyze_orderbook(order_book)

            # Fibonacci seviyeleri
            fib_levels = self._calculate_fibonacci_levels(
                multi_timeframe_data['1d']['high'],
                multi_timeframe_data['1d']['low']
            )

            # İşlem stratejileri
            strategies = self._analyze_trading_strategies(multi_timeframe_data)

            # Hacim profili
            volume_profile = self._analyze_volume_profile(multi_timeframe_data['1h']['df'])

            return {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'current_price': multi_timeframe_data['15m']['close'],
                'multi_timeframe': multi_timeframe_data,
                'funding_rate': funding_rate,
                'orderbook': orderbook_analysis,
                'fibonacci_levels': fib_levels,
                'trading_strategies': strategies,
                'volume_profile': volume_profile,
                'market_status': self._get_market_status(multi_timeframe_data)
            }

        except Exception as e:
            print(f"Veri alma hatası ({symbol}): {str(e)}")
            return {'error': str(e)}

    def _analyze_timeframe(self, df: pd.DataFrame, timeframe: str) -> Dict:
        """Her zaman dilimi için detaylı analiz"""
        # Temel metrikler
        current_close = df['close'].iloc[-1]
        price_change = ((current_close - df['close'].iloc[0]) / df['close'].iloc[0]) * 100
        
        # Volatilite ve hacim
        returns = df['close'].pct_change()
        volatility = returns.std() * np.sqrt(len(df)) * 100
        volume_change = ((df['volume'].iloc[-1] - df['volume'].mean()) / df['volume'].mean()) * 100
        
        # Teknik göstergeler
        rsi = self._calculate_rsi(df)
        macd = self._calculate_macd(df)
        bollinger = self._calculate_bollinger_bands(df)
        
        # Trend göstergeleri
        ema_data = {
            'ema9': df['close'].ewm(span=9).mean().iloc[-1],
            'ema20': df['close'].ewm(span=20).mean().iloc[-1],
            'ema50': df['close'].ewm(span=50).mean().iloc[-1],
            'ema200': df['close'].ewm(span=200).mean().iloc[-1]
        }
        
        # Momentum göstergeleri
        stoch = self._calculate_stochastic(df)
        
        return {
            'timeframe': timeframe,
            'close': current_close,
            'high': df['high'].max(),
            'low': df['low'].min(),
            'price_change': price_change,
            'volatility': volatility,
            'volume_change': volume_change,
            'technical': {
                'rsi': rsi,
                'macd': macd,
                'bollinger': bollinger,
                'ema': ema_data,
                'stochastic': stoch
            },
            'df': df  # İleri analizler için DataFrame'i sakla
        }

    def _analyze_orderbook(self, orderbook: Dict) -> Dict:
        """Emir defteri analizi"""
        bids = orderbook['bids']
        asks = orderbook['asks']
        
        # Toplam hacimler
        bid_volume = sum(bid[1] for bid in bids[:10])
        ask_volume = sum(ask[1] for ask in asks[:10])
        
        # Alış/satış oranı
        buy_sell_ratio = bid_volume / ask_volume if ask_volume > 0 else float('inf')
        
        # En yakın destek/direnç
        support = bids[0][0]
        resistance = asks[0][0]
        
        return {
            'buy_sell_ratio': buy_sell_ratio,
            'bid_volume': bid_volume,
            'ask_volume': ask_volume,
            'support': support,
            'resistance': resistance,
            'spread': resistance - support
        }

    def _calculate_fibonacci_levels(self, high: float, low: float) -> Dict:
        """Fibonacci seviyeleri"""
        diff = high - low
        return {
            'extension_1.618': round(high + (diff * 0.618), 2),
            'extension_1.272': round(high + (diff * 0.272), 2),
            'level_1': round(high, 2),
            'level_0.786': round(high - (diff * 0.786), 2),
            'level_0.618': round(high - (diff * 0.618), 2),
            'level_0.5': round(high - (diff * 0.5), 2),
            'level_0.382': round(high - (diff * 0.382), 2),
            'level_0.236': round(high - (diff * 0.236), 2),
            'level_0': round(low, 2)
        }

    def _analyze_volume_profile(self, df: pd.DataFrame) -> Dict:
        """Hacim profili analizi"""
        # Fiyat aralıklarını belirle
        price_range = df['high'].max() - df['low'].min()
        num_bins = 10
        bin_size = price_range / num_bins
        
        # Her fiyat seviyesindeki hacmi hesapla
        volume_profile = []
        for i in range(num_bins):
            price_level = df['low'].min() + (i * bin_size)
            volume = df[
                (df['close'] >= price_level) & 
                (df['close'] < price_level + bin_size)
            ]['volume'].sum()
            volume_profile.append({
                'price_level': round(price_level, 2),
                'volume': volume
            })
            
        # POC (Point of Control) - En yüksek hacimli seviye
        poc = max(volume_profile, key=lambda x: x['volume'])
        
        return {
            'profile': volume_profile,
            'poc': poc,
            'value_area': {
                'high': poc['price_level'] + bin_size,
                'low': poc['price_level'] - bin_size
            }
        }

    def _calculate_stochastic(self, df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> Dict:
        """Stochastic Oscillator"""
        low_min = df['low'].rolling(window=k_period).min()
        high_max = df['high'].rolling(window=k_period).max()
        
        k = 100 * ((df['close'] - low_min) / (high_max - low_min))
        d = k.rolling(window=d_period).mean()
        
        return {
            'k': float(k.iloc[-1]),
            'd': float(d.iloc[-1])
        }

    def _calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20, std: int = 2) -> Dict:
        """Bollinger Bands"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        bb_middle = typical_price.rolling(window=period).mean()
        bb_std = typical_price.rolling(window=period).std()
        
        return {
            'upper': float(bb_middle.iloc[-1] + (bb_std.iloc[-1] * std)),
            'middle': float(bb_middle.iloc[-1]),
            'lower': float(bb_middle.iloc[-1] - (bb_std.iloc[-1] * std))
        }

    def _calculate_rsi(self, df: pd.DataFrame, periods: int = 14) -> float:
        """RSI hesapla"""
        try:
            close_delta = df['close'].diff()
            
            # Pozitif ve negatif değişimleri ayır
            gain = (close_delta.where(close_delta > 0, 0)).rolling(window=periods).mean()
            loss = (-close_delta.where(close_delta < 0, 0)).rolling(window=periods).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return float(rsi.iloc[-1])
        except:
            return 50  # Hata durumunda nötr değer döndür

    def _calculate_macd(self, df: pd.DataFrame) -> Dict:
        """MACD hesapla"""
        try:
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            macd_hist = macd - signal
            
            return {
                'value': round(macd.iloc[-1], 2),
                'signal': round(signal.iloc[-1], 2),
                'histogram': round(macd_hist.iloc[-1], 2)
            }
        except:
            return {'value': 0, 'signal': 0, 'histogram': 0}

    def _analyze_trading_strategies(self, multi_timeframe_data: Dict) -> Dict:
        """Trading stratejilerini analiz et"""
        try:
            strategies = {
                'trend_following': self._analyze_trend_strategy(multi_timeframe_data),
                'breakout': self._analyze_breakout_strategy(multi_timeframe_data),
                'scalping': self._analyze_scalping_strategy(multi_timeframe_data['15m']),
                'mean_reversion': self._analyze_mean_reversion(multi_timeframe_data['1h'])
            }
            
            # En iyi stratejiyi seç
            best_strategy = max(strategies.items(), key=lambda x: x[1]['score'])
            
            return {
                'strategies': strategies,
                'recommended': {
                    'name': best_strategy[0],
                    'details': best_strategy[1]
                }
            }
        except Exception as e:
            print(f"Strateji analiz hatası: {str(e)}")
            return {
                'error': 'Strateji analizi yapılamadı',
                'details': str(e)
            }

    def _analyze_trend_strategy(self, multi_timeframe_data: Dict) -> Dict:
        """Trend takip stratejisi analizi"""
        try:
            # 1H ve 4H verileri
            h1_data = multi_timeframe_data['1h']
            h4_data = multi_timeframe_data['4h']
            
            # Trend yönü kontrolü
            ema_h1 = h1_data['technical']['ema']
            ema_h4 = h4_data['technical']['ema']
            
            trend_strength = 0
            signals = []
            
            # Trend gücü hesaplama
            if ema_h1['ema9'] > ema_h1['ema20'] > ema_h1['ema50']:
                trend_strength += 2
                signals.append("1H Yükseliş trendi")
            elif ema_h1['ema9'] < ema_h1['ema20'] < ema_h1['ema50']:
                trend_strength -= 2
                signals.append("1H Düşüş trendi")
                
            if ema_h4['ema9'] > ema_h4['ema20'] > ema_h4['ema50']:
                trend_strength += 3
                signals.append("4H Yükseliş trendi")
            elif ema_h4['ema9'] < ema_h4['ema20'] < ema_h4['ema50']:
                trend_strength -= 3
                signals.append("4H Düşüş trendi")
            
            return {
                'score': abs(trend_strength),
                'direction': 'BULLISH' if trend_strength > 0 else 'BEARISH',
                'strength': abs(trend_strength),
                'signals': signals
            }
        except Exception as e:
            return {'error': str(e), 'score': 0}

    def _analyze_breakout_strategy(self, multi_timeframe_data: Dict) -> Dict:
        """Kırılım stratejisi analizi"""
        try:
            h1_data = multi_timeframe_data['1h']
            
            bb = h1_data['technical']['bollinger']
            current_price = h1_data['close']
            
            breakout_score = 0
            signals = []
            
            # Bollinger kırılımı kontrolü
            if current_price > bb['upper']:
                breakout_score += 3
                signals.append("Üst Bollinger kırılımı")
            elif current_price < bb['lower']:
                breakout_score += 3
                signals.append("Alt Bollinger kırılımı")
                
            # Hacim kontrolü
            if h1_data['volume_change'] > 50:
                breakout_score += 2
                signals.append("Yüksek hacim desteği")
                
            return {
                'score': breakout_score,
                'signals': signals,
                'levels': {
                    'upper': bb['upper'],
                    'lower': bb['lower']
                }
            }
        except Exception as e:
            return {'error': str(e), 'score': 0}

    def _analyze_scalping_strategy(self, timeframe_data: Dict) -> Dict:
        """Scalping stratejisi analizi"""
        try:
            technical = timeframe_data['technical']
            
            scalping_score = 0
            signals = []
            
            # RSI kontrolü
            if 30 <= technical['rsi'] <= 70:
                scalping_score += 2
                signals.append("RSI nötr bölgede")
                
            # MACD kontrolü
            if abs(technical['macd']['histogram']) < 0.5:
                scalping_score += 2
                signals.append("Düşük MACD volatilitesi")
                
            # Volatilite kontrolü
            if timeframe_data['volatility'] < 2:
                scalping_score += 1
                signals.append("Düşük volatilite")
                
            return {
                'score': scalping_score,
                'signals': signals,
                'timeframe': '15m'
            }
        except Exception as e:
            return {'error': str(e), 'score': 0}

    def _analyze_mean_reversion(self, timeframe_data: Dict) -> Dict:
        """Ortalamaya dönüş stratejisi analizi"""
        try:
            technical = timeframe_data['technical']
            
            reversion_score = 0
            signals = []
            
            # RSI aşırı seviyeleri
            if technical['rsi'] > 70:
                reversion_score += 3
                signals.append("RSI aşırı alım")
            elif technical['rsi'] < 30:
                reversion_score += 3
                signals.append("RSI aşırı satım")
                
            # Bollinger kontrolü
            bb = technical['bollinger']
            current_price = timeframe_data['close']
            
            if current_price > bb['upper']:
                reversion_score += 2
                signals.append("Fiyat üst bandın üzerinde")
            elif current_price < bb['lower']:
                reversion_score += 2
                signals.append("Fiyat alt bandın altında")
                
            return {
                'score': reversion_score,
                'signals': signals,
                'bands': {
                    'upper': bb['upper'],
                    'lower': bb['lower']
                }
            }
        except Exception as e:
            return {'error': str(e), 'score': 0}

    def _get_market_status(self, multi_timeframe_data: Dict) -> Dict:
        """Piyasa durumu analizi"""
        try:
            # Trend analizi
            trend = self._analyze_trend_strategy(multi_timeframe_data)
            
            # Volatilite durumu
            volatility = multi_timeframe_data['1h']['volatility']
            
            # Hacim durumu
            volume_change = multi_timeframe_data['1h']['volume_change']
            
            status = {
                'trend': trend['direction'],
                'strength': trend['strength'],
                'volatility': 'HIGH' if volatility > 5 else 'MEDIUM' if volatility > 2 else 'LOW',
                'volume': 'HIGH' if volume_change > 50 else 'MEDIUM' if volume_change > 20 else 'LOW'
            }
            
            return status
        except Exception as e:
            return {'error': str(e)}