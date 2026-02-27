"""Tests for TelegramChannel."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.alerts.telegram import TelegramChannel


class FakeAlertLevel:
    value = "info"


class FakeAlertType:
    value = "system"


class FakeAlert:
    type = FakeAlertType()
    level = FakeAlertLevel()
    message = "Test alert message"
    timestamp = datetime(2026, 1, 15, 12, 0, 0)
    data = None

    def format_message(self):
        return f"[{self.type.value}] {self.message}"


@pytest.fixture
def channel():
    return TelegramChannel(bot_token="test-token", chat_id="123456")


@pytest.fixture
def alert():
    return FakeAlert()


class TestTelegramChannel:
    def test_init(self, channel):
        assert channel.name == "telegram"
        assert channel.enabled is True
        assert channel.bot_token == "test-token"
        assert channel.chat_id == "123456"

    def test_disabled(self):
        ch = TelegramChannel(bot_token="t", chat_id="c", enabled=False)
        assert ch.enabled is False

    @pytest.mark.asyncio
    async def test_send_disabled(self, channel, alert):
        channel.disable()
        result = await channel.send(alert)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self, channel, alert):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        channel._client = mock_client

        result = await channel.send(alert)

        assert result is True
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "bot" in call_args.args[0]
        assert call_args.kwargs["json"]["chat_id"] == "123456"
        assert call_args.kwargs["json"]["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_send_fallback_plain_text(self, channel, alert):
        md_fail = MagicMock()
        md_fail.status_code = 400

        plain_ok = MagicMock()
        plain_ok.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[md_fail, plain_ok])
        mock_client.is_closed = False
        channel._client = mock_client

        result = await channel.send(alert)

        assert result is True
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_both_fail(self, channel, alert):
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fail_resp)
        mock_client.is_closed = False
        channel._client = mock_client

        result = await channel.send(alert)

        assert result is False

    @pytest.mark.asyncio
    async def test_send_network_error(self, channel, alert):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.is_closed = False
        channel._client = mock_client

        result = await channel.send(alert)

        assert result is False

    def test_escape_md2(self, channel):
        text = "Hello *world* (test) [link]"
        escaped = channel._escape_md2(text)
        assert "\\*" in escaped
        assert "\\(" in escaped
        assert "\\[" in escaped

    def test_format(self, channel, alert):
        formatted = channel._format(alert)
        assert "SYSTEM" in formatted
        assert "Test alert message" in formatted.replace("\\", "")

    @pytest.mark.asyncio
    async def test_message_truncation(self, channel):
        long_alert = FakeAlert()
        long_alert.message = "x" * 5000

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        channel._client = mock_client

        result = await channel.send(long_alert)

        assert result is True
        call_args = mock_client.post.call_args
        sent_text = call_args.kwargs["json"]["text"]
        assert len(sent_text) <= 4096

    @pytest.mark.asyncio
    async def test_close(self, channel):
        mock_client = AsyncMock()
        mock_client.is_closed = False
        channel._client = mock_client

        await channel.close()
        mock_client.aclose.assert_called_once()
