"""
Script to test individual components of the Crypto Signal Bot.
"""
import asyncio
from src.data_collectors.twitter_client import TwitterClient
from src.data_collectors.reddit_client import RedditClient
from src.analysis.sentiment import SentimentAnalyzer
from src.bot.telegram_bot import CryptoSignalBot

async def test_twitter():
    """Test Twitter data collection."""
    print("\n=== Testing Twitter Client ===")
    client = TwitterClient()
    tweets = client.search_tweets(keywords=["bitcoin", "btc"], hours_ago=1, limit=5)
    print(f"Found {len(tweets)} tweets")
    for tweet in tweets[:2]:  # Show first 2 tweets
        print(f"\nTweet: {tweet['text'][:100]}...")
        print(f"Retweets: {tweet['retweet_count']}")

async def test_reddit():
    """Test Reddit data collection."""
    print("\n=== Testing Reddit Client ===")
    client = RedditClient()
    posts = client.get_hot_posts(subreddits=["cryptocurrency"], limit=5)
    print(f"Found {len(posts)} posts")
    for post in posts[:2]:  # Show first 2 posts
        print(f"\nTitle: {post['title']}")
        print(f"Score: {post['score']}")

async def test_sentiment():
    """Test sentiment analysis."""
    print("\n=== Testing Sentiment Analysis ===")
    analyzer = SentimentAnalyzer()
    texts = [
        "Bitcoin is going to the moon! Very bullish signals! 🚀",
        "Market looks bearish, might be a good time to sell.",
        "Interesting development in the crypto space, need to watch closely."
    ]
    for text in texts:
        analysis = analyzer.analyze_text(text)
        print(f"\nText: {text}")
        print(f"Sentiment: {analysis['sentiment']}")
        print(f"Score: {analysis['combined_score']:.2f}")

async def test_telegram():
    """Test Telegram bot."""
    print("\n=== Testing Telegram Bot ===")
    bot = CryptoSignalBot()
    test_message = {
        "coin": "BTC",
        "sentiment": "bullish",
        "score": 8.5,
        "change": 5.2,
        "source": "twitter, reddit",
        "timestamp": "2024-02-09 12:00:00"
    }
    
    # Replace with your chat ID
    chat_id = input("Enter your Telegram chat ID: ")
    try:
        await bot.send_signal(int(chat_id), "sentiment", test_message)
        print("Test message sent successfully!")
    except Exception as e:
        print(f"Error sending message: {str(e)}")

async def main():
    """Run all tests."""
    try:
        await test_twitter()
    except Exception as e:
        print(f"Twitter test failed: {str(e)}")
    
    try:
        await test_reddit()
    except Exception as e:
        print(f"Reddit test failed: {str(e)}")
    
    try:
        await test_sentiment()
    except Exception as e:
        print(f"Sentiment analysis test failed: {str(e)}")
    
    try:
        await test_telegram()
    except Exception as e:
        print(f"Telegram test failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())