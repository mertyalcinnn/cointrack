import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import matplotlib.pyplot as plt
from io import BytesIO


class VolumeProfileAnalyzer:
    """Hacim profili analizi için sınıf"""
    
    def __init__(self):
        self.num_bins = 20  # Fiyat aralıkları sayısı
        self.poc_window = 5  # POC etrafındaki pencere büyüklüğü
    
    def analyze_volume_profile(self, df: pd.DataFrame) -> Dict:
        """
        Hacim profili analizi yapar
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            
        Returns:
            Dict: Hacim profili analiz sonuçları
        """
        if len(df) < 10:
            return {
                'poc': None,
                'value_area_high': None,
                'value_area_low': None,
                'volume_profile': []
            }
            
        # Fiyat aralığı
        price_range = df['high'].max() - df['low'].min()
        if price_range == 0:
            return {
                'poc': None,
                'value_area_high': None,
                'value_area_low': None,
                'volume_profile': []
            }
            
        bin_size = price_range / self.num_bins
        
        # Fiyat aralıkları oluştur
        price_levels = []
        for i in range(self.num_bins):
            price_level = df['low'].min() + (i * bin_size)
            price_levels.append(price_level)
        
        # Her fiyat aralığı için hacim topla
        volume_profile = []
        for i in range(self.num_bins):
            price_level = price_levels[i]
            next_level = price_level + bin_size
            
            # Bu fiyat aralığındaki mumları bul
            mask = (df['low'] <= next_level) & (df['high'] >= price_level)
            
            # Bu aralıktaki toplam hacim
            if mask.any():
                # Her mumun bu aralıkta geçirdiği yüzdeyi hesapla (yaklaşık)
                volume_in_range = df.loc[mask, 'volume'].sum()
                
                # Ağırlıklı hacim (mumun bu aralıkta geçirdiği zamana göre)
                rows = df.loc[mask]
                for _, row in rows.iterrows():
                    overlap = min(row['high'], next_level) - max(row['low'], price_level)
                    total_range = row['high'] - row['low']
                    if total_range > 0:
                        ratio = overlap / total_range
                    else:
                        ratio = 1.0
                    
                    volume_in_range = volume_in_range * ratio
            else:
                volume_in_range = 0
            
            volume_profile.append({
                'price_level': round(price_level, 8),
                'volume': float(volume_in_range)
            })
        
        # Hacim profilini hacme göre sırala ve en yüksek hacimli aralığı bul (POC)
        volume_profile.sort(key=lambda x: x['volume'], reverse=True)
        poc = volume_profile[0]['price_level'] if volume_profile else None
        
        # Value Area hesapla (toplam hacmin %70'ini içeren alan)
        total_volume = sum(item['volume'] for item in volume_profile)
        value_area_volume = 0
        value_area = []
        
        for item in volume_profile:
            value_area.append(item['price_level'])
            value_area_volume += item['volume']
            
            if value_area_volume >= total_volume * 0.7:
                break
        
        # Value Area High ve Low
        if value_area:
            value_area_high = max(value_area) + bin_size
            value_area_low = min(value_area)
        else:
            value_area_high = None
            value_area_low = None
        
        # Sonucu hacme göre değil, fiyat seviyesine göre sırala
        volume_profile.sort(key=lambda x: x['price_level'])
        
        return {
            'poc': round(poc, 8) if poc is not None else None,
            'value_area_high': round(value_area_high, 8) if value_area_high is not None else None,
            'value_area_low': round(value_area_low, 8) if value_area_low is not None else None,
            'volume_profile': volume_profile
        }
    
    def find_liquidity_zones(self, df: pd.DataFrame) -> Dict:
        """
        Likidite bölgelerini (yüksek ve düşük hacimli alanlar) belirler
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            
        Returns:
            Dict: Likidite bölgeleri
        """
        volume_profile = self.analyze_volume_profile(df)
        
        if not volume_profile['volume_profile']:
            return {
                'high_liquidity': [],
                'low_liquidity': []
            }
        
        # Hacim profilini hacme göre sırala
        profile = sorted(volume_profile['volume_profile'], key=lambda x: x['volume'], reverse=True)
        
        # Yüksek likidite bölgeleri (en yüksek hacimli %20)
        high_liquidity_count = max(1, int(len(profile) * 0.2))
        high_liquidity = profile[:high_liquidity_count]
        
        # Düşük likidite bölgeleri (en düşük hacimli %20)
        low_liquidity_count = max(1, int(len(profile) * 0.2))
        low_liquidity = profile[-low_liquidity_count:]
        
        return {
            'high_liquidity': [{
                'price_level': item['price_level'],
                'volume': item['volume']
            } for item in high_liquidity],
            'low_liquidity': [{
                'price_level': item['price_level'],
                'volume': item['volume']
            } for item in low_liquidity]
        }
    
    def identify_order_blocks(self, df: pd.DataFrame) -> Dict:
        """
        Sipariş bloklarını (order blocks) tespit eder
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            
        Returns:
            Dict: Tespit edilen sipariş blokları
        """
        if len(df) < 10:
            return {'bullish_blocks': [], 'bearish_blocks': []}
        
        # Copy dataframe to avoid modifying original
        df = df.copy()
        
        # Calculate candle body size and direction
        df['body_size'] = abs(df['close'] - df['open'])
        df['body_size_pct'] = df['body_size'] / ((df['high'] - df['low']).rolling(window=10).mean())
        df['is_bullish'] = df['close'] > df['open']
        
        # Calculate momentum
        df['momentum'] = df['close'].diff(3)
        
        bullish_blocks = []
        bearish_blocks = []
        
        # Look for bullish order blocks (support)
        for i in range(3, len(df)-3):
            # Look for strong bearish candle followed by momentum shift upward
            if (not df['is_bullish'].iloc[i] and 
                df['body_size_pct'].iloc[i] > 1.2 and  # Large bearish candle
                df['momentum'].iloc[i+3] > 0):  # Upward momentum after
                
                # Price area of interest is the bearish candle body
                block_low = min(df['open'].iloc[i], df['close'].iloc[i])
                block_high = max(df['open'].iloc[i], df['close'].iloc[i])
                
                bullish_blocks.append({
                    'index': i,
                    'low': round(block_low, 8),
                    'high': round(block_high, 8),
                    'strength': round(df['body_size_pct'].iloc[i] * df['volume'].iloc[i] / df['volume'].rolling(window=10).mean().iloc[i], 2)
                })
        
        # Look for bearish order blocks (resistance)
        for i in range(3, len(df)-3):
            # Look for strong bullish candle followed by momentum shift downward
            if (df['is_bullish'].iloc[i] and 
                df['body_size_pct'].iloc[i] > 1.2 and  # Large bullish candle
                df['momentum'].iloc[i+3] < 0):  # Downward momentum after
                
                # Price area of interest is the bullish candle body
                block_low = min(df['open'].iloc[i], df['close'].iloc[i])
                block_high = max(df['open'].iloc[i], df['close'].iloc[i])
                
                bearish_blocks.append({
                    'index': i,
                    'low': round(block_low, 8),
                    'high': round(block_high, 8),
                    'strength': round(df['body_size_pct'].iloc[i] * df['volume'].iloc[i] / df['volume'].rolling(window=10).mean().iloc[i], 2)
                })
        
        # Sort blocks by strength
        bullish_blocks.sort(key=lambda x: x['strength'], reverse=True)
        bearish_blocks.sort(key=lambda x: x['strength'], reverse=True)
        
        # Take top 3 strongest blocks
        return {
            'bullish_blocks': bullish_blocks[:3],
            'bearish_blocks': bearish_blocks[:3]
        }
    
    def generate_volume_profile_image(self, df: pd.DataFrame) -> Optional[BytesIO]:
        """
        Hacim profili grafiği oluşturur
        
        Args:
            df: OHLCV verilerini içeren DataFrame
            
        Returns:
            BytesIO: PNG formatında grafik içeren buffer
        """
        try:
            volume_profile = self.analyze_volume_profile(df)
            
            if not volume_profile['volume_profile']:
                return None
                
            # Create figure
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # Prepare data
            price_levels = [item['price_level'] for item in volume_profile['volume_profile']]
            volumes = [item['volume'] for item in volume_profile['volume_profile']]
            
            # Horizontal bar chart (rotated volume profile)
            bars = ax.barh(price_levels, volumes, height=price_levels[1]-price_levels[0] if len(price_levels) > 1 else 1)
            
            # Color POC and Value Area
            poc_level = volume_profile['poc']
            vah = volume_profile['value_area_high']
            val = volume_profile['value_area_low']
            
            for i, bar in enumerate(bars):
                if price_levels[i] >= val and price_levels[i] <= vah:
                    bar.set_color('lightblue')
                if abs(price_levels[i] - poc_level) < (price_levels[1] - price_levels[0]) if len(price_levels) > 1 else 1:
                    bar.set_color('red')
            
            # Add current price line
            current_price = df['close'].iloc[-1]
            ax.axhline(y=current_price, color='green', linestyle='-', linewidth=1)
            
            # Add POC and Value Area lines
            ax.axhline(y=poc_level, color='red', linestyle='--', linewidth=1, alpha=0.7)
            ax.axhline(y=vah, color='blue', linestyle='--', linewidth=1, alpha=0.7)
            ax.axhline(y=val, color='blue', linestyle='--', linewidth=1, alpha=0.7)
            
            # Add text labels
            ax.text(ax.get_xlim()[1]*0.95, current_price, f'Current: {current_price:.2f}', 
                    va='center', ha='right', color='green')
            ax.text(ax.get_xlim()[1]*0.95, poc_level, f'POC: {poc_level:.2f}', 
                    va='center', ha='right', color='red')
            ax.text(ax.get_xlim()[1]*0.95, vah, f'VAH: {vah:.2f}', 
                    va='center', ha='right', color='blue')
            ax.text(ax.get_xlim()[1]*0.95, val, f'VAL: {val:.2f}', 
                    va='center', ha='right', color='blue')
            
            # Set labels and title
            ax.set_title('Volume Profile')
            ax.set_xlabel('Volume')
            ax.set_ylabel('Price')
            
            # Format y-axis to show reasonable number of price levels
            max_labels = 8
            step = max(1, len(price_levels) // max_labels)
            ax.set_yticks(price_levels[::step])
            ax.tick_params(axis='y', labelsize=8)
            
            # Tight layout
            plt.tight_layout()
            
            # Save to buffer
            buf = BytesIO()
            plt.savefig(buf, format='png')
            plt.close(fig)
            buf.seek(0)
            
            return buf
        except Exception as e:
            print(f"Error generating volume profile image: {e}")
            return None


# Kullanım örneği
def analyze_volume_distribution(df):
    analyzer = VolumeProfileAnalyzer()
    volume_profile = analyzer.analyze_volume_profile(df)
    liquidity_zones = analyzer.find_liquidity_zones(df)
    order_blocks = analyzer.identify_order_blocks(df)
    
    result = {
        'poc': volume_profile['poc'],  # Point of Control
        'value_area_high': volume_profile['value_area_high'],
        'value_area_low': volume_profile['value_area_low'],
        'high_liquidity': liquidity_zones['high_liquidity'],
        'low_liquidity': liquidity_zones['low_liquidity'],
        'bullish_blocks': order_blocks['bullish_blocks'],
        'bearish_blocks': order_blocks['bearish_blocks']
    }
    
    return result 