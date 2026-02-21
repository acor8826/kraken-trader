"""
Trade Journal Module

Logs every trade decision with full context for learning and review.
Enables self-reflection by capturing reasoning, signals, and outcomes.
"""

import logging
import json
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class TradeJournalEntry:
    """Complete record of a trade decision with full context."""

    # Identification
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pair: str = ""
    cycle_number: int = 0

    # Market Context
    market_data: Dict = field(default_factory=dict)  # Price, OHLCV, indicators
    portfolio_state: Dict = field(default_factory=dict)  # Holdings, available, P&L

    # Analyst Signals (full reasoning captured)
    analyst_signals: List[Dict] = field(default_factory=list)
    # Example: {"source": "technical", "direction": 0.45, "confidence": 0.72,
    #           "reasoning": "RSI oversold (28), SMA12 > SMA24..."}

    # Fusion Result
    fused_direction: float = 0.0
    fused_confidence: float = 0.0
    disagreement: float = 0.0
    regime: str = "UNKNOWN"

    # Strategist Decision
    strategist_action: str = "HOLD"  # BUY/SELL/HOLD
    strategist_confidence: float = 0.0
    strategist_reasoning: str = ""
    strategist_strategy: str = ""
    strategist_key_factors: List[str] = field(default_factory=list)
    strategist_risks: List[str] = field(default_factory=list)

    # Sentinel Validation
    sentinel_approved: bool = True
    sentinel_rejection_reason: Optional[str] = None
    sentinel_modifications: List[str] = field(default_factory=list)

    # Execution
    executed: bool = False
    execution_price: Optional[float] = None
    execution_size_base: Optional[float] = None
    execution_size_quote: Optional[float] = None
    slippage_pct: Optional[float] = None

    # Outcome (filled later by outcome tracker)
    outcome_tracked: bool = False
    price_1h_after: Optional[float] = None
    price_4h_after: Optional[float] = None
    price_24h_after: Optional[float] = None
    actual_pnl: Optional[float] = None
    actual_pnl_pct: Optional[float] = None
    outcome_correct: Optional[bool] = None  # Did direction prediction match?

    # Learning Tags (filled by reflection agent)
    tags: List[str] = field(default_factory=list)
    reflection_notes: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict) -> "TradeJournalEntry":
        """Create from dictionary."""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    def get_outcome_summary(self) -> str:
        """Get human-readable outcome summary."""
        if not self.outcome_tracked:
            return "Pending"

        if self.outcome_correct is True:
            return f"Correct (+{self.actual_pnl_pct:.1%})" if self.actual_pnl_pct else "Correct"
        elif self.outcome_correct is False:
            return f"Incorrect ({self.actual_pnl_pct:+.1%})" if self.actual_pnl_pct else "Incorrect"
        else:
            return "Neutral"


