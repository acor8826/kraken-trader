from integrations.exchanges.kraken import KrakenExchange
from integrations.exchanges.binance import BinanceExchange
from integrations.exchanges.base import MockExchange


def create_exchange(name: str = "binance", **kwargs):
    """Factory: create an exchange instance by name.

    Args:
        name: ``"binance"`` (default), ``"kraken"``, or ``"mock"``.
        **kwargs: passed through to the exchange constructor.

    Returns:
        An IExchange implementation.
    """
    name = name.lower()
    if name == "binance":
        return BinanceExchange(**kwargs)
    elif name == "kraken":
        return KrakenExchange(**kwargs)
    elif name == "mock":
        return MockExchange(**kwargs)
    else:
        raise ValueError(f"Unknown exchange: {name!r}. Supported: binance, kraken, mock")
