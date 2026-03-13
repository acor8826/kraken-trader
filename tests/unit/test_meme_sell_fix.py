"""
Unit tests for meme orchestrator direct-sell fix.

Verifies that SELL orders use the tracked position amount (bypassing the
executor's exchange-balance lookup) so meme coin sells succeed even when
the simulation exchange reports zero balance for the base asset.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from agents.memetrader.orchestrator import MemeOrchestrator
from agents.memetrader.models import MemePosition, MemeTier
from agents.memetrader.config import MemeConfig
from core.models import TradeAction, TradeSignal, OrderType, Portfolio


def _make_orchestrator():
    """Build a MemeOrchestrator with all dependencies mocked."""
    exchange = AsyncMock()
    executor = AsyncMock()
    twitter_analyst = AsyncMock()
    volume_analyst = AsyncMock()
    strategist = MagicMock()
    sentinel = MagicMock()
    listing_detector = MagicMock()

    orch = MemeOrchestrator(
        exchange=exchange,
        executor=executor,
        twitter_analyst=twitter_analyst,
        volume_analyst=volume_analyst,
        strategist=strategist,
        sentinel=sentinel,
        listing_detector=listing_detector,
        config=MemeConfig(),
    )
    return orch


def _make_sell_signal(pair: str = "PEPE/USDT", size_pct: float = 1.0) -> TradeSignal:
    signal = TradeSignal(
        pair=pair,
        action=TradeAction.SELL,
        confidence=0.90,
        size_pct=size_pct,
        reasoning="Hard stop hit",
        order_type=OrderType.MARKET,
    )
    signal.approve()
    return signal


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Direct sell uses tracked position amount (bypasses executor)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sell_uses_tracked_position_not_executor():
    """
    When a tracked position exists, _execute_signal for SELL must call
    exchange.market_sell with the tracked amount and NOT call executor.execute.
    """
    orch = _make_orchestrator()
    symbol = "PEPE"
    pair = "PEPE/USDT"
    tracked_amount = 1_500_000.0  # 1.5M PEPE

    # Put a tracked position in the orchestrator
    pos = MemePosition(symbol=symbol, pair=pair, entry_price=0.0000080, amount=tracked_amount)
    orch._positions[symbol] = pos

    # Mock exchange.market_sell to return a successful result
    sell_price = 0.0000085
    orch.exchange.market_sell = AsyncMock(return_value={"price": sell_price})

    # Mock sentinel.record_meme_trade_result to avoid side effects
    orch.sentinel.record_meme_trade_result = MagicMock()

    signal = _make_sell_signal(pair)
    portfolio = Portfolio(available_quote=100.0, quote_currency="USDT")

    result = await orch._execute_signal(signal, symbol, pair, portfolio, last_price=sell_price)

    # Executor should NOT have been called for SELL with tracked position
    orch.executor.execute.assert_not_called()

    # Exchange.market_sell should have been called with the tracked amount
    orch.exchange.market_sell.assert_called_once_with(pair, tracked_amount)

    # Result should contain correct trade details
    assert result is not None
    assert result["action"] == "SELL"
    assert result["symbol"] == symbol
    assert abs(result["amount"] - tracked_amount) < 0.001
    assert abs(result["price"] - sell_price) < 0.0000001


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Partial sell uses size_pct fraction of tracked amount
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_partial_sell_uses_size_pct_of_tracked_amount():
    """
    For a scaled TP sell (size_pct=0.5), _execute_signal should sell
    exactly 50% of the tracked position amount.
    """
    orch = _make_orchestrator()
    symbol = "BONK"
    pair = "BONK/USDT"
    tracked_amount = 2_000_000.0

    pos = MemePosition(symbol=symbol, pair=pair, entry_price=0.000020, amount=tracked_amount)
    orch._positions[symbol] = pos

    sell_price = 0.000025
    orch.exchange.market_sell = AsyncMock(return_value={"price": sell_price})
    orch.sentinel.record_meme_trade_result = MagicMock()

    signal = _make_sell_signal(pair, size_pct=0.5)
    portfolio = Portfolio(available_quote=200.0, quote_currency="USDT")

    result = await orch._execute_signal(signal, symbol, pair, portfolio, last_price=sell_price)

    expected_sell_amount = tracked_amount * 0.5
    orch.exchange.market_sell.assert_called_once_with(pair, expected_sell_amount)
    assert result is not None
    assert abs(result["amount"] - expected_sell_amount) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: No tracked position falls back to executor
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sell_without_tracked_position_falls_back_to_executor():
    """
    When there is no tracked position for a symbol, SELL should fall back to
    the executor (which may still fail if balance=0, but that's pre-existing
    behaviour and not a regression introduced by this fix).
    """
    orch = _make_orchestrator()
    symbol = "FLOKI"
    pair = "FLOKI/USDT"

    # No position tracked
    assert symbol not in orch._positions

    # Executor returns no fills (simulates balance=0 scenario)
    orch.executor.execute = AsyncMock(return_value=MagicMock(successful_trades=[]))
    orch.exchange.market_sell = AsyncMock()

    signal = _make_sell_signal(pair)
    portfolio = Portfolio(available_quote=0.0, quote_currency="USDT")

    result = await orch._execute_signal(signal, symbol, pair, portfolio, last_price=0.000200)

    # Executor should have been called as fallback
    orch.executor.execute.assert_called_once()
    # Exchange.market_sell should NOT have been called directly
    orch.exchange.market_sell.assert_not_called()
    # Result is None because no fills
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: BUY still uses executor (no change to BUY path)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_buy_still_uses_executor():
    """
    BUY orders must still go through the executor — this fix must not break the
    BUY execution path.
    """
    from core.models import Trade, TradeStatus, TradeAction as TA

    orch = _make_orchestrator()
    symbol = "PEPE"
    pair = "PEPE/USDT"

    mock_trade = Trade(
        pair=pair,
        action=TA.BUY,
        status=TradeStatus.FILLED,
        filled_size_base=1_000_000.0,
        filled_size_quote=10.0,
        average_price=0.000010,
    )
    orch.executor.execute = AsyncMock(return_value=MagicMock(successful_trades=[mock_trade]))
    orch.exchange.market_buy = AsyncMock()

    buy_signal = TradeSignal(
        pair=pair,
        action=TradeAction.BUY,
        confidence=0.80,
        size_pct=0.05,
        reasoning="Strong entry",
        order_type=OrderType.MARKET,
    )
    buy_signal.approve()

    portfolio = Portfolio(available_quote=500.0, quote_currency="USDT")
    result = await orch._execute_signal(buy_signal, symbol, pair, portfolio, last_price=0.000010)

    # Executor must have been called for BUY
    orch.executor.execute.assert_called_once()
    # exchange.market_buy should NOT have been called directly
    orch.exchange.market_buy.assert_not_called()
    assert result is not None
    assert result["action"] == "BUY"
