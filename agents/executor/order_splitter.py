"""
Order Splitter

Splits large orders into smaller chunks to minimize market impact
and avoid detection of trading patterns.

Features:
- Dynamic split sizing based on order book depth
- Randomized chunk sizes for pattern avoidance
- Staggered execution timing
- Parent-child order tracking
"""

import asyncio
import random
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.interfaces import IExchange

logger = logging.getLogger(__name__)


@dataclass
class ChildOrder:
    """A child order from a split"""
    order_num: int
    target_size: float
    executed_size: float = 0.0
    price: float = 0.0
    status: str = "pending"
    order_id: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class SplitResult:
    """Result of split order execution"""
    parent_id: str
    pair: str
    side: str
    total_target: float
    total_executed: float
    average_price: float
    child_orders: List[ChildOrder]
    status: str


class OrderSplitter:
    """
    Splits large orders into smaller chunks.

    Uses order book depth analysis to determine optimal
    chunk sizes that minimize market impact.
    """

    # Maximum slippage target for chunk sizing
    MAX_SLIPPAGE_PCT = 0.01  # 1%

    # Randomization range for chunk sizes (variance from target)
    SIZE_VARIANCE = 0.15  # +/- 15%

    # Stagger timing range (seconds)
    STAGGER_MIN = 30
    STAGGER_MAX = 60

    def __init__(
        self,
        exchange: IExchange,
        max_chunk_pct: float = 0.25  # Max 25% of order in one chunk
    ):
        """
        Initialize order splitter.

        Args:
            exchange: Exchange for order execution
            max_chunk_pct: Maximum percentage of order per chunk
        """
        self.exchange = exchange
        self.max_chunk_pct = max_chunk_pct
        self._order_counter = 0

        logger.info(f"OrderSplitter initialized (max chunk: {max_chunk_pct:.0%})")

    def _generate_parent_id(self) -> str:
        """Generate unique parent order ID"""
        self._order_counter += 1
        return f"SPLIT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self._order_counter}"

    async def analyze_and_split(
        self,
        pair: str,
        size: float,
        side: str
    ) -> List[float]:
        """
        Analyze order book and determine optimal split sizes.

        Args:
            pair: Trading pair
            size: Total order size
            side: "buy" or "sell"

        Returns:
            List of chunk sizes
        """
        try:
            # Get order book depth
            order_book = await self.exchange.get_order_book(pair, depth=25)

            if side == "buy":
                levels = order_book.get("asks", [])
            else:
                levels = order_book.get("bids", [])

            if not levels:
                # No depth data - use default split
                return self._default_split(size)

            # Analyze depth to find max chunk size for target slippage
            max_chunk = self._calculate_max_chunk(levels, size)

            # Calculate number of chunks needed
            min_chunks = max(2, int(size / max_chunk) + 1)

            # Create randomized chunks
            chunks = self._create_randomized_chunks(size, min_chunks)

            logger.debug(f"Split {size:.4f} into {len(chunks)} chunks: {[f'{c:.4f}' for c in chunks]}")
            return chunks

        except Exception as e:
            logger.warning(f"Order book analysis failed: {e}")
            return self._default_split(size)

    def _calculate_max_chunk(self, levels: List, total_size: float) -> float:
        """Calculate max chunk size for target slippage"""
        if not levels:
            return total_size * self.max_chunk_pct

        # Sum volume until we hit slippage threshold
        cumulative_volume = 0
        reference_price = levels[0][0]

        for price, volume, _ in levels:
            price_diff_pct = abs(price - reference_price) / reference_price

            if price_diff_pct > self.MAX_SLIPPAGE_PCT:
                break

            cumulative_volume += volume

        # Max chunk is smaller of: depth-based limit or percentage limit
        depth_limit = cumulative_volume * 0.5  # Use 50% of available depth
        pct_limit = total_size * self.max_chunk_pct

        return min(depth_limit, pct_limit) if depth_limit > 0 else pct_limit

    def _default_split(self, size: float) -> List[float]:
        """Default split when depth analysis unavailable"""
        chunk_count = max(2, int(1 / self.max_chunk_pct))
        base_size = size / chunk_count
        return self._randomize_sizes([base_size] * chunk_count, size)

    def _create_randomized_chunks(self, total: float, min_chunks: int) -> List[float]:
        """Create randomized chunk sizes that sum to total"""
        base_size = total / min_chunks
        chunks = [base_size] * min_chunks
        return self._randomize_sizes(chunks, total)

    def _randomize_sizes(self, chunks: List[float], target_total: float) -> List[float]:
        """Add randomization to chunk sizes while maintaining total"""
        randomized = []

        for chunk in chunks:
            # Random variance
            variance = random.uniform(-self.SIZE_VARIANCE, self.SIZE_VARIANCE)
            randomized.append(chunk * (1 + variance))

        # Normalize to ensure sum equals target
        current_total = sum(randomized)
        scale_factor = target_total / current_total if current_total > 0 else 1

        return [c * scale_factor for c in randomized]

    async def execute_split(
        self,
        pair: str,
        size: float,
        side: str
    ) -> SplitResult:
        """
        Execute a split order.

        Args:
            pair: Trading pair
            size: Total order size
            side: "buy" or "sell"

        Returns:
            SplitResult with execution details
        """
        parent_id = self._generate_parent_id()
        chunks = await self.analyze_and_split(pair, size, side)

        child_orders = [
            ChildOrder(order_num=i, target_size=chunk_size)
            for i, chunk_size in enumerate(chunks)
        ]

        logger.info(f"Executing split order {parent_id}: {len(chunks)} chunks for {pair}")

        total_executed = 0.0
        total_cost = 0.0

        for i, child in enumerate(child_orders):
            try:
                # Execute child order
                if side == "buy":
                    # For buy, size is in quote currency
                    order = await self.exchange.market_buy(pair, child.target_size)
                else:
                    # For sell, size is in base currency
                    order = await self.exchange.market_sell(pair, child.target_size)

                # Get current price for tracking
                ticker = await self.exchange.get_ticker(pair)
                child.price = ticker["price"]
                child.executed_size = child.target_size
                child.status = "filled"
                child.timestamp = datetime.now(timezone.utc)

                total_executed += child.executed_size
                total_cost += child.executed_size * child.price

                logger.debug(f"Child order {i+1}/{len(chunks)}: {child.executed_size:.4f} @ {child.price:.2f}")

            except Exception as e:
                logger.error(f"Child order {i+1} failed: {e}")
                child.status = "failed"

            # Stagger next order (except last)
            if i < len(chunks) - 1:
                stagger = random.uniform(self.STAGGER_MIN, self.STAGGER_MAX)
                await asyncio.sleep(stagger)

        # Calculate results
        average_price = total_cost / total_executed if total_executed > 0 else 0
        status = "completed" if total_executed >= size * 0.95 else "partial"

        return SplitResult(
            parent_id=parent_id,
            pair=pair,
            side=side,
            total_target=size,
            total_executed=total_executed,
            average_price=average_price,
            child_orders=child_orders,
            status=status
        )
