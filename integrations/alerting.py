"""
Alerting Integration

Sends alerts to Slack and Discord webhooks for important trading events.
"""

import logging
import asyncio
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Types of alerts."""
    TRADE_EXECUTED = "trade_executed"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    ANOMALY_DETECTED = "anomaly_detected"
    TARGET_MILESTONE = "target_milestone"
    SYSTEM_ERROR = "system_error"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"


class AlertPriority(Enum):
    """Alert priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Represents an alert to be sent."""

    type: AlertType
    title: str
    message: str
    priority: AlertPriority = AlertPriority.MEDIUM
    data: Dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def emoji(self) -> str:
        """Get emoji for alert type."""
        return {
            AlertType.TRADE_EXECUTED: "💰",
            AlertType.STOP_LOSS_TRIGGERED: "🛑",
            AlertType.CIRCUIT_BREAKER_TRIPPED: "⚡",
            AlertType.ANOMALY_DETECTED: "⚠️",
            AlertType.TARGET_MILESTONE: "🎯",
            AlertType.SYSTEM_ERROR: "🔴",
            AlertType.SYSTEM_START: "🚀",
            AlertType.SYSTEM_STOP: "🛑"
        }.get(self.type, "📢")

    @property
    def color(self) -> str:
        """Get color for alert type (hex for Discord)."""
        return {
            AlertType.TRADE_EXECUTED: "#00ff00",  # Green
            AlertType.STOP_LOSS_TRIGGERED: "#ff6600",  # Orange
            AlertType.CIRCUIT_BREAKER_TRIPPED: "#ff0000",  # Red
            AlertType.ANOMALY_DETECTED: "#ffff00",  # Yellow
            AlertType.TARGET_MILESTONE: "#00ffff",  # Cyan
            AlertType.SYSTEM_ERROR: "#ff0000",  # Red
            AlertType.SYSTEM_START: "#0099ff",  # Blue
            AlertType.SYSTEM_STOP: "#666666"  # Gray
        }.get(self.type, "#ffffff")


class AlertManager:
    """
    Manages alerting to Slack and Discord.

    Features:
    - Webhook-based alerts to Slack and Discord
    - Rate limiting to prevent spam
    - Alert history tracking
    - Priority-based formatting
    """

    # Rate limiting: 1 alert per type per 5 minutes
    RATE_LIMIT_SECONDS = 300
    MAX_HISTORY = 100

    def __init__(
        self,
        slack_webhook_url: Optional[str] = None,
        discord_webhook_url: Optional[str] = None
    ):
        """
        Initialize alert manager.

        Args:
            slack_webhook_url: Slack webhook URL (or env var SLACK_WEBHOOK_URL)
            discord_webhook_url: Discord webhook URL (or env var DISCORD_WEBHOOK_URL)
        """
        self.slack_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.discord_url = discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL")

        self._last_alert_times: Dict[str, datetime] = {}
        self._alert_history: List[Alert] = []
        self._http_client: Optional[httpx.AsyncClient] = None

        enabled = []
        if self.slack_url:
            enabled.append("Slack")
        if self.discord_url:
            enabled.append("Discord")

        if enabled:
            logger.info(f"AlertManager initialized: {', '.join(enabled)}")
        else:
            logger.warning("AlertManager: No webhooks configured")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _is_rate_limited(self, alert_key: str) -> bool:
        """Check if alert is rate limited."""
        last_time = self._last_alert_times.get(alert_key)
        if not last_time:
            return False

        elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
        return elapsed < self.RATE_LIMIT_SECONDS

    def _update_rate_limit(self, alert_key: str) -> None:
        """Update rate limit timestamp."""
        self._last_alert_times[alert_key] = datetime.now(timezone.utc)

    async def send_alert(self, alert: Alert, force: bool = False) -> bool:
        """
        Send an alert to configured channels.

        Args:
            alert: Alert to send
            force: Bypass rate limiting

        Returns:
            True if alert was sent (to at least one channel)
        """
        alert_key = alert.type.value

        # Check rate limiting
        if not force and self._is_rate_limited(alert_key):
            logger.debug(f"Alert rate limited: {alert.type.value}")
            return False

        # Store in history
        self._alert_history.append(alert)
        if len(self._alert_history) > self.MAX_HISTORY:
            self._alert_history = self._alert_history[-self.MAX_HISTORY:]

        # Send to configured channels
        sent = False

        if self.slack_url:
            try:
                await self._send_to_slack(alert)
                sent = True
            except Exception as e:
                logger.error(f"Slack alert failed: {e}")

        if self.discord_url:
            try:
                await self._send_to_discord(alert)
                sent = True
            except Exception as e:
                logger.error(f"Discord alert failed: {e}")

        if sent:
            self._update_rate_limit(alert_key)
            logger.info(f"Alert sent: {alert.type.value} - {alert.title}")

        return sent

    async def _send_to_slack(self, alert: Alert) -> None:
        """Send alert to Slack webhook."""
        client = await self._get_client()

        # Build Slack message
        payload = {
            "text": f"{alert.emoji} *{alert.title}*",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{alert.emoji} {alert.title}",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": alert.message
                    }
                }
            ]
        }

        # Add data fields if present
        if alert.data:
            fields = []
            for key, value in alert.data.items():
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*{key}:* {value}"
                })

            payload["blocks"].append({
                "type": "section",
                "fields": fields[:10]  # Slack limit
            })

        # Add timestamp
        payload["blocks"].append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"⏰ {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                }
            ]
        })

        response = await client.post(self.slack_url, json=payload)
        response.raise_for_status()

    async def _send_to_discord(self, alert: Alert) -> None:
        """Send alert to Discord webhook."""
        client = await self._get_client()

        # Build Discord embed
        embed = {
            "title": f"{alert.emoji} {alert.title}",
            "description": alert.message,
            "color": int(alert.color.replace("#", ""), 16),
            "timestamp": alert.timestamp.isoformat()
        }

        # Add data fields
        if alert.data:
            embed["fields"] = [
                {"name": key, "value": str(value), "inline": True}
                for key, value in list(alert.data.items())[:25]  # Discord limit
            ]

        payload = {
            "embeds": [embed]
        }

        response = await client.post(self.discord_url, json=payload)
        response.raise_for_status()

    # =========================================================================
    # Convenience methods for common alerts
    # =========================================================================

    async def alert_trade_executed(
        self,
        pair: str,
        action: str,
        amount: float,
        price: float,
        pnl: Optional[float] = None
    ) -> bool:
        """Send trade execution alert."""
        data = {
            "Pair": pair,
            "Action": action,
            "Amount": f"{amount:.6f}",
            "Price": f"${price:,.2f}"
        }
        if pnl is not None:
            data["P&L"] = f"${pnl:+,.2f}"

        alert = Alert(
            type=AlertType.TRADE_EXECUTED,
            title=f"Trade Executed: {action} {pair}",
            message=f"Successfully executed {action} order for {pair}",
            priority=AlertPriority.MEDIUM,
            data=data
        )
        return await self.send_alert(alert)

    async def alert_stop_loss_triggered(
        self,
        pair: str,
        entry_price: float,
        exit_price: float,
        loss_pct: float
    ) -> bool:
        """Send stop-loss alert."""
        alert = Alert(
            type=AlertType.STOP_LOSS_TRIGGERED,
            title=f"Stop-Loss Triggered: {pair}",
            message=f"Position closed due to stop-loss at {loss_pct:.1f}% loss",
            priority=AlertPriority.HIGH,
            data={
                "Pair": pair,
                "Entry": f"${entry_price:,.2f}",
                "Exit": f"${exit_price:,.2f}",
                "Loss": f"{loss_pct:.1f}%"
            }
        )
        return await self.send_alert(alert)

    async def alert_circuit_breaker(
        self,
        breaker_type: str,
        reason: str
    ) -> bool:
        """Send circuit breaker alert."""
        alert = Alert(
            type=AlertType.CIRCUIT_BREAKER_TRIPPED,
            title=f"Circuit Breaker Tripped: {breaker_type}",
            message=f"Trading paused due to: {reason}",
            priority=AlertPriority.CRITICAL,
            data={
                "Breaker": breaker_type,
                "Reason": reason
            }
        )
        return await self.send_alert(alert, force=True)

    async def alert_anomaly_detected(
        self,
        pair: str,
        anomaly_type: str,
        score: float
    ) -> bool:
        """Send anomaly detection alert."""
        alert = Alert(
            type=AlertType.ANOMALY_DETECTED,
            title=f"Anomaly Detected: {pair}",
            message=f"Unusual market conditions detected ({anomaly_type})",
            priority=AlertPriority.HIGH,
            data={
                "Pair": pair,
                "Type": anomaly_type,
                "Score": f"{score:.2f}"
            }
        )
        return await self.send_alert(alert)

    async def alert_target_milestone(
        self,
        milestone_pct: int,
        current_value: float,
        target_value: float
    ) -> bool:
        """Send target milestone alert."""
        alert = Alert(
            type=AlertType.TARGET_MILESTONE,
            title=f"Milestone Reached: {milestone_pct}%",
            message=f"Reached {milestone_pct}% of target!",
            priority=AlertPriority.MEDIUM,
            data={
                "Progress": f"{milestone_pct}%",
                "Current": f"${current_value:,.2f}",
                "Target": f"${target_value:,.2f}"
            }
        )
        return await self.send_alert(alert)

    async def alert_system_error(
        self,
        component: str,
        error: str
    ) -> bool:
        """Send system error alert."""
        alert = Alert(
            type=AlertType.SYSTEM_ERROR,
            title=f"System Error: {component}",
            message=f"An error occurred in {component}",
            priority=AlertPriority.CRITICAL,
            data={
                "Component": component,
                "Error": error[:200]  # Truncate long errors
            }
        )
        return await self.send_alert(alert, force=True)

    async def alert_system_start(
        self,
        stage: str,
        pairs: List[str]
    ) -> bool:
        """Send system start alert."""
        alert = Alert(
            type=AlertType.SYSTEM_START,
            title="Trading System Started",
            message=f"System is now active in {stage} mode",
            priority=AlertPriority.LOW,
            data={
                "Stage": stage,
                "Pairs": ", ".join(pairs)
            }
        )
        return await self.send_alert(alert, force=True)

    async def alert_system_stop(self, reason: str) -> bool:
        """Send system stop alert."""
        alert = Alert(
            type=AlertType.SYSTEM_STOP,
            title="Trading System Stopped",
            message=f"System has been stopped: {reason}",
            priority=AlertPriority.MEDIUM,
            data={
                "Reason": reason
            }
        )
        return await self.send_alert(alert, force=True)

    def get_alert_history(self, limit: int = 20) -> List[Dict]:
        """Get recent alert history."""
        return [
            {
                "type": a.type.value,
                "title": a.title,
                "message": a.message,
                "priority": a.priority.value,
                "timestamp": a.timestamp.isoformat()
            }
            for a in self._alert_history[-limit:]
        ]

    def clear_rate_limits(self) -> None:
        """Clear all rate limits (for testing)."""
        self._last_alert_times.clear()


# Global alert manager instance
alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get or create global alert manager."""
    global alert_manager
    if alert_manager is None:
        alert_manager = AlertManager()
    return alert_manager
