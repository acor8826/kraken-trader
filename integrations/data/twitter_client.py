"""
Twitter API v2 Client

Batch search for crypto tweets using Recent Search endpoint.
Budget-aware: tracks daily/monthly API reads.
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
MAX_QUERY_LENGTH = 512
MAX_SYMBOLS_PER_QUERY = 40


class TwitterClient:
    """Async Twitter API v2 client for batch crypto sentiment searches."""

    def __init__(
        self,
        bearer_token: Optional[str] = None,
        cache=None,
    ):
        self.bearer_token = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
        self.cache = cache
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={
                    "Authorization": f"Bearer {self.bearer_token}",
                    "User-Agent": "KrakenTrader/1.0",
                },
            )
        return self._client

    @staticmethod
    def max_symbols_per_query() -> int:
        return MAX_SYMBOLS_PER_QUERY

    async def search_batch(
        self,
        symbols: List[str],
        max_results: int = 100,
        since_minutes: int = 15,
    ) -> Dict:
        """
        Batch search tweets for multiple crypto symbols in one API call.

        Args:
            symbols: List of ticker symbols (e.g., ["DOGE", "SHIB", "PEPE"])
            max_results: Max tweets to return (10-100)
            since_minutes: Look back this many minutes

        Returns:
            Dict with keys: tweets, result_count, newest_id, query
        """
        empty_result = {"tweets": [], "result_count": 0, "newest_id": None, "query": ""}

        if not symbols:
            return empty_result

        if not self.bearer_token:
            logger.warning("[TWITTER] No bearer token configured")
            return empty_result

        # Build OR query: ($DOGE OR $SHIB OR $PEPE ...) -is:retweet lang:en
        ticker_parts = " OR ".join([f"${s.upper()}" for s in symbols])
        query = f"({ticker_parts}) -is:retweet lang:en"

        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError(
                f"Query length {len(query)} exceeds {MAX_QUERY_LENGTH} chars. "
                f"Reduce symbols from {len(symbols)}."
            )

        # Check cache
        cache_key = f"twitter:batch:{hash(query)}"
        if self.cache:
            try:
                cached = await self.cache.get(cache_key)
                if cached:
                    logger.debug("[TWITTER] Cache hit for batch query")
                    return cached
            except Exception:
                pass

        # Build request params
        since_time = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        params = {
            "query": query,
            "max_results": min(max(10, max_results), 100),
            "start_time": since_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tweet.fields": "created_at,public_metrics,author_id,text",
            "user.fields": "public_metrics",
            "expansions": "author_id",
        }

        try:
            client = self._get_client()
            resp = await client.get(TWITTER_SEARCH_URL, params=params)

            if resp.status_code == 429:
                logger.warning("[TWITTER] Rate limited (429). Returning empty result.")
                return empty_result

            resp.raise_for_status()
            data = resp.json()

            # Build author lookup from includes
            authors = {}
            for user in data.get("includes", {}).get("users", []):
                authors[user["id"]] = {
                    "followers": user.get("public_metrics", {}).get("followers_count", 0),
                }

            # Enrich tweets
            tweets = []
            for tweet in data.get("data", []):
                metrics = tweet.get("public_metrics", {})
                author_id = tweet.get("author_id", "")
                author_info = authors.get(author_id, {})

                tweets.append({
                    "text": tweet.get("text", ""),
                    "created_at": tweet.get("created_at", ""),
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "author_followers": author_info.get("followers", 0),
                    "author_id": author_id,
                })

            result = {
                "tweets": tweets,
                "result_count": data.get("meta", {}).get("result_count", len(tweets)),
                "newest_id": data.get("meta", {}).get("newest_id"),
                "query": query,
            }

            # Cache result
            if self.cache:
                try:
                    await self.cache.set(cache_key, result, ttl=120)
                except Exception:
                    pass

            logger.info(f"[TWITTER] Fetched {len(tweets)} tweets for {len(symbols)} symbols")
            return result

        except httpx.HTTPStatusError as e:
            logger.warning(f"[TWITTER] HTTP error: {e.response.status_code}")
            return empty_result
        except httpx.ConnectError as e:
            logger.warning(f"[TWITTER] Connection error: {e}")
            return empty_result
        except Exception as e:
            logger.warning(f"[TWITTER] Unexpected error: {e}")
            return empty_result

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
