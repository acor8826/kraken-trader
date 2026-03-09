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
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

from core.interfaces import IExecutor, IExchange
from core.models import TradingPlan, ExecutionReport, Trade, TradeAction, TradeStatus, OrderType
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
        """
        trades = []

        # Get actual available balance
        balance = await self.exchange.get_balance()
        quote_currency = "USDT"
        available_quote = balance.get(quote_currency, 0)

        for signal in plan.signals:
            if signal.action == TradeAction.HOLD:
                continue

            try:
                ticker = await self.exchange.get_ticker(signal.pair)
                current_price = ticker["price"]

                # Calculate real order value from available balance
                order_value = signal.size_pct * available_quote

                is_volatile = await self._check_volatility(signal.pair)
                strategy = self._select_strategy(order_value, is_volatile, signal)

                logger.info(f"[{signal.pair}] Executing {signal.action.value} "
                           f"via {strategy.method}: {strategy.reason}")

                result = await self._execute_with_strategy(
                    signal, strategy, available_quote
                )

                self.stats["total_orders"] += 1

                # Check for exchange errors
                if result.get("error"):
                    trades.append(Trade(
                        pair=signal.pair,
                        action=signal.action,
                        status=TradeStatus.FAILED,
                        error_message=result["error"],
                        signal_confidence=signal.confidence,
                        reasoning=signal.reasoning,
                    ))
                    continue

                # Extract fill data from exchange result
                fill_price = result.get("price", current_price)
                fill_base = result.get("volume", 0.0)
                fill_quote = result.get("cost", fill_base * fill_price)

                trade = Trade(
                    pair=result.get("pair", signal.pair),
                    action=signal.action,
                    status=TradeStatus.FILLED if result.get("status") == "filled" else TradeStatus.FAILED,
                    average_price=fill_price,
                    exchange_order_id=result.get("order_id") or result.get("txid"),
                    filled_size_quote=fill_quote,
                    filled_size_base=fill_base,
                    signal_confidence=signal.confidence,
                    reasoning=signal.reasoning,
                )
                trades.append(trade)

                # Update available balance for subsequent signals
                if trade.is_successful and signal.action == TradeAction.BUY:
                    available_quote -= fill_quote

            except Exception as e:
                logger.error(f"Execution failed for {signal.pair}: {e}")
                trades.append(Trade(
                    pair=signal.pair,
                    action=signal.action,
                    status=TradeStatus.FAILED,
                    error_message=str(e),
                    signal_confidence=signal.confidence,
                    reasoning=signal.reasoning,
                ))

        return ExecutionReport(
            plan_id=plan.id,
            trades=trades
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
        strategy: ExecutionStrategy,
        available_quote: float = 0
    ) -> Dict:
        """Execute order with selected strategy"""
        pair = signal.pair
        is_buy = signal.action == TradeAction.BUY

        ticker = await self.exchange.get_ticker(pair)
        current_price = ticker["price"]

        if strategy.method == "market":
            return await self._execute_market(pair, signal, is_buy, current_price, available_quote)

        elif strategy.method == "limit":
            return await self._execute_limit(pair, signal, is_buy, current_price, available_quote)

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
        price: float,
        available_quote: float = 0
    ) -> Dict:
        """Execute market order"""
        self.stats["market_orders"] += 1

        if is_buy:
            amount_quote = signal.size_pct * available_quote
            if amount_quote < 5:
                return {"error": f"Order too small: ${amount_quote:.2f}"}
            result = await self.exchange.market_buy(pair, amount_quote)
        else:
            # Get actual position size for sells
            balance = await self.exchange.get_balance()
            base = pair.split("/")[0]
            base_amount = balance.get(base, 0)
            sell_amount = base_amount * signal.size_pct
            if sell_amount <= 0:
                return {"error": f"No {base} to sell"}
            result = await self.exchange.market_sell(pair, sell_amount)

        if result.get("error"):
            return result

        result["status"] = "filled"
        result["strategy"] = "market"
        return result

    async def _execute_limit(
        self,
        pair: str,
        signal,
        is_buy: bool,
        price: float,
        available_quote: float = 0
    ) -> Dict:
        """Execute limit order with timeout and market fallback"""
        self.stats["limit_orders"] += 1

        ticker = await self.exchange.get_ticker(pair)
        spread_buffer = 0.001

        if is_buy:
            limit_price = ticker["ask"] * (1 - spread_buffer)
            amount_quote = signal.size_pct * available_quote
            if amount_quote < 5:
                return {"error": f"Order too small: ${amount_quote:.2f}"}
            result = await self.exchange.limit_buy(pair, amount_quote, limit_price)
        else:
            limit_price = ticker["bid"] * (1 + spread_buffer)
            balance = await self.exchange.get_balance()
            base = pair.split("/")[0]
            sell_amount = balance.get(base, 0) * signal.size_pct
            if sell_amount <= 0:
                return {"error": f"No {base} to sell"}
            result = await self.exchange.limit_sell(pair, sell_amount, limit_price)

        if result.get("error"):
            return result

        result["status"] = "filled"
        result["strategy"] = "limit"
        return result

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

    async def execute_stop_loss(self, trades: List[Trade]) -> ExecutionReport:
        """Execute stop-loss trades via immediate market sell."""
        report = ExecutionReport(plan_id="stop_loss", trades=[])

        for trade in trades:
            try:
                trade.submitted_timestamp = datetime.now(timezone.utc)
                result = await self.exchange.market_sell(
                    trade.pair,
                    trade.requested_size_base
                )
                trade.filled_timestamp = datetime.now(timezone.utc)
                trade.exchange_order_id = result.get("order_id") or (
                    result.get("txid", [None])[0]
                    if isinstance(result.get("txid"), list)
                    else result.get("txid")
                )
                trade.filled_size_base = trade.requested_size_base
                trade.average_price = result.get("price", 0)
                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED

                if trade.entry_price and trade.average_price:
                    trade.exit_price = trade.average_price
                    trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base

                logger.info(
                    f"Stop-loss executed: {trade.pair} @ ${trade.average_price:,.2f} "
                    f"(P&L: ${(trade.realized_pnl or 0):+,.2f})"
                )
                report.trades.append(trade)

            except Exception as e:
                trade.status = TradeStatus.FAILED
                trade.error_message = str(e)
                logger.error(f"Stop-loss failed for {trade.pair}: {e}")
                report.trades.append(trade)

        return report

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
