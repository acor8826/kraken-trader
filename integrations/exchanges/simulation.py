"""
Enhanced Simulation Exchange

Advanced mock exchange with configurable market scenarios,
slippage, order failures, and realistic price dynamics.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
from collections import deque

from core.interfaces import IExchange
from core.models import MarketData

logger = logging.getLogger(__name__)


class MarketScenario(Enum):
    """Pre-defined market scenarios"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CRASH = "crash"
    RALLY = "rally"


@dataclass
class ScenarioConfig:
    """Configuration for a market scenario"""
    name: str
    trend_direction: float  # -1.0 to +1.0
    volatility: float  # 0.0 to 1.0 (base volatility multiplier)
    mean_reversion: float  # 0.0 to 1.0 (how much to revert to mean)

    @classmethod
    def for_scenario(cls, scenario: MarketScenario) -> "ScenarioConfig":
        """Get config for a pre-defined scenario"""
        configs = {
            MarketScenario.TRENDING_UP: cls(
                name="trending_up",
                trend_direction=0.3,
                volatility=0.5,
                mean_reversion=0.1
            ),
            MarketScenario.TRENDING_DOWN: cls(
                name="trending_down",
                trend_direction=-0.3,
                volatility=0.5,
                mean_reversion=0.1
            ),
            MarketScenario.RANGING: cls(
                name="ranging",
                trend_direction=0.0,
                volatility=0.3,
                mean_reversion=0.8
            ),
            MarketScenario.VOLATILE: cls(
                name="volatile",
                trend_direction=0.0,
                volatility=1.0,
                mean_reversion=0.3
            ),
            MarketScenario.CRASH: cls(
                name="crash",
                trend_direction=-0.8,
                volatility=1.2,
                mean_reversion=0.0
            ),
            MarketScenario.RALLY: cls(
                name="rally",
                trend_direction=0.8,
                volatility=0.8,
                mean_reversion=0.0
            ),
        }
        return configs.get(scenario, configs[MarketScenario.RANGING])


@dataclass
class SimulationConfig:
    """Configuration for the simulation exchange"""
    # Initial state
    initial_balance: float = 1000.0
    quote_currency: str = "AUD"

    # Market scenario
    scenario: MarketScenario = MarketScenario.RANGING

    # Price dynamics
    base_volatility: float = 0.02  # 2% base daily volatility
    price_update_interval_seconds: int = 5

    # Slippage
    slippage_enabled: bool = True
    slippage_pct: float = 0.001  # 0.1% default

    # Order failures
    failure_enabled: bool = True
    failure_rate: float = 0.02  # 2% failure rate

    # Partial fills
    partial_fill_enabled: bool = True
    partial_fill_rate: float = 0.10  # 10% chance of partial fill

    # Custom price overrides
    custom_prices: Dict[str, float] = field(default_factory=dict)


@dataclass
class SimulationStats:
    """Statistics for the simulation session"""
    total_orders: int = 0
    successful_orders: int = 0
    failed_orders: int = 0
    partial_fills: int = 0
    total_slippage: float = 0.0
    price_updates: int = 0
    session_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_orders": self.total_orders,
            "successful_orders": self.successful_orders,
            "failed_orders": self.failed_orders,
            "partial_fills": self.partial_fills,
            "total_slippage": round(self.total_slippage, 4),
            "avg_slippage": round(self.total_slippage / max(self.successful_orders, 1), 4),
            "failure_rate": round(self.failed_orders / max(self.total_orders, 1) * 100, 2),
            "price_updates": self.price_updates,
            "session_duration_hours": round(
                (datetime.now(timezone.utc) - self.session_start).total_seconds() / 3600, 2
            )
        }


