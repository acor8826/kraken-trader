"""Tests for public (unauthenticated) BinanceExchange endpoints."""

import time

import pytest
import respx
import httpx

from integrations.exchanges.binance import BinanceExchange
from core.models import MarketData
from tests.conftest import (
    TICKER_24HR_BTCUSDT,
    KLINES_BTCUSDT,
    DEPTH_BTCUSDT,
    SERVER_TIME_RESPONSE,
    EXCHANGE_INFO_BTCUSDT,
    ALL_PAIRS_EXCHANGE_INFO,
)

BASE = BinanceExchange.BASE_URL


# ----------------------------------------------------------------
# get_ticker
# ----------------------------------------------------------------

class TestGetTicker:
    @respx.mock
    async def test_success(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(json=TICKER_24HR_BTCUSDT)

        result = await binance_prod.get_ticker("BTC/USDT")

        assert result["pair"] == "BTC/USDT"
        assert result["price"] == 65432.10
        assert result["bid"] == 65430.00
        assert result["ask"] == 65435.00
        assert result["high_24h"] == 66000.00
        assert result["low_24h"] == 64000.00
        assert result["volume_24h"] == 12345.678
        assert result["vwap_24h"] == 65100.50
        assert result["trades_24h"] == 987654

    @respx.mock
    async def test_pair_conversion_in_params(self, binance_prod):
        route = respx.get(f"{BASE}/api/v3/ticker/24hr").respond(json=TICKER_24HR_BTCUSDT)

        await binance_prod.get_ticker("ETH/USDT")

        assert route.called
        request = route.calls[0].request
        assert b"symbol=ETHUSDT" in request.url.query


# ----------------------------------------------------------------
# get_ohlcv
# ----------------------------------------------------------------

class TestGetOhlcv:
    @respx.mock
    async def test_success(self, binance_prod):
        respx.get(f"{BASE}/api/v3/klines").respond(json=KLINES_BTCUSDT)

        result = await binance_prod.get_ohlcv("BTC/USDT", interval=60, limit=24)

        assert len(result) == 2
        # Each element: [timestamp, open, high, low, close, volume]
        assert len(result[0]) == 6
        assert result[0][0] == 1700000000000
        assert result[0][1] == 65000.00  # open
        assert result[0][4] == 65200.00  # close
        assert isinstance(result[0][5], float)  # volume

    @respx.mock
    async def test_interval_mapping(self, binance_prod):
        route = respx.get(f"{BASE}/api/v3/klines").respond(json=KLINES_BTCUSDT)

        await binance_prod.get_ohlcv("BTC/USDT", interval=60)

        request = route.calls[0].request
        assert b"interval=1h" in request.url.query

    @respx.mock
    async def test_limit_clamped_to_1000(self, binance_prod):
        route = respx.get(f"{BASE}/api/v3/klines").respond(json=KLINES_BTCUSDT)

        await binance_prod.get_ohlcv("BTC/USDT", interval=60, limit=5000)

        request = route.calls[0].request
        assert b"limit=1000" in request.url.query

    async def test_invalid_interval(self, binance_prod):
        with pytest.raises(ValueError, match="Unsupported interval"):
            await binance_prod.get_ohlcv("BTC/USDT", interval=3)


# ----------------------------------------------------------------
# get_order_book
# ----------------------------------------------------------------

class TestGetOrderBook:
    @respx.mock
    async def test_success(self, binance_prod):
        respx.get(f"{BASE}/api/v3/depth").respond(json=DEPTH_BTCUSDT)

        result = await binance_prod.get_order_book("BTC/USDT")

        assert result["pair"] == "BTC/USDT"
        assert len(result["bids"]) == 2
        assert len(result["asks"]) == 2
        assert result["bids"][0] == [65430.00, 1.5]
        assert result["asks"][0] == [65435.00, 0.8]

    @respx.mock
    async def test_depth_clamped(self, binance_prod):
        route = respx.get(f"{BASE}/api/v3/depth").respond(json=DEPTH_BTCUSDT)

        await binance_prod.get_order_book("BTC/USDT", depth=10000)

        request = route.calls[0].request
        assert b"limit=5000" in request.url.query

    @respx.mock
    async def test_weight_key_depth_20(self, binance_prod):
        respx.get(f"{BASE}/api/v3/depth").respond(json=DEPTH_BTCUSDT)

        # depth <= 20 should use weight "depth_20" (5)
        initial_log_len = len(binance_prod._request_log)
        await binance_prod.get_order_book("BTC/USDT", depth=15)

        # Verify a weight was recorded
        assert len(binance_prod._request_log) == initial_log_len + 1


# ----------------------------------------------------------------
# get_market_data
# ----------------------------------------------------------------

class TestGetMarketData:
    @respx.mock
    async def test_returns_market_data_object(self, binance_prod):
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(json=TICKER_24HR_BTCUSDT)
        respx.get(f"{BASE}/api/v3/klines").respond(json=KLINES_BTCUSDT)

        result = await binance_prod.get_market_data("BTC/USDT")

        assert isinstance(result, MarketData)
        assert result.pair == "BTC/USDT"
        assert result.current_price == 65432.10
        assert result.high_24h == 66000.00
        assert result.low_24h == 64000.00
        assert result.volume_24h == 12345.678
        assert result.vwap_24h == 65100.50
        assert result.trades_24h == 987654
        assert len(result.ohlcv) == 2


# ----------------------------------------------------------------
# _sync_time
# ----------------------------------------------------------------

class TestSyncTime:
    @respx.mock
    async def test_offset_computed(self, binance_prod):
        server_time = int(time.time() * 1000) + 500  # 500ms ahead
        respx.get(f"{BASE}/api/v3/time").respond(json={"serverTime": server_time})

        await binance_prod._sync_time()

        assert binance_prod._time_synced is True
        # Offset should be approximately 500 (not exact due to timing jitter)
        assert abs(binance_prod._time_offset_ms - 500) < 500

    @respx.mock
    async def test_failure_sets_zero_and_synced(self, binance_prod):
        respx.get(f"{BASE}/api/v3/time").respond(status_code=500)

        await binance_prod._sync_time()

        assert binance_prod._time_synced is True
        assert binance_prod._time_offset_ms == 0


# ----------------------------------------------------------------
# _ensure_exchange_info
# ----------------------------------------------------------------

class TestEnsureExchangeInfo:
    @respx.mock
    async def test_parses_lot_size(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)

        info = await binance_prod._ensure_exchange_info("BTCUSDT")

        assert info["lot_step"] == 0.00001
        assert info["lot_min"] == 0.00001
        assert info["lot_max"] == 9000.0

    @respx.mock
    async def test_parses_price_filter(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)

        info = await binance_prod._ensure_exchange_info("BTCUSDT")

        assert info["price_tick"] == 0.01
        assert info["price_min"] == 0.01
        assert info["price_max"] == 1000000.0

    @respx.mock
    async def test_parses_min_notional(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)

        info = await binance_prod._ensure_exchange_info("BTCUSDT")

        assert info["min_notional"] == 5.0

    @respx.mock
    async def test_caches_result(self, binance_prod):
        route = respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=EXCHANGE_INFO_BTCUSDT)

        await binance_prod._ensure_exchange_info("BTCUSDT")
        await binance_prod._ensure_exchange_info("BTCUSDT")

        assert route.call_count == 1

    @respx.mock
    async def test_symbol_not_found(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json={"symbols": []})

        info = await binance_prod._ensure_exchange_info("NOPAIR")

        assert info == {}


