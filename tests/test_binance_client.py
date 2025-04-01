import pytest
from src.data_collectors.binance_client import BinanceDataCollector

def test_binance_client_initialization():
    client = BinanceDataCollector()
    assert client is not None

def test_get_klines():
    client = BinanceDataCollector()
    klines = client.get_klines("BTCUSDT", "1h", 10)
    assert len(klines) == 10
    assert all(key in klines[0] for key in ['timestamp', 'open', 'high', 'low', 'close'])

def test_get_ticker_price():
    client = BinanceDataCollector()
    price = client.get_ticker_price("BTCUSDT")
    assert isinstance(price, float)
    assert price > 0