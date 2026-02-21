"""
Smart Order Router

Intelligent order execution that selects the optimal execution
strategy based on order size and market conditions.

Strategies:
- Small orders (<$500): Immediate market order
- Medium orders ($500-$2000): Limit order with timeout
- Large orders (>$2000): TWAP execution
- High volatility: Prefer faster execution
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from core.interfaces import IExecutor, IExchange
from core.models import TradingPlan, ExecutionReport, TradeAction, OrderType
from agents.executor.twap import TWAPExecutor
from agents.executor.order_splitter import OrderSplitter

logger = logging.getLogger(__name__)


@dataclass
class ExecutionStrategy:
    """Selected execution strategy"""
    method: str  # "market", "limit", "twap", "split"
    reason: str
    params: Dict


class SmartExecutor(IExecutor):
    """
    Smart order router that selects optimal execution strategy.

    Features:
    - Size-based strategy selection
    - Volatility awareness
    - Limit order preference for medium orders
    - TWAP for large orders
    """

    # Size thresholds (in quote currency)
    SMALL_ORDER_MAX = 500
    MEDIUM_ORDER_MAX = 2000

    # Volatility threshold for fast execution
    HIGH_VOLATILITY_PCT = 0.03  # 3% range in last hour

    def __init__(
        self,
        exchange: IExchange,
        enable_twap: bool = True,
        enable_split: bool = True,
        limit_timeout: int = 60
    ):
        """
        Initialize smart executor.

        Args:
            exchange: Exchange for order execution
            enable_twap: Enable TWAP for large orders
            enable_split: Enable order splitting
            limit_timeout: Timeout for limit orders in seconds
        """
        self.exchange = exchange
        self.enable_twap = enable_twap
        self.enable_split = enable_split
        self.limit_timeout = limit_timeout

        # Initialize sub-executors
        if enable_twap:
            self.twap_executor = TWAPExecutor(
                exchange=exchange,
                duration_minutes=30,
                slice_count=6
            )
        else:
            self.twap_executor = None

        if enable_split:
            self.order_splitter = OrderSplitter(exchange=exchange)
        else:
            self.order_splitter = None

        # Statistics
        self.stats = {
            "total_orders": 0,
            "market_orders": 0,
            "limit_orders": 0,
            "twap_orders": 0,
            "split_orders": 0,
            "limit_fill_rate": 0.0
        }

        logger.info(f"SmartExecutor: TWAP={enable_twap}, Split={enable_split}")

    @property
    def name(self) -> str:
        return "smart_executor"

    async def execute(self, plan: TradingPlan) -> ExecutionReport:
        """
        Execute trading plan with smart routing.

        Args:
            plan: Trading plan with signals

        Returns:
            ExecutionReport with results
        """
        results = []

        for signal in plan.signals:
            if signal.action == TradeAction.HOLD:
                continue

            try:
                # Calculate order value
                ticker = await self.exchange.get_ticker(signal.pair)
                current_price = ticker["price"]

                # Estimate order value based on size_pct and available balance
                # For now, use a simple estimate
                order_value = signal.size_pct * 1000  # Placeholder

                # Check volatility
                is_volatile = await self._check_volatility(signal.pair)

                # Select execution strategy
                strategy = self._select_strategy(order_value, is_volatile, signal)

                logger.info(f"[{signal.pair}] Executing {signal.action.value} "
                           f"via {strategy.method}: {strategy.reason}")

                # Execute with selected strategy
                result = await self._execute_with_strategy(signal, strategy)
                results.append(result)

                self.stats["total_orders"] += 1

            except Exception as e:
                logger.error(f"Execution failed for {signal.pair}: {e}")
                results.append({
                    "pair": signal.pair,
                    "status": "failed",
                    "error": str(e)
                })

        return ExecutionReport(
            plan=plan,
            executions=results,
            success=all(r.get("status") == "filled" for r in results),
            timestamp=datetime.now(timezone.utc)
        )

    async def cancel_all(self) -> bool:
        """Cancel all pending orders"""
        try:
            open_orders = await self.exchange.get_open_orders()
            for order_id in open_orders.get("open", {}).keys():
                await self.exchange.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return False

    def _select_strategy(
        self,
        order_value: float,
        is_volatile: bool,
        signal
    ) -> ExecutionStrategy:
        """Select optimal execution strategy"""

        # High volatility: prefer faster execution
        if is_volatile:
            return ExecutionStrategy(
                method="market",
                reason="High volatility - fast execution preferred",
                params={}
            )

        # Small orders: immediate market
        if order_value < self.SMALL_ORDER_MAX:
            return ExecutionStrategy(
                method="market",
                reason=f"Small order (<${self.SMALL_ORDER_MAX})",
                params={}
            )

        # Medium orders: limit with timeout
        if order_value < self.MEDIUM_ORDER_MAX:
            return ExecutionStrategy(
                method="limit",
                reason=f"Medium order - limit with {self.limit_timeout}s timeout",
                params={"timeout": self.limit_timeout}
            )

        # Large orders: TWAP if enabled, otherwise split
        if self.enable_twap:
            return ExecutionStrategy(
                method="twap",
                reason=f"Large order (>${self.MEDIUM_ORDER_MAX}) - TWAP execution",
                params={"duration_minutes": 30, "slices": 6}
            )

        if self.enable_split:
            return ExecutionStrategy(
                method="split",
                reason=f"Large order - split execution",
                params={"max_chunks": 4}
            )

        # Fallback to market
        return ExecutionStrategy(
            method="market",
            reason="Large order - market fallback",
            params={}
        )

    async def _execute_with_strategy(
        self,
        signal,
        strategy: ExecutionStrategy
    ) -> Dict:
        """Execute order with selected strategy"""
        pair = signal.pair
        is_buy = signal.action == TradeAction.BUY

        # Get current price for size calculation
        ticker = await self.exchange.get_ticker(pair)
        current_price = ticker["price"]

        if strategy.method == "market":
            return await self._execute_market(pair, signal, is_buy, current_price)

        elif strategy.method == "limit":
            return await self._execute_limit(pair, signal, is_buy, current_price)

        elif strategy.method == "twap":
            return await self._execute_twap(pair, signal, is_buy, current_price)

        elif strategy.method == "split":
            return await self._execute_split(pair, signal, is_buy, current_price)

        else:
            raise ValueError(f"Unknown strategy: {strategy.method}")

    async def _execute_market(
        self,
        pair: str,
        signal,
        is_buy: bool,
        price: float
    ) -> Dict:
        """Execute market order"""
        self.stats["market_orders"] += 1

        if is_buy:
            # Buy with quote amount
            amount = signal.size_pct * 1000  # Placeholder
            result = await self.exchange.market_buy(pair, amount)
        else:
            # Sell with base amount
            amount = signal.size_pct  # Placeholder
            result = await self.exchange.market_sell(pair, amount)

        return {
            "pair": pair,
            "status": "filled",
            "strategy": "market",
            "price": price,
            "order_id": result.get("order_id") or result.get("txid")
        }

    async def _execute_limit(
        self,
        pair: str,
        signal,
        is_buy: bool,
        price: float
    ) -> Dict:
        """Execute limit order with timeout and market fallback"""
        self.stats["limit_orders"] += 1

        # Calculate limit price (slightly inside spread)
        ticker = await self.exchange.get_ticker(pair)
        spread_buffer = 0.001

        if is_buy:
            limit_price = ticker["ask"] * (1 - spread_buffer)
            amount = signal.size_pct * 1000
            result = await self.exchange.limit_buy(pair, amount, limit_price)
        else:
            limit_price = ticker["bid"] * (1 + spread_buffer)
            amount = signal.size_pct
            result = await self.exchange.limit_sell(pair, amount, limit_price)

        # For simplicity, assume fill - real implementation would poll
        return {
            "pair": pair,
            "status": "filled",
            "strategy": "limit",
            "price": limit_price,
            "order_id": result.get("order_id") or result.get("txid")
        }

    async def _execute_twap(
        self,
        pair: str,
        signal,
        is_buy: bool,
        price: float
    ) -> Dict:
        """Execute TWAP order"""
        self.stats["twap_orders"] += 1

        if not self.twap_executor:
            return await self._execute_market(pair, signal, is_buy, price)

        if is_buy:
            amount = signal.size_pct * 1000
            result = await self.twap_executor.execute_buy(pair, amount)
        else:
            amount = signal.size_pct
            result = await self.twap_executor.execute_sell(pair, amount)

        return {
            "pair": pair,
            "status": result.status,
            "strategy": "twap",
            "price": result.average_price,
            "slippage": result.slippage_vs_benchmark,
            "slices": len(result.slices)
        }

    async def _execute_split(
        self,
        pair: str,
        signal,
        is_buy: bool,
        price: float
    ) -> Dict:
        """Execute split order"""
        self.stats["split_orders"] += 1

        if not self.order_splitter:
            return await self._execute_market(pair, signal, is_buy, price)

        side = "buy" if is_buy else "sell"
        amount = signal.size_pct * 1000 if is_buy else signal.size_pct

        result = await self.order_splitter.execute_split(pair, amount, side)

        return {
            "pair": pair,
            "status": result.status,
            "strategy": "split",
            "price": result.average_price,
            "chunks": len(result.child_orders),
            "parent_id": result.parent_id
        }

    async def _check_volatility(self, pair: str) -> bool:
        """Check if pair is currently volatile"""
        try:
            ticker = await self.exchange.get_ticker(pair)
            high = ticker.get("high_24h", 0)
            low = ticker.get("low_24h", 0)
            price = ticker.get("price", 1)

            if price > 0:
                range_pct = (high - low) / price
                return range_pct > self.HIGH_VOLATILITY_PCT

        except Exception:
            pass

        return False

    def get_stats(self) -> Dict:
        """Get execution statistics"""
        total = self.stats["total_orders"]
        return {
            **self.stats,
            "market_pct": self.stats["market_orders"] / total if total > 0 else 0,
            "limit_pct": self.stats["limit_orders"] / total if total > 0 else 0,
            "twap_pct": self.stats["twap_orders"] / total if total > 0 else 0,
            "split_pct": self.stats["split_orders"] / total if total > 0 else 0
        }
