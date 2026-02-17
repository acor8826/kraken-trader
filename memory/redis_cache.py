"""
Redis cache for market data and session state.

Provides fast in-memory caching to reduce API calls to exchanges
and improve performance of frequent data access.
"""

import logging
import json
from typing import Dict, Optional, Any
from datetime import timedelta
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis-backed cache for market data and session state"""

    def __init__(self, redis_url: str, default_ttl: int = 300):
        """
        Initialize Redis cache.

        Args:
            redis_url: Redis connection string (e.g., redis://localhost:6379)
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self._client: Optional[redis.Redis] = None
        logger.info(f"RedisCache initialized with TTL={default_ttl}s")

    async def connect(self):
        """Initialize Redis connection"""
        try:
            self._client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )

            # Verify connection
            await self._client.ping()
            logger.info("Connected to Redis successfully")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection"""
        if self._client:
            await self._client.close()
            logger.info("Redis connection closed")

    # =========================================================================
    # Core Cache Operations
    # =========================================================================

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        if not self._client:
            logger.warning("Redis not connected, cache miss")
            return None

        try:
            value = await self._client.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
            else:
                logger.debug(f"Cache MISS: {key}")
            return value

        except Exception as e:
            logger.error(f"Redis GET error for {key}: {e}")
            return None

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache with optional TTL"""
        if not self._client:
            logger.warning("Redis not connected, skipping cache set")
            return False

        try:
            ttl_seconds = ttl if ttl is not None else self.default_ttl

            if ttl_seconds > 0:
                await self._client.setex(key, ttl_seconds, value)
            else:
                await self._client.set(key, value)

            logger.debug(f"Cache SET: {key} (TTL={ttl_seconds}s)")
            return True

        except Exception as e:
            logger.error(f"Redis SET error for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self._client:
            return False

        try:
            await self._client.delete(key)
            logger.debug(f"Cache DELETE: {key}")
            return True

        except Exception as e:
            logger.error(f"Redis DELETE error for {key}: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self._client:
            return False

        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis EXISTS error for {key}: {e}")
            return False

    # =========================================================================
    # Market Data Cache Methods
    # =========================================================================

    async def cache_ticker(
        self,
        pair: str,
        ticker_data: Dict,
        ttl: int = 60
    ) -> bool:
        """Cache ticker data for a trading pair"""
        key = f"ticker:{pair}"
        value = json.dumps(ticker_data)
        return await self.set(key, value, ttl)

    async def get_ticker(self, pair: str) -> Optional[Dict]:
        """Get cached ticker data"""
        key = f"ticker:{pair}"
        value = await self.get(key)

        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.error(f"Failed to decode ticker data for {pair}")
                return None

        return None

    async def cache_ohlcv(
        self,
        pair: str,
        interval: int,
        ohlcv_data: list,
        ttl: int = 300
    ) -> bool:
        """Cache OHLCV candle data"""
        key = f"ohlcv:{pair}:{interval}"
        value = json.dumps(ohlcv_data)
        return await self.set(key, value, ttl)

    async def get_ohlcv(
        self,
        pair: str,
        interval: int
    ) -> Optional[list]:
        """Get cached OHLCV data"""
        key = f"ohlcv:{pair}:{interval}"
        value = await self.get(key)

        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.error(f"Failed to decode OHLCV data for {pair}")
                return None

        return None

    async def cache_balance(
        self,
        balance_data: Dict,
        ttl: int = 60
    ) -> bool:
        """Cache account balance"""
        key = "balance"
        value = json.dumps(balance_data)
        return await self.set(key, value, ttl)

    async def get_balance(self) -> Optional[Dict]:
        """Get cached balance"""
        value = await self.get("balance")

        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.error("Failed to decode balance data")
                return None

        return None

    # =========================================================================
    # Sentiment Data Cache Methods
    # =========================================================================

    async def cache_fear_greed(
        self,
        data: Dict,
        ttl: int = 900  # 15 minutes
    ) -> bool:
        """Cache Fear & Greed Index"""
        key = "sentiment:fear_greed"
        value = json.dumps(data)
        return await self.set(key, value, ttl)

    async def get_fear_greed(self) -> Optional[Dict]:
        """Get cached Fear & Greed Index"""
        value = await self.get("sentiment:fear_greed")

        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.error("Failed to decode fear/greed data")
                return None

        return None

    async def cache_news(
        self,
        asset: str,
        headlines: list,
        ttl: int = 900  # 15 minutes
    ) -> bool:
        """Cache news headlines for an asset"""
        key = f"news:{asset}"
        value = json.dumps(headlines)
        return await self.set(key, value, ttl)

    async def get_news(self, asset: str) -> Optional[list]:
        """Get cached news headlines"""
        key = f"news:{asset}"
        value = await self.get(key)

        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.error(f"Failed to decode news data for {asset}")
                return None

        return None

    # =========================================================================
    # Session State Methods
    # =========================================================================

    async def increment(
        self,
        key: str,
        amount: int = 1
    ) -> Optional[int]:
        """Increment a counter"""
        if not self._client:
            return None

        try:
            return await self._client.incrby(key, amount)
        except Exception as e:
            logger.error(f"Redis INCR error for {key}: {e}")
            return None

    async def get_int(self, key: str) -> Optional[int]:
        """Get integer value"""
        value = await self.get(key)
        if value:
            try:
                return int(value)
            except ValueError:
                logger.error(f"Failed to parse int from {key}")
                return None
        return None

    async def set_with_expiry(
        self,
        key: str,
        value: str,
        expiry_time: timedelta
    ) -> bool:
        """Set value with expiry time"""
        if not self._client:
            return False

        try:
            await self._client.setex(
                key,
                int(expiry_time.total_seconds()),
                value
            )
            return True
        except Exception as e:
            logger.error(f"Redis SETEX error for {key}: {e}")
            return False

    async def flush_all(self) -> bool:
        """Clear all cached data (use with caution!)"""
        if not self._client:
            return False

        try:
            await self._client.flushdb()
            logger.warning("Redis cache flushed!")
            return True
        except Exception as e:
            logger.error(f"Redis FLUSHDB error: {e}")
            return False

    # =========================================================================
    # Decision Cache Methods (Cost Optimization)
    # =========================================================================

    async def cache_decision(
        self,
        pair: str,
        intel_hash: str,
        decision: Dict,
        price_at_decision: float,
        ttl: int = 1800  # 30 minutes default
    ) -> bool:
        """
        Cache a trading decision for cost optimization.

        The decision is cached with the intel hash and price at time of decision.
        This allows reuse if market conditions haven't changed significantly.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            intel_hash: Hash of the market intel used for the decision
            decision: The trading decision (action, confidence, etc.)
            price_at_decision: Price when decision was made
            ttl: Time-to-live in seconds

        Returns:
            True if cached successfully
        """
        key = f"decision:{pair}:{intel_hash}"
        value = json.dumps({
            "decision": decision,
            "price": price_at_decision,
            "timestamp": self._get_timestamp()
        })
        success = await self.set(key, value, ttl)
        if success:
            logger.info(f"[CACHE] Cached decision for {pair} (hash={intel_hash[:8]})")
        return success

    async def get_cached_decision(
        self,
        pair: str,
        intel_hash: str,
        current_price: float,
        max_price_deviation: float = 0.02  # 2% default
    ) -> Optional[Dict]:
        """
        Get a cached trading decision if still valid.

        The cached decision is invalidated if:
        - The cache entry doesn't exist
        - The price has moved more than max_price_deviation

        Args:
            pair: Trading pair
            intel_hash: Hash of current market intel
            current_price: Current market price
            max_price_deviation: Maximum allowed price change (decimal, e.g., 0.02 for 2%)

        Returns:
            Cached decision dict if valid, None otherwise
        """
        key = f"decision:{pair}:{intel_hash}"
        value = await self.get(key)

        if not value:
            return None

        try:
            data = json.loads(value)
            cached_price = data.get("price", 0)

            if cached_price <= 0:
                logger.warning(f"[CACHE] Invalid cached price for {pair}")
                await self.delete(key)
                return None

            # Check price deviation
            price_change = abs(current_price - cached_price) / cached_price

            if price_change > max_price_deviation:
                logger.info(
                    f"[CACHE] Decision invalidated for {pair}: "
                    f"price moved {price_change:.2%} (threshold: {max_price_deviation:.2%})"
                )
                await self.delete(key)
                return None

            logger.info(
                f"[CACHE] Using cached decision for {pair} "
                f"(price change: {price_change:.2%})"
            )
            return data.get("decision")

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[CACHE] Failed to parse cached decision for {pair}: {e}")
            await self.delete(key)
            return None

    async def invalidate_decisions(self, pair: Optional[str] = None) -> int:
        """
        Invalidate cached decisions.

        Args:
            pair: Specific pair to invalidate, or None for all pairs

        Returns:
            Number of keys deleted
        """
        if not self._client:
            return 0

        try:
            pattern = f"decision:{pair}:*" if pair else "decision:*"
            keys = []

            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self._client.delete(*keys)
                logger.info(f"[CACHE] Invalidated {deleted} decision cache entries")
                return deleted

            return 0

        except Exception as e:
            logger.error(f"[CACHE] Failed to invalidate decisions: {e}")
            return 0

    async def get_decision_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about decision cache usage."""
        if not self._client:
            return {"enabled": False}

        try:
            # Count decision cache keys
            decision_keys = 0
            async for _ in self._client.scan_iter(match="decision:*"):
                decision_keys += 1

            return {
                "enabled": True,
                "cached_decisions": decision_keys
            }

        except Exception as e:
            logger.error(f"[CACHE] Failed to get decision cache stats: {e}")
            return {"enabled": False, "error": str(e)}

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp."""
        from datetime import datetime
        return datetime.utcnow().isoformat()

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self._client:
            return {"connected": False}

        try:
            info = await self._client.info()
            decision_stats = await self.get_decision_cache_stats()

            return {
                "connected": True,
                "used_memory": info.get("used_memory_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "decision_cache": decision_stats
            }
        except Exception as e:
            logger.error(f"Failed to get Redis stats: {e}")
            return {"connected": False, "error": str(e)}
