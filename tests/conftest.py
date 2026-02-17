"""Shared fixtures and canonical Binance API response payloads."""

import time
import pytest
from typing import Dict, Any

from integrations.exchanges.binance import BinanceExchange


# ----------------------------------------------------------------
# Canonical Binance API response payloads
# ----------------------------------------------------------------

SERVER_TIME_RESPONSE: Dict[str, Any] = {
    "serverTime": int(time.time() * 1000),
}

EXCHANGE_INFO_BTCUSDT: Dict[str, Any] = {
    "symbols": [{
        "symbol": "BTCUSDT",
        "status": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "filters": [
            {
                "filterType": "LOT_SIZE",
                "minQty": "0.00001000",
                "maxQty": "9000.00000000",
                "stepSize": "0.00001000",
            },
            {
                "filterType": "PRICE_FILTER",
                "minPrice": "0.01000000",
                "maxPrice": "1000000.00",
                "tickSize": "0.01000000",
            },
            {
                "filterType": "NOTIONAL",
                "minNotional": "5.00000000",
            },
        ],
    }],
}

TICKER_24HR_BTCUSDT: Dict[str, Any] = {
    "symbol": "BTCUSDT",
    "lastPrice": "65432.10",
    "bidPrice": "65430.00",
    "askPrice": "65435.00",
    "highPrice": "66000.00",
    "lowPrice": "64000.00",
    "volume": "12345.678",
    "weightedAvgPrice": "65100.50",
    "count": 987654,
}

KLINES_BTCUSDT = [
    [
        1700000000000, "65000.00", "65500.00", "64800.00", "65200.00",
        "100.5", 1700003599999, "6542600.00", 500, "50.25", "3271300.00", "0",
    ],
    [
        1700003600000, "65200.00", "65800.00", "65100.00", "65600.00",
        "120.3", 1700007199999, "7894800.00", 600, "60.15", "3947400.00", "0",
    ],
]

DEPTH_BTCUSDT: Dict[str, Any] = {
    "lastUpdateId": 123456789,
    "bids": [["65430.00", "1.500"], ["65429.00", "2.300"]],
    "asks": [["65435.00", "0.800"], ["65436.00", "1.100"]],
}

ACCOUNT_RESPONSE: Dict[str, Any] = {
    "balances": [
        {"asset": "BTC", "free": "0.50000000", "locked": "0.00000000"},
        {"asset": "USDT", "free": "10000.00000000", "locked": "0.00000000"},
        {"asset": "ETH", "free": "0.00000000", "locked": "0.00000000"},
    ],
}

MARKET_ORDER_RESPONSE: Dict[str, Any] = {
    "symbol": "BTCUSDT",
    "orderId": 123456,
    "clientOrderId": "abc123",
    "transactTime": 1700000000000,
    "price": "0.00000000",
    "origQty": "0.01000000",
    "executedQty": "0.01000000",
    "cummulativeQuoteQty": "654.32",
    "status": "FILLED",
    "type": "MARKET",
    "side": "BUY",
}

LIMIT_ORDER_RESPONSE: Dict[str, Any] = {
    "symbol": "BTCUSDT",
    "orderId": 789012,
    "clientOrderId": "def456",
    "transactTime": 1700000000000,
    "price": "64000.00000000",
    "origQty": "0.01000000",
    "executedQty": "0.00000000",
    "cummulativeQuoteQty": "0.00000000",
    "status": "NEW",
    "type": "LIMIT",
    "side": "BUY",
    "timeInForce": "GTC",
}

OPEN_ORDERS_RESPONSE = [
    {
        "symbol": "BTCUSDT",
        "orderId": 789012,
        "clientOrderId": "def456",
        "price": "64000.00000000",
        "origQty": "0.01000000",
        "executedQty": "0.00000000",
        "cummulativeQuoteQty": "0.00000000",
        "status": "NEW",
        "type": "LIMIT",
        "side": "BUY",
        "time": 1700000000000,
        "updateTime": 1700000000000,
    }
]

QUERY_ORDER_RESPONSE: Dict[str, Any] = {
    "symbol": "BTCUSDT",
    "orderId": 123456,
    "clientOrderId": "abc123",
    "price": "0.00000000",
    "origQty": "0.01000000",
    "executedQty": "0.01000000",
    "cummulativeQuoteQty": "654.32",
    "status": "FILLED",
    "type": "MARKET",
    "side": "BUY",
    "time": 1700000000000,
    "updateTime": 1700000000000,
}

CANCEL_ORDER_RESPONSE: Dict[str, Any] = {
    "symbol": "BTCUSDT",
    "orderId": 789012,
    "clientOrderId": "def456",
    "origQty": "0.01000000",
    "executedQty": "0.00000000",
    "status": "CANCELED",
}

ALL_PAIRS_EXCHANGE_INFO: Dict[str, Any] = {
    "symbols": [
        {"baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING"},
        {"baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING"},
        {"baseAsset": "SOL", "quoteAsset": "USDT", "status": "TRADING"},
        {"baseAsset": "OLD", "quoteAsset": "USDT", "status": "BREAK"},
        {"baseAsset": "BTC", "quoteAsset": "AUD", "status": "TRADING"},
    ],
}


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------

@pytest.fixture
def binance_prod() -> BinanceExchange:
    """BinanceExchange pointed at production URL with dummy keys."""
    return BinanceExchange(
        api_key="test-api-key",
        api_secret="test-api-secret",
        testnet=False,
    )


@pytest.fixture
def binance_testnet_unit() -> BinanceExchange:
    """BinanceExchange pointed at testnet URL with dummy keys."""
    return BinanceExchange(
        api_key="test-api-key",
        api_secret="test-api-secret",
        testnet=True,
    )


@pytest.fixture
def binance_no_keys() -> BinanceExchange:
    """BinanceExchange with empty credentials."""
    return BinanceExchange(api_key="", api_secret="", testnet=False)


@pytest.fixture
def binance_time_synced(binance_prod: BinanceExchange) -> BinanceExchange:
    """BinanceExchange with time already synced."""
    binance_prod._time_synced = True
    binance_prod._time_offset_ms = 0
    return binance_prod
