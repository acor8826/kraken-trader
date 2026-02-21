"""
In-memory cache for decision caching (Stage 1).

Provides decision caching without requiring Redis, enabling the cost
optimization feature for small portfolios in Stage 1.
"""

import logging
import json
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with TTL tracking."""
    value: str
    expires_at: float


class InMemoryCache:
    """
    Simple in-memory cache for Stage 1 decision caching.

    Provides the same interface as RedisCache for decision caching,
    but stores data in memory. Suitable for single-process deployments.
    """

    def __init__(self, default_ttl: int = 300):
        """
        Initialize in-memory cache.

        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
        """
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0
        }
        logger.info(f"InMemoryCache initialized with TTL={default_ttl}s")

    async def connect(self):
        """No-op for in-memory cache (maintains API compatibility)."""
        logger.info("InMemoryCache ready (no connection needed)")

    async def disconnect(self):
        """Clear cache on disconnect."""
        self._cache.clear()
        logger.info("InMemoryCache cleared")

    def _get_timestamp(self) -> float:
        """Get current timestamp."""
        return time.time()

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if a cache entry has expired."""
        return self._get_timestamp() > entry.expires_at

    def _cleanup_expired(self):
        """Remove expired entries (called periodically)."""
        now = self._get_timestamp()
        expired_keys = [
            key for key, entry in self._cache.items()
            if now > entry.expires_at
        ]
        for key in expired_keys:
            del self._cache[key]
        if expired_keys:
            logger.debug(f"[CACHE] Cleaned up {len(expired_keys)} expired entries")

    # =========================================================================
    # Core Cache Operations
    # =========================================================================

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache."""
        # Periodic cleanup (every 100 operations)
        if (self._stats["hits"] + self._stats["misses"]) % 100 == 0:
            self._cleanup_expired()

        entry = self._cache.get(key)

        if entry is None:
            self._stats["misses"] += 1
            logger.debug(f"Cache MISS: {key}")
            return None

        if self._is_expired(entry):
            del self._cache[key]
            self._stats["misses"] += 1
            logger.debug(f"Cache EXPIRED: {key}")
            return None

        self._stats["hits"] += 1
        logger.debug(f"Cache HIT: {key}")
        return entry.value

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in cache with optional TTL."""
        try:
            effective_ttl = ttl if ttl is not None else self.default_ttl
            expires_at = self._get_timestamp() + effective_ttl

            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
            self._stats["sets"] += 1
            logger.debug(f"Cache SET: {key} (TTL={effective_ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Cache SET error for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        if key in self._cache:
            del self._cache[key]
            self._stats["deletes"] += 1
            logger.debug(f"Cache DELETE: {key}")
            return True
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
            max_price_deviation: Maximum allowed price change

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
        pattern_prefix = f"decision:{pair}:" if pair else "decision:"
        keys_to_delete = [
            key for key in self._cache.keys()
            if key.startswith(pattern_prefix)
        ]

        for key in keys_to_delete:
            del self._cache[key]

        if keys_to_delete:
            logger.info(f"[CACHE] Invalidated {len(keys_to_delete)} decision cache entries")

        return len(keys_to_delete)

    async def get_decision_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about decision cache usage."""
        # Count decision cache keys
        decision_keys = sum(
            1 for key in self._cache.keys()
            if key.startswith("decision:") and not self._is_expired(self._cache[key])
        )

        return {
            "enabled": True,
            "cached_decisions": decision_keys,
            "cache_type": "in-memory"
        }

    async def get_all_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        decision_stats = await self.get_decision_cache_stats()

        return {
            "type": "in-memory",
            "total_entries": len(self._cache),
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "sets": self._stats["sets"],
            "deletes": self._stats["deletes"],
            "hit_rate": (
                self._stats["hits"] / max(1, self._stats["hits"] + self._stats["misses"])
            ),
            "decision_cache": decision_stats
        }
