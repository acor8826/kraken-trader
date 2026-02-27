"""
Executor Agent

Handles trade execution - converts trading plans into actual orders.
"""

from typing import Dict, List, Optional
import logging
from datetime import datetime, timezone

from core.interfaces import IExecutor, IExchange, IMemory
from core.models import (
    TradingPlan, Trade, ExecutionReport,
    TradeAction, TradeStatus, OrderType
)
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SimpleExecutor(IExecutor):
    @staticmethod
    def _extract_fee_quote(result: Dict) -> float:
        """Best-effort fee extraction from exchange response."""
        fee = result.get("fee") or result.get("fees") or result.get("commission") or 0
        if isinstance(fee, (int, float)):
            return float(fee)
        if isinstance(fee, list) and fee:
            first = fee[0]
            if isinstance(first, dict):
                return float(first.get("cost") or first.get("fee") or 0)
            if isinstance(first, (int, float)):
                return float(first)
        if isinstance(fee, dict):
            return float(fee.get("cost") or fee.get("fee") or 0)
        return 0.0

    @staticmethod
    def _apply_latency_metrics(trade: Trade) -> None:
        if trade.decision_timestamp and trade.submitted_timestamp:
            trade.latency_decision_to_submit_ms = (
                (trade.submitted_timestamp - trade.decision_timestamp).total_seconds() * 1000
            )
        if trade.submitted_timestamp and trade.filled_timestamp:
            trade.latency_submit_to_fill_ms = (
                (trade.filled_timestamp - trade.submitted_timestamp).total_seconds() * 1000
            )
        if trade.decision_timestamp and trade.filled_timestamp:
            trade.latency_decision_to_fill_ms = (
                (trade.filled_timestamp - trade.decision_timestamp).total_seconds() * 1000
            )
    """
    Stage 1 Executor - Market orders only.
    
    Simple execution: approved signals → market orders
    """
    
    def __init__(
        self,
        exchange: IExchange,
        memory: IMemory = None,
        settings: Settings = None
    ):
        self.exchange = exchange
        self.memory = memory
        self.settings = settings or get_settings()
    
    async def execute(self, plan: TradingPlan) -> ExecutionReport:
        """
        Execute all approved signals in the plan.
        """
        trades: List[Trade] = []
        
        # Get current balance for position sizing
        balance = await self.exchange.get_balance()
        available_quote = balance.get(self.settings.trading.quote_currency, 0)
        
        for signal in plan.actionable_signals:
            try:
                trade = await self._execute_signal(signal, available_quote, balance)
                trades.append(trade)
                
                # Update available balance
                if trade.is_successful and signal.action == TradeAction.BUY:
                    available_quote -= trade.filled_size_quote
                    
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
        
        report = ExecutionReport(
            plan_id=plan.id,
            trades=trades
        )
        
        # Log summary
        logger.info(f"Execution report: {len(report.successful_trades)} successful, "
                   f"{len(report.failed_trades)} failed, "
                   f"volume=${report.total_volume_quote:,.2f}")
        
        return report
    
    async def _execute_signal(
        self,
        signal,  # TradeSignal
        available_quote: float,
        balance: Dict
    ) -> Trade:
        """Execute a single signal"""
        
        trade = Trade(
            pair=signal.pair,
            action=signal.action,
            order_type=signal.order_type,
            signal_confidence=signal.confidence,
            reasoning=signal.reasoning,
            decision_timestamp=datetime.now(timezone.utc)
        )
        
        try:
            if signal.action == TradeAction.BUY:
                # Calculate buy amount
                amount_quote = available_quote * signal.size_pct
                trade.requested_size_quote = amount_quote
                
                if amount_quote < 10:  # Minimum
                    trade.status = TradeStatus.REJECTED
                    trade.error_message = "Amount too small"
                    return trade
                
                # Execute market buy
                logger.info(f"Executing BUY: {signal.pair} for ${amount_quote:.2f}")
                trade.submitted_timestamp = datetime.now(timezone.utc)
                result = await self.exchange.market_buy(signal.pair, amount_quote)
                trade.filled_timestamp = datetime.now(timezone.utc)
                trade.fees_quote = self._extract_fee_quote(result)

                # Parse result
                trade.exchange_order_id = result.get("order_id") or (result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("txid"))
                trade.filled_size_quote = amount_quote  # Approximate
                trade.average_price = result.get("price") or await self._get_current_price(signal.pair)
                if not trade.average_price or trade.average_price <= 0:
                    trade.status = TradeStatus.FAILED
                    trade.error_message = "Could not determine execution price"
                    return trade
                trade.filled_size_base = trade.filled_size_quote / trade.average_price
                trade.status = TradeStatus.FILLED
                
                # Record entry price for stop-loss tracking (weighted avg)
                if self.memory:
                    base_asset = signal.pair.split("/")[0]
                    await self.memory.set_entry_price(
                        base_asset, trade.average_price, trade.filled_size_base
                    )
                
            elif signal.action == TradeAction.SELL:
                # Get position to sell
                base_asset = signal.pair.split("/")[0]
                position_amount = balance.get(base_asset, 0)
                
                if position_amount <= 0:
                    trade.status = TradeStatus.REJECTED
                    trade.error_message = f"No {base_asset} to sell"
                    return trade
                
                # Sell entire position
                trade.requested_size_base = position_amount
                
                logger.info(f"Executing SELL: {signal.pair} - {position_amount:.8f}")
                trade.submitted_timestamp = datetime.now(timezone.utc)
                result = await self.exchange.market_sell(signal.pair, position_amount)
                trade.filled_timestamp = datetime.now(timezone.utc)
                trade.fees_quote = self._extract_fee_quote(result)

                # Parse result
                trade.exchange_order_id = result.get("order_id") or (result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("txid"))
                trade.filled_size_base = position_amount
                trade.average_price = result.get("price") or await self._get_current_price(signal.pair)
                if not trade.average_price or trade.average_price <= 0:
                    trade.status = TradeStatus.FAILED
                    trade.error_message = "Could not determine sell execution price"
                    return trade
                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED
                
                # Calculate P&L if we have entry price
                if self.memory:
                    entry_price = await self.memory.get_entry_price(base_asset)
                    if entry_price:
                        trade.entry_price = entry_price
                        trade.exit_price = trade.average_price
                        trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base
                        trade.realized_pnl_after_fees = (trade.realized_pnl or 0) - (trade.fees_quote or 0)

                        if hasattr(self.memory, 'record_event') and trade.realized_pnl_after_fees < 0:
                            await self.memory.record_event(
                                event_type="losing_trade_detected",
                                source="executor.simple",
                                data={
                                    "trade_id": trade.id,
                                    "pair": trade.pair,
                                    "entry_price": trade.entry_price,
                                    "exit_price": trade.exit_price,
                                    "filled_size_base": trade.filled_size_base,
                                    "realized_pnl": trade.realized_pnl,
                                    "fees_quote": trade.fees_quote,
                                    "realized_pnl_after_fees": trade.realized_pnl_after_fees,
                                    "timestamp": trade.timestamp.isoformat(),
                                },
                            )
                    # Clear entry price after selling so it doesn't corrupt next trade
                    if hasattr(self.memory, 'clear_entry_price'):
                        await self.memory.clear_entry_price(base_asset)
                    if hasattr(self.memory, 'clear_peak_price'):
                        await self.memory.clear_peak_price(base_asset)

            self._apply_latency_metrics(trade)

            # Record trade
            if self.memory and trade.is_successful:
                await self.memory.record_trade(trade)
            
        except Exception as e:
            trade.status = TradeStatus.FAILED
            trade.error_message = str(e)
            logger.error(f"Trade execution failed: {e}")
        
        return trade
    
    async def _get_current_price(self, pair: str) -> float:
        """Get current price for a pair"""
        try:
            ticker = await self.exchange.get_ticker(pair)
            return ticker.get("price", 0)
        except:
            return 0
    
    async def cancel_all(self) -> bool:
        """Cancel all pending orders"""
        # For market orders, there's nothing to cancel
        # This would be used for limit orders in Stage 2+
        return True
    
    async def execute_stop_loss(self, trades: List[Trade]) -> ExecutionReport:
        """Execute stop-loss trades"""
        results = []
        
        for trade in trades:
            try:
                trade.submitted_timestamp = datetime.now(timezone.utc)
                result = await self.exchange.market_sell(
                    trade.pair,
                    trade.requested_size_base
                )
                trade.filled_timestamp = datetime.now(timezone.utc)
                trade.fees_quote = self._extract_fee_quote(result)

                trade.exchange_order_id = result.get("order_id") or (result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("txid"))
                trade.filled_size_base = trade.requested_size_base
                trade.average_price = result.get("price") or await self._get_current_price(trade.pair)

                if not trade.average_price or trade.average_price <= 0:
                    trade.status = TradeStatus.FAILED
                    trade.error_message = "Could not determine exit price"
                    logger.error(f"Stop-loss for {trade.pair} failed: exit price is 0")
                    results.append(trade)
                    continue

                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED

                # Calculate P&L
                if trade.entry_price:
                    trade.exit_price = trade.average_price
                    trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base
                    trade.realized_pnl_after_fees = (trade.realized_pnl or 0) - (trade.fees_quote or 0)

                self._apply_latency_metrics(trade)

                logger.info(f"{trade.order_type.value} executed: {trade.pair} @ ${trade.average_price:,.2f} "
                           f"(P&L after fees: ${((trade.realized_pnl_after_fees if trade.realized_pnl_after_fees is not None else trade.realized_pnl) or 0):+,.2f})")

                # Persist exit trade so dashboard/history includes SELLs
                if self.memory and trade.is_successful:
                    await self.memory.record_trade(trade)
                    base_asset = trade.pair.split("/")[0]
                    # Clear peak price tracking for closed position
                    if hasattr(self.memory, 'clear_peak_price'):
                        await self.memory.clear_peak_price(base_asset)
                    # Clear entry price so it doesn't corrupt next trade
                    if hasattr(self.memory, 'clear_entry_price'):
                        await self.memory.clear_entry_price(base_asset)
                    # Record stop-loss cooldown to prevent immediate re-entry
                    if trade.order_type == OrderType.STOP_LOSS and hasattr(self.memory, 'record_stop_loss_exit'):
                        await self.memory.record_stop_loss_exit(base_asset)
                
            except Exception as e:
                trade.status = TradeStatus.FAILED
                trade.error_message = str(e)
                logger.error(f"Stop-loss execution failed: {e}")
            
            results.append(trade)
        
        return ExecutionReport(plan_id="stop_loss", trades=results)
