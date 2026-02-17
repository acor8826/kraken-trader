"""
Integration tests against Binance Testnet.

Run with:  pytest -m integration -v
Requires:  BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET env vars.
"""

import os

import pytest

from integrations.exchanges.binance import BinanceExchange
from core.models import MarketData

# Skip entire module if testnet credentials are absent
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("BINANCE_TESTNET_KEY") or not os.getenv("BINANCE_TESTNET_SECRET"),
        reason="BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET env vars required",
    ),
]


@pytest.fixture(scope="module")
def binance_testnet() -> BinanceExchange:
    """Real BinanceExchange connected to testnet."""
    return BinanceExchange(
        api_key=os.environ["BINANCE_TESTNET_KEY"],
        api_secret=os.environ["BINANCE_TESTNET_SECRET"],
        testnet=True,
    )


# ----------------------------------------------------------------
# Public endpoints
# ----------------------------------------------------------------

class TestTestnetPublicEndpoints:
    async def test_get_ticker(self, binance_testnet):
        result = await binance_testnet.get_ticker("BTC/USDT")

        assert result["pair"] == "BTC/USDT"
        assert result["price"] > 0
        assert result["bid"] > 0
        assert result["ask"] > 0

    async def test_get_ohlcv(self, binance_testnet):
        result = await binance_testnet.get_ohlcv("BTC/USDT", interval=60, limit=10)

        assert len(result) > 0
        assert len(result[0]) == 6  # [ts, o, h, l, c, v]

    async def test_get_orderbook(self, binance_testnet):
        result = await binance_testnet.get_order_book("BTC/USDT")

        assert result["pair"] == "BTC/USDT"
        assert len(result["bids"]) > 0
        assert len(result["asks"]) > 0

    async def test_get_all_pairs(self, binance_testnet):
        result = await binance_testnet.get_all_pairs("USDT")

        assert len(result) > 0
        assert "BTC/USDT" in result

    async def test_get_market_data(self, binance_testnet):
        result = await binance_testnet.get_market_data("BTC/USDT")

        assert isinstance(result, MarketData)
        assert result.current_price > 0


# ----------------------------------------------------------------
# Private endpoints
# ----------------------------------------------------------------

class TestTestnetPrivateEndpoints:
    async def test_get_balance(self, binance_testnet):
        result = await binance_testnet.get_balance()

        assert "total" in result
        assert isinstance(result["total"], float)

    async def test_time_sync(self, binance_testnet):
        # Trigger a signed request to force time sync
        await binance_testnet.get_balance()
        assert binance_testnet._time_synced is True


# ----------------------------------------------------------------
# Order lifecycle
# ----------------------------------------------------------------

class TestTestnetOrderLifecycle:
    async def test_limit_order_lifecycle(self, binance_testnet):
        """Place limit buy -> query -> verify in open orders -> cancel -> verify removed."""
        # 1. Get current price
        ticker = await binance_testnet.get_ticker("BTC/USDT")
        # Place 10% below market so it won't fill but still meets MIN_NOTIONAL
        below_price = ticker["price"] * 0.90

        # 2. Place limit buy with enough quote to meet filters
        order = await binance_testnet.limit_buy(
            "BTC/USDT",
            amount_quote=100.0,
            price=below_price,
        )
        assert "order_id" in order
        order_id = order["order_id"]

        try:
            # 3. Query order
            status = await binance_testnet.query_order(order_id, "BTC/USDT")
            assert status["status"] in ("NEW", "PARTIALLY_FILLED")
            assert status["order_id"] == order_id

            # 4. Verify in open orders
            open_orders = await binance_testnet.get_open_orders("BTC/USDT")
            order_ids = [str(o.get("orderId", o.get("order_id"))) for o in open_orders]
            assert order_id in order_ids

            # 5. Cancel
            cancel_result = await binance_testnet.cancel_order(order_id, symbol="BTC/USDT")
            assert cancel_result["status"] == "CANCELED"

            # 6. Verify removed from open orders
            open_orders_after = await binance_testnet.get_open_orders("BTC/USDT")
            remaining_ids = [str(o.get("orderId", o.get("order_id"))) for o in open_orders_after]
            assert order_id not in remaining_ids

        except Exception:
            # Always try to clean up the order
            try:
                await binance_testnet.cancel_order(order_id, symbol="BTC/USDT")
            except Exception:
                pass
            raise
