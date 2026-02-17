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
        self._intel_history: List[MarketIntel] = []
        
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
    
    async def set_entry_price(self, symbol: str, price: float) -> None:
        """Record entry price for a position"""
        self._entry_prices[symbol] = price
        logger.debug(f"Set entry price for {symbol}: ${price:,.2f}")
    
    async def clear_entry_price(self, symbol: str) -> None:
        """Clear entry price (position closed)"""
        if symbol in self._entry_prices:
            del self._entry_prices[symbol]
    
    async def get_performance_summary(self) -> Dict:
        """Get trading performance summary"""
        if not self._trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0
            }
        
        winning = [t for t in self._trades if t.realized_pnl and t.realized_pnl > 0]
        losing = [t for t in self._trades if t.realized_pnl and t.realized_pnl < 0]
        total_pnl = sum(t.realized_pnl or 0 for t in self._trades)
        
        return {
            "total_trades": len(self._trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "total_pnl": total_pnl,
            "win_rate": len(winning) / len(self._trades) if self._trades else 0
        }
