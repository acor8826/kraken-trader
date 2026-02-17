"""
Alert Manager

Centralized alerting system for trade notifications and threshold alerts.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from collections import deque

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of alerts"""
    TRADE_EXECUTED = "trade_executed"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TARGET_REACHED = "target_reached"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    CIRCUIT_BREAKER = "circuit_breaker"
    PORTFOLIO_MILESTONE = "portfolio_milestone"
    SYSTEM = "system"
    ERROR = "error"


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Alert data structure"""
    type: AlertType
    level: AlertLevel
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "type": self.type.value,
            "level": self.level.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data or {}
        }

    def format_message(self) -> str:
        """Format alert for display"""
        level_emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.CRITICAL: "🚨"
        }
        emoji = level_emoji.get(self.level, "")
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"{emoji} [{self.level.value.upper()}] {time_str} - {self.message}"


class AlertManager:
    """
    Manages alert dispatching across multiple channels.

    Supports:
    - Console logging
    - Webhook (Discord/Slack)
    - File logging
    """

    def __init__(
        self,
        channels: List["AlertChannel"] = None,
        max_history: int = 1000
    ):
        self.channels = channels or []
        self.alert_history: deque = deque(maxlen=max_history)
        self._lock = asyncio.Lock()
        self._enabled = True
        logger.info(f"AlertManager initialized with {len(self.channels)} channels")

    def add_channel(self, channel: "AlertChannel") -> None:
        """Add an alert channel"""
        self.channels.append(channel)
        logger.info(f"Added alert channel: {channel.name}")

    def remove_channel(self, channel_name: str) -> bool:
        """Remove a channel by name"""
        for i, ch in enumerate(self.channels):
            if ch.name == channel_name:
                self.channels.pop(i)
                logger.info(f"Removed alert channel: {channel_name}")
                return True
        return False

    async def send(self, alert: Alert) -> None:
        """Send alert to all channels"""
        if not self._enabled:
            return

        async with self._lock:
            self.alert_history.append(alert)

        # Send to all channels concurrently
        tasks = [channel.send(alert) for channel in self.channels]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Channel {self.channels[i].name} failed: {result}")

    async def trade_executed(
        self,
        pair: str,
        action: str,
        price: float,
        amount: float,
        pnl: Optional[float] = None
    ) -> None:
        """Alert on trade execution"""
        pnl_str = f", P&L: ${pnl:.2f}" if pnl is not None else ""
        message = f"Trade Executed: {action.upper()} {amount:.6f} {pair} @ ${price:.2f}{pnl_str}"

        alert = Alert(
            type=AlertType.TRADE_EXECUTED,
            level=AlertLevel.INFO,
            message=message,
            data={
                "pair": pair,
                "action": action,
                "price": price,
                "amount": amount,
                "pnl": pnl
            }
        )
        await self.send(alert)

    async def stop_loss_triggered(
        self,
        pair: str,
        entry_price: float,
        exit_price: float,
        loss_pct: float
    ) -> None:
        """Alert on stop-loss trigger"""
        message = f"Stop-Loss Triggered: {pair} exited at ${exit_price:.2f} (entry: ${entry_price:.2f}, loss: {loss_pct:.1%})"

        alert = Alert(
            type=AlertType.STOP_LOSS_TRIGGERED,
            level=AlertLevel.WARNING,
            message=message,
            data={
                "pair": pair,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "loss_pct": loss_pct
            }
        )
        await self.send(alert)

    async def target_reached(
        self,
        pair: str,
        entry_price: float,
        exit_price: float,
        profit_pct: float
    ) -> None:
        """Alert on profit target reached"""
        message = f"Target Reached: {pair} closed at ${exit_price:.2f} (entry: ${entry_price:.2f}, profit: {profit_pct:.1%})"

        alert = Alert(
            type=AlertType.TARGET_REACHED,
            level=AlertLevel.INFO,
            message=message,
            data={
                "pair": pair,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "profit_pct": profit_pct
            }
        )
        await self.send(alert)

    async def daily_loss_limit(
        self,
        current_loss_pct: float,
        limit_pct: float
    ) -> None:
        """Alert on daily loss limit breach"""
        message = f"Daily Loss Limit Hit: Down {current_loss_pct:.1%} (limit: {limit_pct:.1%}). Trading paused."

        alert = Alert(
            type=AlertType.DAILY_LOSS_LIMIT,
            level=AlertLevel.CRITICAL,
            message=message,
            data={
                "current_loss_pct": current_loss_pct,
                "limit_pct": limit_pct
            }
        )
        await self.send(alert)

    async def circuit_breaker_activated(
        self,
        breaker_name: str,
        reason: str
    ) -> None:
        """Alert on circuit breaker activation"""
        message = f"Circuit Breaker Activated: {breaker_name} - {reason}"

        alert = Alert(
            type=AlertType.CIRCUIT_BREAKER,
            level=AlertLevel.CRITICAL,
            message=message,
            data={
                "breaker_name": breaker_name,
                "reason": reason
            }
        )
        await self.send(alert)

    async def portfolio_milestone(
        self,
        current_value: float,
        target_value: float,
        progress_pct: float
    ) -> None:
        """Alert on portfolio milestone (every 10% towards target)"""
        message = f"Portfolio Milestone: ${current_value:.2f} ({progress_pct:.0%} of ${target_value:.2f} target)"

        alert = Alert(
            type=AlertType.PORTFOLIO_MILESTONE,
            level=AlertLevel.INFO,
            message=message,
            data={
                "current_value": current_value,
                "target_value": target_value,
                "progress_pct": progress_pct
            }
        )
        await self.send(alert)

    async def system_alert(
        self,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a system alert"""
        alert = Alert(
            type=AlertType.SYSTEM,
            level=level,
            message=message,
            data=data
        )
        await self.send(alert)

    async def error_alert(
        self,
        error: str,
        context: Optional[str] = None
    ) -> None:
        """Send an error alert"""
        message = f"Error: {error}"
        if context:
            message += f" (Context: {context})"

        alert = Alert(
            type=AlertType.ERROR,
            level=AlertLevel.CRITICAL,
            message=message,
            data={
                "error": error,
                "context": context
            }
        )
        await self.send(alert)

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts"""
        alerts = list(self.alert_history)[-limit:]
        return [a.to_dict() for a in reversed(alerts)]

    def get_config(self) -> Dict[str, Any]:
        """Get alert configuration"""
        return {
            "enabled": self._enabled,
            "channels": [
                {
                    "name": ch.name,
                    "type": ch.__class__.__name__,
                    "enabled": ch.enabled
                }
                for ch in self.channels
            ],
            "history_size": len(self.alert_history),
            "max_history": self.alert_history.maxlen
        }

    def enable(self) -> None:
        """Enable alerting"""
        self._enabled = True
        logger.info("Alerting enabled")

    def disable(self) -> None:
        """Disable alerting"""
        self._enabled = False
        logger.info("Alerting disabled")


# Import channel for type hints (avoid circular import)
from core.alerts.channels import AlertChannel
