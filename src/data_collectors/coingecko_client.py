"""
CoinGecko API client for collecting cryptocurrency data
"""
import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

class CoinGeckoClient:
    def __init__(self):
        """Initialize CoinGecko API client."""
        self.base_url = "https://api.coingecko.com/api/v3"
        self.session = requests.Session()
        
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """
        Make a request to CoinGecko API with rate limit handling.
        
        Args:
            endpoint: API endpoint to call
            params: Query parameters
            
        Returns:
            API response as dictionary
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            response = self.session.get(url, params=params)
            
            # Handle rate limits
            if response.status_code == 429:
                retry_after = int(response.headers.get('retry-after', 60))
                logger.warning(f"Rate limit reached. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                return self._make_request(endpoint, params)
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {str(e)}")
            raise

    def get_trending_coins(self) -> List[Dict]:
        """
        Get trending coins in the last 24 hours.
        
        Returns:
            List of trending coins with their data
        """
        try:
            response = self._make_request("search/trending")
            coins = []
            
            for coin in response.get('coins', []):
                coin_data = coin['item']
                coins.append({
                    "id": coin_data['id'],
                    "name": coin_data['name'],
                    "symbol": coin_data['symbol'].upper(),
                    "market_cap_rank": coin_data['market_cap_rank'],
                    "price_btc": coin_data['price_btc'],
                    "score": coin_data['score']
                })
                
            return coins
            
        except Exception as e:
            logger.error(f"Error getting trending coins: {str(e)}")
            return []

    def get_coin_data(self, coin_id: str) -> Dict:
        """
        Get detailed data for a specific coin.
        
        Args:
            coin_id: CoinGecko coin ID (e.g., 'bitcoin')
            
        Returns:
            Dictionary containing coin data
        """
        try:
            response = self._make_request(
                f"coins/{coin_id}",
                params={
                    'localization': 'false',
                    'tickers': 'false',
                    'community_data': 'true',
                    'developer_data': 'false'
                }
            )
            
            market_data = response.get('market_data', {})
            community_data = response.get('community_data', {})
            
            return {
                "id": response['id'],
                "symbol": response['symbol'].upper(),
                "name": response['name'],
                "current_price": market_data.get('current_price', {}).get('usd'),
                "market_cap": market_data.get('market_cap', {}).get('usd'),
                "total_volume": market_data.get('total_volume', {}).get('usd'),
                "price_change_24h": market_data.get('price_change_percentage_24h'),
                "price_change_7d": market_data.get('price_change_percentage_7d'),
                "market_cap_rank": market_data.get('market_cap_rank'),
                "reddit_subscribers": community_data.get('reddit_subscribers'),
                "reddit_active_accounts": community_data.get('reddit_active_accounts'),
                "twitter_followers": community_data.get('twitter_followers'),
                "sentiment_votes_up_percentage": community_data.get('sentiment_votes_up_percentage')
            }
            
        except Exception as e:
            logger.error(f"Error getting data for coin {coin_id}: {str(e)}")
            return {}

    def get_market_data(
        self,
        vs_currency: str = "usd",
        limit: int = 100,
        order: str = "market_cap_desc"
    ) -> List[Dict]:
        """
        Get market data for top cryptocurrencies.
        
        Args:
            vs_currency: Currency to compare against (e.g., 'usd')
            limit: Number of coins to return
            order: How to order the results
            
        Returns:
            List of coins with market data
        """
        try:
            response = self._make_request(
                "coins/markets",
                params={
                    'vs_currency': vs_currency,
                    'order': order,
                    'per_page': limit,
                    'page': 1,
                    'sparkline': False,
                    'price_change_percentage': '24h,7d'
                }
            )
            
            coins = []
            for coin in response:
                coins.append({
                    "id": coin['id'],
                    "symbol": coin['symbol'].upper(),
                    "name": coin['name'],
                    "current_price": coin['current_price'],
                    "market_cap": coin['market_cap'],
                    "market_cap_rank": coin['market_cap_rank'],
                    "total_volume": coin['total_volume'],
                    "price_change_24h": coin['price_change_percentage_24h'],
                    "price_change_7d": coin.get('price_change_percentage_7d'),
                    "circulating_supply": coin['circulating_supply'],
                    "total_supply": coin['total_supply'],
                    "ath": coin['ath'],
                    "ath_date": coin['ath_date']
                })
                
            return coins
            
        except Exception as e:
            logger.error(f"Error getting market data: {str(e)}")
            return []

    def get_historical_data(
        self,
        coin_id: str,
        days: int = 30,
        interval: str = "daily"
    ) -> Dict:
        """
        Get historical market data for a coin.
        
        Args:
            coin_id: CoinGecko coin ID
            days: Number of days of data to retrieve
            interval: Data interval ('daily' or 'hourly')
            
        Returns:
            Dictionary containing historical data
        """
        try:
            response = self._make_request(
                f"coins/{coin_id}/market_chart",
                params={
                    'vs_currency': 'usd',
                    'days': days,
                    'interval': interval
                }
            )
            
            # Process timestamps and create organized data
            prices = []
            market_caps = []
            volumes = []
            
            for price_data in response.get('prices', []):
                timestamp = datetime.fromtimestamp(price_data[0] / 1000)
                prices.append({
                    "timestamp": timestamp,
                    "value": price_data[1]
                })
                
            for mc_data in response.get('market_caps', []):
                timestamp = datetime.fromtimestamp(mc_data[0] / 1000)
                market_caps.append({
                    "timestamp": timestamp,
                    "value": mc_data[1]
                })
                
            for vol_data in response.get('total_volumes', []):
                timestamp = datetime.fromtimestamp(vol_data[0] / 1000)
                volumes.append({
                    "timestamp": timestamp,
                    "value": vol_data[1]
                })
                
            return {
                "prices": prices,
                "market_caps": market_caps,
                "volumes": volumes
            }
            
        except Exception as e:
            logger.error(f"Error getting historical data for coin {coin_id}: {str(e)}")
            return {}