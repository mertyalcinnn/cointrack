"""
Test script for Twitter API V2 integration with optimized queries
"""
from dotenv import load_dotenv
from src.data_collectors.twitter_client import TwitterClient
import time

def main():
    # Load environment variables
    load_dotenv()
    
    # Initialize Twitter client
    client = TwitterClient()
    
    # Test tweet search with more specific query
    print("Testing tweet search...")
    print("Searching for Bitcoin-related tweets...")
    
    try:
        # Just search for Bitcoin to minimize API usage
        tweets = client.search_tweets(
            keywords=["bitcoin price", "btc price"],  # More specific keywords
            hours_ago=1,
            limit=10
        )
        
        print(f"\nFound {len(tweets)} tweets")
        for tweet in tweets:
            print("\n-------------------")
            print(f"User: @{tweet['user']}")
            print(f"Tweet: {tweet['text']}")
            print(f"Metrics:")
            print(f"  - Retweets: {tweet['retweet_count']}")
            print(f"  - Likes: {tweet['like_count']}")
            if tweet['hashtags']:
                print(f"Hashtags: {', '.join(['#' + tag for tag in tweet['hashtags']])}")
    
    except Exception as e:
        if "Rate limit" in str(e):
            retry_after = 60  # Default retry after 1 minute
            try:
                # Try to get retry time from error message
                retry_after = int(str(e).split("Sleeping for")[1].split("seconds")[0].strip())
            except:
                pass
            
            print(f"\nRate limit reached. Please try again in {retry_after} seconds.")
            print("This is normal with Twitter's free API tier.")
            print("\nAlternatives while waiting:")
            print("1. Use more specific search terms")
            print("2. Reduce the time range (currently 1 hour)")
            print("3. Consider upgrading to a paid API tier")
        else:
            print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()