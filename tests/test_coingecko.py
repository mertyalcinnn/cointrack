"""
Test script for CoinGecko API integration
"""
from src.data_collectors.coingecko_client import CoinGeckoClient
from datetime import datetime

def main():
    client = CoinGeckoClient()
    
    # Test 1: Get trending coins
    print("\n=== Testing Trending Coins ===")
    trending = client.get_trending_coins()
    print(f"Found {len(trending)} trending coins:")
    for coin in trending[:5]:  # Show top 5
        print(f"- {coin['name']} ({coin['symbol']}): Rank #{coin['market_cap_rank']}")
    
    # Test 2: Get Bitcoin data
    print("\n=== Testing Bitcoin Data ===")
    btc_data = client.get_coin_data('bitcoin')
    if btc_data:
        print(f"Bitcoin Current Price: ${btc_data['current_price']:,.2f}")
        print(f"24h Change: {btc_data['price_change_24h']:.2f}%")
        print(f"Market Cap: ${btc_data['market_cap']:,.0f}")
        print(f"Reddit Subscribers: {btc_data['reddit_subscribers']:,}")
        print(f"Twitter Followers: {btc_data['twitter_followers']:,}")
    
    # Test 3: Get top market data
    print("\n=== Testing Market Data ===")
    market_data = client.get_market_data(limit=10)  # Get top 10 coins
    print("\nTop 10 Cryptocurrencies by Market Cap:")
    for coin in market_data:
        print(f"{coin['market_cap_rank']}. {coin['name']} ({coin['symbol']})")
        print(f"   Price: ${coin['current_price']:,.2f}")
        print(f"   24h Change: {coin['price_change_24h']:.2f}%")
    
    # Test 4: Get Bitcoin historical data
    print("\n=== Testing Historical Data ===")
    hist_data = client.get_historical_data('bitcoin', days=7)  # Last 7 days
    if hist_data and hist_data['prices']:
        prices = hist_data['prices']
        print(f"\nBitcoin price history (last {len(prices)} days):")
        for price_data in prices[-5:]:  # Show last 5 data points
            date = price_data['timestamp'].strftime('%Y-%m-%d %H:%M')
            price = price_data['value']
            print(f"{date}: ${price:,.2f}")

if __name__ == "__main__":
    main()