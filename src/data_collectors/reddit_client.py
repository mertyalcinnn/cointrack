"""
Reddit API client for collecting crypto-related posts and comments.
"""
import os
import logging
from typing import List, Dict
import praw
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class RedditClient:
    def __init__(self):
        """Initialize Reddit API client using credentials from environment variables."""
        self.client_id = os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        self.user_agent = os.getenv("REDDIT_USER_AGENT", "CryptoSignalBot/1.0")
        
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Missing Reddit API credentials in environment variables")
        
        # Initialize Reddit client
        self.reddit = praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent
        )
        
        # Default crypto subreddits to monitor
        self.default_subreddits = [
            "cryptocurrency",
            "bitcoin",
            "ethereum",
            "cryptomarkets",
            "altcoin",
            "defi",
            "bitcoinmarkets"
        ]

    def get_hot_posts(
        self,
        subreddits: List[str] = None,
        limit: int = 50,
        min_score: int = 10
    ) -> List[Dict]:
        """
        Get hot posts from specified crypto subreddits.
        
        Args:
            subreddits: List of subreddit names. If None, uses default list.
            limit: Maximum number of posts to return per subreddit.
            min_score: Minimum score (upvotes) required for posts.
            
        Returns:
            List of dictionaries containing post data.
        """
        if subreddits is None:
            subreddits = self.default_subreddits
            
        posts = []
        for subreddit_name in subreddits:
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
                for post in subreddit.hot(limit=limit):
                    if post.score >= min_score:
                        post_data = {
                            "id": post.id,
                            "created_utc": datetime.fromtimestamp(post.created_utc),
                            "title": post.title,
                            "selftext": post.selftext,
                            "score": post.score,
                            "upvote_ratio": post.upvote_ratio,
                            "num_comments": post.num_comments,
                            "subreddit": subreddit_name,
                            "url": post.url,
                            "permalink": f"https://reddit.com{post.permalink}"
                        }
                        posts.append(post_data)
                        
            except Exception as e:
                logger.error(f"Error getting posts from r/{subreddit_name}: {str(e)}")
                
        return posts

    def get_new_posts(
        self,
        subreddits: List[str] = None,
        hours_ago: int = 24,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get new posts from specified crypto subreddits within time range.
        
        Args:
            subreddits: List of subreddit names. If None, uses default list.
            hours_ago: How many hours back to look for posts.
            limit: Maximum number of posts to return per subreddit.
            
        Returns:
            List of dictionaries containing post data.
        """
        if subreddits is None:
            subreddits = self.default_subreddits
            
        posts = []
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_ago)
        
        for subreddit_name in subreddits:
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
                for post in subreddit.new(limit=limit):
                    post_time = datetime.fromtimestamp(post.created_utc)
                    if post_time >= cutoff_time:
                        post_data = {
                            "id": post.id,
                            "created_utc": post_time,
                            "title": post.title,
                            "selftext": post.selftext,
                            "score": post.score,
                            "upvote_ratio": post.upvote_ratio,
                            "num_comments": post.num_comments,
                            "subreddit": subreddit_name,
                            "url": post.url,
                            "permalink": f"https://reddit.com{post.permalink}"
                        }
                        posts.append(post_data)
                        
            except Exception as e:
                logger.error(f"Error getting posts from r/{subreddit_name}: {str(e)}")
                
        return posts

    def get_post_comments(
        self,
        post_id: str,
        limit: int = 100,
        min_score: int = 5
    ) -> List[Dict]:
        """
        Get comments from a specific Reddit post.
        
        Args:
            post_id: Reddit post ID to get comments from.
            limit: Maximum number of comments to return.
            min_score: Minimum score (upvotes) required for comments.
            
        Returns:
            List of dictionaries containing comment data.
        """
        comments = []
        try:
            submission = self.reddit.submission(id=post_id)
            submission.comments.replace_more(limit=0)  # Flatten comment tree
            
            for comment in submission.comments.list()[:limit]:
                if comment.score >= min_score:
                    comment_data = {
                        "id": comment.id,
                        "created_utc": datetime.fromtimestamp(comment.created_utc),
                        "body": comment.body,
                        "score": comment.score,
                        "author": str(comment.author),
                        "is_submitter": comment.is_submitter
                    }
                    comments.append(comment_data)
                    
        except Exception as e:
            logger.error(f"Error getting comments for post {post_id}: {str(e)}")
            
        return comments