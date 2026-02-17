"""
FRED (Federal Reserve Economic Data) API Client

Fetches macroeconomic data from the Federal Reserve Bank of St. Louis:
- Federal Funds Rate
- Treasury Yields
- Dollar Index (DXY)

Free API key available at: https://fred.stlouisfed.org/docs/api/api_key.html
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import httpx

logger = logging.getLogger(__name__)


class FREDClient:
    """Client for FRED (Federal Reserve Economic Data) API"""

    BASE_URL = "https://api.stlouisfed.org/fred"

    # FRED series IDs for key economic indicators
    SERIES = {
        "fed_funds": "FEDFUNDS",           # Federal Funds Effective Rate
        "treasury_2y": "DGS2",             # 2-Year Treasury Rate
        "treasury_10y": "DGS10",           # 10-Year Treasury Rate
        "treasury_30y": "DGS30",           # 30-Year Treasury Rate
        "dxy": "DTWEXBGS",                 # Trade Weighted U.S. Dollar Index (Broad)
        "cpi": "CPIAUCSL",                 # Consumer Price Index
        "unemployment": "UNRATE",          # Unemployment Rate
        "vix": "VIXCLS",                   # CBOE Volatility Index
    }

    def __init__(self, api_key: str = None, cache=None):
        """
        Initialize FRED API client.

        Args:
            api_key: FRED API key (falls back to FRED_API_KEY env var)
            cache: Optional RedisCache instance for caching responses
        """
        self.api_key = api_key or os.getenv("FRED_API_KEY", "")
        self.cache = cache
        self._client = httpx.AsyncClient(timeout=30.0)

        if not self.api_key:
            logger.warning("No FRED API key provided. Macro data will be unavailable.")
        else:
            logger.info("FREDClient initialized")

    async def close(self):
        """Close HTTP client"""
        await self._client.aclose()

    async def _fetch_series(
        self,
        series_id: str,
        limit: int = 10,
        frequency: str = None
    ) -> Optional[List[Dict]]:
        """
        Fetch time series data from FRED.

        Args:
            series_id: FRED series identifier
            limit: Number of observations to fetch
            frequency: Optional frequency aggregation (d, w, m, q, a)

        Returns:
            List of observations [{date, value}, ...]
        """
        if not self.api_key:
            logger.debug("FRED API key not configured")
            return None

        try:
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit
            }

            if frequency:
                params["frequency"] = frequency

            url = f"{self.BASE_URL}/series/observations"
            response = await self._client.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            if "observations" in data:
                return [
                    {
                        "date": obs["date"],
                        "value": float(obs["value"]) if obs["value"] != "." else None
                    }
                    for obs in data["observations"]
                    if obs["value"] != "."  # Skip missing values
                ]

            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                logger.error(f"FRED API bad request for series {series_id}")
            elif e.response.status_code == 429:
                logger.warning("FRED API rate limit exceeded")
            else:
                logger.error(f"FRED API error: {e.response.status_code}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching from FRED: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching from FRED: {e}")
            return None

    async def get_fed_funds_rate(self) -> Optional[Dict]:
        """
        Get current Federal Funds Rate.

        The Fed Funds Rate is a key indicator of monetary policy:
        - Rising rates = tighter policy = risk-off
        - Falling rates = looser policy = risk-on

        Returns:
            {
                "rate": 5.33,
                "change_1m": -0.25,
                "direction": "easing",
                "timestamp": "2026-01-12"
            }
        """
        cache_key = "fred:fed_funds"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        data = await self._fetch_series(self.SERIES["fed_funds"], limit=3)
        if not data or len(data) == 0:
            return None

        try:
            current = data[0]["value"]
            previous = data[-1]["value"] if len(data) > 1 else current

            change = current - previous if previous else 0

            if change < -0.10:
                direction = "easing"
            elif change > 0.10:
                direction = "tightening"
            else:
                direction = "stable"

            result = {
                "rate": current,
                "change_1m": round(change, 2),
                "direction": direction,
                "timestamp": data[0]["date"]
            }

            # Cache for 1 hour
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=3600)

            logger.info(f"Fed Funds Rate: {current}% ({direction})")
            return result

        except Exception as e:
            logger.error(f"Error parsing Fed Funds data: {e}")
            return None

    async def get_treasury_yield(self, maturity: str = "10y") -> Optional[Dict]:
        """
        Get Treasury yield for specified maturity.

        Treasury yields indicate risk-free rate and economic outlook:
        - Rising yields = growth expectations / inflation concerns
        - Falling yields = economic slowdown / flight to safety

        Args:
            maturity: "2y", "10y", or "30y"

        Returns:
            {
                "yield": 4.25,
                "change_1m": 0.15,
                "maturity": "10y",
                "timestamp": "2026-01-12"
            }
        """
        series_map = {
            "2y": self.SERIES["treasury_2y"],
            "10y": self.SERIES["treasury_10y"],
            "30y": self.SERIES["treasury_30y"]
        }

        series_id = series_map.get(maturity, self.SERIES["treasury_10y"])

        cache_key = f"fred:treasury:{maturity}"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        data = await self._fetch_series(series_id, limit=30)
        if not data or len(data) == 0:
            return None

        try:
            current = data[0]["value"]

            # Find value from ~1 month ago
            previous = data[-1]["value"] if len(data) > 20 else data[0]["value"]
            change = current - previous if previous else 0

            result = {
                "yield": current,
                "change_1m": round(change, 2),
                "maturity": maturity,
                "timestamp": data[0]["date"]
            }

            # Cache for 1 hour
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=3600)

            logger.info(f"Treasury {maturity} yield: {current}%")
            return result

        except Exception as e:
            logger.error(f"Error parsing Treasury yield data: {e}")
            return None

    async def get_yield_curve_spread(self) -> Optional[Dict]:
        """
        Get yield curve spread (10Y - 2Y).

        Yield curve spread indicates economic outlook:
        - Positive spread = normal curve = economic expansion
        - Negative spread = inverted curve = recession signal

        Returns:
            {
                "spread": 0.45,
                "is_inverted": False,
                "yield_2y": 4.50,
                "yield_10y": 4.95,
                "signal": "normal",
                "timestamp": "2026-01-12"
            }
        """
        yield_2y = await self.get_treasury_yield("2y")
        yield_10y = await self.get_treasury_yield("10y")

        if not yield_2y or not yield_10y:
            return None

        try:
            spread = yield_10y["yield"] - yield_2y["yield"]
            is_inverted = spread < 0

            if spread < -0.5:
                signal = "deeply_inverted"
            elif spread < 0:
                signal = "inverted"
            elif spread < 0.5:
                signal = "flat"
            else:
                signal = "normal"

            return {
                "spread": round(spread, 2),
                "is_inverted": is_inverted,
                "yield_2y": yield_2y["yield"],
                "yield_10y": yield_10y["yield"],
                "signal": signal,
                "timestamp": yield_10y["timestamp"]
            }

        except Exception as e:
            logger.error(f"Error calculating yield curve spread: {e}")
            return None

    async def get_dollar_index(self) -> Optional[Dict]:
        """
        Get US Dollar Index (DXY).

        DXY indicates dollar strength:
        - Rising DXY = stronger dollar = typically bearish for crypto
        - Falling DXY = weaker dollar = typically bullish for crypto

        Returns:
            {
                "value": 102.5,
                "change_1m": -1.2,
                "change_pct": -0.012,
                "direction": "weakening",
                "timestamp": "2026-01-12"
            }
        """
        cache_key = "fred:dxy"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        data = await self._fetch_series(self.SERIES["dxy"], limit=30)
        if not data or len(data) == 0:
            return None

        try:
            current = data[0]["value"]

            # Find value from ~1 month ago
            previous = data[-1]["value"] if len(data) > 20 else data[0]["value"]
            change = current - previous if previous else 0
            change_pct = change / previous if previous and previous > 0 else 0

            if change_pct < -0.02:
                direction = "weakening"
            elif change_pct > 0.02:
                direction = "strengthening"
            else:
                direction = "stable"

            result = {
                "value": round(current, 2),
                "change_1m": round(change, 2),
                "change_pct": round(change_pct, 4),
                "direction": direction,
                "timestamp": data[0]["date"]
            }

            # Cache for 1 hour
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=3600)

            logger.info(f"DXY: {current} ({direction})")
            return result

        except Exception as e:
            logger.error(f"Error parsing DXY data: {e}")
            return None

    async def get_vix(self) -> Optional[Dict]:
        """
        Get VIX (CBOE Volatility Index).

        VIX indicates market fear/volatility:
        - High VIX (>25) = high fear = risk-off environment
        - Low VIX (<15) = complacency = potential risk-on

        Returns:
            {
                "value": 18.5,
                "change_1w": 2.3,
                "level": "normal",
                "timestamp": "2026-01-12"
            }
        """
        cache_key = "fred:vix"
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                import json
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        data = await self._fetch_series(self.SERIES["vix"], limit=10)
        if not data or len(data) == 0:
            return None

        try:
            current = data[0]["value"]

            # Find value from ~1 week ago
            previous = data[-1]["value"] if len(data) > 5 else data[0]["value"]
            change = current - previous if previous else 0

            if current > 30:
                level = "extreme_fear"
            elif current > 25:
                level = "high_fear"
            elif current > 20:
                level = "elevated"
            elif current > 15:
                level = "normal"
            else:
                level = "complacent"

            result = {
                "value": round(current, 2),
                "change_1w": round(change, 2),
                "level": level,
                "timestamp": data[0]["date"]
            }

            # Cache for 1 hour
            if self.cache:
                import json
                await self.cache.set(cache_key, json.dumps(result), ttl=3600)

            logger.info(f"VIX: {current} ({level})")
            return result

        except Exception as e:
            logger.error(f"Error parsing VIX data: {e}")
            return None

    async def is_available(self) -> bool:
        """Check if FRED API is configured and accessible"""
        if not self.api_key:
            return False

        try:
            # Simple test request
            params = {
                "series_id": "FEDFUNDS",
                "api_key": self.api_key,
                "file_type": "json",
                "limit": 1
            }
            response = await self._client.get(
                f"{self.BASE_URL}/series/observations",
                params=params
            )
            return response.status_code == 200
        except Exception:
            return False
