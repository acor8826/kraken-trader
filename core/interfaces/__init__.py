"""
Core Interfaces - The contracts that enable modularity

All agents and components implement these interfaces, allowing
implementations to be swapped without changing dependent code.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime


class IAnalyst(ABC):
    """Interface for market analysts"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this analyst"""
        pass
    
    @property
    @abstractmethod
    def weight(self) -> float:
        """Default weight in intelligence fusion (0.0-1.0)"""
        pass
    
    @abstractmethod
    async def analyze(self, pair: str, market_data: Dict) -> "AnalystSignal":
        """Analyze market and return signal"""
        pass


class IStrategist(ABC):
    """Interface for trading strategist"""
    
    @abstractmethod
    async def create_plan(
        self,
        intel: "MarketIntel",
        portfolio: "Portfolio",
        risk_params: Dict
    ) -> "TradingPlan":
        """Convert market intelligence into trading plan"""
        pass


class IExecutor(ABC):
    """Interface for trade executor"""
    
    @abstractmethod
    async def execute(self, plan: "TradingPlan") -> "ExecutionReport":
        """Execute a trading plan"""
        pass
    
    @abstractmethod
    async def cancel_all(self) -> bool:
        """Cancel all pending orders"""
        pass


class ISentinel(ABC):
    """Interface for risk management sentinel"""
    
    @abstractmethod
    async def validate_plan(self, plan: "TradingPlan", portfolio: "Portfolio") -> "TradingPlan":
        """Validate and filter trading plan against risk rules"""
        pass
    
    @abstractmethod
    async def check_stop_losses(self, positions: Dict) -> List["Trade"]:
        """Check positions for stop-loss triggers, return trades to execute"""
        pass
    
    @abstractmethod
    async def system_healthy(self) -> bool:
        """Check if system is healthy enough to trade"""
        pass
    
    @abstractmethod
    async def emergency_stop(self) -> None:
        """Trigger emergency stop"""
        pass


class IMemory(ABC):
    """Interface for state/memory management"""
    
    @abstractmethod
    async def get_portfolio(self) -> "Portfolio":
        """Get current portfolio state"""
        pass
    
    @abstractmethod
    async def save_portfolio(self, portfolio: "Portfolio") -> None:
        """Save portfolio state"""
        pass
    
    @abstractmethod
    async def record_trade(self, trade: "Trade", intel: Optional["MarketIntel"] = None) -> None:
        """Record executed trade"""
        pass
    
    @abstractmethod
    async def get_trade_history(self, limit: int = 100) -> List["Trade"]:
        """Get recent trade history"""
        pass
    
    @abstractmethod
    async def get_entry_price(self, symbol: str) -> Optional[float]:
        """Get entry price for a position"""
        pass
    
    @abstractmethod
    async def set_entry_price(self, symbol: str, price: float) -> None:
        """Record entry price for a position"""
        pass


class IExchange(ABC):
    """Interface for exchange integrations"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Exchange name"""
        pass
    
    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """Get account balance"""
        pass
    
    @abstractmethod
    async def get_ticker(self, pair: str) -> Dict:
        """Get current ticker data"""
        pass
    
    @abstractmethod
    async def get_ohlcv(self, pair: str, interval: int, limit: int) -> List:
        """Get OHLCV candles"""
        pass
    
    @abstractmethod
    async def market_buy(self, pair: str, amount_quote: float) -> Dict:
        """Execute market buy (amount in quote currency)"""
        pass
    
    @abstractmethod
    async def market_sell(self, pair: str, amount_base: float) -> Dict:
        """Execute market sell (amount in base currency)"""
        pass
    
    @abstractmethod
    async def limit_buy(self, pair: str, amount_quote: float, price: float) -> Dict:
        """Place limit buy order"""
        pass
    
    @abstractmethod
    async def limit_sell(self, pair: str, amount_base: float, price: float) -> Dict:
        """Place limit sell order"""
        pass


class ILLM(ABC):
    """Interface for LLM providers"""
    
    @abstractmethod
    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        """Get completion from LLM"""
        pass
    
    @abstractmethod
    async def complete_json(self, prompt: str, max_tokens: int = 1000) -> Dict:
        """Get JSON completion from LLM"""
        pass


# Forward references for type hints
from core.models.signals import AnalystSignal, MarketIntel
from core.models.trading import Trade, TradingPlan, ExecutionReport
from core.models.portfolio import Portfolio
