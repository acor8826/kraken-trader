"""
Glassnode API client for on-chain analytics.

Fetches blockchain metrics including active addresses, exchange flows,
and whale transactions for crypto assets.
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import httpx

logger = logging.getLogger(__name__)


class GlassnodeClient:
    """Client for Glassnode on-chain analytics API"""

    BASE_URL = "https://api.glassnode.com/v1/metrics"

    # Asset mapping from trading pairs to Glassnode asset codes
    ASSET_MAP = {
        "BTC": "BTC",
        "ETH": "ETH",
        "SOL": "SOL",
        "AVAX": "AVAX",
        "DOT": "DOT",
        "XRP": "XRP",
        "ADA": "ADA",
        "LINK": "LINK",
    }

    def __init__(self, api_key: str = None, cache=None):
        """
        Initialize Glassnode API client.

        Args:
            api_key: Glassnode API key (falls back to GLASSNODE_API_KEY env var)
            cache: Optional RedisCache instance for caching responses
        """
        self.api_key = api_key or os.getenv("GLASSNODE_API_KEY", "")
        self.cache = cache
        self._client = httpx.AsyncClient(timeout=30.0)

        if not self.api_key:
            logger.warning("No Glassnode API key provided. On-chain data will be unavailable.")
        else:
            logger.info("GlassnodeClient initialized")

    async def close(self):
        """Close HTTP client"""
        await self._client.aclose()

    def _get_asset_code(self, asset: str) -> Optional[str]:
        """Convert asset symbol to Glassnode asset code"""
        # Handle pairs like BTC/AUD -> BTC
        base = asset.split("/")[0] if "/" in asset else asset
        return self.ASSET_MAP.get(base.upper())

    async def _fetch(self, endpoint: str, params: Dict) -> Optional[Dict]:
        """Make authenticated API request"""
        if not self.api_key:
            logger.debug("Glassnode API key not configured")
            return None

        try:
            params["api_key"] = self.api_key
            url = f"{self.BASE_URL}/{endpoint}"

            response = await self._client.get(url, params=params)
            response.raise_for_status()

            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error("Glassnode API authentication failed. Check API key.")
            elif e.response.status_code == 429:
                logger.warning("Glassnode API rate limit exceeded")
            else:
                logger.error(f"Glassnode API error: {e.response.status_code}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching from Glassnode: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching from Glassnode: {e}")
            return None

    async def get_active_addresses(self, asset: str) -> Optional[Dict]:
        """
        Get active addresses count for an asset.

        Active addresses indicates network usage and adoption.
        Higher counts suggest more network activity.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", or "BTC/AUD")

        Returns:
            {
                "value": 850000,  # Number of active addresses
                "change_24h": 0.05,  # 24h percentage change
                "timestamp": "2026-01-12T00:00:00Z"
            }
        """
        asset_code = self._get_asset_code(asset)
        if not asset_code:
            logger.warning(f"Asset {asset} not supported by Glassnode")
            return None

        # Check cache first
        cache_key = f"glassnode:active_addresses:{asset_code}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    logger.debug(f"Glassnode active addresses: Using cached data for {asset_code}")
                    return json.loads(cached)
                except Exception:
                    pass

        # Fetch from API
        params = {
            "a": asset_code,
            "i": "24h",  # Daily resolution
            "s": int((datetime.utcnow() - timedelta(days=2)).timestamp()),
        }

        data = await self._fetch("addresses/active_count", params)
        if not data or not isinstance(data, list) or len(data) < 2:
            return None

        try:
            current = data[-1]
            previous = data[-2] if len(data) >= 2 else data[-1]

            current_value = current.get("v", 0)
            previous_value = previous.get("v", 1)  # Avoid division by zero

            change_24h = (current_value - previous_value) / previous_value if previous_value > 0 else 0

            result = {
                "value": int(current_value),
                "change_24h": round(change_24h, 4),
                "timestamp": datetime.utcfromtimestamp(current.get("t", 0)).isoformat() + "Z"
            }

            # Cache for 15 minutes
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=900)

            logger.info(f"Glassnode active addresses for {asset_code}: {result['value']:,} ({result['change_24h']:+.2%})")
            return result

        except Exception as e:
            logger.error(f"Error parsing active addresses data: {e}")
            return None

    async def get_exchange_netflow(self, asset: str) -> Optional[Dict]:
        """
        Get net exchange flow for an asset.

        Net flow = deposits - withdrawals
        Positive = more coins entering exchanges (bearish, selling pressure)
        Negative = more coins leaving exchanges (bullish, accumulation)

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")

        Returns:
            {
                "netflow": -1500.5,  # Negative = outflows (bullish)
                "netflow_usd": -45000000,  # USD value of netflow
                "direction": "outflow",  # "inflow" or "outflow"
                "signal": 0.6,  # -1 to +1 (positive = bullish)
                "timestamp": "2026-01-12T00:00:00Z"
            }
        """
        asset_code = self._get_asset_code(asset)
        if not asset_code:
            logger.warning(f"Asset {asset} not supported by Glassnode")
            return None

        # Check cache first
        cache_key = f"glassnode:exchange_netflow:{asset_code}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    logger.debug(f"Glassnode exchange netflow: Using cached data for {asset_code}")
                    return json.loads(cached)
                except Exception:
                    pass

        # Fetch exchange net position change
        params = {
            "a": asset_code,
            "i": "24h",
            "s": int((datetime.utcnow() - timedelta(days=7)).timestamp()),
        }

        data = await self._fetch("distribution/exchange_net_position_change", params)
        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        try:
            # Get latest data point
            latest = data[-1]
            netflow = latest.get("v", 0)

            # Calculate average to normalize signal
            avg_netflow = sum(d.get("v", 0) for d in data) / len(data) if data else 0
            std_netflow = (sum((d.get("v", 0) - avg_netflow) ** 2 for d in data) / len(data)) ** 0.5 if len(data) > 1 else 1

            # Normalize to -1 to +1 signal
            # Negative netflow (outflows) = bullish = positive signal
            if std_netflow > 0:
                z_score = (netflow - avg_netflow) / std_netflow
                signal = max(-1.0, min(1.0, -z_score * 0.5))  # Invert because outflows are bullish
            else:
                signal = 0.0

            result = {
                "netflow": round(netflow, 4),
                "netflow_usd": None,  # Would need price data
                "direction": "inflow" if netflow > 0 else "outflow",
                "signal": round(signal, 4),
                "timestamp": datetime.utcfromtimestamp(latest.get("t", 0)).isoformat() + "Z"
            }

            # Cache for 15 minutes
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=900)

            logger.info(f"Glassnode exchange netflow for {asset_code}: {result['netflow']:.2f} ({result['direction']}, signal={result['signal']:.2f})")
            return result

        except Exception as e:
            logger.error(f"Error parsing exchange netflow data: {e}")
            return None

    async def get_whale_transactions(
        self,
        asset: str,
        min_value: int = 100000
    ) -> Optional[Dict]:
        """
        Get whale transaction activity.

        Tracks large transactions (>$100k by default) as indicator
        of institutional/whale activity.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")
            min_value: Minimum transaction value in USD (default: $100,000)

        Returns:
            {
                "count": 150,  # Number of whale transactions in 24h
                "total_volume": 5000000000,  # Total USD volume
                "change_24h": 0.15,  # 24h percentage change in count
                "signal": 0.3,  # -1 to +1 based on activity level
                "timestamp": "2026-01-12T00:00:00Z"
            }
        """
        asset_code = self._get_asset_code(asset)
        if not asset_code:
            logger.warning(f"Asset {asset} not supported by Glassnode")
            return None

        # Check cache first
        cache_key = f"glassnode:whale_tx:{asset_code}:{min_value}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    logger.debug(f"Glassnode whale transactions: Using cached data for {asset_code}")
                    return json.loads(cached)
                except Exception:
                    pass

        # Use transaction count for large transactions
        # Glassnode has specific endpoints for >$1M, >$10M etc.
        params = {
            "a": asset_code,
            "i": "24h",
            "s": int((datetime.utcnow() - timedelta(days=7)).timestamp()),
        }

        # Try to get large transaction count
        # Using transfers volume for whales
        data = await self._fetch("transactions/transfers_volume_sum", params)
        if not data or not isinstance(data, list) or len(data) < 2:
            # Fallback: return neutral if data unavailable
            return None

        try:
            current = data[-1]
            previous = data[-2] if len(data) >= 2 else data[-1]

            current_volume = current.get("v", 0)
            previous_volume = previous.get("v", 1)

            change_24h = (current_volume - previous_volume) / previous_volume if previous_volume > 0 else 0

            # Calculate signal based on volume trend
            # Increasing volume with positive market = bullish
            avg_volume = sum(d.get("v", 0) for d in data) / len(data) if data else current_volume
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

            # High volume slightly bullish (more activity), but capped
            signal = min(0.5, max(-0.5, (volume_ratio - 1.0) * 0.5))

            result = {
                "count": None,  # Would need specific whale transaction count endpoint
                "total_volume": round(current_volume, 2),
                "change_24h": round(change_24h, 4),
                "signal": round(signal, 4),
                "timestamp": datetime.utcfromtimestamp(current.get("t", 0)).isoformat() + "Z"
            }

            # Cache for 15 minutes
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=900)

            logger.info(f"Glassnode whale activity for {asset_code}: volume={result['total_volume']:.0f} ({result['change_24h']:+.2%})")
            return result

        except Exception as e:
            logger.error(f"Error parsing whale transaction data: {e}")
            return None

    async def get_supply_on_exchanges(self, asset: str) -> Optional[Dict]:
        """
        Get supply held on exchanges as percentage of total supply.

        Lower exchange supply = bullish (coins moving to cold storage)
        Higher exchange supply = bearish (coins available for selling)

        Args:
            asset: Asset symbol

        Returns:
            {
                "balance": 2500000,  # Coins on exchanges
                "percentage": 0.12,  # 12% of supply on exchanges
                "change_7d": -0.005,  # 7-day change in percentage
                "signal": 0.4,  # -1 to +1
                "timestamp": "..."
            }
        """
        asset_code = self._get_asset_code(asset)
        if not asset_code:
            return None

        cache_key = f"glassnode:exchange_balance:{asset_code}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        params = {
            "a": asset_code,
            "i": "24h",
            "s": int((datetime.utcnow() - timedelta(days=8)).timestamp()),
        }

        data = await self._fetch("distribution/balance_exchanges", params)
        if not data or not isinstance(data, list) or len(data) < 2:
            return None

        try:
            current = data[-1]
            week_ago = data[0] if len(data) >= 7 else data[0]

            current_balance = current.get("v", 0)
            week_ago_balance = week_ago.get("v", current_balance)

            # Calculate weekly change
            change_7d = (current_balance - week_ago_balance) / week_ago_balance if week_ago_balance > 0 else 0

            # Decreasing exchange balance = bullish
            signal = max(-1.0, min(1.0, -change_7d * 10))  # Scale appropriately

            result = {
                "balance": round(current_balance, 4),
                "percentage": None,  # Would need total supply
                "change_7d": round(change_7d, 4),
                "signal": round(signal, 4),
                "timestamp": datetime.utcfromtimestamp(current.get("t", 0)).isoformat() + "Z"
            }

            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=900)

            logger.info(f"Glassnode exchange balance for {asset_code}: {result['balance']:.0f} ({result['change_7d']:+.2%})")
            return result

        except Exception as e:
            logger.error(f"Error parsing exchange balance data: {e}")
            return None

    async def is_available(self) -> bool:
        """Check if Glassnode API is configured and accessible"""
        if not self.api_key:
            return False

        try:
            # Simple ping to verify API key
            params = {
                "a": "BTC",
                "i": "24h",
                "api_key": self.api_key
            }
            response = await self._client.get(
                f"{self.BASE_URL}/market/price_usd_close",
                params=params
            )
            return response.status_code == 200
        except Exception:
            return False
