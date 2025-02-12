"""
Twitter API V2 client with optimized queries and rate limit handling
"""
import os
import logging
from typing import List, Dict, Optional
import tweepy
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

class TwitterClient:
    def __init__(self):
        """Initialize Twitter API V2 client using credentials from environment variables."""
        self.bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
        
        if not self.bearer_token:
            raise ValueError("Missing TWITTER_BEARER_TOKEN in environment variables")
        
        # Initialize API V2 client with Bearer Token
        self.client = tweepy.Client(
            bearer_token=self.bearer_token,
            wait_on_rate_limit=True,
            return_type=dict  # Return dictionary instead of Response object
        )
        
        # Common crypto-related hashtags and keywords
        self.default_keywords = [
            "bitcoin price", "btc price",
            "ethereum price", "eth price"
        ]

    def search_tweets(
        self,
        keywords: Optional[List[str]] = None,
        hours_ago: int = 1,  # Reduced default time range
        limit: int = 10
    ) -> List[Dict]:
        """
        Search for crypto-related tweets using Twitter API V2.
        
        Args:
            keywords: List of keywords to search for. If None, uses default keywords.
            hours_ago: How many hours back to search.
            limit: Maximum number of tweets to return (must be between 10 and 100).
            
        Returns:
            List of dictionaries containing tweet data.
        """
        if keywords is None:
            keywords = self.default_keywords
            
        # Ensure limit is within API bounds
        limit = max(10, min(limit, 100))
            
        # Create optimized search query
        query = "(" + " OR ".join(f'"{keyword}"' for keyword in keywords) + ")"
        query += " -is:retweet -is:reply lang:en"  # Exclude retweets and replies
        
        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours_ago)
        
        tweets = []
        try:
            # Search tweets using API V2
            response = self.client.search_recent_tweets(
                query=query,
                max_results=limit,
                start_time=start_time,
                tweet_fields='created_at,public_metrics,entities',
                user_fields='username',
                expansions='author_id'
            )
            
            if response and 'data' in response:
                # Create a user lookup dictionary
                users = {
                    user['id']: user 
                    for user in response.get('includes', {}).get('users', [])
                } if 'includes' in response else {}
                
                for tweet in response['data']:
                    author = users.get(tweet['author_id'])
                    metrics = tweet.get('public_metrics', {})
                    
                    tweet_data = {
                        "id": tweet['id'],
                        "created_at": tweet['created_at'],
                        "text": tweet['text'],
                        "user": author['username'] if author else "unknown",
                        "retweet_count": metrics.get('retweet_count', 0),
                        "like_count": metrics.get('like_count', 0),
                        "reply_count": metrics.get('reply_count', 0),
                        "quote_count": metrics.get('quote_count', 0),
                        "hashtags": [
                            tag['tag'] 
                            for tag in tweet.get('entities', {}).get('hashtags', [])
                        ] if 'entities' in tweet and 'hashtags' in tweet['entities'] else []
                    }
                    tweets.append(tweet_data)
                
        except tweepy.errors.TooManyRequests as e:
            # Get retry-after time from response
            try:
                retry_after = int(e.response.headers.get('x-rate-limit-reset', 60))
                current_time = int(time.time())
                wait_time = retry_after - current_time
                if wait_time > 0:
                    raise Exception(f"Rate limit exceeded. Sleeping for {wait_time} seconds.")
            except:
                raise Exception("Rate limit exceeded. Please try again later.")
        except Exception as e:
            logger.error(f"Error searching tweets: {str(e)}")
            raise
            
        return tweets

    def get_user_tweets(
        self,
        username: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get recent tweets from a specific user using Twitter API V2.
        
        Args:
            username: Twitter username to fetch tweets from.
            limit: Maximum number of tweets to return (must be between 10 and 100).
            
        Returns:
            List of dictionaries containing tweet data.
        """
        tweets = []
        try:
            # Ensure limit is within API bounds
            limit = max(10, min(limit, 100))
            
            # First get user ID from username
            user_response = self.client.get_user(username=username)
            if not user_response or 'data' not in user_response:
                return tweets
            
            user_id = user_response['data']['id']
            
            # Get user's tweets
            response = self.client.get_users_tweets(
                id=user_id,
                max_results=limit,
                tweet_fields='created_at,public_metrics,entities'
            )
            
            if response and 'data' in response:
                for tweet in response['data']:
                    metrics = tweet.get('public_metrics', {})
                    
                    tweet_data = {
                        "id": tweet['id'],
                        "created_at": tweet['created_at'],
                        "text": tweet['text'],
                        "retweet_count": metrics.get('retweet_count', 0),
                        "like_count": metrics.get('like_count', 0),
                        "reply_count": metrics.get('reply_count', 0),
                        "quote_count": metrics.get('quote_count', 0),
                        "hashtags": [
                            tag['tag'] 
                            for tag in tweet.get('entities', {}).get('hashtags', [])
                        ] if 'entities' in tweet and 'hashtags' in tweet['entities'] else []
                    }
                    tweets.append(tweet_data)
                
        except Exception as e:
            logger.error(f"Error getting user tweets: {str(e)}")
            raise
            
        return tweets