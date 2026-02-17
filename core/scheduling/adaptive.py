"""
Adaptive Scheduler

Adjusts trading cycle frequency based on portfolio size and market conditions.
Reduces API costs for smaller portfolios by checking less frequently.

Portfolio Tiers:
- Micro (<$500): 2 hour intervals - ~$1/month API cost
- Small ($500-$2K): 1 hour intervals - ~$3/month API cost
- Medium ($2K-$10K): 30 min intervals - ~$6/month API cost
- Large (>$10K): 15 min intervals - ~$12/month API cost
"""

from dataclasses import dataclass
from typing import Optional, Callable, Any
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class PortfolioTier:
    """Defines a portfolio size tier and its associated settings."""
    name: str
    min_value: float
    max_value: float
    check_interval_minutes: int
    description: str

    def __contains__(self, value: float) -> bool:
        """Check if a portfolio value falls within this tier."""
        return self.min_value <= value < self.max_value


# Default tier configuration optimized for cost savings
DEFAULT_TIERS = [
    PortfolioTier(
        name="micro",
        min_value=0,
        max_value=500,
        check_interval_minutes=120,  # 2 hours
        description="Micro portfolio - minimal API usage"
    ),
    PortfolioTier(
        name="small",
        min_value=500,
        max_value=2000,
        check_interval_minutes=60,  # 1 hour
        description="Small portfolio - hourly checks"
    ),
    PortfolioTier(
        name="medium",
        min_value=2000,
        max_value=10000,
        check_interval_minutes=30,  # 30 min
        description="Medium portfolio - standard frequency"
    ),
    PortfolioTier(
        name="large",
        min_value=10000,
        max_value=float('inf'),
        check_interval_minutes=15,  # 15 min
        description="Large portfolio - high frequency"
    )
]


class AdaptiveScheduler:
    """
    Manages trading cycle scheduling based on portfolio value.

    Automatically adjusts the check interval when portfolio value changes
    between tiers. Designed to reduce API costs for smaller portfolios
    while maintaining responsiveness for larger ones.
    """

    def __init__(
        self,
        tiers: list[PortfolioTier] = None,
        on_interval_change: Optional[Callable[[int, int, str], None]] = None,
        min_interval_minutes: int = 5,
        max_interval_minutes: int = 240
    ):
        """
        Initialize adaptive scheduler.

        Args:
            tiers: List of portfolio tiers (uses DEFAULT_TIERS if None)
            on_interval_change: Callback when interval changes (old, new, tier_name)
            min_interval_minutes: Minimum allowed interval
            max_interval_minutes: Maximum allowed interval
        """
        self.tiers = tiers or DEFAULT_TIERS
        self.on_interval_change = on_interval_change
        self.min_interval = min_interval_minutes
        self.max_interval = max_interval_minutes

        self._current_tier: Optional[PortfolioTier] = None
        self._current_interval: int = 60  # Default 1 hour
        self._last_portfolio_value: float = 0
        self._last_adjustment: Optional[datetime] = None

        # Statistics
        self._tier_changes: int = 0
        self._total_cycles: int = 0

    @property
    def current_interval(self) -> int:
        """Get current check interval in minutes."""
        return self._current_interval

    @property
    def current_tier_name(self) -> str:
        """Get current tier name."""
        return self._current_tier.name if self._current_tier else "unknown"

    def get_tier(self, portfolio_value: float) -> PortfolioTier:
        """
        Get the tier for a given portfolio value.

        Args:
            portfolio_value: Total portfolio value

        Returns:
            The matching PortfolioTier
        """
        for tier in self.tiers:
            if portfolio_value in tier:
                return tier

        # Fallback to largest tier
        return self.tiers[-1]

    def calculate_interval(
        self,
        portfolio_value: float,
        volatility_multiplier: float = 1.0
    ) -> int:
        """
        Calculate the appropriate check interval.

        Args:
            portfolio_value: Current portfolio value
            volatility_multiplier: Optional volatility adjustment (0.5-2.0)
                - < 1.0: More frequent checks (higher volatility)
                - > 1.0: Less frequent checks (lower volatility)

        Returns:
            Check interval in minutes
        """
        tier = self.get_tier(portfolio_value)
        base_interval = tier.check_interval_minutes

        # Apply volatility adjustment
        adjusted = int(base_interval * volatility_multiplier)

        # Clamp to allowed range
        return max(self.min_interval, min(self.max_interval, adjusted))

    def should_adjust(self, portfolio_value: float) -> bool:
        """
        Check if the interval should be adjusted.

        Returns True if portfolio has moved to a different tier.
        """
        new_tier = self.get_tier(portfolio_value)
        return new_tier != self._current_tier

    def adjust_interval(
        self,
        portfolio_value: float,
        volatility_multiplier: float = 1.0
    ) -> tuple[bool, int]:
        """
        Adjust the check interval based on portfolio value.

        Args:
            portfolio_value: Current portfolio value
            volatility_multiplier: Optional volatility adjustment

        Returns:
            Tuple of (changed: bool, new_interval: int)
        """
        new_tier = self.get_tier(portfolio_value)
        new_interval = self.calculate_interval(portfolio_value, volatility_multiplier)

        changed = False
        old_interval = self._current_interval

        if new_tier != self._current_tier:
            old_tier_name = self._current_tier.name if self._current_tier else "none"
            logger.info(
                f"[ADAPTIVE] Portfolio tier change: {old_tier_name} -> {new_tier.name} "
                f"(value: ${portfolio_value:.2f})"
            )
            logger.info(
                f"[ADAPTIVE] Interval change: {old_interval} -> {new_interval} minutes"
            )

            self._current_tier = new_tier
            self._tier_changes += 1
            changed = True

            # Fire callback if registered
            if self.on_interval_change:
                self.on_interval_change(old_interval, new_interval, new_tier.name)

        self._current_interval = new_interval
        self._last_portfolio_value = portfolio_value
        self._last_adjustment = datetime.now()

        return changed, new_interval

    def get_next_cycle_time(self) -> datetime:
        """Calculate when the next trading cycle should run."""
        return datetime.now() + timedelta(minutes=self._current_interval)

    def record_cycle(self):
        """Record that a trading cycle has completed."""
        self._total_cycles += 1

    def get_stats(self) -> dict:
        """Get scheduler statistics."""
        return {
            "current_tier": self.current_tier_name,
            "current_interval_minutes": self._current_interval,
            "last_portfolio_value": self._last_portfolio_value,
            "tier_changes": self._tier_changes,
            "total_cycles": self._total_cycles,
            "last_adjustment": self._last_adjustment.isoformat() if self._last_adjustment else None
        }

    def get_estimated_monthly_cost(self, cost_per_call: float = 0.002) -> float:
        """
        Estimate monthly API cost based on current interval.

        Args:
            cost_per_call: Estimated cost per Claude API call (~$0.002 for Sonnet)

        Returns:
            Estimated monthly cost in dollars
        """
        # Calls per day = 24 * 60 / interval_minutes
        calls_per_day = (24 * 60) / self._current_interval
        # Monthly = daily * 30
        calls_per_month = calls_per_day * 30
        return calls_per_month * cost_per_call


