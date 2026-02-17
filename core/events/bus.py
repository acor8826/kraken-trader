"""
Event System

Pub/sub event bus with optional PostgreSQL persistence.
Enables Stage 2+ event-driven architecture while being optional in Stage 1.

Features:
- Async event publishing
- Multiple subscribers per event type
- Optional PostgreSQL persistence
- Event history with filtering
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Callable, Any, Optional, TYPE_CHECKING
from enum import Enum
import asyncio
import logging
import json

if TYPE_CHECKING:
    from memory.postgres import PostgresStore

logger = logging.getLogger(__name__)


class EventType(Enum):
    """System event types"""
    # Lifecycle
    SYSTEM_START = "system.start"
    SYSTEM_STOP = "system.stop"
    CYCLE_START = "cycle.start"
    CYCLE_END = "cycle.end"
    
    # Market
    MARKET_DATA_UPDATED = "market.data.updated"
    PRICE_ALERT = "market.price.alert"
    
    # Analysis
    ANALYST_SIGNAL = "analyst.signal"
    INTEL_FUSED = "intel.fused"
    
    # Trading
    PLAN_CREATED = "trading.plan.created"
    PLAN_VALIDATED = "trading.plan.validated"
    TRADE_EXECUTED = "trading.trade.executed"
    TRADE_FAILED = "trading.trade.failed"
    
    # Risk
    STOP_LOSS_TRIGGERED = "risk.stop_loss.triggered"
    RISK_LIMIT_REACHED = "risk.limit.reached"
    EMERGENCY_STOP = "risk.emergency_stop"
    
    # Portfolio
    PORTFOLIO_UPDATED = "portfolio.updated"
    TARGET_REACHED = "portfolio.target.reached"


@dataclass
class Event:
    """
    A system event.
    """
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp.isoformat()
        }


class EventBus:
    """
    Async event bus with optional PostgreSQL persistence.

    Usage:
        bus = EventBus()

        # Subscribe
        async def on_trade(event: Event):
            print(f"Trade executed: {event.data}")

        bus.subscribe(EventType.TRADE_EXECUTED, on_trade)

        # Publish
        await bus.publish(Event(
            type=EventType.TRADE_EXECUTED,
            data={"pair": "BTC/AUD", "amount": 100}
        ))

        # With persistence
        bus = EventBus(persist=True, store=postgres_store)
    """

    def __init__(
        self,
        persist: bool = False,
        store: Optional["PostgresStore"] = None,
        max_history: int = 1000
    ):
        """
        Initialize EventBus.

        Args:
            persist: Whether to persist events to PostgreSQL
            store: PostgresStore instance for persistence
            max_history: Max events to keep in memory
        """
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._history: List[Event] = []
        self._max_history = max_history
        self._persist = persist and store is not None
        self._store = store
        self._pending_persists: List[Event] = []
        self._persist_task: Optional[asyncio.Task] = None

        if self._persist:
            logger.info("EventBus initialized with PostgreSQL persistence")
        else:
            logger.info("EventBus initialized (in-memory only)")

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Subscribe to an event type"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type.value}")

    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """Unsubscribe from an event type"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
            except ValueError:
                pass

    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.

        Events are:
        1. Added to in-memory history
        2. Persisted to PostgreSQL (if enabled, async/non-blocking)
        3. Dispatched to all subscribers
        """
        logger.debug(f"Publishing event: {event.type.value}")

        # Store in memory history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Persist to database (async, non-blocking)
        if self._persist and self._store:
            asyncio.create_task(self._persist_event(event))

        # Notify subscribers (async)
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Error in event handler {handler.__name__}: {e}")

    async def _persist_event(self, event: Event) -> None:
        """Persist event to PostgreSQL"""
        try:
            await self._store.record_event(
                event_type=event.type.value,
                source=event.source,
                data=event.data
            )
        except Exception as e:
            logger.error(f"Failed to persist event {event.type.value}: {e}")
            # Don't raise - persistence failure shouldn't break main flow

    async def emit(
        self,
        event_type: EventType,
        data: Dict[str, Any] = None,
        source: str = "system"
    ) -> None:
        """
        Convenience method to create and publish an event.

        Args:
            event_type: Type of event
            data: Event payload
            source: Event source identifier
        """
        event = Event(
            type=event_type,
            data=data or {},
            source=source
        )
        await self.publish(event)

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        limit: int = 100
    ) -> List[Event]:
        """Get event history from memory"""
        if event_type:
            events = [e for e in self._history if e.type == event_type]
        else:
            events = self._history
        return events[-limit:]

    async def get_persisted_events(
        self,
        event_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get events from PostgreSQL (if persistence enabled)"""
        if not self._persist or not self._store:
            return []

        try:
            # This would query the events table
            # For now, return empty (would need PostgresStore method)
            return []
        except Exception as e:
            logger.error(f"Failed to get persisted events: {e}")
            return []

    def subscriber_count(self, event_type: Optional[EventType] = None) -> int:
        """Get number of subscribers"""
        if event_type:
            return len(self._subscribers.get(event_type, []))
        return sum(len(handlers) for handlers in self._subscribers.values())

    def clear_history(self) -> None:
        """Clear in-memory event history"""
        self._history.clear()
        logger.debug("Event history cleared")


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus(
    persist: bool = False,
    store: Optional["PostgresStore"] = None
) -> EventBus:
    """
    Get or create global event bus.

    Args:
        persist: Enable PostgreSQL persistence
        store: PostgresStore instance (required if persist=True)

    Returns:
        Global EventBus instance
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus(persist=persist, store=store)
    return _event_bus


def reset_event_bus() -> None:
    """Reset global event bus (for testing)"""
    global _event_bus
    _event_bus = None
