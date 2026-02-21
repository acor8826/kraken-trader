"""
Trading Models

Models for trades, trading plans, and execution reports.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid


class TradeAction(Enum):
    """Trade action types"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeStatus(Enum):
    """Trade execution status"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderType(Enum):
    """Order types"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


@dataclass
class TradeSignal:
    """
    A trading signal from the strategist.
    Part of a TradingPlan before execution.
    """
    pair: str
    action: TradeAction
    confidence: float                    # 0.0 to 1.0
    size_pct: float                      # Suggested size as % of available (0.0-1.0)
    reasoning: str
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    
    # Set by Sentinel
    status: TradeStatus = TradeStatus.PENDING
    rejection_reason: Optional[str] = None
    
    def approve(self) -> None:
        self.status = TradeStatus.APPROVED
    
    def reject(self, reason: str) -> None:
        self.status = TradeStatus.REJECTED
        self.rejection_reason = reason
    
    def to_dict(self) -> Dict:
        return {
            "pair": self.pair,
            "action": self.action.value,
            "confidence": self.confidence,
            "size_pct": self.size_pct,
            "reasoning": self.reasoning,
            "order_type": self.order_type.value,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason
        }


@dataclass
class Trade:
    """
    An executed (or attempted) trade.
    Created after execution attempt.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pair: str = ""
    action: TradeAction = TradeAction.HOLD
    order_type: OrderType = OrderType.MARKET
    
    # Requested
    requested_size_quote: Optional[float] = None  # e.g., AUD amount for buys
    requested_size_base: Optional[float] = None   # e.g., BTC amount for sells
    
    # Filled
    filled_size_base: float = 0.0
    filled_size_quote: float = 0.0
    average_price: float = 0.0
    
    # Status
    status: TradeStatus = TradeStatus.PENDING
    exchange_order_id: Optional[str] = None
    error_message: Optional[str] = None
    
    # Metadata
    signal_confidence: float = 0.0
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # For P&L tracking
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    realized_pnl_percent: Optional[float] = None  # P&L as percentage

    # Aliases for analytics compatibility
    @property
    def pnl(self) -> Optional[float]:
        """Alias for realized_pnl"""
        return self.realized_pnl

    @property
    def pnl_percent(self) -> Optional[float]:
        """Alias for realized_pnl_percent"""
        return self.realized_pnl_percent

    @property
    def price(self) -> float:
        """Alias for average_price"""
        return self.average_price

    @property
    def amount(self) -> float:
        """Alias for filled_size_base"""
        return self.filled_size_base

    @property
    def is_successful(self) -> bool:
        return self.status in [TradeStatus.FILLED, TradeStatus.PARTIALLY_FILLED]
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "pair": self.pair,
            "action": self.action.value,
            "order_type": self.order_type.value,
            "filled_size_base": self.filled_size_base,
            "filled_size_quote": self.filled_size_quote,
            "average_price": self.average_price,
            "status": self.status.value,
            "signal_confidence": self.signal_confidence,
            "reasoning": self.reasoning,
            "timestamp": self.timestamp.isoformat(),
            "realized_pnl": self.realized_pnl
        }


@dataclass
class TradingPlan:
    """
    A complete trading plan from the strategist.
    Contains multiple trade signals to be validated and executed.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    signals: List[TradeSignal] = field(default_factory=list)
    strategy_name: str = "unknown"
    regime: str = "unknown"
    overall_confidence: float = 0.0
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def approved_signals(self) -> List[TradeSignal]:
        return [s for s in self.signals if s.status == TradeStatus.APPROVED]
    
    @property
    def rejected_signals(self) -> List[TradeSignal]:
        return [s for s in self.signals if s.status == TradeStatus.REJECTED]
    
    @property
    def actionable_signals(self) -> List[TradeSignal]:
        """Signals that require action (not HOLD)"""
        return [s for s in self.approved_signals if s.action != TradeAction.HOLD]
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "strategy_name": self.strategy_name,
            "regime": self.regime,
            "overall_confidence": self.overall_confidence,
            "reasoning": self.reasoning,
            "signals": [s.to_dict() for s in self.signals],
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ExecutionReport:
    """
    Report of executed trades from a plan.
    """
    plan_id: str
    trades: List[Trade] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def successful_trades(self) -> List[Trade]:
        return [t for t in self.trades if t.is_successful]
    
    @property
    def failed_trades(self) -> List[Trade]:
        return [t for t in self.trades if not t.is_successful]
    
    @property
    def total_volume_quote(self) -> float:
        return sum(t.filled_size_quote for t in self.successful_trades)
    
    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "trades": [t.to_dict() for t in self.trades],
            "successful_count": len(self.successful_trades),
            "failed_count": len(self.failed_trades),
            "total_volume_quote": self.total_volume_quote,
            "timestamp": self.timestamp.isoformat()
        }
