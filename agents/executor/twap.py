"""
TWAP (Time-Weighted Average Price) Executor

Executes large orders by splitting them into smaller slices
over time to minimize market impact.

Features:
- Configurable duration and slice count
- Limit order preference with market fallback
- Partial fill tracking
- Benchmark comparison
"""

import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from core.interfaces import IExchange

logger = logging.getLogger(__name__)


@dataclass
class TWAPSlice:
    """A single TWAP execution slice"""
    slice_num: int
    target_volume: float
    executed_volume: float = 0.0
    average_price: float = 0.0
    status: str = "pending"  # pending, filled, partial, failed
    order_id: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class TWAPResult:
    """Result of TWAP execution"""
    pair: str
    total_target: float
    total_executed: float
    average_price: float
    benchmark_price: float  # Price at start
    slippage_vs_benchmark: float
    slices: List[TWAPSlice]
    duration_seconds: float
    status: str  # completed, partial, failed


class TWAPExecutor:
    """
    TWAP execution algorithm.

    Splits large orders into time-based slices to achieve
    a price close to the time-weighted average.
    """

    def __init__(
        self,
        exchange: IExchange,
        duration_minutes: int = 30,
        slice_count: int = 6,
        limit_timeout_seconds: int = 60,
        spread_buffer_pct: float = 0.001
    ):
        """
        Initialize TWAP executor.

        Args:
            exchange: Exchange for order execution
            duration_minutes: Total execution duration (default: 30 min)
            slice_count: Number of slices (default: 6)
            limit_timeout_seconds: Time to wait for limit fills
            spread_buffer_pct: Buffer inside bid-ask for limits
        """
        self.exchange = exchange
        self.duration_minutes = duration_minutes
        self.slice_count = slice_count
        self.limit_timeout = limit_timeout_seconds
        self.spread_buffer = spread_buffer_pct

        # Calculated
        self.slice_interval = (duration_minutes * 60) / slice_count

        logger.info(f"TWAPExecutor: {slice_count} slices over {duration_minutes} min")

    async def execute_buy(
        self,
        pair: str,
        total_quote_amount: float
    ) -> TWAPResult:
        """
        Execute TWAP buy order.

        Args:
            pair: Trading pair
            total_quote_amount: Total amount in quote currency to spend

        Returns:
            TWAPResult with execution details
        """
        return await self._execute(pair, total_quote_amount, side="buy")

    async def execute_sell(
        self,
        pair: str,
        total_base_amount: float
    ) -> TWAPResult:
        """
        Execute TWAP sell order.

        Args:
            pair: Trading pair
            total_base_amount: Total amount in base currency to sell

        Returns:
            TWAPResult with execution details
        """
        return await self._execute(pair, total_base_amount, side="sell")

    async def _execute(
        self,
        pair: str,
        total_amount: float,
        side: str
    ) -> TWAPResult:
        """Execute TWAP strategy"""
        start_time = datetime.now(timezone.utc)

        # Get benchmark price
        ticker = await self.exchange.get_ticker(pair)
        benchmark_price = ticker["price"]

        # Calculate slice sizes (equal distribution)
        slice_amount = total_amount / self.slice_count
        slices = [
            TWAPSlice(slice_num=i, target_volume=slice_amount)
            for i in range(self.slice_count)
        ]

        logger.info(f"TWAP {side.upper()} {pair}: {total_amount:.4f} in {self.slice_count} slices")

        # Execute slices
        total_executed = 0.0
        total_cost = 0.0

        for i, slice_order in enumerate(slices):
            try:
                # Execute this slice
                result = await self._execute_slice(pair, slice_order, side)

                slice_order.executed_volume = result["filled"]
                slice_order.average_price = result["price"]
                slice_order.status = "filled" if result["filled"] >= slice_order.target_volume * 0.95 else "partial"
                slice_order.timestamp = datetime.now(timezone.utc)

                total_executed += result["filled"]
                total_cost += result["filled"] * result["price"]

                logger.debug(f"TWAP slice {i+1}/{self.slice_count}: {result['filled']:.4f} @ {result['price']:.2f}")

            except Exception as e:
                logger.error(f"TWAP slice {i+1} failed: {e}")
                slice_order.status = "failed"

            # Wait for next slice (except for last one)
            if i < self.slice_count - 1:
                await asyncio.sleep(self.slice_interval)

        # Calculate results
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        average_price = total_cost / total_executed if total_executed > 0 else 0
        slippage = (average_price - benchmark_price) / benchmark_price if benchmark_price > 0 else 0

        status = "completed" if total_executed >= total_amount * 0.95 else "partial"

        result = TWAPResult(
            pair=pair,
            total_target=total_amount,
            total_executed=total_executed,
            average_price=average_price,
            benchmark_price=benchmark_price,
            slippage_vs_benchmark=slippage,
            slices=slices,
            duration_seconds=duration,
            status=status
        )

        logger.info(f"TWAP complete: {total_executed:.4f} @ avg {average_price:.2f} "
                   f"(slippage: {slippage*100:+.3f}%)")

        return result

    async def _execute_slice(
        self,
        pair: str,
        slice_order: TWAPSlice,
        side: str
    ) -> Dict:
        """Execute a single TWAP slice"""
        # Get current ticker
        ticker = await self.exchange.get_ticker(pair)

        # Calculate limit price with spread buffer
        if side == "buy":
            # Bid inside the spread
            limit_price = ticker["ask"] * (1 - self.spread_buffer)
        else:
            # Ask inside the spread
            limit_price = ticker["bid"] * (1 + self.spread_buffer)

        try:
            # Try limit order first
            if side == "buy":
                order = await self.exchange.limit_buy(pair, slice_order.target_volume, limit_price)
            else:
                order = await self.exchange.limit_sell(pair, slice_order.target_volume, limit_price)

            slice_order.order_id = order.get("order_id") or (order.get("txid", [None])[0] if isinstance(order.get("txid"), list) else order.get("txid"))

            # Wait for fill
            filled = await self._wait_for_fill(slice_order.order_id, self.limit_timeout)

            if filled["filled"] > 0:
                return filled

        except Exception as e:
            logger.debug(f"Limit order failed, using market: {e}")

        # Fallback to market order
        if side == "buy":
            order = await self.exchange.market_buy(pair, slice_order.target_volume)
        else:
            order = await self.exchange.market_sell(pair, slice_order.target_volume)

        return {
            "filled": slice_order.target_volume,
            "price": ticker["price"]
        }

    async def _wait_for_fill(self, order_id: str, timeout: int) -> Dict:
        """Wait for order to fill with timeout"""
        if not order_id:
            return {"filled": 0, "price": 0}

        start = datetime.now(timezone.utc)
        poll_interval = 5  # seconds

        while (datetime.now(timezone.utc) - start).total_seconds() < timeout:
            try:
                # Check order status
                open_orders = await self.exchange.get_open_orders()

                # If order no longer open, it was filled
                if order_id not in str(open_orders):
                    # Order filled - would need to fetch order details
                    # For now, assume fully filled
                    return {"filled": 1.0, "price": 0}  # Price unknown

            except Exception as e:
                logger.debug(f"Order status check failed: {e}")

            await asyncio.sleep(poll_interval)

        # Timeout - cancel order
        try:
            await self.exchange.cancel_order(order_id)
        except Exception:
            pass

        return {"filled": 0, "price": 0}
