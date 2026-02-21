"""
Fear & Greed Index API client.

Fetches the crypto Fear & Greed Index from alternative.me API.
This is a free API that provides market sentiment on a 0-100 scale.
"""

import logging
from typing import Dict, Optional
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)


class FearGreedAPI:
    """Client for Fear & Greed Index API"""

    BASE_URL = "https://api.alternative.me/fng/"

    def __init__(self, cache=None):
        """
        Initialize Fear & Greed API client.

        Args:
            cache: Optional RedisCache instance for caching responses
        """
        self.cache = cache
        self._client = httpx.AsyncClient(timeout=10.0)
        logger.info("FearGreedAPI initialized")

    async def close(self):
        """Close HTTP client"""
        await self._client.aclose()

    async def get_current(self) -> Optional[Dict]:
        """
        Get current Fear & Greed Index.

        Returns:
            {
                "value": "25",  # 0-100
                "value_classification": "Extreme Fear",
                "timestamp": "1234567890"
            }
        """
        # Check cache first
        if self.cache:
            cached = await self.cache.get_fear_greed()
            if cached:
                logger.debug("Fear & Greed: Using cached data")
                return cached

        try:
            response = await self._client.get(f"{self.BASE_URL}?limit=1")
            response.raise_for_status()

            data = response.json()

            if "data" in data and len(data["data"]) > 0:
                result = {
                    "value": int(data["data"][0]["value"]),
                    "value_classification": data["data"][0]["value_classification"],
                    "timestamp": data["data"][0]["timestamp"]
                }

                # Cache for 15 minutes
                if self.cache:
                    await self.cache.cache_fear_greed(result, ttl=900)

                logger.info(f"Fear & Greed Index: {result['value']} ({result['value_classification']})")
                return result

            logger.warning("No Fear & Greed data returned from API")
            return None

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching Fear & Greed Index: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching Fear & Greed Index: {e}")
            return None

    async def get_historical(self, days: int = 7) -> Optional[list]:
        """
        Get historical Fear & Greed Index data.

        Args:
            days: Number of days to fetch (max 30)

        Returns:
            List of historical data points
        """
        try:
            response = await self._client.get(f"{self.BASE_URL}?limit={days}")
            response.raise_for_status()

            data = response.json()

            if "data" in data:
                return [
                    {
                        "value": int(item["value"]),
                        "classification": item["value_classification"],
                        "timestamp": item["timestamp"]
                    }
                    for item in data["data"]
                ]

            return None

        except Exception as e:
            logger.error(f"Error fetching historical Fear & Greed data: {e}")
            return None