class VolatilityAwareScheduler(AdaptiveScheduler):
    """
    Extended scheduler that also considers market volatility.

    More frequent checks during high volatility,
    less frequent during calm markets.
    """

    def __init__(
        self,
        tiers: list[PortfolioTier] = None,
        volatility_low_threshold: float = 0.02,  # 2% daily
        volatility_high_threshold: float = 0.08,  # 8% daily
        **kwargs
    ):
        super().__init__(tiers, **kwargs)
        self.volatility_low = volatility_low_threshold
        self.volatility_high = volatility_high_threshold
        self._current_volatility: float = 0.0

    def calculate_volatility_multiplier(self, volatility: float) -> float:
        """
        Calculate interval multiplier based on volatility.

        Low volatility -> higher multiplier (less frequent)
        High volatility -> lower multiplier (more frequent)
        """
        if volatility <= self.volatility_low:
            return 1.5  # 50% longer intervals
        elif volatility >= self.volatility_high:
            return 0.5  # 50% shorter intervals
        else:
            # Linear interpolation
            range_size = self.volatility_high - self.volatility_low
            position = (volatility - self.volatility_low) / range_size
            return 1.5 - position  # 1.5 -> 0.5

    def adjust_interval_with_volatility(
        self,
        portfolio_value: float,
        market_volatility: float
    ) -> tuple[bool, int]:
        """
        Adjust interval considering both portfolio and volatility.

        Args:
            portfolio_value: Current portfolio value
            market_volatility: Current market volatility (as decimal, e.g., 0.05 for 5%)

        Returns:
            Tuple of (changed: bool, new_interval: int)
        """
        self._current_volatility = market_volatility
        multiplier = self.calculate_volatility_multiplier(market_volatility)

        return self.adjust_interval(portfolio_value, multiplier)

    def get_stats(self) -> dict:
        """Get scheduler statistics including volatility."""
        stats = super().get_stats()
        stats["current_volatility"] = self._current_volatility
        stats["volatility_multiplier"] = self.calculate_volatility_multiplier(self._current_volatility)
        return stats
