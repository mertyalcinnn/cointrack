from typing import List, Dict
import ccxt.async_support as ccxt_async
import pandas as pd
import asyncio
import numpy as np
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.volatility import BollingerBands
from ta.volume import VolumeWeightedAveragePrice
from datetime import datetime

class MarketScanner:
    def __init__(self):
        """Initialize the market scanner with extended signals."""
        self.exchange = ccxt_async.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })
        self.min_volume = 50000  # Minimum 50k USDT hacim (daha fazla coin tarayabilmek için düşürüldü)
        self.min_price = 0.000001

        # Hariç tutulacak coin/kaldıraçlı token/fiat vs. kalıpları - Genişletilmiş liste
        self.excluded_patterns = [
            'UP/', 'DOWN/', 'BULL/', 'BEAR/',
            'USDC/', 'BUSD/', 'TUSD/', 'DAI/', 'FDUSD/', 'PYUSD/',
            'EUR/', 'GBP/', 'AUD/', 'BRL/', 'TRY/', 'JPY/', 'CAD/', 'CNH/', 'CHF/', 'NZD/',
            'RUB/', 'ZAR/', 'SGD/', 'HKD/', 'KRW/', 'MXN/', 'PLN/', 'SEK/', 'NOK/', 'DKK/',
            'IDRT/', 'UAH/', 'VAI/', 'NGN/', 'BIDR/', 'BVND/', 'BKRW/'
        ]
        
        # Hariç tutulacak özel coin listesi
        self.excluded_coins = [
            'EUR/USDT', 'GBP/USDT', 'TRY/USDT', 'AUD/USDT', 'BRL/USDT', 'RUB/USDT',
            'CAD/USDT', 'JPY/USDT', 'CNH/USDT', 'CHF/USDT', 'BUSD/USDT', 'TUSD/USDT', 
            'USDC/USDT', 'DAI/USDT', 'FDUSD/USDT', 'PYUSD/USDT'
        ]

    async def scan_opportunities(self) -> Dict:
        """
        Geliştirilmiş kripto fırsat taraması:
        - Mevcut stratejiler
        - Yeni eklenen candlestick pattern, stochastic RSI, bollinger squeeze vb.
        """
        try:
            opportunities = {
                'strong_buy': [],
                'potential_buy': [],
                'breakout': [],
                'oversold': [],
                'trend_following': [],
                'volume_surge': [],
                # Yeni eklenen kategoriler
                'candlestick_patterns': [],
                'ema_cross': [],
                'bollinger_breakout': [],
                'stoch_oversold': []
            }

            # Tüm marketleri al (Binance)
            markets = await self.exchange.load_markets()

            # USDT çiftlerini filtrele - hem pattern hem de özel excluded coins listesini kullanarak
            valid_pairs = [
                symbol for symbol in markets.keys()
                if symbol.endswith('/USDT')
                and not any(pattern in symbol for pattern in self.excluded_patterns)
                and symbol not in self.excluded_coins
            ]

            print(f"Taranan toplam coin sayısı: {len(valid_pairs)}")

            for symbol in valid_pairs:
                try:
                    # Ticker bilgilerini al
                    ticker = await self.get_ticker(symbol)
                    if not ticker:
                        continue

                    # Minimum gereksinimleri kontrol et - hacim eşiği düşürüldü
                    if ticker['quoteVolume'] < self.min_volume or ticker['last'] < self.min_price:
                        # Blacklist'te olmayan düşük hacimli coinler için log ekle
                        print(f"Hacim filtresi: {symbol} - {ticker['quoteVolume']:.2f} USDT")
                        continue

                    # OHLCV verilerini al
                    ohlcv = await self.get_ohlcv(symbol)
                    if ohlcv is None or ohlcv.empty:
                        continue

                    df = ohlcv

                    # Teknik analiz
                    analysis = self._calculate_indicators(df)

                    # Özel analiz: candlestick formasyonları
                    candle_patterns = self._detect_candlestick_patterns(df)

                    # Stochastic RSI
                    stoch_rsi_signal = self._check_stoch_rsi_signal(df)

                    # Bollinger Sıkışması
                    bollinger_info = self._check_bollinger_squeeze(df)

                    # Golden Cross / Death Cross kontrolü (EMA200-EMA50 vb.)
                    ema_cross_signal = self._check_ema_cross(df)

                    # Strateji sinyalleri
                    signals = self._check_strategies(analysis, ticker)

                    # Volatilite hesapla
                    volatility = (
                        (df['high'].max() - df['low'].min()) / df['low'].min() * 100
                    )

                    coin_data = {
                        'symbol': symbol,
                        'price': ticker['last'],
                        'volume': ticker['quoteVolume'],
                        'change_24h': ticker['percentage'],
                        'volatility': volatility,
                        'analysis': analysis
                    }

                    # Fırsatları kategorize et (mevcut mantık)
                    if signals['signal_strength'] >= 2.5:
                        opportunities['strong_buy'].append(coin_data)
                    elif signals['signal_strength'] >= 1.5:
                        opportunities['potential_buy'].append(coin_data)

                    if signals.get('breakout', False):
                        opportunities['breakout'].append(coin_data)
                    if signals.get('oversold', False):
                        opportunities['oversold'].append(coin_data)
                    if signals.get('trend_following', False):
                        opportunities['trend_following'].append(coin_data)
                    if analysis['volume_change'] > 50:
                        opportunities['volume_surge'].append(coin_data)

                    # Yeni eklenen kategoriler:

                    # Candlestick Patterns
                    if candle_patterns:
                        coin_data['candle_patterns'] = candle_patterns
                        opportunities['candlestick_patterns'].append(coin_data)

                    # EMA Cross
                    if ema_cross_signal is not None:
                        # ema_cross_signal: "golden_cross" veya "death_cross"
                        coin_data['ema_cross'] = ema_cross_signal
                        opportunities['ema_cross'].append(coin_data)

                    # Bollinger Breakout
                    if bollinger_info['is_squeeze_breakout']:
                        coin_data['bollinger_breakout'] = True
                        opportunities['bollinger_breakout'].append(coin_data)

                    # Stoch RSI Oversold (örnek)
                    if stoch_rsi_signal == 'oversold':
                        coin_data['stoch_rsi'] = 'oversold'
                        opportunities['stoch_oversold'].append(coin_data)

                except Exception as e:
                    print(f"Hata {symbol}: {str(e)}")
                    continue

            # Her kategori için en iyi fırsatları seç (aynı mantık)
            for category in opportunities:
                opportunities[category] = sorted(
                    opportunities[category],
                    key=lambda x: (x['analysis']['volume_change'], abs(x['change_24h'])),
                    reverse=True
                )[:10]

            print("Tarama tamamlandı!")
            print(f"Bulunan fırsatlar:")
            for category, signals in opportunities.items():
                print(f"{category}: {len(signals)} coin")

            return opportunities

        except Exception as e:
            print(f"Tarama hatası: {str(e)}")
            # Hata durumunda boş döndür
            return {
                'strong_buy': [],
                'potential_buy': [],
                'breakout': [],
                'oversold': [],
                'trend_following': [],
                'volume_surge': [],
                'candlestick_patterns': [],
                'ema_cross': [],
                'bollinger_breakout': [],
                'stoch_oversold': []
            }
        finally:
            await self.exchange.close()

    async def get_ticker(self, symbol: str) -> Dict:
        """Sembol için ticker verilerini al."""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            if not ticker or not isinstance(ticker, dict):
                print(f"⚠️ {symbol} için geçersiz ticker verisi")
                return None

            required_fields = ['last', 'quoteVolume']
            if not all(field in ticker for field in required_fields):
                print(f"⚠️ {symbol} için eksik ticker alanları")
                return None

            return ticker

        except Exception as e:
            if 'ERR_RATE_LIMIT' in str(e):
                print(f"⏳ Rate limit - {symbol} için bekleniyor...")
                await asyncio.sleep(1)
                return await self.get_ticker(symbol)
            print(f"❌ Ticker hatası {symbol}: {str(e)}")
            return None

    async def get_ohlcv(self, symbol: str) -> pd.DataFrame:
        """OHLCV verilerini al (1h, son 100 mum)."""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, '1h', limit=100)
            if not ohlcv or len(ohlcv) < 2:
                print(f"⚠️ {symbol} için yetersiz OHLCV verisi")
                return None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df

        except Exception as e:
            if 'ERR_RATE_LIMIT' in str(e):
                print(f"⏳ Rate limit - {symbol} için bekleniyor...")
                await asyncio.sleep(1)
                return await self.get_ohlcv(symbol)
            print(f"❌ OHLCV hatası {symbol}: {str(e)}")
            return None

    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        """Teknik göstergeleri hesapla."""
        try:
            # RSI
            rsi = RSIIndicator(df['close'], window=14)
            current_rsi = float(rsi.rsi().iloc[-1])

            # EMA20, EMA50
            ema20 = float(EMAIndicator(df['close'], window=20).ema_indicator().iloc[-1])
            ema50 = float(EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1])

            # MACD
            macd = MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
            current_macd = float(macd.macd().iloc[-1])
            current_signal = float(macd.macd_signal().iloc[-1])

            # VWAP
            vwap = float(VolumeWeightedAveragePrice(
                high=df['high'],
                low=df['low'],
                close=df['close'],
                volume=df['volume']
            ).volume_weighted_average_price().iloc[-1])

            # Bollinger Bands (20, 2)
            bb_indicator = BollingerBands(df['close'], window=20, window_dev=2)
            bb_upper = float(bb_indicator.bollinger_hband().iloc[-1])
            bb_lower = float(bb_indicator.bollinger_lband().iloc[-1])

            # Hacim değişimi
            recent_vol = float(df['volume'].iloc[-3:].mean())
            prev_vol = float(df['volume'].iloc[-6:-3].mean())
            volume_change = ((recent_vol - prev_vol) / prev_vol * 100) if prev_vol > 0 else 0.0

            # Fiyat değişimi (son 2 saat mumuna bakarak)
            price_change = float(
                (df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100
            )

            return {
                'rsi': current_rsi,
                'ema20': ema20,
                'ema50': ema50,
                'macd': current_macd,
                'macd_signal': current_signal,
                'vwap': vwap,
                'volume_change': volume_change,
                'price_change': price_change,
                'bb_upper': bb_upper,
                'bb_lower': bb_lower,
                'current_price': float(df['close'].iloc[-1])
            }

        except Exception as e:
            print(f"Gösterge hesaplama hatası: {str(e)}")
            return {
                'rsi': 0.0,
                'ema20': 0.0,
                'ema50': 0.0,
                'macd': 0.0,
                'macd_signal': 0.0,
                'vwap': 0.0,
                'volume_change': 0.0,
                'price_change': 0.0,
                'bb_upper': 0.0,
                'bb_lower': 0.0,
                'current_price': 0.0
            }

    def _check_strategies(self, analysis: dict, ticker: dict) -> dict:
        """Önceden var olan strateji sinyallerini kontrol et - daha hassas."""
        signals = {
            'signals': [],
            'signal_strength': 0,
            'breakout': False,
            'oversold': False,
            'trend_following': False
        }
        try:
            # RSI kontrolleri
            if analysis['rsi'] < 30:
                signals['signals'].append("Güçlü aşırı satış (RSI)")
                signals['signal_strength'] += 1.5
                signals['oversold'] = True
            elif analysis['rsi'] < 40:
                signals['signals'].append("Aşırı satış bölgesi (RSI)")
                signals['signal_strength'] += 1
                signals['oversold'] = True
            elif analysis['rsi'] > 65:
                signals['signals'].append("Güçlü momentum (RSI)")
                signals['signal_strength'] += 1

            # EMA trend kontrolü
            if analysis['ema20'] > analysis['ema50'] * 1.002:
                signals['signals'].append("Güçlü yükselen trend (EMA20>EMA50)")
                signals['signal_strength'] += 1.5
                signals['trend_following'] = True
            elif analysis['ema20'] > analysis['ema50']:
                signals['signals'].append("Yükselen trend (EMA20>EMA50)")
                signals['signal_strength'] += 1
                signals['trend_following'] = True

            # MACD kontrolü
            if analysis['macd'] > analysis['macd_signal'] * 1.1:
                signals['signals'].append("Güçlü MACD sinyali")
                signals['signal_strength'] += 1.5
            elif analysis['macd'] > analysis['macd_signal']:
                signals['signals'].append("MACD pozitif")
                signals['signal_strength'] += 1

            # Hacim kontrolü
            if analysis['volume_change'] > 100:
                signals['signals'].append("Çok yüksek hacim artışı")
                signals['signal_strength'] += 1.5
            elif analysis['volume_change'] > 50:
                signals['signals'].append("Yüksek hacim artışı")
                signals['signal_strength'] += 1

            # Fiyat kırılımı kontrolü
            if analysis['price_change'] > 3 and analysis['volume_change'] > 50:
                signals['signals'].append("Güçlü fiyat kırılımı")
                signals['signal_strength'] += 1.5
                signals['breakout'] = True
            elif analysis['price_change'] > 2 and analysis['volume_change'] > 30:
                signals['signals'].append("Fiyat kırılımı")
                signals['signal_strength'] += 1
                signals['breakout'] = True

            return signals

        except Exception as e:
            print(f"Strateji kontrol hatası: {str(e)}")
            return signals

    def _detect_candlestick_patterns(self, df: pd.DataFrame) -> List[str]:
        """
        Basit bazı candlestick (mum) formasyonlarını tespit etme örneği.
        Gelişmiş analiz için ek kütüphaneler (ör. pandas-ta) veya özel algoritmalar kullanılabilir.
        """
        patterns = []
        try:
            # Son 2-3 mum üzerinde bir kontrol:
            recent = df.iloc[-3:].reset_index(drop=True)

            # Örnek 1: Hammer (basit tanım)
            # - Alt gölge uzun, gövde küçük, üst gölge kısa
            for i in range(len(recent)):
                open_ = recent.at[i, 'open']
                close_ = recent.at[i, 'close']
                high_ = recent.at[i, 'high']
                low_ = recent.at[i, 'low']
                candle_range = abs(high_ - low_)
                body_size = abs(close_ - open_)
                lower_wick = min(open_, close_) - low_
                upper_wick = high_ - max(open_, close_)

                # Çok basit bir “hammer” tanımı
                if body_size <= candle_range * 0.3 and lower_wick >= candle_range * 0.5 and upper_wick <= candle_range * 0.1:
                    patterns.append("Hammer")

            # Örnek 2: Doji (open ve close birbirine çok yakın)
            for i in range(len(recent)):
                open_ = recent.at[i, 'open']
                close_ = recent.at[i, 'close']
                if abs(close_ - open_) <= (open_ * 0.0015):  # ~%0.15
                    patterns.append("Doji")

            # Örnek 3: Bullish Engulfing (son iki mumda)
            if len(recent) >= 2:
                # Bir önceki mumun gövdesi küçük, şimdikinin gövdesi önceki gövdeyi kapsıyorsa
                prev_open, prev_close = recent.at[1, 'open'], recent.at[1, 'close']
                curr_open, curr_close = recent.at[2, 'open'], recent.at[2, 'close']

                if (prev_close < prev_open) and (curr_close > curr_open):
                    # “Bearish mum” sonra “Bullish mum” -> Engulfing
                    if curr_close > prev_open and curr_open < prev_close:
                        patterns.append("Bullish Engulfing")

            return list(set(patterns))  # Aynı pattern birden çok defa eklenmesin

        except Exception as e:
            print(f"Candlestick pattern hatası: {str(e)}")
            return patterns

    def _check_stoch_rsi_signal(self, df: pd.DataFrame) -> str:
        """
        Stochastic RSI ile basit oversold/overbought örneği:
        stoch_rsi < 0.2 -> oversold,
        stoch_rsi > 0.8 -> overbought
        """
        try:
            stoch = StochRSIIndicator(close=df['close'], window=14, smooth1=3, smooth2=3)
            stoch_rsi = stoch.stochrsi_k().iloc[-1]  # 0-1 arasında değer
            if stoch_rsi < 0.2:
                return 'oversold'
            elif stoch_rsi > 0.8:
                return 'overbought'
            else:
                return 'neutral'
        except Exception as e:
            print(f"Stoch RSI hesaplama hatası: {str(e)}")
            return 'error'

    def _check_bollinger_squeeze(self, df: pd.DataFrame) -> dict:
        """
        Bollinger Band sıkışması & breakout sinyali.
        Klasik yaklaşım: band genişliği belirli bir eşiğin altına düştüyse 'sıkışma' var.
        Fiyat aniden üst banda doğru hareket ederse 'breakout'.
        """
        result = {
            'is_squeeze': False,
            'is_squeeze_breakout': False
        }
        try:
            bb = BollingerBands(df['close'], window=20, window_dev=2)
            band_width = bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]
            middle_band = bb.bollinger_mavg().iloc[-1]
            close_price = df['close'].iloc[-1]

            # Basit bir eşik: band genişliği son 20 mumun ortalamasının %50 altına inmişse
            all_band_widths = (bb.bollinger_hband() - bb.bollinger_lband()).iloc[-20:]
            avg_band_width = all_band_widths.mean()
            if band_width < avg_band_width * 0.5:
                result['is_squeeze'] = True

            # Breakout: close_price üst bandın (veya alt bandın) dışına çıkmışsa
            # ya da yakınından hızlı uzaklaşıyorsa
            upper_band = bb.bollinger_hband().iloc[-1]
            if close_price > upper_band * 1.01:  # %1 üstüne çıkması
                result['is_squeeze_breakout'] = True

            return result
        except Exception as e:
            print(f"Bollinger squeeze hatası: {str(e)}")
            return result

    def _check_ema_cross(self, df: pd.DataFrame) -> str:
        """
        Basit bir Golden/Death Cross tespiti:
        - Golden Cross: EMA50 son değeri, EMA200 son değerini aşağıdan yukarı keserse
        - Death Cross: Tam tersi.
        
        İsteğe göre SMA veya farklı periyotlar da kullanılabilir.
        """
        try:
            # Örnek: 50 ve 200 EMAsı
            ema50 = EMAIndicator(df['close'], window=50).ema_indicator()
            ema200 = EMAIndicator(df['close'], window=200).ema_indicator()

            # Son iki değerde kesişim analizi
            prev50, prev200 = ema50.iloc[-2], ema200.iloc[-2]
            curr50, curr200 = ema50.iloc[-1], ema200.iloc[-1]

            # Golden Cross: Önce küçük, şimdi büyük
            if prev50 < prev200 and curr50 > curr200:
                return "golden_cross"
            # Death Cross: Önce büyük, şimdi küçük
            elif prev50 > prev200 and curr50 < curr200:
                return "death_cross"
            return None
        except Exception as e:
            print(f"EMA cross hesaplama hatası: {str(e)}")
            return None

    async def get_all_symbols(self) -> List[str]:
        """Binance'deki tüm sembolleri getir."""
        try:
            markets = await self.exchange.load_markets()
            if not markets:
                print("⚠️ Piyasa verileri alınamadı")
                return []

            # Sadece USDT çiftlerini filtrele ve aktif olanları al
            usdt_pairs = [
                symbol for symbol in markets.keys()
                if (symbol.endswith('USDT')
                    and 'USDT' not in symbol.split('/')[0]  # USDT/USDT gibi çiftleri filtrele
                    and markets[symbol].get('active', False))
            ]

            # Bilinen hatalı veya sorunlu çiftleri filtrele
            excluded_pairs = ['ERD/USDT']  # Sorunlu çiftleri buraya ekle
            filtered_pairs = [p for p in usdt_pairs if p not in excluded_pairs]

            return filtered_pairs

        except Exception as e:
            print(f"❌ Sembol listesi alınamadı: {str(e)}")
            return []

    async def scan_market(self):
        """
        Eski tip bir 'scan_market' metodu, tüm semboller üzerinde 
        basit bir işlem yapıp sonuçları döndürüyor.
        """
        try:
            symbols = await self.get_all_symbols()
            results = []

            for symbol in symbols:
                try:
                    # Ticker verilerini alırken await kullanmayı unutma
                    ticker = await self.get_ticker(symbol)
                    if ticker and ticker.get('quoteVolume', 0) > 1000000:  # 1M USDT hacim
                        analysis = await self.analyze_symbol(symbol)
                        if analysis:
                            # Ticker bir dictionary olduğunda burası çalışır
                            results.append({
                                'symbol': symbol,
                                'price': ticker['last'],
                                'volume': ticker['quoteVolume'],
                                'change': ticker['percentage'],
                                **analysis
                            })

                    await asyncio.sleep(0.1)  # Rate limit

                except Exception as e:
                    print(f"Coin tarama hatası {symbol}: {str(e)}")
                    continue

            # Hacme göre sırala
            results.sort(key=lambda x: x['volume'], reverse=True)
            return results

        except Exception as e:
            print(f"Piyasa tarama hatası: {str(e)}")
            return []

    async def analyze_symbol(self, symbol: str) -> dict:
        """
        İsteğe bağlı örnek analiz fonksiyonu. 
        Sembole dair kısa bir özet döndürebilir.
        """
        try:
            df = await self.get_ohlcv(symbol)
            if df is None or df.empty:
                return {}
            analysis = self._calculate_indicators(df)
            return analysis
        except Exception as e:
            print(f"Symbol analiz hatası ({symbol}): {str(e)}")
            return {}