# ----------------------------------------------------------------
# get_all_pairs
# ----------------------------------------------------------------

class TestGetAllPairs:
    @respx.mock
    async def test_returns_sorted_trading_pairs(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=ALL_PAIRS_EXCHANGE_INFO)

        result = await binance_prod.get_all_pairs("USDT")

        assert result == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        # OLD/USDT excluded (status=BREAK), BTC/AUD excluded (wrong quote)

    @respx.mock
    async def test_custom_quote_currency(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=ALL_PAIRS_EXCHANGE_INFO)

        result = await binance_prod.get_all_pairs("AUD")

        assert result == ["BTC/AUD"]


# ----------------------------------------------------------------
# get_tradable_pairs
# ----------------------------------------------------------------

class TestGetTradablePairs:
    @respx.mock
    async def test_no_volume_filter(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=ALL_PAIRS_EXCHANGE_INFO)

        result = await binance_prod.get_tradable_pairs("USDT", min_volume_24h=0)

        assert len(result) == 3

    @respx.mock
    async def test_with_volume_filter(self, binance_prod):
        respx.get(f"{BASE}/api/v3/exchangeInfo").respond(json=ALL_PAIRS_EXCHANGE_INFO)
        tickers = [
            {"symbol": "BTCUSDT", "quoteVolume": "1000000.00"},
            {"symbol": "ETHUSDT", "quoteVolume": "500000.00"},
            {"symbol": "SOLUSDT", "quoteVolume": "100.00"},
        ]
        respx.get(f"{BASE}/api/v3/ticker/24hr").respond(json=tickers)

        result = await binance_prod.get_tradable_pairs("USDT", min_volume_24h=100000)

        assert "BTC/USDT" in result
        assert "ETH/USDT" in result
        assert "SOL/USDT" not in result
