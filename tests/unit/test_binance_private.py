"""Tests for authenticated (signed) BinanceExchange endpoints."""

import hmac
import hashlib

import pytest
import respx

from integrations.exchanges.binance import BinanceExchange
from tests.conftest import (
    ACCOUNT_RESPONSE,
    TICKER_24HR_BTCUSDT,
    MARKET_ORDER_RESPONSE,
    LIMIT_ORDER_RESPONSE,
    OPEN_ORDERS_RESPONSE,
    QUERY_ORDER_RESPONSE,
    CANCEL_ORDER_RESPONSE,
    EXCHANGE_INFO_BTCUSDT,
    SERVER_TIME_RESPONSE,
)

BASE = BinanceExchange.BASE_URL


def compute_expected_signature(secret: str, query_string: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ----------------------------------------------------------------
# _sign
# ----------------------------------------------------------------

class TestSign:
    def test_known_vector(self, binance_prod):
        qs = "symbol=BTCUSDT&timestamp=1700000000000"
        expected = compute_expected_signature("test-api-secret", qs)
        assert binance_prod._sign(qs) == expected

    def test_empty_string(self, binance_prod):
        result = binance_prod._sign("")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

    def test_special_characters(self, binance_prod):
        qs = "symbol=BTC%2FUSDT&price=65000.50&timestamp=123"
        expected = compute_expected_signature("test-api-secret", qs)
        assert binance_prod._sign(qs) == expected


# ----------------------------------------------------------------
# _signed_request mechanics
# ----------------------------------------------------------------

class TestSignedRequest:
    @respx.mock
    async def test_timestamp_injected(self, binance_time_synced):
        route = respx.get(url__startswith=f"{BASE}/api/v3/account").respond(
            json=ACCOUNT_RESPONSE
        )

        await binance_time_synced._signed_request("GET", "/api/v3/account", weight_key="account")

        request = route.calls[0].request
        assert b"timestamp=" in request.url.query

    @respx.mock
    async def test_signature_appended(self, binance_time_synced):
        route = respx.get(url__startswith=f"{BASE}/api/v3/account").respond(
            json=ACCOUNT_RESPONSE
        )

        await binance_time_synced._signed_request("GET", "/api/v3/account", weight_key="account")

        request = route.calls[0].request
        query = request.url.query.decode()
        assert "signature=" in query
        # signature should be the last parameter
        assert query.rindex("signature=") > query.rindex("timestamp=")

    @respx.mock
    async def test_header_contains_apikey(self, binance_time_synced):
        route = respx.get(url__startswith=f"{BASE}/api/v3/account").respond(
            json=ACCOUNT_RESPONSE
        )

        await binance_time_synced._signed_request("GET", "/api/v3/account", weight_key="account")

        request = route.calls[0].request
        assert request.headers["X-MBX-APIKEY"] == "test-api-key"

    @respx.mock
    async def test_auto_syncs_time_on_first_call(self, binance_prod):
        respx.get(f"{BASE}/api/v3/time").respond(json=SERVER_TIME_RESPONSE)
        respx.get(url__startswith=f"{BASE}/api/v3/account").respond(json=ACCOUNT_RESPONSE)

        assert binance_prod._time_synced is False
        await binance_prod._signed_request("GET", "/api/v3/account", weight_key="account")
        assert binance_prod._time_synced is True

    async def test_no_credentials_raises(self, binance_no_keys):
        with pytest.raises(Exception, match="credentials not configured"):
            await binance_no_keys._signed_request("GET", "/api/v3/account")

    @respx.mock
    async def test_unsupported_method_raises(self, binance_time_synced):
        with pytest.raises(ValueError, match="Unsupported HTTP method"):
            await binance_time_synced._signed_request("PATCH", "/api/v3/order")


# ----------------------------------------------------------------
# get_balance
# ----------------------------------------------------------------

class TestGetBalance:
    @respx.mock
    async def test_success(self, binance_time_synced):
        respx.get(url__startswith=f"{BASE}/api/v3/account").respond(json=ACCOUNT_RESPONSE)
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(json=TICKER_24HR_BTCUSDT)

        result = await binance_time_synced.get_balance()

        assert result["BTC"] == 0.5
        assert result["USDT"] == 10000.0
        assert "ETH" not in result  # zero balance excluded
        assert "total" in result
        assert result["total"] > 10000.0  # USDT + BTC value

    @respx.mock
    async def test_empty_balances(self, binance_time_synced):
        respx.get(url__startswith=f"{BASE}/api/v3/account").respond(
            json={"balances": []}
        )

        result = await binance_time_synced.get_balance()

        assert result["total"] == 0.0


# ----------------------------------------------------------------
# market_buy
# ----------------------------------------------------------------

class TestMarketBuy:
    @respx.mock
    async def test_success(self, binance_time_synced):
        route = respx.post(url__startswith=f"{BASE}/api/v3/order").respond(
            json=MARKET_ORDER_RESPONSE
        )

        result = await binance_time_synced.market_buy("BTC/USDT", amount_quote=654.32)

        assert result["order_id"] == "123456"
        assert result["txid"] == ["123456"]
        assert result["status"] == "FILLED"
        assert result["side"] == "buy"
        assert result["pair"] == "BTC/USDT"

    @respx.mock
    async def test_sends_quote_order_qty(self, binance_time_synced):
        route = respx.post(url__startswith=f"{BASE}/api/v3/order").respond(
            json=MARKET_ORDER_RESPONSE
        )

        await binance_time_synced.market_buy("BTC/USDT", amount_quote=100.0)

        request = route.calls[0].request
        query = request.url.query.decode()
        assert "quoteOrderQty=" in query
        assert "side=BUY" in query
        assert "type=MARKET" in query


# ----------------------------------------------------------------
# market_sell
# ----------------------------------------------------------------

class TestMarketSell:
    @respx.mock
    async def test_success(self, binance_time_synced):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)
        sell_response = {**MARKET_ORDER_RESPONSE, "side": "SELL"}
        respx.post(url__startswith=f"{BASE}/api/v3/order").respond(json=sell_response)

        result = await binance_time_synced.market_sell("BTC/USDT", amount_base=0.01)

        assert result["side"] == "sell"
        assert result["order_id"] == "123456"

    @respx.mock
    async def test_rounds_quantity(self, binance_time_synced):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)
        sell_response = {**MARKET_ORDER_RESPONSE, "side": "SELL"}
        route = respx.post(url__startswith=f"{BASE}/api/v3/order").respond(json=sell_response)

        await binance_time_synced.market_sell("BTC/USDT", amount_base=0.01234567)

        request = route.calls[0].request
        query = request.url.query.decode()
        # stepSize=0.00001, so 0.01234567 -> 0.01234
        assert "quantity=0.01234000" in query


