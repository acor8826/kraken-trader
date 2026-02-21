"""
Alert Channels

Different delivery channels for alerts.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Optional aiohttp for webhook support
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger(__name__)


class AlertChannel(ABC):
    """Base class for alert channels"""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    @abstractmethod
    async def send(self, alert: "Alert") -> bool:
        """Send an alert. Returns True if successful."""
        pass

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False


class ConsoleChannel(AlertChannel):
    """Console/logging channel"""

    def __init__(self, enabled: bool = True):
        super().__init__("console", enabled)
        self._alert_logger = logging.getLogger("alerts")

    async def send(self, alert: "Alert") -> bool:
        if not self.enabled:
            return False

        try:
            message = alert.format_message()

            # Use appropriate log level
            from core.alerts.manager import AlertLevel
            if alert.level == AlertLevel.CRITICAL:
                self._alert_logger.error(message)
            elif alert.level == AlertLevel.WARNING:
                self._alert_logger.warning(message)
            else:
                self._alert_logger.info(message)

            return True
        except Exception as e:
            logger.error(f"Console channel error: {e}")
            return False


class FileChannel(AlertChannel):
    """File logging channel for audit trail"""

    def __init__(
        self,
        file_path: str = "alerts.log",
        enabled: bool = True,
        max_size_mb: int = 10
    ):
        super().__init__("file", enabled)
        self.file_path = Path(file_path)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = asyncio.Lock()

        # Ensure directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    async def send(self, alert: "Alert") -> bool:
        if not self.enabled:
            return False

        try:
            async with self._lock:
                # Check file size and rotate if needed
                await self._maybe_rotate()

                # Write alert
                line = f"{alert.format_message()}\n"

                # Use sync write in thread pool (more reliable)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._write_line, line)

            return True
        except Exception as e:
            logger.error(f"File channel error: {e}")
            return False

    def _write_line(self, line: str) -> None:
        """Synchronous write"""
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line)

    async def _maybe_rotate(self) -> None:
        """Rotate log file if it exceeds max size"""
        try:
            if self.file_path.exists():
                size = self.file_path.stat().st_size
                if size > self.max_size_bytes:
                    # Rotate by renaming
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = self.file_path.with_suffix(f".{timestamp}.log")
                    self.file_path.rename(backup_path)
                    logger.info(f"Rotated alert log to {backup_path}")
        except Exception as e:
            logger.error(f"Log rotation error: {e}")


class WebhookChannel(AlertChannel):
    """
    Webhook channel for Discord/Slack notifications.

    Discord format: {"content": "message"}
    Slack format: {"text": "message"}
    """

    def __init__(
        self,
        url: str,
        name: str = "webhook",
        enabled: bool = True,
        platform: str = "discord",
        timeout: float = 10.0
    ):
        super().__init__(name, enabled)
        self.url = url
        self.platform = platform.lower()
        self.timeout = timeout

    async def send(self, alert: "Alert") -> bool:
        if not self.enabled or not self.url:
            return False

        if not HAS_AIOHTTP:
            logger.warning("Webhook channel requires aiohttp. Install with: pip install aiohttp")
            return False

        try:
            message = alert.format_message()

            # Format payload based on platform
            if self.platform == "slack":
                payload = {
                    "text": message,
                    "attachments": self._format_slack_attachments(alert)
                }
            else:  # Discord (default)
                payload = {
                    "content": message,
                    "embeds": self._format_discord_embeds(alert)
                }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status in (200, 204):
                        return True
                    else:
                        text = await response.text()
                        logger.warning(f"Webhook returned {response.status}: {text[:200]}")
                        return False

        except asyncio.TimeoutError:
            logger.error(f"Webhook timeout after {self.timeout}s")
            return False
        except Exception as e:
            logger.error(f"Webhook channel error: {e}")
            return False

    def _format_discord_embeds(self, alert: "Alert") -> list:
        """Format Discord embed with alert data"""
        from core.alerts.manager import AlertLevel, AlertType

        # Color based on level
        colors = {
            AlertLevel.INFO: 0x3498db,      # Blue
            AlertLevel.WARNING: 0xf39c12,   # Orange
            AlertLevel.CRITICAL: 0xe74c3c   # Red
        }

        embed = {
            "title": f"{alert.type.value.replace('_', ' ').title()}",
            "description": alert.message,
            "color": colors.get(alert.level, 0x95a5a6),
            "timestamp": alert.timestamp.isoformat(),
            "footer": {"text": "Kraken Trading Agent"}
        }

        # Add fields for data
        if alert.data:
            fields = []
            for key, value in alert.data.items():
                if value is not None:
                    # Format value nicely
                    if isinstance(value, float):
                        if "pct" in key or "percent" in key:
                            formatted = f"{value:.1%}"
                        elif "price" in key or "value" in key:
                            formatted = f"${value:.2f}"
                        else:
                            formatted = f"{value:.4f}"
                    else:
                        formatted = str(value)

                    fields.append({
                        "name": key.replace("_", " ").title(),
                        "value": formatted,
                        "inline": True
                    })

            if fields:
                embed["fields"] = fields[:25]  # Discord limit

        return [embed]

    def _format_slack_attachments(self, alert: "Alert") -> list:
        """Format Slack attachment with alert data"""
        from core.alerts.manager import AlertLevel

        # Color based on level
        colors = {
            AlertLevel.INFO: "good",      # Green
            AlertLevel.WARNING: "warning", # Yellow
            AlertLevel.CRITICAL: "danger"  # Red
        }

        attachment = {
            "color": colors.get(alert.level, "#808080"),
            "title": alert.type.value.replace("_", " ").title(),
            "text": alert.message,
            "ts": int(alert.timestamp.timestamp())
        }

        # Add fields for data
        if alert.data:
            fields = []
            for key, value in alert.data.items():
                if value is not None:
                    if isinstance(value, float):
                        if "pct" in key:
                            formatted = f"{value:.1%}"
                        elif "price" in key or "value" in key:
                            formatted = f"${value:.2f}"
                        else:
                            formatted = f"{value:.4f}"
                    else:
                        formatted = str(value)

                    fields.append({
                        "title": key.replace("_", " ").title(),
                        "value": formatted,
                        "short": True
                    })

            if fields:
                attachment["fields"] = fields

        return [attachment]


# Import Alert for type hints
from core.alerts.manager import Alert
