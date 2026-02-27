"""
Telegram Alert Channel

Sends alerts to a Telegram chat via the Bot API using httpx.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from .channels import AlertChannel

if TYPE_CHECKING:
    from .manager import Alert

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096


class TelegramChannel(AlertChannel):
    """Sends alerts to a Telegram chat."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        super().__init__(name="telegram", enabled=enabled)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def send(self, alert: "Alert") -> bool:
        if not self.enabled:
            return False

        text = self._format(alert)
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[: MAX_MESSAGE_LENGTH - 3] + "..."

        url = f"{TELEGRAM_API}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }

        try:
            client = await self._get_client()
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True

            # Fallback: retry without MarkdownV2 in case of formatting issues
            logger.debug("Telegram MarkdownV2 failed (%s), retrying plain text", resp.status_code)
            payload["parse_mode"] = ""
            payload["text"] = alert.format_message()
            if len(payload["text"]) > MAX_MESSAGE_LENGTH:
                payload["text"] = payload["text"][: MAX_MESSAGE_LENGTH - 3] + "..."
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True

            logger.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.warning("Telegram send error: %s", e)
            return False

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_md2(text: str) -> str:
        """Escape special chars for Telegram MarkdownV2."""
        special = r"_*[]()~`>#+-=|{}.!"
        out = []
        for ch in text:
            if ch in special:
                out.append("\\")
            out.append(ch)
        return "".join(out)

    def _format(self, alert: "Alert") -> str:
        """Format alert for Telegram MarkdownV2."""
        level_emoji = {
            "info": "\u2139\ufe0f",
            "warning": "\u26a0\ufe0f",
            "critical": "\U0001f6a8",
            "success": "\u2705",
        }
        level = getattr(alert.level, "value", str(alert.level)).lower()
        emoji = level_emoji.get(level, "\U0001f4e2")

        title = self._escape_md2(f"{emoji} {alert.type.value.upper()}")
        body = self._escape_md2(alert.message)
        ts = self._escape_md2(alert.timestamp.strftime("%H:%M UTC"))

        return f"*{title}*\n{body}\n_{ts}_"