class SimulationExchange(IExchange):
    """
    Enhanced simulation exchange with realistic market dynamics.

    Features:
    - Configurable market scenarios (trending, ranging, volatile)
    - Realistic price dynamics with trend and mean reversion
    - Configurable slippage
    - Simulated order failures
    - Partial fill simulation
    - Comprehensive statistics
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        self.config = config or SimulationConfig()
        self._quote = self.config.quote_currency

        # Initialize state
        self._balance = {self._quote: self.config.initial_balance}
        self._positions: Dict[str, float] = {}
        self._entry_prices: Dict[str, float] = {}

        # Price state
        self._base_prices: Dict[str, float] = {
            "BTC": 100000.0,
            "ETH": 5000.0,
            "SOL": 200.0,
            "DOGE": 0.40,
            "AVAX": 45.0,
            "ARB": 1.20,
        }
        self._current_prices: Dict[str, float] = dict(self._base_prices)
        self._price_history: Dict[str, deque] = {
            k: deque(maxlen=1000) for k in self._base_prices
        }

        # Apply custom prices
        self._current_prices.update(self.config.custom_prices)

        # Scenario
        self._scenario_config = ScenarioConfig.for_scenario(self.config.scenario)

        # Statistics
        self.stats = SimulationStats()

        logger.info(
            f"[SIM] Exchange initialized | "
            f"Scenario: {self.config.scenario.value} | "
            f"Balance: ${self.config.initial_balance} | "
            f"Slippage: {self.config.slippage_pct * 100:.1f}% | "
            f"Failure rate: {self.config.failure_rate * 100:.1f}%"
        )

    @property
    def name(self) -> str:
        return "simulation"

    def set_scenario(self, scenario: MarketScenario) -> None:
        """Change the market scenario"""
        self.config.scenario = scenario
        self._scenario_config = ScenarioConfig.for_scenario(scenario)
        logger.info(f"[SIM] Scenario changed to: {scenario.value}")

    def set_slippage(self, pct: float) -> None:
        """Set slippage percentage"""
        self.config.slippage_pct = pct
        logger.info(f"[SIM] Slippage set to: {pct * 100:.2f}%")

    def set_failure_rate(self, rate: float) -> None:
        """Set order failure rate"""
        self.config.failure_rate = rate
        logger.info(f"[SIM] Failure rate set to: {rate * 100:.2f}%")

    def get_config(self) -> Dict[str, Any]:
        """Get current configuration"""
        return {
            "scenario": self.config.scenario.value,
            "base_volatility": self.config.base_volatility,
            "slippage_enabled": self.config.slippage_enabled,
            "slippage_pct": self.config.slippage_pct,
            "failure_enabled": self.config.failure_enabled,
            "failure_rate": self.config.failure_rate,
            "partial_fill_enabled": self.config.partial_fill_enabled,
            "partial_fill_rate": self.config.partial_fill_rate,
        }

    def _update_price(self, base: str) -> float:
        """
        Update price with scenario-based dynamics.

        Returns the new price.
        """
        current = self._current_prices.get(base, 1000)
        base_price = self._base_prices.get(base, current)

        sc = self._scenario_config

        # Calculate price change
        # 1. Random component (volatility)
        volatility = self.config.base_volatility * (1 + sc.volatility)
        random_change = random.gauss(0, volatility)

        # 2. Trend component
        trend_change = sc.trend_direction * self.config.base_volatility * 0.1

        # 3. Mean reversion component
        deviation = (current - base_price) / base_price
        reversion_change = -deviation * sc.mean_reversion * 0.1

        # Combine
        total_change = random_change + trend_change + reversion_change
        new_price = current * (1 + total_change)

        # Clamp to reasonable range (50% - 200% of base)
        new_price = max(base_price * 0.5, min(base_price * 2.0, new_price))

        self._current_prices[base] = new_price
        self._price_history[base].append({
            "price": new_price,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self.stats.price_updates += 1

        return new_price

    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        """Apply slippage to a price"""
        if not self.config.slippage_enabled:
            return price

        slippage = random.uniform(0, self.config.slippage_pct)
        self.stats.total_slippage += slippage

        if is_buy:
            return price * (1 + slippage)  # Pay more
        else:
            return price * (1 - slippage)  # Receive less

    def _should_fail(self) -> bool:
        """Check if order should fail"""
        if not self.config.failure_enabled:
            return False
        return random.random() < self.config.failure_rate

    def _should_partial_fill(self) -> float:
        """Check if order should partially fill, return fill ratio"""
        if not self.config.partial_fill_enabled:
            return 1.0
        if random.random() < self.config.partial_fill_rate:
            return random.uniform(0.5, 0.95)
        return 1.0

    async def get_balance(self) -> Dict[str, float]:
        """Get simulated balance"""
        balance = dict(self._balance)

        # Calculate position values
        total = balance.get(self._quote, 0)
        for symbol, amount in self._positions.items():
            if amount > 0:
                balance[symbol] = amount
                price = self._current_prices.get(symbol, 0)
                total += amount * price

        balance["total"] = total
        return balance

    async def get_ticker(self, pair: str) -> Dict:
        """Get simulated ticker with price update"""
        base = pair.split("/")[0]
        price = self._update_price(base)

        return {
            "pair": pair,
            "price": price,
            "high_24h": price * (1 + self.config.base_volatility),
            "low_24h": price * (1 - self.config.base_volatility),
            "volume_24h": random.uniform(1000000, 10000000),
            "bid": price * (1 - 0.001),
            "ask": price * (1 + 0.001)
        }

    async def get_ohlcv(self, pair: str, interval: int, limit: int) -> List:
        """Get simulated OHLCV data"""
        base = pair.split("/")[0]
        current_price = self._current_prices.get(base, 1000)

        candles = []
        price = current_price * 0.95  # Start 5% lower

        sc = self._scenario_config
        volatility = self.config.base_volatility * (1 + sc.volatility)

        for i in range(limit):
            timestamp = int(time.time()) - (limit - i) * interval * 60

            # Apply scenario dynamics
            trend = sc.trend_direction * volatility * 0.5
            random_change = random.gauss(trend, volatility)

            open_price = price
            close_price = price * (1 + random_change)
            high = max(open_price, close_price) * (1 + random.uniform(0, volatility))
            low = min(open_price, close_price) * (1 - random.uniform(0, volatility))
            volume = random.uniform(100, 1000) * (1 + sc.volatility)

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
        """Simulate market buy with slippage and failure"""
        self.stats.total_orders += 1
        base = pair.split("/")[0]

        # Check for failure
        if self._should_fail():
            self.stats.failed_orders += 1
            logger.warning(f"[SIM] Order FAILED (simulated): BUY {pair}")
            return {"error": "Order failed (simulated)", "code": "SIM_FAILURE"}

        # Get price with slippage
        raw_price = self._current_prices.get(base, 1000)
        price = self._apply_slippage(raw_price, is_buy=True)

        # Check balance
        available = self._balance.get(self._quote, 0)
        if amount_quote > available:
            self.stats.failed_orders += 1
            logger.warning(f"[SIM] Insufficient balance: {amount_quote} > {available}")
            return {"error": "Insufficient balance"}

        # Check for partial fill
        fill_ratio = self._should_partial_fill()
        actual_quote = amount_quote * fill_ratio

        if fill_ratio < 1.0:
            self.stats.partial_fills += 1
            logger.info(f"[SIM] Partial fill: {fill_ratio:.0%} of order")

        # Execute
        amount_base = actual_quote / price
        self._balance[self._quote] = available - actual_quote
        self._positions[base] = self._positions.get(base, 0) + amount_base
        self._entry_prices[base] = price

        self.stats.successful_orders += 1

        logger.info(
            f"[SIM] BUY {amount_base:.6f} {base} @ ${price:,.2f} = ${actual_quote:.2f} | "
            f"Slippage: ${price - raw_price:+.2f}"
        )

        sim_order_id = f"SIM-{int(time.time())}-{random.randint(1000, 9999)}"
        return {
            "order_id": sim_order_id,
            "txid": sim_order_id,
            "pair": pair,
            "side": "buy",
            "price": price,
            "volume": amount_base,
            "cost": actual_quote,
            "fill_ratio": fill_ratio,
            "slippage": price - raw_price
        }

    async def market_sell(self, pair: str, amount_base: float) -> Dict:
        """Simulate market sell with slippage and failure"""
        self.stats.total_orders += 1
        base = pair.split("/")[0]

        # Check for failure
        if self._should_fail():
            self.stats.failed_orders += 1
            logger.warning(f"[SIM] Order FAILED (simulated): SELL {pair}")
            return {"error": "Order failed (simulated)", "code": "SIM_FAILURE"}

        # Check position
        position = self._positions.get(base, 0)
        if amount_base > position:
            amount_base = position

        if amount_base <= 0:
            self.stats.failed_orders += 1
            logger.warning(f"[SIM] No {base} to sell")
            return {"error": "No position"}

        # Get price with slippage
        raw_price = self._current_prices.get(base, 1000)
        price = self._apply_slippage(raw_price, is_buy=False)

        # Check for partial fill
        fill_ratio = self._should_partial_fill()
        actual_base = amount_base * fill_ratio

        if fill_ratio < 1.0:
            self.stats.partial_fills += 1
            logger.info(f"[SIM] Partial fill: {fill_ratio:.0%} of order")

        # Execute
        amount_quote = actual_base * price
        self._positions[base] = position - actual_base
        self._balance[self._quote] = self._balance.get(self._quote, 0) + amount_quote

        self.stats.successful_orders += 1

        logger.info(
            f"[SIM] SELL {actual_base:.6f} {base} @ ${price:,.2f} = ${amount_quote:.2f} | "
            f"Slippage: ${raw_price - price:+.2f}"
        )

        sim_order_id = f"SIM-{int(time.time())}-{random.randint(1000, 9999)}"
        return {
            "order_id": sim_order_id,
            "txid": sim_order_id,
            "pair": pair,
            "side": "sell",
            "price": price,
            "volume": actual_base,
            "cost": amount_quote,
            "fill_ratio": fill_ratio,
            "slippage": raw_price - price
        }

    async def limit_buy(self, pair: str, amount_quote: float, price: float) -> Dict:
        """Simulate limit buy (executes if market price <= limit)"""
        base = pair.split("/")[0]
        market_price = self._current_prices.get(base, 1000)

        if market_price <= price:
            return await self.market_buy(pair, amount_quote)
        else:
            logger.info(f"[SIM] Limit BUY not filled: market ${market_price:,.2f} > limit ${price:,.2f}")
            return {"status": "pending", "pair": pair, "limit_price": price}

    async def limit_sell(self, pair: str, amount_base: float, price: float) -> Dict:
        """Simulate limit sell (executes if market price >= limit)"""
        base = pair.split("/")[0]
        market_price = self._current_prices.get(base, 1000)

        if market_price >= price:
            return await self.market_sell(pair, amount_base)
        else:
            logger.info(f"[SIM] Limit SELL not filled: market ${market_price:,.2f} < limit ${price:,.2f}")
            return {"status": "pending", "pair": pair, "limit_price": price}

    def get_session_report(self) -> Dict[str, Any]:
        """Generate end-of-session report"""
        balance = {}
        for k, v in self._balance.items():
            balance[k] = round(v, 2)

        positions = {}
        pnl_by_position = {}
        for symbol, amount in self._positions.items():
            if amount > 0:
                positions[symbol] = round(amount, 8)
                entry = self._entry_prices.get(symbol, 0)
                current = self._current_prices.get(symbol, 0)
                if entry > 0:
                    pnl_pct = ((current - entry) / entry) * 100
                    pnl_by_position[symbol] = {
                        "entry_price": round(entry, 2),
                        "current_price": round(current, 2),
                        "pnl_percent": round(pnl_pct, 2)
                    }

        return {
            "session_start": self.stats.session_start.isoformat(),
            "session_end": datetime.now(timezone.utc).isoformat(),
            "scenario": self.config.scenario.value,
            "config": self.get_config(),
            "balance": balance,
            "positions": positions,
            "position_pnl": pnl_by_position,
            "statistics": self.stats.to_dict()
        }
