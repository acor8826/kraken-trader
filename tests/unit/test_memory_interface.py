"""
Tests for IMemory interface compliance and PostgresStore behaviour.

Covers:
- set_entry_price accepts optional size parameter (regression: phase3 passes 3 args)
- record_trade propagates regime from MarketIntel (regression: regime always "unknown")
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional
import inspect

from core.interfaces import IMemory
from core.models.signals import MarketIntel, AnalystSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ConcreteMemory(IMemory):
    """Minimal concrete IMemory used to verify interface signature only."""

    async def get_portfolio(self):
        pass

    async def save_portfolio(self, portfolio) -> None:
        pass

    async def record_trade(self, trade, intel=None) -> None:
        pass

    async def get_trade_history(self, limit=100):
        return []

    async def get_entry_price(self, symbol: str) -> Optional[float]:
        return None

    async def set_entry_price(self, symbol: str, price: float, size: Optional[float] = None) -> None:
        pass  # accepts optional size


# ---------------------------------------------------------------------------
# Interface signature tests
# ---------------------------------------------------------------------------

class TestIMemoryInterface:
    """Verify the IMemory interface declares set_entry_price with optional size."""

    def test_set_entry_price_accepts_optional_size(self):
        """
        Regression: phase3._process_pair calls set_entry_price(symbol, price, size).
        The interface must accept 3 positional args (size optional) so implementations
        don't raise TypeError.
        """
        sig = inspect.signature(IMemory.set_entry_price)
        params = list(sig.parameters.keys())
        assert "size" in params, "IMemory.set_entry_price must declare a 'size' parameter"
        size_param = sig.parameters["size"]
        assert size_param.default is not inspect.Parameter.empty, (
            "IMemory.set_entry_price 'size' must be optional (have a default)"
        )

    def test_concrete_implementation_accepts_size(self):
        """Concrete implementation honouring the updated interface compiles and is callable."""
        mem = _ConcreteMemory()
        # Should not raise TypeError
        sig = inspect.signature(mem.set_entry_price)
        params = sig.parameters
        assert "size" in params


# ---------------------------------------------------------------------------
# PostgresStore unit tests (no real DB — mock asyncpg)
# ---------------------------------------------------------------------------

class TestPostgresStoreSetEntryPrice:
    """Unit tests for PostgresStore.set_entry_price signature compliance."""

    @pytest.mark.asyncio
    async def test_set_entry_price_two_args(self):
        """Calling with (symbol, price) must work (backwards compat)."""
        from memory.postgres import PostgresStore
        store = PostgresStore("postgresql://dummy")

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        with patch.object(store, '_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await store.set_entry_price("BTC", 65000.0)

        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_entry_price_three_args(self):
        """
        Regression: phase3 calls set_entry_price(symbol, price, size).
        Must NOT raise TypeError.
        """
        from memory.postgres import PostgresStore
        store = PostgresStore("postgresql://dummy")

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        with patch.object(store, '_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            # This call pattern is what phase3._process_pair uses
            await store.set_entry_price("ETH", 3200.0, 0.5)

        mock_conn.execute.assert_called_once()


class TestPostgresStoreRecordTradeRegime:
    """Unit tests verifying regime is extracted from MarketIntel and passed to INSERT."""

    def _make_intel(self, regime_value: Optional[str]) -> MarketIntel:
        """Build a minimal MarketIntel with a regime."""
        intel = MagicMock(spec=MarketIntel)
        if regime_value is not None:
            regime_mock = MagicMock()
            regime_mock.value = regime_value
            intel.regime = regime_mock
        else:
            intel.regime = None
        intel.signals = []
        return intel

    @pytest.mark.asyncio
    async def test_record_trade_with_regime(self):
        """record_trade should pass regime string as $27 to INSERT."""
        from memory.postgres import PostgresStore
        from core.models.trading import Trade, TradeAction, TradeStatus, OrderType

        store = PostgresStore("postgresql://dummy")

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="trade-uuid-1234")
        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        trade = Trade(
            pair="BTC/USDT",
            action=TradeAction.BUY,
            order_type=OrderType.MARKET,
            status=TradeStatus.FILLED,
        )
        intel = self._make_intel("RANGING")

        with patch.object(store, '_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await store.record_trade(trade, intel)

        # Verify fetchval was called and the last positional arg is the regime
        call_args = mock_conn.fetchval.call_args
        positional_args = call_args[0]  # (sql, *values)
        # Last value passed should be "RANGING"
        assert positional_args[-1] == "RANGING", (
            f"Expected last INSERT param to be 'RANGING', got {positional_args[-1]!r}"
        )

    @pytest.mark.asyncio
    async def test_record_trade_without_intel_regime_is_null(self):
        """record_trade with no intel should insert NULL for regime."""
        from memory.postgres import PostgresStore
        from core.models.trading import Trade, TradeAction, TradeStatus, OrderType

        store = PostgresStore("postgresql://dummy")

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="trade-uuid-5678")
        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_txn)

        trade = Trade(
            pair="ETH/USDT",
            action=TradeAction.SELL,
            order_type=OrderType.MARKET,
            status=TradeStatus.FILLED,
        )

        with patch.object(store, '_connection') as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await store.record_trade(trade, intel=None)

        call_args = mock_conn.fetchval.call_args
        positional_args = call_args[0]
        assert positional_args[-1] is None, (
            f"Expected last INSERT param to be None, got {positional_args[-1]!r}"
        )
