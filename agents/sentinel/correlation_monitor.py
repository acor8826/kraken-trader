"""
Position Correlation Monitor

Monitors portfolio position correlations to prevent over-concentration.
Blocks new positions that would increase correlation above threshold.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class CorrelationMatrix:
    """Stores pairwise correlations between assets."""

    correlations: Dict[Tuple[str, str], float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lookback_hours: int = 24

    def get_correlation(self, pair1: str, pair2: str) -> float:
        """Get correlation between two pairs."""
        if pair1 == pair2:
            return 1.0

        # Normalize key order
        key = tuple(sorted([pair1, pair2]))
        return self.correlations.get(key, 0.0)

    def set_correlation(self, pair1: str, pair2: str, correlation: float) -> None:
        """Set correlation between two pairs."""
        if pair1 != pair2:
            key = tuple(sorted([pair1, pair2]))
            self.correlations[key] = correlation

    def is_stale(self, max_age_hours: int = 1) -> bool:
        """Check if matrix needs refresh."""
        age = datetime.now(timezone.utc) - self.last_updated
        return age > timedelta(hours=max_age_hours)


@dataclass
class CorrelationAlert:
    """Alert when correlation threshold exceeded."""

    pair1: str
    pair2: str
    correlation: float
    threshold: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def message(self) -> str:
        return f"High correlation ({self.correlation:.2f}) between {self.pair1} and {self.pair2}"


class CorrelationMonitor:
    """
    Monitors position correlations to prevent over-concentration.

    Features:
    - Calculate pairwise correlation from price history
    - Block positions that would exceed correlation threshold
    - Alert on high portfolio correlation
    - Hourly matrix refresh
    """

    DEFAULT_CORRELATION_THRESHOLD = 0.8
    REFRESH_INTERVAL_HOURS = 1
    MIN_DATA_POINTS = 20  # Minimum candles for correlation calculation

    def __init__(
        self,
        exchange=None,
        threshold: float = DEFAULT_CORRELATION_THRESHOLD,
        event_bus=None
    ):
        """
        Initialize correlation monitor.

        Args:
            exchange: Exchange for fetching price data
            threshold: Maximum allowed correlation (0.0 to 1.0)
            event_bus: Event bus for publishing alerts
        """
        self.exchange = exchange
        self.threshold = threshold
        self.event_bus = event_bus

        self._matrix = CorrelationMatrix()
        self._price_cache: Dict[str, List[float]] = {}
        self._alerts: List[CorrelationAlert] = []
        self._refresh_lock = asyncio.Lock()

        logger.info(f"CorrelationMonitor initialized with threshold {threshold}")

    async def check_new_position(
        self,
        new_pair: str,
        current_positions: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a new position would cause over-concentration.

        Args:
            new_pair: Pair to potentially add
            current_positions: List of currently held pairs

        Returns:
            Tuple of (is_allowed, rejection_reason)
        """
        if not current_positions:
            return True, None

        # Refresh matrix if stale
        if self._matrix.is_stale(self.REFRESH_INTERVAL_HOURS):
            await self.refresh_correlation_matrix(current_positions + [new_pair])

        # Check correlation with each existing position
        for existing_pair in current_positions:
            correlation = self._matrix.get_correlation(new_pair, existing_pair)

            if abs(correlation) >= self.threshold:
                reason = (
                    f"Position {new_pair} blocked: "
                    f"correlation {correlation:.2f} with {existing_pair} "
                    f"exceeds threshold {self.threshold}"
                )
                logger.warning(reason)

                # Record alert
                alert = CorrelationAlert(
                    pair1=new_pair,
                    pair2=existing_pair,
                    correlation=correlation,
                    threshold=self.threshold
                )
                self._alerts.append(alert)
                await self._publish_alert(alert)

                return False, reason

        return True, None

    async def get_portfolio_correlation(
        self,
        positions: List[str]
    ) -> float:
        """
        Calculate average pairwise correlation of portfolio.

        Returns value between -1 and 1.
        """
        if len(positions) < 2:
            return 0.0

        # Refresh if needed
        if self._matrix.is_stale(self.REFRESH_INTERVAL_HOURS):
            await self.refresh_correlation_matrix(positions)

        # Calculate average pairwise correlation
        total_correlation = 0.0
        pair_count = 0

        for i, pair1 in enumerate(positions):
            for pair2 in positions[i + 1:]:
                correlation = self._matrix.get_correlation(pair1, pair2)
                total_correlation += abs(correlation)
                pair_count += 1

        if pair_count == 0:
            return 0.0

        return total_correlation / pair_count

    async def refresh_correlation_matrix(self, pairs: List[str]) -> None:
        """Refresh correlation matrix for given pairs."""
        async with self._refresh_lock:
            logger.info(f"Refreshing correlation matrix for {len(pairs)} pairs")

            # Fetch price history for all pairs
            await self._fetch_price_data(pairs)

            # Calculate pairwise correlations
            for i, pair1 in enumerate(pairs):
                for pair2 in pairs[i + 1:]:
                    correlation = self._calculate_correlation(pair1, pair2)
                    self._matrix.set_correlation(pair1, pair2, correlation)

            self._matrix.last_updated = datetime.now(timezone.utc)
            logger.info(f"Correlation matrix updated with {len(self._matrix.correlations)} pairs")

    async def _fetch_price_data(self, pairs: List[str]) -> None:
        """Fetch historical prices for correlation calculation."""
        if not self.exchange:
            logger.warning("No exchange available for price data")
            return

        for pair in pairs:
            if pair in self._price_cache:
                continue

            try:
                # Get hourly candles for last 24 hours
                candles = await self.exchange.get_ohlcv(
                    symbol=pair,
                    timeframe="1h",
                    limit=self._matrix.lookback_hours
                )

                if candles and len(candles) >= self.MIN_DATA_POINTS:
                    # Extract close prices
                    closes = [c["close"] for c in candles if "close" in c]
                    self._price_cache[pair] = closes

            except Exception as e:
                logger.error(f"Failed to fetch price data for {pair}: {e}")

    def _calculate_correlation(self, pair1: str, pair2: str) -> float:
        """
        Calculate Pearson correlation coefficient between two pairs.

        Returns 0.0 if insufficient data.
        """
        prices1 = self._price_cache.get(pair1, [])
        prices2 = self._price_cache.get(pair2, [])

        if not prices1 or not prices2:
            return 0.0

        # Align series length
        min_len = min(len(prices1), len(prices2))
        if min_len < self.MIN_DATA_POINTS:
            return 0.0

        p1 = prices1[-min_len:]
        p2 = prices2[-min_len:]

        # Calculate returns (percentage changes)
        returns1 = [(p1[i] - p1[i-1]) / p1[i-1] if p1[i-1] != 0 else 0
                    for i in range(1, len(p1))]
        returns2 = [(p2[i] - p2[i-1]) / p2[i-1] if p2[i-1] != 0 else 0
                    for i in range(1, len(p2))]

        if not returns1 or not returns2:
            return 0.0

        # Calculate correlation
        n = len(returns1)
        mean1 = sum(returns1) / n
        mean2 = sum(returns2) / n

        numerator = sum((r1 - mean1) * (r2 - mean2) for r1, r2 in zip(returns1, returns2))

        var1 = sum((r - mean1) ** 2 for r in returns1)
        var2 = sum((r - mean2) ** 2 for r in returns2)

        if var1 == 0 or var2 == 0:
            return 0.0

        denominator = (var1 * var2) ** 0.5

        if denominator == 0:
            return 0.0

        correlation = numerator / denominator

        # Clamp to [-1, 1] for numerical stability
        return max(-1.0, min(1.0, correlation))

    async def _publish_alert(self, alert: CorrelationAlert) -> None:
        """Publish correlation alert to event bus."""
        if self.event_bus:
            try:
                await self.event_bus.publish("CORRELATION_ALERT", {
                    "pair1": alert.pair1,
                    "pair2": alert.pair2,
                    "correlation": alert.correlation,
                    "threshold": alert.threshold,
                    "timestamp": alert.timestamp.isoformat()
                })
            except Exception as e:
                logger.error(f"Failed to publish correlation alert: {e}")

    def get_alerts(self, limit: int = 10) -> List[CorrelationAlert]:
        """Get recent correlation alerts."""
        return self._alerts[-limit:]

    def get_matrix_summary(self) -> Dict:
        """Get summary of correlation matrix."""
        return {
            "pair_count": len(self._matrix.correlations),
            "last_updated": self._matrix.last_updated.isoformat(),
            "is_stale": self._matrix.is_stale(self.REFRESH_INTERVAL_HOURS),
            "threshold": self.threshold,
            "high_correlations": [
                {
                    "pairs": list(key),
                    "correlation": value
                }
                for key, value in self._matrix.correlations.items()
                if abs(value) >= self.threshold
            ]
        }

    def clear_cache(self) -> None:
        """Clear price cache to force fresh data on next refresh."""
        self._price_cache.clear()
        logger.info("Price cache cleared")
