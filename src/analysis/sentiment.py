"""
Sentiment analysis module for crypto-related text content.
"""
import logging
from typing import Dict, List, Union
from textblob import TextBlob
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('punkt')
    nltk.download('stopwords')

logger = logging.getLogger(__name__)

class SentimentAnalyzer:
    def __init__(self):
        """Initialize sentiment analyzer with crypto-specific configurations."""
        # Crypto-specific positive and negative words
        self.crypto_positive = {
            "bullish", "moon", "mooning", "hodl", "buy", "long",
            "support", "breakthrough", "breakout", "buy_the_dip",
            "adoption", "partnership", "launched", "huge", "gain"
        }
        
        self.crypto_negative = {
            "bearish", "dump", "selling", "short", "resistance",
            "scam", "hack", "fraud", "ban", "crash", "rugpull",
            "ponzi", "correction", "postponed", "delayed"
        }
        
        # Initialize stopwords
        self.stop_words = set(stopwords.words('english'))

    def analyze_text(self, text: str) -> Dict[str, Union[float, str]]:
        """
        Analyze sentiment of given text using TextBlob and custom crypto lexicon.
        
        Args:
            text: Text content to analyze.
            
        Returns:
            Dictionary containing sentiment scores and classification.
        """
        # Clean and tokenize text
        tokens = word_tokenize(text.lower())
        tokens = [token for token in tokens if token not in self.stop_words]
        
        # Count crypto-specific terms
        crypto_positive_count = sum(1 for token in tokens if token in self.crypto_positive)
        crypto_negative_count = sum(1 for token in tokens if token in self.crypto_negative)
        
        # Get TextBlob sentiment
        blob = TextBlob(text)
        
        # Calculate custom crypto sentiment score
        crypto_score = (crypto_positive_count - crypto_negative_count) / (crypto_positive_count + crypto_negative_count + 1)
        
        # Combine TextBlob and crypto-specific sentiment
        combined_score = (blob.sentiment.polarity + crypto_score) / 2
        
        # Determine sentiment classification
        if combined_score > 0.2:
            sentiment = "bullish"
        elif combined_score < -0.2:
            sentiment = "bearish"
        else:
            sentiment = "neutral"
            
        return {
            "textblob_score": blob.sentiment.polarity,
            "textblob_subjectivity": blob.sentiment.subjectivity,
            "crypto_score": crypto_score,
            "combined_score": combined_score,
            "sentiment": sentiment,
            "crypto_positive_terms": crypto_positive_count,
            "crypto_negative_terms": crypto_negative_count
        }

    def analyze_multiple_texts(self, texts: List[str]) -> Dict[str, Union[float, List[Dict]]]:
        """
        Analyze sentiment for multiple texts and provide aggregate scores.
        
        Args:
            texts: List of text content to analyze.
            
        Returns:
            Dictionary containing individual and aggregate sentiment analysis.
        """
        results = []
        total_combined_score = 0
        
        for text in texts:
            analysis = self.analyze_text(text)
            results.append(analysis)
            total_combined_score += analysis["combined_score"]
            
        avg_score = total_combined_score / len(texts) if texts else 0
        
        # Determine overall sentiment
        if avg_score > 0.2:
            overall_sentiment = "bullish"
        elif avg_score < -0.2:
            overall_sentiment = "bearish"
        else:
            overall_sentiment = "neutral"
            
        return {
            "individual_analyses": results,
            "average_score": avg_score,
            "overall_sentiment": overall_sentiment,
            "total_texts": len(texts)
        }

    def get_sentiment_trends(self, texts_with_time: List[Dict[str, str]]) -> Dict:
        """
        Analyze sentiment trends over time.
        
        Args:
            texts_with_time: List of dictionaries containing text and timestamp.
                           Format: [{"text": "...", "timestamp": "..."}, ...]
            
        Returns:
            Dictionary containing sentiment trends and changes.
        """
        # Sort texts by timestamp
        sorted_texts = sorted(texts_with_time, key=lambda x: x["timestamp"])
        
        trends = {
            "sentiment_scores": [],
            "timestamps": [],
            "sentiment_changes": []
        }
        
        previous_score = None
        
        for item in sorted_texts:
            analysis = self.analyze_text(item["text"])
            current_score = analysis["combined_score"]
            
            trends["sentiment_scores"].append(current_score)
            trends["timestamps"].append(item["timestamp"])
            
            if previous_score is not None:
                change = current_score - previous_score
                trends["sentiment_changes"].append(change)
            
            previous_score = current_score
            
        # Calculate trend statistics
        if trends["sentiment_scores"]:
            trends["average_score"] = sum(trends["sentiment_scores"]) / len(trends["sentiment_scores"])
            trends["max_score"] = max(trends["sentiment_scores"])
            trends["min_score"] = min(trends["sentiment_scores"])
            
            if len(trends["sentiment_changes"]) > 0:
                trends["average_change"] = sum(trends["sentiment_changes"]) / len(trends["sentiment_changes"])
                trends["volatility"] = sum(abs(change) for change in trends["sentiment_changes"]) / len(trends["sentiment_changes"])
            
        return trends