# ----------------------------------------------------------------
# limit_buy
# ----------------------------------------------------------------

class TestLimitBuy:
    @respx.mock
    async def test_success(self, binance_time_synced):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)
        respx.post(url__startswith=f"{BASE}/api/v3/order").respond(json=LIMIT_ORDER_RESPONSE)

        result = await binance_time_synced.limit_buy("BTC/USDT", amount_quote=640.0, price=64000.0)

        assert result["order_id"] == "789012"
        assert result["status"] == "NEW"
        assert result["side"] == "buy"

    @respx.mock
    async def test_sends_gtc(self, binance_time_synced):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)
        route = respx.post(url__startswith=f"{BASE}/api/v3/order").respond(json=LIMIT_ORDER_RESPONSE)

        await binance_time_synced.limit_buy("BTC/USDT", amount_quote=640.0, price=64000.0)

        query = route.calls[0].request.url.query.decode()
        assert "timeInForce=GTC" in query
        assert "type=LIMIT" in query
        assert "side=BUY" in query


# ----------------------------------------------------------------
# limit_sell
# ----------------------------------------------------------------

class TestLimitSell:
    @respx.mock
    async def test_success(self, binance_time_synced):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)
        sell_response = {**LIMIT_ORDER_RESPONSE, "side": "SELL"}
        respx.post(url__startswith=f"{BASE}/api/v3/order").respond(json=sell_response)

        result = await binance_time_synced.limit_sell("BTC/USDT", amount_base=0.01, price=70000.0)

        assert result["side"] == "sell"

    @respx.mock
    async def test_rounds_price_and_quantity(self, binance_time_synced):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)
        sell_response = {**LIMIT_ORDER_RESPONSE, "side": "SELL"}
        route = respx.post(url__startswith=f"{BASE}/api/v3/order").respond(json=sell_response)

        await binance_time_synced.limit_sell("BTC/USDT", amount_base=0.01234567, price=70000.555)

        query = route.calls[0].request.url.query.decode()
        # quantity rounded to stepSize=0.00001 -> 0.01234
        assert "quantity=0.01234000" in query
        # price rounded to tickSize=0.01 -> 70000.55
        assert "price=70000.55000000" in query


