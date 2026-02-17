"""
Pair Manager Module

Manages dynamic pair selection and rotation for trading opportunities.
Discovers all available pairs, ranks by opportunity, and rotates through them.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from statistics import stdev, mean

from core.interfaces import IExchange

logger = logging.getLogger(__name__)


@dataclass
class PairMetrics:
    """Metrics for pair ranking and opportunity scoring."""
    pair: str
    volume_24h: float = 0.0
    volatility: float = 0.0  # Price range / price
    spread_pct: float = 0.0
    momentum_score: float = 0.0  # Recent price movement
    opportunity_score: float = 0.0  # Composite score (0-100)
    last_analyzed: Optional[datetime] = None
    price: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "pair": self.pair,
            "volume_24h": round(self.volume_24h, 2),
            "volatility": round(self.volatility, 4),
            "spread_pct": round(self.spread_pct, 4),
            "momentum_score": round(self.momentum_score, 4),
            "opportunity_score": round(self.opportunity_score, 2),
            "last_analyzed": self.last_analyzed.isoformat() if self.last_analyzed else None,
            "price": round(self.price, 8)
        }


@dataclass
class PairConfig:
    """Configuration for pair selection."""
    quote_currency: str = "AUD"
    min_volume_aud: float = 500  # Minimum 24h volume
    max_spread_pct: float = 0.03  # Maximum 3% spread
    always_analyze: List[str] = field(default_factory=lambda: ["BTC/AUD", "ETH/AUD"])
    max_active_pairs: int = 10  # Max pairs to analyze per cycle
    rotation_size: int = 3  # How many pairs to rotate each cycle
    opportunity_threshold: float = 30.0  # Min score to be considered
    cache_ttl_minutes: int = 15  # How long to cache pair data


class PairManager:
    """
    Manages dynamic pair selection and rotation.

    Three-tier system:
    - Tier 1 (Always): High-volume pairs + pairs with open positions
    - Tier 2 (Rotating): Top opportunity pairs, rotated each cycle
    - Tier 3 (Prescreened): All other pairs, lightweight check only
    """

    def __init__(
        self,
        exchange: IExchange,
        config: PairConfig = None
    ):
        self.exchange = exchange
        self.config = config or PairConfig()

        self._all_pairs: List[Dict] = []
        self._pair_metrics: Dict[str, PairMetrics] = {}
        self._rotation_index = 0
        self._last_discovery: Optional[datetime] = None
        self._open_positions: List[str] = []

    async def discover_pairs(self, force: bool = False) -> List[Dict]:
        """
        Discover all available pairs from exchange.

        Args:
            force: Force refresh even if cache is valid

        Returns:
            List of pair info dictionaries
        """
        now = datetime.now(timezone.utc)

        # Use cache if valid
        if not force and self._last_discovery:
            cache_age = (now - self._last_discovery).total_seconds() / 60
            if cache_age < self.config.cache_ttl_minutes and self._all_pairs:
                return self._all_pairs

        try:
            # Check if exchange supports get_all_pairs
            if hasattr(self.exchange, 'get_all_pairs'):
                self._all_pairs = await self.exchange.get_all_pairs(
                    self.config.quote_currency
                )
            else:
                # Fallback to static list
                logger.warning("Exchange does not support get_all_pairs, using static list")
                self._all_pairs = [
                    {"pair": p, "base_asset": p.split("/")[0]}
                    for p in self.config.always_analyze
                ]

            self._last_discovery = now
            logger.info(f"[PAIRS] Discovered {len(self._all_pairs)} pairs")
            return self._all_pairs

        except Exception as e:
            logger.error(f"Error discovering pairs: {e}")
            return self._all_pairs or []

    async def prescreen_pair(self, pair: str) -> bool:
        """
        Quick check if a pair is worth full analysis.

        Uses only ticker data (single API call) to filter out
        low-opportunity pairs.

        Returns:
            True if pair passes prescreen
        """
        try:
            ticker = await self.exchange.get_ticker(pair)

            # Volume check
            volume_quote = ticker["volume_24h"] * ticker["price"]
            if volume_quote < self.config.min_volume_aud:
                return False

            # Price movement check (at least 1% range)
            price_range = abs(ticker["high_24h"] - ticker["low_24h"]) / ticker["price"]
            if price_range < 0.01:
                return False

            # Spread check
            spread = (ticker["ask"] - ticker["bid"]) / ticker["price"]
            if spread > self.config.max_spread_pct:
                return False

            return True

        except Exception as e:
            logger.debug(f"Prescreen failed for {pair}: {e}")
            return False

    def calculate_opportunity_score(
        self,
        pair: str,
        ticker: Dict,
        ohlcv: List = None
    ) -> PairMetrics:
        """
        Calculate opportunity score for a pair.

        Score components (0-25 each, total 0-100):
        - Volume trend (25): Higher volume = more opportunity
        - Volatility sweet spot (25): 1-5% daily is ideal
        - Momentum (25): Strong trends = opportunity
        - Spread (25): Tighter spread = better execution
        """
        scores = {}

        # 1. Volume score (0-25)
        # Scale: $10K+ volume = max score
        volume_quote = ticker.get("volume_24h", 0) * ticker.get("price", 0)
        scores["volume"] = min(25, (volume_quote / 10000) * 25)

        # 2. Volatility score (0-25) - Goldilocks zone
        price = ticker.get("price", 1)
        high = ticker.get("high_24h", price)
        low = ticker.get("low_24h", price)
        volatility = (high - low) / price if price > 0 else 0

        # Sweet spot: 1-5% daily volatility
        if 0.01 <= volatility <= 0.05:
            scores["volatility"] = 25
        elif volatility < 0.01:
            scores["volatility"] = volatility * 2500  # Scale up
        else:
            # Penalize high volatility (risky)
            scores["volatility"] = max(0, 25 - (volatility - 0.05) * 200)

        # 3. Momentum score (0-25)
        # Use OHLCV if available for better momentum calculation
        if ohlcv and len(ohlcv) >= 4:
            # Calculate momentum from recent candles
            recent_closes = [c[4] for c in ohlcv[-4:]]  # Last 4 closes
            if len(recent_closes) >= 2 and recent_closes[0] > 0:
                momentum = (recent_closes[-1] - recent_closes[0]) / recent_closes[0]
                scores["momentum"] = min(25, abs(momentum) * 500)  # Strong moves = opportunity
            else:
                scores["momentum"] = 12.5  # Neutral
        else:
            # Fallback: use 24h range position
            if high > low:
                position = (price - low) / (high - low)
                # Middle of range = neutral, extremes = opportunity
                scores["momentum"] = abs(position - 0.5) * 50

        # 4. Spread score (0-25) - Tighter is better
        bid = ticker.get("bid", 0)
        ask = ticker.get("ask", 0)
        if price > 0 and bid > 0 and ask > 0:
            spread_pct = (ask - bid) / price
            scores["spread"] = max(0, 25 - spread_pct * 2500)
        else:
            scores["spread"] = 0

        total_score = sum(scores.values())

        return PairMetrics(
            pair=pair,
            volume_24h=volume_quote,
            volatility=volatility,
            spread_pct=(ask - bid) / price if price > 0 else 0,
            momentum_score=scores.get("momentum", 0) / 25,  # Normalize to 0-1
            opportunity_score=total_score,
            last_analyzed=datetime.now(timezone.utc),
            price=price,
            high_24h=high,
            low_24h=low
        )

    async def rank_by_opportunity(self, pairs: List[str] = None) -> List[PairMetrics]:
        """
        Rank pairs by opportunity score.

        Args:
            pairs: List of pairs to rank, or None to use all discovered pairs

        Returns:
            List of PairMetrics sorted by opportunity score descending
        """
        if pairs is None:
            await self.discover_pairs()
            pairs = [p["pair"] for p in self._all_pairs]

        rankings = []

        for pair in pairs:
            try:
                ticker = await self.exchange.get_ticker(pair)

                # Try to get OHLCV for momentum calculation
                ohlcv = None
                try:
                    ohlcv = await self.exchange.get_ohlcv(pair, interval=60, limit=12)
                except:
                    pass

                metrics = self.calculate_opportunity_score(pair, ticker, ohlcv)
                self._pair_metrics[pair] = metrics
                rankings.append(metrics)

            except Exception as e:
                logger.debug(f"Could not rank {pair}: {e}")

        # Sort by opportunity score descending
        rankings.sort(key=lambda x: x.opportunity_score, reverse=True)

        return rankings

    def set_open_positions(self, positions: List[str]) -> None:
        """Update list of pairs with open positions."""
        self._open_positions = positions

    async def get_active_pairs(self, portfolio_value: float = None) -> List[str]:
        """
        Get pairs to analyze this cycle.

        Uses tiered selection:
        1. Always: High-volume pairs (BTC, ETH) + pairs with positions
        2. Rotating: Top opportunity pairs (rotate each cycle)
        3. Filtered: Only pairs that pass prescreen

        Args:
            portfolio_value: Current portfolio value for scaling

        Returns:
            List of pair names to analyze
        """
        await self.discover_pairs()

        active = set()

        # Tier 1: Always analyze (high-volume + positions)
        for pair in self.config.always_analyze:
            active.add(pair)

        for pair in self._open_positions:
            active.add(pair)

        # Tier 2: Rotating opportunity pairs
        remaining_slots = self.config.max_active_pairs - len(active)

        if remaining_slots > 0:
            # Get pairs not already in active set
            other_pairs = [
                p["pair"] for p in self._all_pairs
                if p["pair"] not in active
            ]

            # Rank by opportunity
            rankings = await self.rank_by_opportunity(other_pairs)

            # Filter by opportunity threshold
            qualified = [
                m for m in rankings
                if m.opportunity_score >= self.config.opportunity_threshold
            ]

            # Rotate through qualified pairs
            start = self._rotation_index
            for i in range(min(remaining_slots, len(qualified))):
                idx = (start + i) % len(qualified)
                active.add(qualified[idx].pair)

            # Update rotation index
            self._rotation_index = (self._rotation_index + self.config.rotation_size) % max(1, len(qualified))

        result = list(active)
        logger.info(f"[PAIRS] Active pairs this cycle: {result}")

        return result

    def get_pair_metrics(self, pair: str) -> Optional[PairMetrics]:
        """Get cached metrics for a pair."""
        return self._pair_metrics.get(pair)

    def get_all_metrics(self) -> List[Dict]:
        """Get all cached pair metrics."""
        return [m.to_dict() for m in self._pair_metrics.values()]

    def get_status(self) -> Dict:
        """Get pair manager status."""
        return {
            "total_discovered": len(self._all_pairs),
            "cached_metrics": len(self._pair_metrics),
            "rotation_index": self._rotation_index,
            "always_analyze": self.config.always_analyze,
            "open_positions": self._open_positions,
            "max_active": self.config.max_active_pairs,
            "last_discovery": self._last_discovery.isoformat() if self._last_discovery else None
        }