class ITradeJournal(ABC):
    """Interface for trade journal storage."""

    @abstractmethod
    async def record_decision(self, entry: TradeJournalEntry) -> str:
        """Record a trade decision with full context."""
        pass

    @abstractmethod
    async def update_outcome(self, entry_id: str, outcome: Dict) -> None:
        """Update entry with actual outcome (price movement, P&L)."""
        pass

    @abstractmethod
    async def get_entry(self, entry_id: str) -> Optional[TradeJournalEntry]:
        """Get a specific journal entry."""
        pass

    @abstractmethod
    async def get_entries(
        self,
        pair: Optional[str] = None,
        action: Optional[str] = None,
        outcome: Optional[str] = None,  # "win" | "loss" | "pending"
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[TradeJournalEntry]:
        """Query journal entries with filters."""
        pass

    @abstractmethod
    async def get_pending_outcomes(self) -> List[TradeJournalEntry]:
        """Get entries that need outcome tracking."""
        pass

    @abstractmethod
    async def get_summary_stats(self, days: int = 30) -> Dict:
        """Get aggregated statistics for reflection."""
        pass


class InMemoryTradeJournal(ITradeJournal):
    """In-memory implementation of trade journal."""

    def __init__(self, max_entries: int = 10000):
        self._entries: Dict[str, TradeJournalEntry] = {}
        self._max_entries = max_entries

    async def record_decision(self, entry: TradeJournalEntry) -> str:
        """Record a trade decision."""
        self._entries[entry.id] = entry

        # Prune old entries if needed
        if len(self._entries) > self._max_entries:
            # Remove oldest 10%
            sorted_entries = sorted(
                self._entries.items(),
                key=lambda x: x[1].timestamp
            )
            to_remove = len(self._entries) - int(self._max_entries * 0.9)
            for entry_id, _ in sorted_entries[:to_remove]:
                del self._entries[entry_id]

        logger.info(f"[JOURNAL] Recorded decision {entry.id[:8]} for {entry.pair}: {entry.strategist_action}")
        return entry.id

    async def update_outcome(self, entry_id: str, outcome: Dict) -> None:
        """Update entry with outcome data."""
        if entry_id not in self._entries:
            logger.warning(f"[JOURNAL] Entry {entry_id} not found for outcome update")
            return

        entry = self._entries[entry_id]

        # Update fields
        for key, value in outcome.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        entry.outcome_tracked = True
        logger.info(f"[JOURNAL] Updated outcome for {entry_id[:8]}: {entry.get_outcome_summary()}")

    async def get_entry(self, entry_id: str) -> Optional[TradeJournalEntry]:
        """Get a specific entry."""
        return self._entries.get(entry_id)

    async def get_entries(
        self,
        pair: Optional[str] = None,
        action: Optional[str] = None,
        outcome: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[TradeJournalEntry]:
        """Query entries with filters."""
        entries = list(self._entries.values())

        # Apply filters
        if pair:
            entries = [e for e in entries if e.pair == pair]

        if action:
            entries = [e for e in entries if e.strategist_action == action]

        if outcome:
            if outcome == "win":
                entries = [e for e in entries if e.actual_pnl and e.actual_pnl > 0]
            elif outcome == "loss":
                entries = [e for e in entries if e.actual_pnl and e.actual_pnl < 0]
            elif outcome == "pending":
                entries = [e for e in entries if not e.outcome_tracked]

        if start_date:
            entries = [e for e in entries if e.timestamp >= start_date]

        if end_date:
            entries = [e for e in entries if e.timestamp <= end_date]

        # Sort by timestamp descending
        entries.sort(key=lambda x: x.timestamp, reverse=True)

        return entries[:limit]

    async def get_pending_outcomes(self) -> List[TradeJournalEntry]:
        """Get entries needing outcome tracking."""
        now = datetime.now(timezone.utc)
        pending = []

        for entry in self._entries.values():
            if entry.executed and not entry.outcome_tracked:
                # Check if enough time has passed
                age_hours = (now - entry.timestamp).total_seconds() / 3600
                if age_hours >= 1:  # At least 1 hour old
                    pending.append(entry)

        return pending

    async def get_summary_stats(self, days: int = 30) -> Dict:
        """Get aggregated statistics."""
        cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)

        entries = [e for e in self._entries.values() if e.timestamp >= cutoff]
        executed = [e for e in entries if e.executed]
        tracked = [e for e in executed if e.outcome_tracked]
        wins = [e for e in tracked if e.actual_pnl and e.actual_pnl > 0]
        losses = [e for e in tracked if e.actual_pnl and e.actual_pnl < 0]

        total_pnl = sum(e.actual_pnl or 0 for e in tracked)
        win_rate = len(wins) / len(tracked) if tracked else 0

        # Average win/loss
        avg_win = sum(e.actual_pnl for e in wins) / len(wins) if wins else 0
        avg_loss = sum(e.actual_pnl for e in losses) / len(losses) if losses else 0

        # Profit factor
        gross_profit = sum(e.actual_pnl for e in wins) if wins else 0
        gross_loss = abs(sum(e.actual_pnl for e in losses)) if losses else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # By action
        buys = [e for e in executed if e.strategist_action == "BUY"]
        sells = [e for e in executed if e.strategist_action == "SELL"]
        holds = [e for e in entries if e.strategist_action == "HOLD"]

        # By pair
        pairs = {}
        for e in executed:
            if e.pair not in pairs:
                pairs[e.pair] = {"count": 0, "wins": 0, "pnl": 0}
            pairs[e.pair]["count"] += 1
            if e.outcome_correct:
                pairs[e.pair]["wins"] += 1
            pairs[e.pair]["pnl"] += e.actual_pnl or 0

        return {
            "period_days": days,
            "total_decisions": len(entries),
            "executed_trades": len(executed),
            "tracked_outcomes": len(tracked),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor if profit_factor != float("inf") else None,
            "by_action": {
                "buy": len(buys),
                "sell": len(sells),
                "hold": len(holds)
            },
            "by_pair": pairs
        }

    async def add_tag(self, entry_id: str, tag: str) -> None:
        """Add a learning tag to an entry."""
        if entry_id in self._entries:
            entry = self._entries[entry_id]
            if tag not in entry.tags:
                entry.tags.append(tag)

    async def add_reflection_note(self, entry_id: str, note: str) -> None:
        """Add reflection notes to an entry."""
        if entry_id in self._entries:
            self._entries[entry_id].reflection_notes = note


def create_journal_entry(
    pair: str,
    cycle_number: int,
    market_data: Dict,
    portfolio_state: Dict,
    analyst_signals: List[Dict],
    fused_direction: float,
    fused_confidence: float,
    disagreement: float = 0.0,
    regime: str = "UNKNOWN"
) -> TradeJournalEntry:
    """
    Helper function to create a journal entry with common fields.

    Called before strategist decision is made, then updated after.
    """
    return TradeJournalEntry(
        pair=pair,
        cycle_number=cycle_number,
        market_data=market_data,
        portfolio_state=portfolio_state,
        analyst_signals=analyst_signals,
        fused_direction=fused_direction,
        fused_confidence=fused_confidence,
        disagreement=disagreement,
        regime=regime
    )