# ----------------------------------------------------------------
# query_order
# ----------------------------------------------------------------

class TestQueryOrder:
    @respx.mock
    async def test_success(self, binance_time_synced):
        respx.get(url__startswith=f"{BASE}/api/v3/order").respond(json=QUERY_ORDER_RESPONSE)

        result = await binance_time_synced.query_order("123456", "BTC/USDT")

        assert result["order_id"] == "123456"
        assert result["status"] == "FILLED"
        assert result["side"] == "BUY"
        assert result["type"] == "MARKET"
        assert result["executed_qty"] == 0.01
        assert result["price"] == pytest.approx(65432.0)

    @respx.mock
    async def test_zero_executed_qty(self, binance_time_synced):
        response = {**QUERY_ORDER_RESPONSE, "executedQty": "0.00000000", "cummulativeQuoteQty": "0.00000000"}
        respx.get(url__startswith=f"{BASE}/api/v3/order").respond(json=response)

        result = await binance_time_synced.query_order("123456", "BTC/USDT")

        assert result["price"] == 0.0  # no division by zero


# ----------------------------------------------------------------
# get_open_orders
# ----------------------------------------------------------------

class TestGetOpenOrders:
    @respx.mock
    async def test_with_symbol(self, binance_time_synced):
        route = respx.get(url__startswith=f"{BASE}/api/v3/openOrders").respond(
            json=OPEN_ORDERS_RESPONSE
        )

        result = await binance_time_synced.get_open_orders("BTC/USDT")

        assert len(result) == 1
        query = route.calls[0].request.url.query.decode()
        assert "symbol=BTCUSDT" in query

    @respx.mock
    async def test_without_symbol(self, binance_time_synced):
        route = respx.get(url__startswith=f"{BASE}/api/v3/openOrders").respond(json=[])

        result = await binance_time_synced.get_open_orders()

        assert result == []
        query = route.calls[0].request.url.query.decode()
        assert "symbol=" not in query.split("timestamp=")[0]


# ----------------------------------------------------------------
# cancel_order
# ----------------------------------------------------------------

class TestCancelOrder:
    @respx.mock
    async def test_success(self, binance_time_synced):
        respx.delete(url__startswith=f"{BASE}/api/v3/order").respond(json=CANCEL_ORDER_RESPONSE)

        result = await binance_time_synced.cancel_order("789012", symbol="BTC/USDT")

        assert result["status"] == "CANCELED"

    async def test_requires_symbol(self, binance_time_synced):
        with pytest.raises(ValueError, match="requires the symbol"):
            await binance_time_synced.cancel_order("789012", symbol=None)
