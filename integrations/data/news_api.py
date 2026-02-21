"""
Crypto News API client.

Fetches cryptocurrency news from CryptoPanic API.
Free tier available with rate limits.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import httpx

logger = logging.getLogger(__name__)


class CryptoNewsAPI:
    """Client for CryptoPanic News API"""

    BASE_URL = "https://cryptopanic.com/api/v1"

    def __init__(self, api_token: Optional[str] = None, cache=None):
        """
        Initialize Crypto News API client.

        Args:
            api_token: CryptoPanic API token (optional, free tier available without)
            cache: Optional RedisCache instance
        """
        self.api_token = api_token
        self.cache = cache
        self._client = httpx.AsyncClient(timeout=10.0)
        logger.info(f"CryptoNewsAPI initialized (token={'yes' if api_token else 'no'})")

    async def close(self):
        """Close HTTP client"""
        await self._client.aclose()

    async def get_headlines(
        self,
        asset: str = "BTC",
        limit: int = 10,
        hours: int = 24
    ) -> Optional[List[Dict]]:
        """
        Get recent news headlines for an asset.

        Args:
            asset: Cryptocurrency symbol (BTC, ETH, etc.)
            limit: Number of headlines to return
            hours: Look back this many hours

        Returns:
            List of headlines with title, source, published_at
        """
        # Check cache first
        cache_key = f"news:{asset}"
        if self.cache:
            cached = await self.cache.get_news(asset)
            if cached:
                logger.debug(f"News for {asset}: Using cached data")
                return cached

        try:
            params = {
                "currencies": asset,
                "filter": "hot",
                "kind": "news"
            }

            if self.api_token:
                params["auth_token"] = self.api_token

            response = await self._client.get(
                f"{self.BASE_URL}/posts/",
                params=params
            )
            response.raise_for_status()

            data = response.json()

            if "results" in data:
                # Filter by time window
                cutoff = datetime.now() - timedelta(hours=hours)
                headlines = []

                for item in data["results"][:limit]:
                    try:
                        published = datetime.fromisoformat(
                            item["published_at"].replace("Z", "+00:00")
                        )

                        if published > cutoff:
                            headlines.append({
                                "title": item["title"],
                                "source": item.get("source", {}).get("title", "Unknown"),
                                "published_at": item["published_at"],
                                "url": item.get("url", "")
                            })
                    except Exception as e:
                        logger.debug(f"Skipping malformed news item: {e}")
                        continue

                # Cache for 15 minutes
                if self.cache and headlines:
                    await self.cache.cache_news(asset, headlines, ttl=900)

                logger.info(f"Fetched {len(headlines)} news headlines for {asset}")
                return headlines

            logger.warning(f"No news data returned for {asset}")
            return []

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching news for {asset}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching news for {asset}: {e}")
            return []

    async def get_trending_news(self, limit: int = 20) -> Optional[List[Dict]]:
        """
        Get trending crypto news (all currencies).

        Args:
            limit: Number of headlines to return

        Returns:
            List of trending headlines
        """
        try:
            params = {
                "filter": "hot",
                "kind": "news"
            }

            if self.api_token:
                params["auth_token"] = self.api_token

            response = await self._client.get(
                f"{self.BASE_URL}/posts/",
                params=params
            )
            response.raise_for_status()

            data = response.json()

            if "results" in data:
                headlines = []

                for item in data["results"][:limit]:
                    headlines.append({
                        "title": item["title"],
                        "source": item.get("source", {}).get("title", "Unknown"),
                        "published_at": item["published_at"],
                        "currencies": [c["code"] for c in item.get("currencies", [])]
                    })

                logger.info(f"Fetched {len(headlines)} trending headlines")
                return headlines

            return []

        except Exception as e:
            logger.error(f"Error fetching trending news: {e}")
            return []
