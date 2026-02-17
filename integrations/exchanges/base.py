"""
Exchange Integrations - Base and Mock

Base interface for exchanges and a mock implementation for paper trading.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import logging
import time
import random
from datetime import datetime, timezone

from core.interfaces import IExchange
from core.models import MarketData

logger = logging.getLogger(__name__)


class MockExchange(IExchange):
    """
    Paper trading exchange for testing without real money.
    Simulates market conditions and order execution.
    """
    
    def __init__(self, initial_balance: float = 1000.0, quote_currency: str = "AUD"):
        self._balance = {quote_currency: initial_balance}
        self._quote = quote_currency
        self._positions: Dict[str, float] = {}
        self._prices: Dict[str, float] = {
            "BTC": 100000.0,
            "ETH": 5000.0,
            "SOL": 200.0,
            "DOGE": 0.25,
            "SHIB": 0.000035,
            "PEPE": 0.000018,
            "BONK": 0.000045,
            "FLOKI": 0.00032,
            "WIF": 3.50,
        }
        logger.info(f"[MOCK] Exchange initialized with ${initial_balance} {quote_currency}")
    
    @property
    def name(self) -> str:
        return "mock"
    
    async def get_balance(self) -> Dict[str, float]:
        """Get simulated balance"""
        balance = dict(self._balance)
        
        # Add position values
        total = balance.get(self._quote, 0)
        for symbol, amount in self._positions.items():
            if amount > 0:
                balance[symbol] = amount
                total += amount * self._prices.get(symbol, 0)
        
        balance["total"] = total
        return balance
    
    async def get_ticker(self, pair: str) -> Dict:
        """Get simulated ticker"""
        base = pair.split("/")[0]
        price = self._prices.get(base, 1000)
        
        # Add some random movement
        change_pct = random.uniform(-0.02, 0.02)
        self._prices[base] = price * (1 + change_pct)
        
        return {
            "pair": pair,
            "price": self._prices[base],
            "high_24h": self._prices[base] * 1.03,
            "low_24h": self._prices[base] * 0.97,
            "volume_24h": random.uniform(1000000, 10000000)
        }
    
    async def get_ohlcv(self, pair: str, interval: int, limit: int) -> List:
        """Get simulated OHLCV data"""
        base = pair.split("/")[0]
        current_price = self._prices.get(base, 1000)

        candles = []
        price = current_price * 0.95  # Start 5% lower

        for i in range(limit):
            timestamp = int(time.time()) - (limit - i) * interval * 60
            change = random.uniform(-0.01, 0.015)  # Slight upward bias
            open_price = price
            close_price = price * (1 + change)
            high = max(open_price, close_price) * (1 + random.uniform(0, 0.01))
            low = min(open_price, close_price) * (1 - random.uniform(0, 0.01))
            volume = random.uniform(100, 1000)

            candles.append([timestamp, open_price, high, low, close_price, volume])
            price = close_price

        return candles

    async def get_market_data(self, pair: str) -> MarketData:
        """Get comprehensive market data for analysis"""
        ticker = await self.get_ticker(pair)
        ohlcv = await self.get_ohlcv(pair, interval=60, limit=24)

        return MarketData(
            pair=pair,
            current_price=ticker["price"],
            high_24h=ticker["high_24h"],
            low_24h=ticker["low_24h"],
            volume_24h=ticker["volume_24h"],
            ohlcv=ohlcv
        )

    async def market_buy(self, pair: str, amount_quote: float) -> Dict:
        """Simulate market buy"""
        base = pair.split("/")[0]
        price = self._prices.get(base, 1000)
        
        # Check balance
        available = self._balance.get(self._quote, 0)
        if amount_quote > available:
            logger.warning(f"[MOCK] Insufficient balance: {amount_quote} > {available}")
            return {"error": "Insufficient balance"}
        
        # Execute
        amount_base = amount_quote / price
        self._balance[self._quote] = available - amount_quote
        self._positions[base] = self._positions.get(base, 0) + amount_base
        
        logger.info(f"[MOCK] BUY {amount_base:.6f} {base} @ ${price:,.2f} = ${amount_quote:.2f}")

        mock_order_id = f"MOCK-{int(time.time())}"
        return {
            "order_id": mock_order_id,
            "txid": mock_order_id,
            "pair": pair,
            "side": "buy",
            "price": price,
            "volume": amount_base,
            "cost": amount_quote
        }
    
    async def market_sell(self, pair: str, amount_base: float) -> Dict:
        """Simulate market sell"""
        base = pair.split("/")[0]
        price = self._prices.get(base, 1000)
        
        # Check position
        position = self._positions.get(base, 0)
        if amount_base > position:
            amount_base = position  # Sell what we have
        
        if amount_base <= 0:
            logger.warning(f"[MOCK] No {base} to sell")
            return {"error": "No position"}
        
        # Execute
        amount_quote = amount_base * price
        self._positions[base] = position - amount_base
        self._balance[self._quote] = self._balance.get(self._quote, 0) + amount_quote
        
        logger.info(f"[MOCK] SELL {amount_base:.6f} {base} @ ${price:,.2f} = ${amount_quote:.2f}")

        mock_order_id = f"MOCK-{int(time.time())}"
        return {
            "order_id": mock_order_id,
            "txid": mock_order_id,
            "pair": pair,
            "side": "sell",
            "price": price,
            "volume": amount_base,
            "cost": amount_quote
        }
    
    async def limit_buy(self, pair: str, amount_quote: float, price: float) -> Dict:
        """Simulate limit buy (executes immediately in mock)"""
        return await self.market_buy(pair, amount_quote)
    
    async def limit_sell(self, pair: str, amount_base: float, price: float) -> Dict:
        """Simulate limit sell (executes immediately in mock)"""
        return await self.market_sell(pair, amount_base)
