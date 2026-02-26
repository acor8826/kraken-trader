"""
Enhanced Executor - Phase 2

Supports limit orders with timeout and fallback to market orders.

Features:
- Limit order execution with spread buffer
- Order timeout with polling
- Partial fill handling
- Automatic fallback to market orders
- Execution statistics tracking
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field

from core.interfaces import IExecutor, IExchange, IMemory
from core.models import (
    TradingPlan, Trade, ExecutionReport,
    TradeAction, TradeStatus, OrderType
)
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class ExecutionStats:
    """Track execution statistics"""
    total_orders: int = 0
    limit_orders: int = 0
    market_orders: int = 0
    limit_fills: int = 0
    limit_timeouts: int = 0
    partial_fills: int = 0
    total_slippage: float = 0.0


class EnhancedExecutor(IExecutor):
    """
    Phase 2 Executor - Limit orders with fallback.

    Execution Strategy:
    1. Try limit order at calculated price (spread buffer inside bid-ask)
    2. Poll order status for timeout period (default 60s)
    3. If partial fill: record partial, market order remainder
    4. If no fill: cancel and market order
    5. Track statistics for analysis
    """

    def __init__(
        self,
        exchange: IExchange,
        memory: IMemory = None,
        settings: Settings = None,
        limit_timeout_seconds: int = 60,
        spread_buffer_pct: float = 0.001,  # 0.1% inside spread
        poll_interval_seconds: float = 5.0,
        enable_limit_orders: bool = True
    ):
        """
        Initialize Enhanced Executor.

        Args:
            exchange: Exchange integration
            memory: Memory store for trade recording
            settings: Application settings
            limit_timeout_seconds: How long to wait for limit order fill
            spread_buffer_pct: How far inside spread to place limit order
            poll_interval_seconds: How often to check order status
            enable_limit_orders: Whether to use limit orders (False = market only)
        """
        self.exchange = exchange
        self.memory = memory
        self.settings = settings or get_settings()

        self.limit_timeout = limit_timeout_seconds
        self.spread_buffer_pct = spread_buffer_pct
        self.poll_interval = poll_interval_seconds
        self.enable_limit_orders = enable_limit_orders

        self.stats = ExecutionStats()
        self._pending_orders: Dict[str, dict] = {}

        logger.info(
            f"EnhancedExecutor initialized: "
            f"limit_orders={'enabled' if enable_limit_orders else 'disabled'}, "
            f"timeout={limit_timeout_seconds}s, "
            f"spread_buffer={spread_buffer_pct:.2%}"
        )

    async def execute(self, plan: TradingPlan) -> ExecutionReport:
        """
        Execute all approved signals in the plan.
        Uses limit orders with fallback to market orders.
        """
        trades: List[Trade] = []

        # Get current balance
        balance = await self.exchange.get_balance()
        available_quote = balance.get(self.settings.trading.quote_currency, 0)

        for signal in plan.actionable_signals:
            try:
                self.stats.total_orders += 1

                if self.enable_limit_orders:
                    trade = await self._execute_with_limit(signal, available_quote, balance)
                else:
                    trade = await self._execute_market(signal, available_quote, balance)

                trades.append(trade)

                # Update available balance
                if trade.is_successful and signal.action == TradeAction.BUY:
                    available_quote -= trade.filled_size_quote or 0

            except Exception as e:
                logger.error(f"Execution error for {signal.pair}: {e}")
                trades.append(Trade(
                    pair=signal.pair,
                    action=signal.action,
                    status=TradeStatus.FAILED,
                    error_message=str(e),
                    signal_confidence=signal.confidence,
                    reasoning=signal.reasoning
                ))

        report = ExecutionReport(plan_id=plan.id, trades=trades)

        logger.info(
            f"Execution report: {len(report.successful_trades)} successful, "
            f"{len(report.failed_trades)} failed, "
            f"volume=${report.total_volume_quote:,.2f}"
        )

        return report

    async def _execute_with_limit(
        self,
        signal,
        available_quote: float,
        balance: Dict
    ) -> Trade:
        """Execute signal with limit order, fallback to market"""

        trade = Trade(
            pair=signal.pair,
            action=signal.action,
            order_type=OrderType.LIMIT,
            signal_confidence=signal.confidence,
            reasoning=signal.reasoning
        )

        try:
            # Get current ticker for price calculation
            ticker = await self.exchange.get_ticker(signal.pair)
            bid = ticker.get("bid", 0)
            ask = ticker.get("ask", 0)

            if not bid or not ask:
                logger.warning(f"No bid/ask for {signal.pair}, falling back to market")
                return await self._execute_market(signal, available_quote, balance)

            # Calculate limit price
            if signal.action == TradeAction.BUY:
                # Buy slightly below ask (but above bid)
                spread = ask - bid
                limit_price = ask - (spread * self.spread_buffer_pct)
                amount_quote = available_quote * signal.size_pct
                trade.requested_size_quote = amount_quote

                if amount_quote < 10:
                    trade.status = TradeStatus.REJECTED
                    trade.error_message = "Amount too small"
                    return trade

                # Place limit buy
                logger.info(
                    f"Placing LIMIT BUY: {signal.pair} "
                    f"${amount_quote:.2f} @ ${limit_price:,.2f}"
                )

                self.stats.limit_orders += 1
                result = await self.exchange.limit_buy(signal.pair, amount_quote, limit_price)

            else:  # SELL
                # Sell slightly above bid (but below ask)
                spread = ask - bid
                limit_price = bid + (spread * self.spread_buffer_pct)

                base_asset = signal.pair.split("/")[0]
                position_amount = balance.get(base_asset, 0)

                if position_amount <= 0:
                    trade.status = TradeStatus.REJECTED
                    trade.error_message = f"No {base_asset} to sell"
                    return trade

                trade.requested_size_base = position_amount

                # Place limit sell
                logger.info(
                    f"Placing LIMIT SELL: {signal.pair} "
                    f"{position_amount:.8f} @ ${limit_price:,.2f}"
                )

                self.stats.limit_orders += 1
                result = await self.exchange.limit_sell(signal.pair, position_amount, limit_price)

            # Get order ID
            order_id = self._extract_order_id(result)
            trade.exchange_order_id = order_id

            if not order_id:
                logger.warning("No order ID returned, falling back to market")
                return await self._execute_market(signal, available_quote, balance)

            # Poll for fill
            filled = await self._wait_for_fill(order_id, signal.pair)

            if filled["status"] == "filled":
                # Fully filled
                self.stats.limit_fills += 1
                trade.status = TradeStatus.FILLED
                trade.filled_size_base = filled.get("filled_base", 0)
                trade.filled_size_quote = filled.get("filled_quote", 0)
                trade.average_price = filled.get("average_price", limit_price)

            elif filled["status"] == "partial":
                # Partial fill - record partial, market order rest
                self.stats.partial_fills += 1
                trade.status = TradeStatus.PARTIALLY_FILLED
                trade.filled_size_base = filled.get("filled_base", 0)
                trade.filled_size_quote = filled.get("filled_quote", 0)
                trade.average_price = filled.get("average_price", limit_price)

                # Market order remainder
                remainder_trade = await self._market_order_remainder(
                    signal, filled, available_quote, balance
                )

                # Combine with partial
                if remainder_trade.is_successful:
                    trade.filled_size_base = (trade.filled_size_base or 0) + (remainder_trade.filled_size_base or 0)
                    trade.filled_size_quote = (trade.filled_size_quote or 0) + (remainder_trade.filled_size_quote or 0)
                    trade.status = TradeStatus.FILLED

            else:
                # Not filled - cancel and market order
                self.stats.limit_timeouts += 1
                logger.info(f"Limit order timeout for {signal.pair}, falling back to market")

                try:
                    await self._cancel_order(order_id, signal.pair)
                except Exception as e:
                    logger.warning(f"Failed to cancel order: {e}")

                return await self._execute_market(signal, available_quote, balance)

            # Record entry price for buys
            if trade.is_successful and signal.action == TradeAction.BUY and self.memory:
                base_asset = signal.pair.split("/")[0]
                await self.memory.set_entry_price(base_asset, trade.average_price)

            # Calculate P&L for sells
            if trade.is_successful and signal.action == TradeAction.SELL and self.memory:
                base_asset = signal.pair.split("/")[0]
                entry_price = await self.memory.get_entry_price(base_asset)
                if entry_price:
                    trade.entry_price = entry_price
                    trade.exit_price = trade.average_price
                    trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base

            # Record trade
            if self.memory and trade.is_successful:
                await self.memory.record_trade(trade)

            return trade

        except Exception as e:
            logger.error(f"Limit order failed: {e}, falling back to market")
            return await self._execute_market(signal, available_quote, balance)

    async def _execute_market(
        self,
        signal,
        available_quote: float,
        balance: Dict
    ) -> Trade:
        """Execute market order (fallback or direct)"""

        trade = Trade(
            pair=signal.pair,
            action=signal.action,
            order_type=OrderType.MARKET,
            signal_confidence=signal.confidence,
            reasoning=signal.reasoning
        )

        self.stats.market_orders += 1

        try:
            if signal.action == TradeAction.BUY:
                amount_quote = available_quote * signal.size_pct
                trade.requested_size_quote = amount_quote

                if amount_quote < 10:
                    trade.status = TradeStatus.REJECTED
                    trade.error_message = "Amount too small"
                    return trade

                logger.info(f"Executing MARKET BUY: {signal.pair} for ${amount_quote:.2f}")
                result = await self.exchange.market_buy(signal.pair, amount_quote)

                trade.exchange_order_id = self._extract_order_id(result)
                trade.filled_size_quote = amount_quote
                trade.average_price = result.get("price", 0) or await self._get_price(signal.pair)
                trade.filled_size_base = trade.filled_size_quote / trade.average_price if trade.average_price else 0
                trade.status = TradeStatus.FILLED

                if self.memory:
                    base_asset = signal.pair.split("/")[0]
                    await self.memory.set_entry_price(base_asset, trade.average_price)

            else:  # SELL
                base_asset = signal.pair.split("/")[0]
                position_amount = balance.get(base_asset, 0)

                if position_amount <= 0:
                    trade.status = TradeStatus.REJECTED
                    trade.error_message = f"No {base_asset} to sell"
                    return trade

                trade.requested_size_base = position_amount

                logger.info(f"Executing MARKET SELL: {signal.pair} - {position_amount:.8f}")
                result = await self.exchange.market_sell(signal.pair, position_amount)

                trade.exchange_order_id = self._extract_order_id(result)
                trade.filled_size_base = position_amount
                trade.average_price = result.get("price", 0) or await self._get_price(signal.pair)
                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED

                if self.memory:
                    entry_price = await self.memory.get_entry_price(base_asset)
                    if entry_price:
                        trade.entry_price = entry_price
                        trade.exit_price = trade.average_price
                        trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base

            if self.memory and trade.is_successful:
                await self.memory.record_trade(trade)

        except Exception as e:
            trade.status = TradeStatus.FAILED
            trade.error_message = str(e)
            logger.error(f"Market order failed: {e}")

        return trade

    async def _wait_for_fill(self, order_id: str, pair: str) -> dict:
        """
        Poll order status until filled or timeout.

        Returns:
            {"status": "filled"|"partial"|"pending", ...}
        """
        start = datetime.now(timezone.utc)

        while True:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()

            if elapsed >= self.limit_timeout:
                return {"status": "pending"}

            try:
                # Check order status (exchange-specific)
                status = await self._get_order_status(order_id, pair)

                if status.get("status") in ("closed", "filled", "FILLED"):
                    return {
                        "status": "filled",
                        "filled_base": float(status.get("filled_base", 0) or status.get("vol_exec", 0)),
                        "filled_quote": float(status.get("filled_quote", 0) or status.get("cost", 0)),
                        "average_price": status.get("price", 0)
                    }
                elif float(status.get("filled_base", 0) or status.get("vol_exec", 0)) > 0:
                    return {
                        "status": "partial",
                        "filled_base": float(status.get("filled_base", 0) or status.get("vol_exec", 0)),
                        "filled_quote": float(status.get("filled_quote", 0) or status.get("cost", 0)),
                        "average_price": status.get("price", 0),
                        "remaining": float(status.get("vol", 0) or 0) - float(status.get("filled_base", 0) or status.get("vol_exec", 0))
                    }

            except Exception as e:
                logger.debug(f"Order status check failed: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _get_order_status(self, order_id: str, pair: str) -> dict:
        """Get order status from exchange"""
        # This would call exchange.query_orders() or similar
        # For now, return pending (exchange-specific implementation needed)
        if hasattr(self.exchange, 'query_order'):
            return await self.exchange.query_order(order_id)
        return {"status": "pending"}

    async def _cancel_order(self, order_id: str, pair: str) -> bool:
        """Cancel an open order"""
        if hasattr(self.exchange, 'cancel_order'):
            await self.exchange.cancel_order(order_id)
            return True
        return False

    async def _market_order_remainder(
        self,
        signal,
        filled: dict,
        available_quote: float,
        balance: Dict
    ) -> Trade:
        """Market order the unfilled remainder of a partial fill"""

        trade = Trade(
            pair=signal.pair,
            action=signal.action,
            order_type=OrderType.MARKET,
            reasoning="Remainder after partial limit fill"
        )

        try:
            if signal.action == TradeAction.BUY:
                filled_quote = filled.get("filled_quote", 0)
                total_quote = available_quote * signal.size_pct
                remainder = total_quote - filled_quote

                if remainder < 10:
                    trade.status = TradeStatus.REJECTED
                    return trade

                result = await self.exchange.market_buy(signal.pair, remainder)
                trade.filled_size_quote = remainder
                trade.average_price = result.get("price", 0)
                trade.filled_size_base = remainder / trade.average_price if trade.average_price else 0
                trade.status = TradeStatus.FILLED

            else:  # SELL
                remaining = filled.get("remaining", 0)

                if remaining <= 0:
                    trade.status = TradeStatus.REJECTED
                    return trade

                result = await self.exchange.market_sell(signal.pair, remaining)
                trade.filled_size_base = remaining
                trade.average_price = result.get("price", 0)
                trade.filled_size_quote = remaining * trade.average_price
                trade.status = TradeStatus.FILLED

        except Exception as e:
            trade.status = TradeStatus.FAILED
            trade.error_message = str(e)

        return trade

    async def _get_price(self, pair: str) -> float:
        """Get current price"""
        try:
            ticker = await self.exchange.get_ticker(pair)
            return ticker.get("price", 0)
        except:
            return 0

    def _extract_order_id(self, result: dict) -> Optional[str]:
        """Extract order ID from exchange response (supports both Binance and Kraken formats)"""
        # Prefer normalized order_id, fall back to Kraken's txid
        order_id = result.get("order_id")
        if order_id:
            return str(order_id)
        txid = result.get("txid")
        if isinstance(txid, list):
            return txid[0] if txid else None
        return txid

    async def cancel_all(self) -> bool:
        """Cancel all pending orders"""
        success = True

        for order_id, info in list(self._pending_orders.items()):
            try:
                await self._cancel_order(order_id, info.get("pair", ""))
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")
                success = False

        self._pending_orders.clear()
        return success

    async def execute_stop_loss(self, trades: List[Trade]) -> ExecutionReport:
        """Execute stop-loss trades (always market orders)"""
        results = []

        for trade in trades:
            try:
                result = await self.exchange.market_sell(
                    trade.pair,
                    trade.requested_size_base
                )

                trade.exchange_order_id = self._extract_order_id(result)
                trade.filled_size_base = trade.requested_size_base
                trade.average_price = result.get("price", 0) or await self._get_price(trade.pair)
                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED
                trade.order_type = OrderType.MARKET

                if trade.entry_price:
                    trade.exit_price = trade.average_price
                    trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base

                logger.info(
                    f"{trade.order_type.value} executed: {trade.pair} @ ${trade.average_price:,.2f} "
                    f"(P&L: ${trade.realized_pnl:+,.2f})"
                )

                # Clear peak price tracking for closed position
                if self.memory and trade.is_successful and hasattr(self.memory, 'clear_peak_price'):
                    base_asset = trade.pair.split("/")[0]
                    await self.memory.clear_peak_price(base_asset)

            except Exception as e:
                trade.status = TradeStatus.FAILED
                trade.error_message = str(e)
                logger.error(f"Stop-loss execution failed: {e}")

            results.append(trade)

        return ExecutionReport(plan_id="stop_loss", trades=results)

    def get_stats(self) -> dict:
        """Get execution statistics"""
        fill_rate = (
            self.stats.limit_fills / self.stats.limit_orders
            if self.stats.limit_orders > 0 else None
        )
        avg_slippage = (
            self.stats.total_slippage / self.stats.total_orders
            if self.stats.total_orders > 0 else None
        )
        market_fallbacks = self.stats.limit_timeouts + self.stats.partial_fills

        return {
            "total_orders": self.stats.total_orders,
            "limit_orders": self.stats.limit_orders,
            "market_orders": self.stats.market_orders,
            "limit_fills": self.stats.limit_fills,
            "limit_timeouts": self.stats.limit_timeouts,
            "partial_fills": self.stats.partial_fills,
            # Dashboard-friendly format
            "fill_rate": fill_rate,
            "avg_slippage": avg_slippage,
            "market_fallbacks": market_fallbacks
        }
