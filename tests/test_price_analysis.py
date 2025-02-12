import pytest
from datetime import datetime, timedelta
from src.analysis.price_analysis import PriceAnalyzer

@pytest.fixture
def sample_price_data():
    # Test için örnek fiyat verileri oluştur
    base_time = datetime.now()
    return [
        {
            'timestamp': (base_time - timedelta(hours=i)).isoformat(),
            'price': price
        }
        for i, price in enumerate([
            100, 102, 105, 103, 106, 110,  # Son 6 saat yükseliş trendi
            108, 107, 106, 105, 104, 103,  # Önceki 6 saat düşüş trendi
            102, 101, 100, 99, 98, 97      # Daha önceki 6 saat düşüş trendi
        ])
    ]

def test_price_trend_analysis_short_term(sample_price_data):
    analyzer = PriceAnalyzer()
    result = analyzer.analyze_price_trend(sample_price_data, 'SHORT')
    
    assert result['trend'] == 'BULLISH'
    assert result['price_change'] > 0
    assert 0 <= result['confidence'] <= 1

def test_price_trend_analysis_empty_data():
    analyzer = PriceAnalyzer()
    result = analyzer.analyze_price_trend([], 'SHORT')
    
    assert result['trend'] == 'NEUTRAL'
    assert result['confidence'] == 0
    assert result['price_change'] == 0

def test_breakout_detection(sample_price_data):
    analyzer = PriceAnalyzer()
    # Örnek veriye ani bir fiyat artışı ekle
    sample_price_data.insert(0, {
        'timestamp': datetime.now().isoformat(),
        'price': 150  # Ani yükseliş
    })
    
    result = analyzer.detect_breakout(sample_price_data)
    assert result is not None
    assert result['type'] == 'UPWARD_BREAKOUT'
    assert result['magnitude'] > 0

def test_no_breakout_normal_movement(sample_price_data):
    analyzer = PriceAnalyzer()
    result = analyzer.detect_breakout(sample_price_data)
    assert result is None