import pytest

from agents.sentinel.basic import BasicSentinel
from core.config import Settings, RiskConfig, ExitManagementConfig, TrailingStopConfig, BreakevenConfig
from core.models import Position, OrderType


def _make_settings(**risk_kw):
    """Helper to create Settings with custom risk and exit_management config."""
    exit_mgmt = risk_kw.pop("exit_management", ExitManagementConfig())
    return Settings(risk=RiskConfig(**risk_kw), exit_management=exit_mgmt)


# =====================================================================
# Fixed stop-loss tests (Feature A: tighter stops)
# =====================================================================

@pytest.mark.asyncio
async def test_stop_loss_trigger_creates_sell_trade():
    sentinel = BasicSentinel()
    positions = {
        "BTC": Position(symbol="BTC", amount=0.1, entry_price=100.0, current_price=94.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert len(trades) == 1
    assert trades[0].pair.endswith("/USDT")
    assert trades[0].order_type == OrderType.STOP_LOSS
    assert trades[0].requested_size_base == 0.1


@pytest.mark.asyncio
async def test_tighter_stop_loss_triggers_at_new_threshold():
    """Default stop is now 2.5% -- a 3% loss should trigger."""
    sentinel = BasicSentinel()  # uses default 2.5%
    positions = {
        "ETH": Position(symbol="ETH", amount=1.0, entry_price=100.0, current_price=97.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert len(trades) == 1
    assert trades[0].order_type == OrderType.STOP_LOSS


@pytest.mark.asyncio
async def test_take_profit_trigger_creates_sell_trade():
    sentinel = BasicSentinel()
    # Default: 2.5% stop * 2.0 multiplier = 5% take profit
    positions = {
        "ETH": Position(symbol="ETH", amount=1.5, entry_price=100.0, current_price=106.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert len(trades) == 1
    assert trades[0].pair.endswith("/USDT")
    assert trades[0].order_type == OrderType.TAKE_PROFIT
    assert trades[0].requested_size_base == 1.5


@pytest.mark.asyncio
async def test_no_exit_when_between_stop_and_take_profit_thresholds():
    sentinel = BasicSentinel()
    # 2% gain is between 2.5% stop and 5% TP
    positions = {
        "SOL": Position(symbol="SOL", amount=10.0, entry_price=100.0, current_price=102.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []


@pytest.mark.asyncio
async def test_take_profit_uses_configured_multiplier():
    settings = _make_settings(stop_loss_pct=0.025, take_profit_multiplier=3.0)
    sentinel = BasicSentinel(settings=settings)
    # 5% gain, but TP target is 2.5% * 3 = 7.5%
    positions = {
        "ADA": Position(symbol="ADA", amount=100.0, entry_price=100.0, current_price=105.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []


# =====================================================================
# Trailing stop tests (Feature B)
# =====================================================================

@pytest.mark.asyncio
async def test_trailing_stop_activates_at_threshold():
    """Position at +1.5% should activate trailing stop (threshold is 1%)."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=True,
            trailing_stop=TrailingStopConfig(activation_pct=0.01, distance_pct=0.007),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    positions = {
        "BTC": Position(symbol="BTC", amount=0.1, entry_price=100.0, current_price=101.5)
    }

    trades = await sentinel.check_exit_triggers(positions)

    # No exit yet, but trailing should be activated on the position
    assert trades == []
    assert positions["BTC"].trailing_stop_active is True
    assert positions["BTC"].peak_price == 101.5
    assert positions["BTC"].trailing_stop_price is not None


@pytest.mark.asyncio
async def test_trailing_stop_triggers_sell_on_reversal():
    """Price drops below trailing stop price -> sell."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=True,
            trailing_stop=TrailingStopConfig(activation_pct=0.01, distance_pct=0.007),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    # Position already has trailing stop active with peak at 103.0
    # Trail at 0.7% below peak = 103.0 * 0.993 = 102.279
    positions = {
        "BTC": Position(
            symbol="BTC", amount=0.1, entry_price=100.0, current_price=102.0,
            peak_price=103.0, trailing_stop_active=True,
            trailing_stop_price=round(103.0 * 0.993, 2),
        )
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert len(trades) == 1
    assert trades[0].order_type == OrderType.TRAILING_STOP
    assert trades[0].requested_size_base == 0.1


@pytest.mark.asyncio
async def test_trailing_stop_does_not_trigger_above_trail():
    """Price still above trail -> no exit."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=True,
            trailing_stop=TrailingStopConfig(activation_pct=0.01, distance_pct=0.007),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    # Trail at 102.28, current at 102.50 -> above trail
    positions = {
        "BTC": Position(
            symbol="BTC", amount=0.1, entry_price=100.0, current_price=102.5,
            peak_price=103.0, trailing_stop_active=True,
            trailing_stop_price=round(103.0 * 0.993, 2),
        )
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []


@pytest.mark.asyncio
async def test_trailing_stop_disabled():
    """When trailing is disabled, no activation even at big gains."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(enable_trailing_stop=False),
    )
    sentinel = BasicSentinel(settings=settings)
    # 2% gain, between stop and TP
    positions = {
        "BTC": Position(symbol="BTC", amount=0.1, entry_price=100.0, current_price=102.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []
    assert positions["BTC"].trailing_stop_active is False


# =====================================================================
# Breakeven stop tests (Feature F)
# =====================================================================

@pytest.mark.asyncio
async def test_breakeven_stop_triggers_when_peak_was_above_threshold():
    """Peak was above 0.5% gain, price reverted to entry + buffer -> breakeven exit."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=False,
            enable_breakeven_stop=True,
            breakeven=BreakevenConfig(activation_pct=0.005, buffer_pct=0.001),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    # Peak was 101.0 (1% gain > 0.5% activation), now price dropped to 100.10
    # breakeven_price = 100 * 1.001 = 100.10
    positions = {
        "BTC": Position(
            symbol="BTC", amount=0.1, entry_price=100.0, current_price=100.10,
            peak_price=101.0,
        )
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert len(trades) == 1
    assert trades[0].order_type == OrderType.BREAKEVEN_STOP


@pytest.mark.asyncio
async def test_breakeven_stop_does_not_trigger_if_peak_below_threshold():
    """Peak never reached activation threshold -> no breakeven."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=False,
            enable_breakeven_stop=True,
            breakeven=BreakevenConfig(activation_pct=0.005, buffer_pct=0.001),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    # Peak was only 100.30 (0.3% gain < 0.5% activation)
    positions = {
        "BTC": Position(
            symbol="BTC", amount=0.1, entry_price=100.0, current_price=100.10,
            peak_price=100.30,
        )
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []


@pytest.mark.asyncio
async def test_breakeven_not_active_when_trailing_active():
    """Breakeven should not trigger when trailing stop is already active."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=True,
            enable_breakeven_stop=True,
            trailing_stop=TrailingStopConfig(activation_pct=0.01, distance_pct=0.007),
            breakeven=BreakevenConfig(activation_pct=0.005, buffer_pct=0.001),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    # Trailing is active, price above trail -> no exit at all
    # Trail = 103.0 * 0.993 = 102.279, current = 102.50 (above trail)
    positions = {
        "BTC": Position(
            symbol="BTC", amount=0.1, entry_price=100.0, current_price=102.50,
            peak_price=103.0, trailing_stop_active=True,
            trailing_stop_price=round(103.0 * 0.993, 2),
        )
    }

    trades = await sentinel.check_exit_triggers(positions)

    # No breakeven exit because trailing is active (and price is above trail)
    assert trades == []


# =====================================================================
# Exit priority tests
# =====================================================================

@pytest.mark.asyncio
async def test_trailing_stop_takes_priority_over_fixed_stop():
    """If trailing stop triggers, fixed stop should not also trigger."""
    settings = _make_settings(
        stop_loss_pct=0.025,
        exit_management=ExitManagementConfig(
            enable_trailing_stop=True,
            trailing_stop=TrailingStopConfig(activation_pct=0.01, distance_pct=0.007),
        ),
    )
    sentinel = BasicSentinel(settings=settings)
    # Position has trailing active, trail at 102.28, current at 102.0
    # Both trailing (102.0 < 102.28) and potentially other exits could trigger
    positions = {
        "BTC": Position(
            symbol="BTC", amount=0.1, entry_price=100.0, current_price=102.0,
            peak_price=103.0, trailing_stop_active=True,
            trailing_stop_price=round(103.0 * 0.993, 2),
        )
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert len(trades) == 1
    assert trades[0].order_type == OrderType.TRAILING_STOP


@pytest.mark.asyncio
async def test_position_with_no_entry_price_is_skipped():
    """Positions without entry price should be ignored."""
    sentinel = BasicSentinel()
    positions = {
        "XRP": Position(symbol="XRP", amount=100.0, entry_price=None, current_price=0.5)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []


@pytest.mark.asyncio
async def test_zero_amount_position_is_skipped():
    """Positions with zero amount should be ignored."""
    sentinel = BasicSentinel()
    positions = {
        "BTC": Position(symbol="BTC", amount=0, entry_price=100.0, current_price=90.0)
    }

    trades = await sentinel.check_exit_triggers(positions)

    assert trades == []
