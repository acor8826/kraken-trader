"""
Memory System

State management and persistence.
Stage 1: In-memory storage
Stage 2+: PostgreSQL persistence
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone
import logging

from core.interfaces import IMemory
from core.models import Portfolio, Position, Trade, MarketIntel

logger = logging.getLogger(__name__)


class InMemoryStore(IMemory):
    """
    Stage 1 Memory - Simple in-memory storage.
    
    Note: Data is lost on restart. For production use PostgreSQL.
    """
    
    def __init__(self, initial_capital: float = 1000.0):
        self._portfolio = Portfolio(
            available_quote=initial_capital,
            initial_value=initial_capital
        )
        self._trades: List[Trade] = []
        self._entry_prices: Dict[str, float] = {}
        self._position_costs: Dict[str, tuple] = {}  # symbol -> (total_cost, total_amount)
        self._peak_prices: Dict[str, float] = {}
        self._intel_history: List[MarketIntel] = []
        self._stop_loss_cooldowns: Dict[str, datetime] = {}  # symbol -> last stop-loss time

        logger.info(f"In-memory store initialized with ${initial_capital} capital")
    
    async def get_portfolio(self) -> Portfolio:
        """Get current portfolio state"""
        return self._portfolio
    
    async def save_portfolio(self, portfolio: Portfolio) -> None:
        """Save portfolio state"""
        self._portfolio = portfolio
    
    async def record_trade(self, trade: Trade, intel: Optional[MarketIntel] = None) -> None:
        """Record executed trade"""
        self._trades.append(trade)
        
        if intel:
            self._intel_history.append(intel)
        
        logger.debug(f"Recorded trade: {trade.action.value} {trade.pair}")
    
    async def get_trade_history(self, limit: int = 100) -> List[Trade]:
        """Get recent trade history"""
        return self._trades[-limit:]
    
    async def get_entry_price(self, symbol: str) -> Optional[float]:
        """Get entry price for a position"""
        return self._entry_prices.get(symbol)
    
    async def set_entry_price(self, symbol: str, price: float, amount: float = 0) -> None:
        """Record entry price for a position using weighted average cost basis."""
        if amount > 0 and symbol in self._position_costs:
            # Weighted average with existing position
            old_cost, old_amount = self._position_costs[symbol]
            new_cost = old_cost + (price * amount)
            new_amount = old_amount + amount
            avg_price = new_cost / new_amount
            self._position_costs[symbol] = (new_cost, new_amount)
            self._entry_prices[symbol] = avg_price
            logger.debug(f"Updated avg entry for {symbol}: ${avg_price:,.2f} "
                        f"(added {amount} @ ${price:,.2f}, total {new_amount})")
        else:
            # First entry or no amount provided -- use raw price
            self._entry_prices[symbol] = price
            if amount > 0:
                self._position_costs[symbol] = (price * amount, amount)
            logger.debug(f"Set entry price for {symbol}: ${price:,.2f}")

    async def clear_entry_price(self, symbol: str) -> None:
        """Clear entry price and cost tracking (position closed)"""
        self._entry_prices.pop(symbol, None)
        self._position_costs.pop(symbol, None)

    async def record_stop_loss_exit(self, symbol: str) -> None:
        """Record that a stop-loss exit occurred for cooldown tracking"""
        self._stop_loss_cooldowns[symbol] = datetime.now(timezone.utc)
        logger.debug(f"Recorded stop-loss cooldown for {symbol}")

    async def get_stop_loss_time(self, symbol: str) -> Optional[datetime]:
        """Get the last stop-loss exit time for a symbol"""
        return self._stop_loss_cooldowns.get(symbol)
    
    async def get_peak_price(self, symbol: str) -> Optional[float]:
        """Get peak price for a position (for trailing stop)"""
        return self._peak_prices.get(symbol)

    async def set_peak_price(self, symbol: str, price: float) -> None:
        """Record peak price for a position"""
        self._peak_prices[symbol] = price

    async def clear_peak_price(self, symbol: str) -> None:
        """Clear peak price (position closed)"""
        self._peak_prices.pop(symbol, None)

    async def get_performance_summary(self) -> Dict:
        """Get trading performance summary with full metrics."""
        if not self._trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "total_exposure": 0.0,
                "sharpe_ratio": 0.0,
            }

        winning = [t for t in self._trades if t.realized_pnl and t.realized_pnl > 0]
        losing = [t for t in self._trades if t.realized_pnl and t.realized_pnl < 0]
        total_pnl = sum(t.realized_pnl or 0 for t in self._trades)

        # Profit factor
        gross_profit = sum(t.realized_pnl for t in winning) if winning else 0
        gross_loss = abs(sum(t.realized_pnl for t in losing)) if losing else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        # Max drawdown from cumulative PnL curve
        max_drawdown = 0.0
        cumulative = 0.0
        peak = 0.0
        for t in self._trades:
            cumulative += t.realized_pnl or 0
            if cumulative > peak:
                peak = cumulative
            dd = (peak - cumulative) / self._portfolio.initial_value if self._portfolio.initial_value else 0
            if dd > max_drawdown:
                max_drawdown = dd

        # Total exposure: fraction of portfolio currently in positions
        total_value = self._portfolio.total_value or self._portfolio.initial_value or 1
        positions_value = sum(
            pos.amount * (pos.current_price or pos.entry_price or 0)
            for pos in self._portfolio.positions.values()
        )
        total_exposure = positions_value / total_value if total_value > 0 else 0.0

        # Sharpe ratio from trade returns
        returns = [t.realized_pnl / self._portfolio.initial_value for t in self._trades if t.realized_pnl is not None] if self._portfolio.initial_value else []
        if len(returns) >= 2:
            import statistics
            mean_ret = statistics.mean(returns)
            std_ret = statistics.stdev(returns)
            sharpe_ratio = mean_ret / std_ret if std_ret > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        return {
            "total_trades": len(self._trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "total_pnl": total_pnl,
            "win_rate": len(winning) / len(self._trades) if self._trades else 0,
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": round(max_drawdown, 4),
            "total_exposure": round(total_exposure, 4),
            "sharpe_ratio": round(sharpe_ratio, 2),
        }

    async def save_signal(self, signal_data: Dict) -> None:
        """Store signal data (no-op for in-memory, silences learning module errors)."""
        pass
