"""
Web üzerinde araştırma yaparak kripto para analizi için veri toplayan modül.
"""

import os
import json
import time
import logging
import asyncio
import aiohttp
import requests
from typing import Dict, List, Tuple, Any, Optional
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

# Opsiyonel API'ler için
try:
    from serpapi import GoogleSearch
except ImportError:
    GoogleSearch = None

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

class WebResearcher:
    """Kripto projeler hakkında web araştırması yaparak veri toplayan sınıf"""
    
    def __init__(self, logger=None, cache_dir="cache/web_research"):
        """WebResearcher sınıfını başlat"""
        self.logger = logger or logging.getLogger('WebResearcher')
        
        # .env dosyasının yolunu bul ve yükle
        env_path = Path(__file__).parent.parent.parent / '.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
        
        # API anahtarlarını al
        self.serp_api_key = os.getenv('SERPAPI_KEY')
        
        # HTTP oturumu
        self.session = None
        
        # Önbellek ayarları
        self.cache_dir = cache_dir
        self.cache_duration = 3600 * 12  # 12 saat (saniye cinsinden)
        
        # Önbellek dizinini oluştur
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.allowed_domains = [
            'coinmarketcap.com', 'coingecko.com', 'coindesk.com', 
            'cointelegraph.com', 'bloomberg.com', 'reuters.com',
            'investing.com', 'finance.yahoo.com', 'github.com',
            'medium.com', 'messari.io', 'defipulse.com',
            'binance.com', 'cryptoslate.com', 'decrypt.co',
            'theblockcrypto.com', 'theblock.co', 'trustnodes.com',
            'bitcoinist.com', 'twitter.com', 'reddit.com',
            'hackernoon.com', 'tradingview.com', 'bitfinex.com'
        ]
        
        self.logger.info("WebResearcher başlatıldı")
    
    async def initialize(self):
        """Async başlatma"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            
        return self
    
    async def close(self):
        """Kaynakları serbest bırak"""
        if self.session:
            try:
                self.logger.info("HTTP oturumu kapatılıyor...")
                await self.session.close()
                self.session = None
                self.logger.info("HTTP oturumu başarıyla kapatıldı")
            except Exception as e:
                self.logger.error(f"HTTP oturumu kapatılırken hata: {e}")
                # Yöntemi değiştirerek kapatmayı dene
                try:
                    if hasattr(self.session, '_connector'):
                        if hasattr(self.session._connector, '_close'):
                            await self.session._connector._close()
                    if hasattr(self.session, '_connector_owner') and self.session._connector_owner:
                        await self.session._connector.close()
                    self.session = None
                    self.logger.info("HTTP oturumu alternatif yöntemle kapatıldı")
                except Exception as e2:
                    self.logger.error(f"HTTP oturumu alternatif yöntemle kapatılırken hata: {e2}")
    
    async def research_crypto(self, symbol: str, include_price: bool = True) -> Dict:
        """Kripto para birimi hakkında web araştırması yap"""
        # Sembol formatını düzenle
        clean_symbol = symbol.replace('USDT', '')  # BTCUSDT -> BTC
        
        # Önbellek kontrolü
        cache_file = os.path.join(self.cache_dir, f"{clean_symbol.lower()}_research.json")
        cached_data = self._check_cache(cache_file)
        if cached_data:
            self.logger.info(f"{clean_symbol} için önbellekten araştırma sonucu kullanılıyor")
            return cached_data
        
        # Araştırma sonuçları için birleştirilmiş sonuç
        research_results = {
            "symbol": clean_symbol,
            "full_name": "",
            "description": "",
            "website": "",
            "github": "",
            "twitter": "",
            "reddit": "",
            "team": [],
            "market_data": {},
            "news": [],
            "sentiment": {},
            "project_metrics": {},
            "analysis_summary": "",
            "last_updated": datetime.now().isoformat()
        }
        
        # Temel bilgileri topla
        project_info = await self._get_project_info(clean_symbol)
        if project_info:
            research_results.update(project_info)
        
        # Piyasa verilerini topla (isteğe bağlı)
        if include_price:
            market_data = await self._get_market_data(clean_symbol)
            if market_data:
                research_results["market_data"] = market_data
        
        # Haberleri topla
        news = await self._get_news(clean_symbol, limit=5)
        if news:
            research_results["news"] = news
        
        # Sosyal medya ve topluluk verilerini topla
        community_data = await self._get_community_data(clean_symbol)
        if community_data:
            research_results.update(community_data)
        
        # Özet analiz
        research_results["analysis_summary"] = await self._generate_analysis_summary(
            clean_symbol, research_results
        )
        
        # Önbelleğe kaydet
        self._save_to_cache(cache_file, research_results)
        
        return research_results
    
    async def _get_project_info(self, symbol: str) -> Dict:
        """Kripto para projesi hakkında temel bilgileri al"""
        try:
            # Farklı kaynaklardan temel bilgileri toplayalım
            results = {}
            
            # CoinGecko üzerinden bilgi almaya çalış
            async with self.session.get(
                f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}",
                headers={"accept": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    results["full_name"] = data.get("name", "")
                    results["description"] = data.get("description", {}).get("en", "")
                    results["website"] = data.get("links", {}).get("homepage", [""])[0]
                    results["github"] = data.get("links", {}).get("repos_url", {}).get("github", [""])[0]
                    results["twitter"] = data.get("links", {}).get("twitter_screen_name", "")
                    results["reddit"] = data.get("links", {}).get("subreddit_url", "")
                    
                    # Kurucular bilgisi
                    team_info = []
                    if "team" in data:
                        for member in data["team"]:
                            team_info.append({
                                "name": member.get("name", ""),
                                "position": member.get("position", ""),
                                "avatar": member.get("avatar", "")
                            })
                    results["team"] = team_info
            
            # Eğer veriler eksikse web araştırması yap
            if not results.get("description") or not results.get("full_name"):
                web_info = await self._search_web_for_project_info(symbol)
                
                # Eksik alanları doldur
                for key, value in web_info.items():
                    if not results.get(key) and value:
                        results[key] = value
            
            return results
        except Exception as e:
            self.logger.error(f"Proje bilgileri alınırken hata: {e}")
            return {}
    
    async def _search_web_for_project_info(self, symbol: str) -> Dict:
        """Web üzerinde arama yaparak proje bilgilerini topla"""
        results = {
            "full_name": "",
            "description": "",
            "website": "",
            "github": "",
            "twitter": "",
            "reddit": ""
        }
        
        try:
            # 1. Arama sorgusu oluştur
            search_query = f"{symbol} cryptocurrency project information"
            
            # 2. DuckDuckGo veya Google arama sonuçları
            search_results = []
            
            # DuckDuckGo arama (API anahtarı gerektirmez)
            if DDGS:
                with DDGS() as ddgs:
                    ddg_results = list(ddgs.text(search_query, max_results=5))
                    if ddg_results:
                        search_results.extend([{
                            'title': r.get('title', ''),
                            'link': r.get('href', ''),
                            'snippet': r.get('body', '')
                        } for r in ddg_results])
            
            # Google arama (SerpAPI ile - API anahtarı gerektirir)
            if not search_results and GoogleSearch and self.serp_api_key:
                params = {
                    "engine": "google",
                    "q": search_query,
                    "api_key": self.serp_api_key,
                    "num": 5
                }
                search = GoogleSearch(params)
                data = search.get_dict()
                if "organic_results" in data:
                    search_results.extend([{
                        'title': r.get('title', ''),
                        'link': r.get('link', ''),
                        'snippet': r.get('snippet', '')
                    } for r in data["organic_results"]])
            
            # Sonuçlar yoksa, basit bir web araması yap
            if not search_results:
                async with self.session.get(
                    f"https://www.google.com/search?q={search_query}",
                    headers={"User-Agent": "Mozilla/5.0"}
                ) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Google sonuç elementlerini bul
                        for result in soup.select('.g'):
                            title_elem = result.select_one('.LC20lb')
                            link_elem = result.select_one('a')
                            snippet_elem = result.select_one('.VwiC3b')
                            
                            if title_elem and link_elem and snippet_elem:
                                search_results.append({
                                    'title': title_elem.get_text(),
                                    'link': link_elem.get('href', ''),
                                    'snippet': snippet_elem.get_text()
                                })
            
            # 3. Arama sonuçlarını analiz et
            for result in search_results:
                # Tam adı bul
                if symbol.lower() in result['title'].lower() and not results['full_name']:
                    potential_name = result['title'].split('-')[0].strip()
                    if len(potential_name) < 50:  # Uzun başlıkları engelle
                        results['full_name'] = potential_name
                
                # Açıklama bul
                if not results['description'] and len(result['snippet']) > 50:
                    results['description'] = result['snippet']
                
                # Web sitesi, GitHub, Twitter ve Reddit bağlantıları
                link = result['link'].lower()
                if link.startswith('http') and not any(d in link for d in ['google.com', 'youtube.com']):
                    # Resmi web sitesi
                    if not results['website'] and symbol.lower() in link:
                        results['website'] = link
                    
                    # GitHub
                    if 'github.com' in link and not results['github']:
                        results['github'] = link
                    
                    # Twitter
                    if 'twitter.com' in link and not results['twitter']:
                        results['twitter'] = link
                    
                    # Reddit
                    if 'reddit.com/r/' in link and not results['reddit']:
                        results['reddit'] = link
            
            # 4. Eğer yine de açıklama bulunamadıysa, Wikipedia'dan dene
            if not results['description']:
                async with self.session.get(
                    f"https://en.wikipedia.org/wiki/{symbol}_(cryptocurrency)",
                    headers={"User-Agent": "Mozilla/5.0"}
                ) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # İlk paragrafı al
                        first_paragraph = soup.select_one('.mw-parser-output > p')
                        if first_paragraph:
                            results['description'] = first_paragraph.get_text()
            
            return results
        except Exception as e:
            self.logger.error(f"Web araştırması sırasında hata: {e}")
            return results
    
    async def _get_market_data(self, symbol: str) -> Dict:
        """Kripto para birimi için piyasa verilerini al"""
        try:
            # CoinGecko API ile piyasa verilerini al
            async with self.session.get(
                f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}/market_chart?vs_currency=usd&days=30",
                headers={"accept": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Son fiyat
                    prices = data.get("prices", [])
                    current_price = prices[-1][1] if prices else None
                    
                    # Piyasa değeri
                    market_caps = data.get("market_caps", [])
                    market_cap = market_caps[-1][1] if market_caps else None
                    
                    # Hacim
                    volumes = data.get("total_volumes", [])
                    volume = volumes[-1][1] if volumes else None
                    
                    # Fiyat değişimi (30 gün)
                    price_change_30d = ((prices[-1][1] / prices[0][1]) - 1) * 100 if prices and len(prices) > 1 else None
                    
                    return {
                        "current_price": current_price,
                        "market_cap": market_cap,
                        "volume": volume,
                        "price_change_30d": price_change_30d
                    }
            
            return {}
        except Exception as e:
            self.logger.error(f"Piyasa verileri alınırken hata: {e}")
            return {}
    
    async def _get_news(self, symbol: str, limit: int = 5) -> List[Dict]:
        """Kripto para birimi hakkında haberleri al"""
        try:
            news_results = []
            
            # Haber arama sorgusu
            search_query = f"{symbol} cryptocurrency news"
            
            # DuckDuckGo News arama
            if DDGS:
                with DDGS() as ddgs:
                    ddg_results = list(ddgs.news(search_query, max_results=limit))
                    if ddg_results:
                        for r in ddg_results:
                            news_results.append({
                                'title': r.get('title', ''),
                                'url': r.get('url', ''),
                                'source': r.get('source', ''),
                                'date': r.get('date', ''),
                                'snippet': r.get('body', '')
                            })
            
            # Google News arama (SerpAPI ile)
            if not news_results and GoogleSearch and self.serp_api_key:
                params = {
                    "engine": "google_news",
                    "q": search_query,
                    "api_key": self.serp_api_key,
                    "num": limit
                }
                search = GoogleSearch(params)
                data = search.get_dict()
                if "news_results" in data:
                    for r in data["news_results"]:
                        news_results.append({
                            'title': r.get('title', ''),
                            'url': r.get('link', ''),
                            'source': r.get('source', ''),
                            'date': r.get('date', ''),
                            'snippet': r.get('snippet', '')
                        })
            
            # Manuel haber kaynaklarını tarama (son çare)
            if not news_results:
                news_sources = [
                    f"https://www.coindesk.com/search?s={symbol}",
                    f"https://cointelegraph.com/search?query={symbol}",
                    f"https://cryptoslate.com/search/{symbol}/"
                ]
                
                for source_url in news_sources:
                    async with self.session.get(
                        source_url, 
                        headers={"User-Agent": "Mozilla/5.0"}
                    ) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # CoinDesk için
                            if "coindesk.com" in source_url:
                                articles = soup.select('.article-cardstyles__AcTitle-sc-q1x8lc-1')
                                for article in articles[:limit]:
                                    link_elem = article.find('a')
                                    if link_elem:
                                        url = "https://www.coindesk.com" + link_elem.get('href', '')
                                        title = link_elem.get_text()
                                        news_results.append({
                                            'title': title,
                                            'url': url,
                                            'source': 'CoinDesk',
                                            'date': '',
                                            'snippet': ''
                                        })
                            
                            # CoinTelegraph için
                            elif "cointelegraph.com" in source_url:
                                articles = soup.select('.post-card-inline')
                                for article in articles[:limit]:
                                    title_elem = article.select_one('.post-card-inline__title')
                                    link_elem = article.select_one('a')
                                    if title_elem and link_elem:
                                        title = title_elem.get_text()
                                        url = "https://cointelegraph.com" + link_elem.get('href', '')
                                        news_results.append({
                                            'title': title,
                                            'url': url,
                                            'source': 'CoinTelegraph',
                                            'date': '',
                                            'snippet': ''
                                        })
            
            return news_results[:limit]
        except Exception as e:
            self.logger.error(f"Haberler alınırken hata: {e}")
            return []
    
    async def _get_community_data(self, symbol: str) -> Dict:
        """Kripto para birimi topluluk verilerini al"""
        try:
            community_data = {
                "social_metrics": {},
                "developer_activity": {}
            }
            
            # Farklı kaynaklardan veri topla
            try:
                # CoinGecko'dan topluluk verileri
                async with self.session.get(
                    f"https://api.coingecko.com/api/v3/coins/{symbol.lower()}?community_data=true&developer_data=true",
                    headers={"accept": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Sosyal medya metrikleri
                        social = data.get("community_data", {})
                        if social:
                            community_data["social_metrics"] = {
                                "twitter_followers": social.get("twitter_followers", 0),
                                "reddit_subscribers": social.get("reddit_subscribers", 0),
                                "telegram_users": social.get("telegram_channel_user_count", 0),
                            }
                        
                        # Geliştirici aktivitesi
                        dev_data = data.get("developer_data", {})
                        if dev_data:
                            community_data["developer_activity"] = {
                                "github_stars": dev_data.get("stars", 0),
                                "github_subscribers": dev_data.get("subscribers", 0),
                                "github_contributors": dev_data.get("contributors", 0),
                                "github_commits_4_weeks": dev_data.get("commit_count_4_weeks", 0)
                            }
            except Exception as api_error:
                self.logger.error(f"CoinGecko API hatası: {api_error}")
            
            return community_data
        except Exception as e:
            self.logger.error(f"Topluluk verileri alınırken hata: {e}")
            return {}
    
    async def _generate_analysis_summary(self, symbol: str, research_data: Dict) -> str:
        """Toplanan verilere dayanarak bir analiz özeti oluştur"""
        try:
            summary_parts = []
            
            # Proje açıklaması
            if research_data.get("description"):
                # Açıklamayı kısalt
                description = research_data["description"]
                if len(description) > 500:
                    description = description[:500] + "..."
                summary_parts.append(f"Project Overview: {description}")
            
            # Fiyat ve piyasa verileri
            market_data = research_data.get("market_data", {})
            if market_data:
                market_summary = "Market Data: "
                if market_data.get("current_price"):
                    market_summary += f"Current price: ${market_data['current_price']:.4f}. "
                if market_data.get("market_cap"):
                    market_summary += f"Market cap: ${market_data['market_cap']:,.0f}. "
                if market_data.get("price_change_30d") is not None:
                    direction = "up" if market_data["price_change_30d"] > 0 else "down"
                    market_summary += f"Price change (30d): {abs(market_data['price_change_30d']):.2f}% {direction}."
                
                summary_parts.append(market_summary)
            
            # Topluluk ve geliştirici verileri
            community_data = research_data.get("social_metrics", {})
            dev_data = research_data.get("developer_activity", {})
            
            if community_data or dev_data:
                community_summary = "Community & Development: "
                
                # Twitter takipçileri
                if community_data.get("twitter_followers"):
                    community_summary += f"{community_data['twitter_followers']:,} Twitter followers. "
                
                # Reddit aboneleri
                if community_data.get("reddit_subscribers"):
                    community_summary += f"{community_data['reddit_subscribers']:,} Reddit subscribers. "
                
                # GitHub aktivitesi
                if dev_data.get("github_commits_4_weeks"):
                    community_summary += f"{dev_data['github_commits_4_weeks']} GitHub commits in last 4 weeks."
                
                summary_parts.append(community_summary)
            
            # Son haberler
            news = research_data.get("news", [])
            if news:
                news_summary = "Recent News: "
                news_titles = [n.get("title", "") for n in news[:3]]
                news_summary += "; ".join(news_titles)
                
                summary_parts.append(news_summary)
            
            # Tüm parçaları birleştir
            return "\n\n".join(summary_parts)
        except Exception as e:
            self.logger.error(f"Analiz özeti oluşturulurken hata: {e}")
            return "Analysis unavailable due to insufficient data."
    
    def _check_cache(self, cache_file: str) -> Dict:
        """Önbellekte sonuç var mı kontrol eder"""
        try:
            if not os.path.exists(cache_file):
                return None
                
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            
            # Önbellek süresini kontrol et
            last_updated = datetime.fromisoformat(cache_data.get("last_updated", "2000-01-01"))
            now = datetime.now()
            
            if (now - last_updated).total_seconds() <= self.cache_duration:
                return cache_data
            
            return None
        except Exception as e:
            self.logger.error(f"Önbellek kontrolü hatası: {e}")
            return None
    
    def _save_to_cache(self, cache_file: str, data: Dict) -> None:
        """Araştırma sonucunu önbelleğe kaydet"""
        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Önbelleğe kaydetme hatası: {e}")
    
    async def get_sentiment_analysis(self, symbol: str) -> Dict:
        """Kripto para birimi için duyarlılık analizi yap"""
        try:
            # Sentiment analizi için haberleri topla
            news = await self._get_news(symbol, limit=10)
            
            # Basit bir duyarlılık analizi
            sentiment = {
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "overall_score": 0
            }
            
            # Basit bir kelime tabanlı analiz
            positive_words = ['bullish', 'surge', 'soar', 'gain', 'rally', 'breakthrough', 'rise', 'jump', 'positive']
            negative_words = ['bearish', 'plunge', 'crash', 'drop', 'fall', 'decline', 'negative', 'concern', 'risk']
            
            for article in news:
                title = article.get('title', '').lower()
                snippet = article.get('snippet', '').lower()
                text = title + ' ' + snippet
                
                pos_count = sum(1 for word in positive_words if word in text)
                neg_count = sum(1 for word in negative_words if word in text)
                
                if pos_count > neg_count:
                    sentiment["positive"] += 1
                elif neg_count > pos_count:
                    sentiment["negative"] += 1
                else:
                    sentiment["neutral"] += 1
            
            # Genel puan hesapla (-100 ila 100 arası)
            total_articles = len(news)
            if total_articles > 0:
                sentiment["overall_score"] = int(
                    ((sentiment["positive"] - sentiment["negative"]) / total_articles) * 100
                )
            
            return sentiment
        except Exception as e:
            self.logger.error(f"Duyarlılık analizi hatası: {e}")
            return {
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "overall_score": 0,
                "error": str(e)
            }

# Test kodu
if __name__ == "__main__":
    async def test():
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("WebResearcherTest")
        
        researcher = WebResearcher(logger)
        await researcher.initialize()
        
        try:
            result = await researcher.research_crypto("BTC")
            print(json.dumps(result, indent=2))
        finally:
            await researcher.close()
    
    asyncio.run(test())
