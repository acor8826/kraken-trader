import pytest

from agents.executor.simple import SimpleExecutor
from core.models import Trade, TradeAction, TradeStatus


class _FakeExchange:
    async def market_sell(self, pair, amount_base):
        return {"order_id": "sell-1", "price": 105.0}

    async def get_ticker(self, pair):
        return {"price": 105.0}


class _FakeMemory:
    def __init__(self):
        self.recorded = []

    async def record_trade(self, trade, intel=None):
        self.recorded.append(trade)


@pytest.mark.asyncio
async def test_execute_stop_loss_records_successful_sell_trade():
    executor = SimpleExecutor(exchange=_FakeExchange(), memory=_FakeMemory())
    trade = Trade(
        pair="BTC/USDT",
        action=TradeAction.SELL,
        requested_size_base=0.1,
        entry_price=100.0
    )

    report = await executor.execute_stop_loss([trade])

    assert len(report.trades) == 1
    assert report.trades[0].status == TradeStatus.FILLED
    assert len(executor.memory.recorded) == 1
    assert executor.memory.recorded[0].action == TradeAction.SELL
