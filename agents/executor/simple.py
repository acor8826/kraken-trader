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
        available_quote = balance.get("AUD", 0)
        
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
            reasoning=signal.reasoning
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
                result = await self.exchange.market_buy(signal.pair, amount_quote)
                
                # Parse result
                trade.exchange_order_id = result.get("order_id") or (result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("txid"))
                trade.filled_size_quote = amount_quote  # Approximate
                trade.average_price = result.get("price", 0) or await self._get_current_price(signal.pair)
                trade.filled_size_base = trade.filled_size_quote / trade.average_price if trade.average_price else 0
                trade.status = TradeStatus.FILLED
                
                # Record entry price for stop-loss tracking
                if self.memory:
                    base_asset = signal.pair.split("/")[0]
                    await self.memory.set_entry_price(base_asset, trade.average_price)
                
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
                result = await self.exchange.market_sell(signal.pair, position_amount)
                
                # Parse result
                trade.exchange_order_id = result.get("order_id") or (result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("txid"))
                trade.filled_size_base = position_amount
                trade.average_price = result.get("price", 0) or await self._get_current_price(signal.pair)
                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED
                
                # Calculate P&L if we have entry price
                if self.memory:
                    entry_price = await self.memory.get_entry_price(base_asset)
                    if entry_price:
                        trade.entry_price = entry_price
                        trade.exit_price = trade.average_price
                        trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base
            
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
                result = await self.exchange.market_sell(
                    trade.pair,
                    trade.requested_size_base
                )
                
                trade.exchange_order_id = result.get("order_id") or (result.get("txid", [None])[0] if isinstance(result.get("txid"), list) else result.get("txid"))
                trade.filled_size_base = trade.requested_size_base
                trade.average_price = result.get("price", 0) or await self._get_current_price(trade.pair)
                trade.filled_size_quote = trade.filled_size_base * trade.average_price
                trade.status = TradeStatus.FILLED
                
                # Calculate P&L
                if trade.entry_price:
                    trade.exit_price = trade.average_price
                    trade.realized_pnl = (trade.exit_price - trade.entry_price) * trade.filled_size_base
                
                logger.info(f"Stop-loss executed: {trade.pair} @ ${trade.average_price:,.2f} "
                           f"(P&L: ${trade.realized_pnl:+,.2f})")
                
            except Exception as e:
                trade.status = TradeStatus.FAILED
                trade.error_message = str(e)
                logger.error(f"Stop-loss execution failed: {e}")
            
            results.append(trade)
        
        return ExecutionReport(plan_id="stop_loss", trades=results)
