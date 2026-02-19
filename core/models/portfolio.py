"""
Portfolio Models

Models for portfolio state, positions, and balances.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class Position:
    """
    A position in an asset.
    """
    symbol: str                          # e.g., "BTC"
    amount: float                        # Amount held
    entry_price: Optional[float] = None  # Average entry price
    current_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    estimated_sell_date: Optional[str] = None  # ISO format string
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def value_quote(self) -> float:
        """Current value in quote currency"""
        if self.current_price:
            return self.amount * self.current_price
        return 0.0
    
    @property
    def unrealized_pnl(self) -> Optional[float]:
        """Unrealized P&L in quote currency"""
        if self.entry_price and self.current_price:
            return (self.current_price - self.entry_price) * self.amount
        return None
    
    @property
    def unrealized_pnl_pct(self) -> Optional[float]:
        """Unrealized P&L as percentage"""
        if self.entry_price and self.current_price and self.entry_price > 0:
            return ((self.current_price - self.entry_price) / self.entry_price) * 100
        return None
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "amount": self.amount,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "estimated_sell_date": self.estimated_sell_date,
            "value_quote": self.value_quote,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct
        }


@dataclass
class Portfolio:
    """
    Complete portfolio state.
    """
    quote_currency: str = "USDT"         # Base currency for valuation
    available_quote: float = 0.0         # Available cash
    positions: Dict[str, Position] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Target tracking
    initial_value: float = 1000.0
    target_value: float = 5000.0
    
    @property
    def positions_value(self) -> float:
        """Total value of all positions in quote currency"""
        return sum(p.value_quote for p in self.positions.values())
    
    @property
    def total_value(self) -> float:
        """Total portfolio value in quote currency"""
        return self.available_quote + self.positions_value
    
    @property
    def total_pnl(self) -> float:
        """Total P&L from initial value"""
        return self.total_value - self.initial_value
    
    @property
    def total_pnl_pct(self) -> float:
        """Total P&L as percentage"""
        if self.initial_value > 0:
            return (self.total_pnl / self.initial_value) * 100
        return 0.0
    
    @property
    def progress_to_target(self) -> float:
        """Progress toward target as percentage (0-100+)"""
        if self.target_value > self.initial_value:
            gain_needed = self.target_value - self.initial_value
            gain_achieved = self.total_value - self.initial_value
            return (gain_achieved / gain_needed) * 100
        return 100.0
    
    @property
    def exposure_pct(self) -> float:
        """Percentage of portfolio in positions (not cash)"""
        if self.total_value > 0:
            return (self.positions_value / self.total_value) * 100
        return 0.0
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol"""
        return self.positions.get(symbol)
    
    def has_position(self, symbol: str) -> bool:
        """Check if we have a position in symbol"""
        pos = self.positions.get(symbol)
        return pos is not None and pos.amount > 0
    
    def to_dict(self) -> Dict:
        return {
            "quote_currency": self.quote_currency,
            "available_quote": self.available_quote,
            "positions_value": self.positions_value,
            "total_value": self.total_value,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "progress_to_target": self.progress_to_target,
            "exposure_pct": self.exposure_pct,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "timestamp": self.timestamp.isoformat()
        }
    
    def to_summary(self) -> str:
        """Compact summary for prompts (token-optimized)"""
        positions_summary = ", ".join([
            f"{symbol}: ${pos.value_quote:,.0f} ({pos.unrealized_pnl_pct:+.1f}%)"
            if pos.entry_price else
            f"{symbol}: ${pos.value_quote:,.0f}"
            for symbol, pos in self.positions.items()
        ]) or "None"

        return (
            f"Value: ${self.total_value:,.0f} | Cash: ${self.available_quote:,.0f} | "
            f"Exposure: {self.exposure_pct:.0f}% | P&L: ${self.total_pnl:+,.0f}\n"
            f"Positions: {positions_summary}"
        )


@dataclass
class PerformanceMetrics:
    """
    Trading performance metrics.
    """
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_volume: float = 0.0
    
    # Advanced metrics
    max_drawdown_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    win_rate: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    profit_factor: Optional[float] = None
    
    @property
    def calculated_win_rate(self) -> float:
        if self.total_trades > 0:
            return self.winning_trades / self.total_trades
        return 0.0
    
    def to_dict(self) -> Dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate or self.calculated_win_rate,
            "total_pnl": self.total_pnl,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "profit_factor": self.profit_factor
        }
