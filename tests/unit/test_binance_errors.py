"""Tests for error handling and edge cases in BinanceExchange."""

import pytest
import respx
import httpx

from integrations.exchanges.binance import BinanceExchange
from tests.conftest import SERVER_TIME_RESPONSE

BASE = BinanceExchange.BASE_URL


# ----------------------------------------------------------------
# API error responses
# ----------------------------------------------------------------

class TestApiErrors:
    @respx.mock
    async def test_binance_error_code(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(
            json={"code": -1121, "msg": "Invalid symbol."}
        )

        with pytest.raises(Exception, match="Binance API error -1121"):
            await binance_prod.get_ticker("INVALID/PAIR")

    @respx.mock
    async def test_http_400(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(status_code=400)

        with pytest.raises(httpx.HTTPStatusError):
            await binance_prod.get_ticker("BTC/USDT")

    @respx.mock
    async def test_http_403_ip_banned(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(status_code=403)

        with pytest.raises(httpx.HTTPStatusError):
            await binance_prod.get_ticker("BTC/USDT")

    @respx.mock
    async def test_http_429_rate_limited(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(status_code=429)

        with pytest.raises(httpx.HTTPStatusError):
            await binance_prod.get_ticker("BTC/USDT")

    @respx.mock
    async def test_http_500_server_error(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            await binance_prod.get_ticker("BTC/USDT")

    @respx.mock
    async def test_timeout(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").mock(side_effect=httpx.TimeoutException("timeout"))

        with pytest.raises(httpx.TimeoutException):
            await binance_prod.get_ticker("BTC/USDT")


# ----------------------------------------------------------------
# Signed request errors
# ----------------------------------------------------------------

class TestSignedRequestErrors:
    @respx.mock
    async def test_binance_error_on_signed(self, binance_time_synced):
        respx.get(url__startswith=f"{BASE}/api/v3/account").respond(
            json={"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."}
        )

        with pytest.raises(Exception, match="Binance API error -2015"):
            await binance_time_synced.get_balance()

    @respx.mock
    async def test_http_401_on_signed(self, binance_time_synced):
        respx.get(url__startswith=f"{BASE}/api/v3/account").respond(status_code=401)

        with pytest.raises(httpx.HTTPStatusError):
            await binance_time_synced.get_balance()


# ----------------------------------------------------------------
# Edge cases
# ----------------------------------------------------------------

class TestEdgeCases:
    @respx.mock
    async def test_empty_klines(self, binance_prod):
        respx.get(f"{BASE}/api/v3/klines").respond(json=[])

        result = await binance_prod.get_ohlcv("BTC/USDT")

        assert result == []

    @respx.mock
    async def test_empty_orderbook(self, binance_prod):
        respx.get(f"{BASE}/api/v3/depth").respond(
            json={"lastUpdateId": 1, "bids": [], "asks": []}
        )

        result = await binance_prod.get_order_book("BTC/USDT")

        assert result["bids"] == []
        assert result["asks"] == []

    @respx.mock
    async def test_empty_balances(self, binance_time_synced):
        respx.get(url__startswith=f"{BASE}/api/v3/account").respond(
            json={"balances": []}
        )

        result = await binance_time_synced.get_balance()

        assert result == {"total": 0.0}

    @respx.mock
    async def test_exchange_info_empty_symbols(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json={"symbols": []})

        result = await binance_prod.get_all_pairs("USDT")

        assert result == []

    def test_round_quantity_zero(self):
        assert BinanceExchange._round_step(0, 0.001) == 0

    def test_round_price_very_small_tick(self):
        result = BinanceExchange._round_step(0.123456789, 0.00000001)
        assert result == 0.12345678


# ----------------------------------------------------------------
# Rate limit edge cases
# ----------------------------------------------------------------

class TestRateLimitEdge:
    async def test_burst_requests(self, binance_prod, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            # Simulate weight above 80% threshold but below limit
            await binance_prod._record_weight(1100)

        assert "rate limit approaching" in caplog.text.lower()

    async def test_weight_recovery_after_60s(self, binance_prod, caplog):
        import time as time_mod
        import logging

        # Add old weight (61 seconds ago)
        old_ts = time_mod.time() - 61
        binance_prod._request_log.append((old_ts, 1200))

        # Record small new weight; old entry should be pruned
        with caplog.at_level(logging.WARNING):
            await binance_prod._record_weight(1)

        # Only new entry remains, total=1 which is below threshold
        assert len(binance_prod._request_log) == 1
        assert "rate limit" not in caplog.text.lower()
