"""
Signal generator module that combines data collection and analysis to generate trading signals.
"""
import logging
from typing import Dict, List
from datetime import datetime
from ..data_collectors.twitter_client import TwitterClient
from ..data_collectors.reddit_client import RedditClient
from ..analysis.sentiment import SentimentAnalyzer

logger = logging.getLogger(__name__)

class SignalGenerator:
    def __init__(self):
        """Initialize signal generator with necessary components."""
        self.twitter_client = TwitterClient()
        self.reddit_client = RedditClient()
        self.sentiment_analyzer = SentimentAnalyzer()
        
    async def generate_sentiment_signals(self, coin: str) -> Dict:
        """
        Generate sentiment-based signals for a specific cryptocurrency.
        
        Args:
            coin: Cryptocurrency symbol (e.g., "BTC", "ETH")
            
        Returns:
            Dictionary containing sentiment signals and analysis.
        """
        signals = {
            "coin": coin,
            "timestamp": datetime.utcnow(),
            "twitter_sentiment": None,
            "reddit_sentiment": None,
            "combined_sentiment": None,
            "signal_strength": 0,
            "sources": []
        }
        
        try:
            # Get Twitter data
            tweets = self.twitter_client.search_tweets(
                keywords=[coin, f"#{coin}", f"#{coin.lower()}", f"#{coin}usdt"],
                hours_ago=24,
                min_retweets=10
            )
            
            # Get Reddit data
            subreddits = [
                "cryptocurrency",
                f"{coin.lower()}",
                "cryptomarkets",
                "cryptocurrencytrading"
            ]
            posts = self.reddit_client.get_hot_posts(subreddits=subreddits, limit=50)
            
            # Analyze Twitter sentiment
            if tweets:
                twitter_texts = [tweet["text"] for tweet in tweets]
                twitter_analysis = self.sentiment_analyzer.analyze_multiple_texts(twitter_texts)
                signals["twitter_sentiment"] = twitter_analysis["overall_sentiment"]
                signals["sources"].append({
                    "platform": "twitter",
                    "count": len(tweets),
                    "analysis": twitter_analysis
                })
                
            # Analyze Reddit sentiment
            if posts:
                reddit_texts = [f"{post['title']} {post['selftext']}" for post in posts]
                reddit_analysis = self.sentiment_analyzer.analyze_multiple_texts(reddit_texts)
                signals["reddit_sentiment"] = reddit_analysis["overall_sentiment"]
                signals["sources"].append({
                    "platform": "reddit",
                    "count": len(posts),
                    "analysis": reddit_analysis
                })
                
            # Calculate combined sentiment and signal strength
            if signals["twitter_sentiment"] and signals["reddit_sentiment"]:
                # Get sentiment scores
                twitter_score = signals["sources"][0]["analysis"]["average_score"]
                reddit_score = signals["sources"][1]["analysis"]["average_score"]
                
                # Weight Twitter more heavily (0.6) than Reddit (0.4)
                combined_score = (twitter_score * 0.6) + (reddit_score * 0.4)
                
                # Determine combined sentiment
                if combined_score > 0.2:
                    signals["combined_sentiment"] = "bullish"
                    signals["signal_strength"] = min(combined_score * 5, 10)  # Scale 0-10
                elif combined_score < -0.2:
                    signals["combined_sentiment"] = "bearish"
                    signals["signal_strength"] = min(abs(combined_score) * 5, 10)
                else:
                    signals["combined_sentiment"] = "neutral"
                    signals["signal_strength"] = min(abs(combined_score) * 3, 10)
                    
        except Exception as e:
            logger.error(f"Error generating sentiment signals for {coin}: {str(e)}")
            
        return signals
    
    def generate_volume_signal(self, volume_data: Dict) -> Dict:
        """
        Generate volume-based trading signals.
        
        Args:
            volume_data: Dictionary containing volume metrics.
            
        Returns:
            Dictionary containing volume analysis and signals.
        """
        signals = {
            "timestamp": datetime.utcnow(),
            "volume_change_24h": 0,
            "volume_signal": "neutral",
            "signal_strength": 0
        }
        
        try:
            # Calculate volume changes
            current_volume = volume_data.get("current_volume", 0)
            avg_volume = volume_data.get("average_volume_24h", 0)
            
            if avg_volume > 0:
                volume_change = ((current_volume - avg_volume) / avg_volume) * 100
                signals["volume_change_24h"] = volume_change
                
                # Generate volume signals
                if volume_change > 50:  # Volume spike
                    signals["volume_signal"] = "high_activity"
                    signals["signal_strength"] = min(volume_change / 10, 10)
                elif volume_change < -50:  # Volume drop
                    signals["volume_signal"] = "low_activity"
                    signals["signal_strength"] = min(abs(volume_change) / 10, 10)
                else:
                    signals["volume_signal"] = "normal"
                    signals["signal_strength"] = min(abs(volume_change) / 20, 10)
                    
        except Exception as e:
            logger.error(f"Error generating volume signals: {str(e)}")
            
        return signals
    
    def combine_signals(self, sentiment_signals: Dict, volume_signals: Dict) -> Dict:
        """
        Combine different types of signals into a final trading signal.
        
        Args:
            sentiment_signals: Dictionary containing sentiment analysis.
            volume_signals: Dictionary containing volume analysis.
            
        Returns:
            Dictionary containing combined signals and trading recommendation.
        """
        combined = {
            "timestamp": datetime.utcnow(),
            "sentiment": sentiment_signals.get("combined_sentiment", "neutral"),
            "sentiment_strength": sentiment_signals.get("signal_strength", 0),
            "volume": volume_signals.get("volume_signal", "normal"),
            "volume_strength": volume_signals.get("signal_strength", 0),
            "final_signal": "hold",
            "confidence": 0
        }
        
        try:
            # Weight sentiment (0.7) and volume (0.3) for final confidence
            confidence = (
                (combined["sentiment_strength"] * 0.7) +
                (combined["volume_strength"] * 0.3)
            )
            combined["confidence"] = min(confidence, 10)
            
            # Generate final signal
            if combined["sentiment"] == "bullish" and combined["volume"] == "high_activity":
                combined["final_signal"] = "strong_buy"
            elif combined["sentiment"] == "bearish" and combined["volume"] == "high_activity":
                combined["final_signal"] = "strong_sell"
            elif combined["sentiment"] == "bullish":
                combined["final_signal"] = "buy"
            elif combined["sentiment"] == "bearish":
                combined["final_signal"] = "sell"
            else:
                combined["final_signal"] = "hold"
                
        except Exception as e:
            logger.error(f"Error combining signals: {str(e)}")
            
        return combined