from src.data_collectors.binance_client import BinanceDataCollector

def main():
    client = BinanceDataCollector()
    
    # BTCUSDT için son 5 saatlik mum verilerini al
    klines = client.get_klines("BTCUSDT", "1h", 5)
    print("\nSon 5 saatlik BTCUSDT verileri:")
    for k in klines:
        print(f"Zaman: {k['timestamp']}, Kapanış: {k['close']}, Hacim: {k['volume']}")
    
    # Anlık BTC fiyatını al
    price = client.get_ticker_price("BTCUSDT")
    print(f"\nBTCUSDT Anlık Fiyat: {price}")

if __name__ == "__main__":
    main()