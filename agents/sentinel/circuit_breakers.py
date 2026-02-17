"""
Circuit Breakers - Phase 2 Risk Management

Automatically pauses trading when predefined risk thresholds are breached.

Breaker Types:
1. Daily Loss - Portfolio down >10% from day start → Pause all trading
2. Trade Frequency - >15 trades in 24 hours → Pause new trades
3. Volatility - Asset moves >10% in 1 hour → Pause that pair
4. Consecutive Loss - 3+ losing trades → Reduce position size
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BreakerState:
    """State of a single circuit breaker"""
    triggered: bool = False
    triggered_at: Optional[datetime] = None
    reason: str = ""
    reset_at: Optional[datetime] = None


class CircuitBreakers:
    """
    Circuit breaker management system.

    Automatically trips when risk thresholds are exceeded,
    preventing catastrophic losses.
    """

    def __init__(
        self,
        max_daily_loss_pct: float = 0.10,
        max_daily_trades: int = 15,
        volatility_threshold_pct: float = 0.10,
        consecutive_loss_limit: int = 3
    ):
        """
        Initialize circuit breakers.

        Args:
            max_daily_loss_pct: Max allowed daily loss (0.10 = 10%)
            max_daily_trades: Max trades per 24 hours
            volatility_threshold_pct: Pause pair if moves >this in 1 hour
            consecutive_loss_limit: Number of consecutive losses before trigger
        """
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_trades = max_daily_trades
        self.volatility_threshold_pct = volatility_threshold_pct
        self.consecutive_loss_limit = consecutive_loss_limit

        # Breaker states
        self._breakers: Dict[str, BreakerState] = {
            "daily_loss": BreakerState(),
            "trade_frequency": BreakerState(),
            "volatility": BreakerState(),
            "consecutive_loss": BreakerState()
        }

        # Tracking data
        self._day_start_value: Optional[float] = None
        self._daily_trades: int = 0
        self._consecutive_losses: int = 0
        self._last_reset: datetime = datetime.now(timezone.utc)

        logger.info(
            f"CircuitBreakers initialized: "
            f"max_loss={max_daily_loss_pct:.1%}, "
            f"max_trades={max_daily_trades}, "
            f"volatility={volatility_threshold_pct:.1%}"
        )

    def check_all(
        self,
        portfolio_value: float,
        pair: str = None
    ) -> Tuple[bool, str]:
        """
        Check all circuit breakers.

        Args:
            portfolio_value: Current portfolio total value
            pair: Optional specific trading pair to check

        Returns:
            (can_trade, reason) tuple
        """
        self._maybe_reset_daily()

        # Check each breaker
        for name, breaker in self._breakers.items():
            if breaker.triggered:
                # Check if breaker should auto-reset
                if breaker.reset_at and datetime.now(timezone.utc) > breaker.reset_at:
                    breaker.triggered = False
                    logger.info(f"Circuit breaker auto-reset: {name}")
                else:
                    return False, f"Circuit breaker active: {breaker.reason}"

        return True, ""

    def check_daily_loss(self, current_value: float) -> bool:
        """
        Check daily loss limit.

        Args:
            current_value: Current portfolio value

        Returns:
            True if safe, False if breaker tripped
        """
        # Initialize day start value if needed
        if self._day_start_value is None:
            self._day_start_value = current_value
            logger.info(f"Day start portfolio value: ${current_value:.2f}")
            return True

        # Calculate loss percentage
        loss_pct = (self._day_start_value - current_value) / self._day_start_value

        if loss_pct >= self.max_daily_loss_pct:
            self._trip_breaker(
                "daily_loss",
                f"Daily loss limit reached: {loss_pct:.1%} (limit: {self.max_daily_loss_pct:.1%})",
                reset_tomorrow=True
            )
            return False

        # Log warning if approaching limit
        if loss_pct >= self.max_daily_loss_pct * 0.75:
            logger.warning(
                f"⚠️  Approaching daily loss limit: {loss_pct:.1%} "
                f"(limit: {self.max_daily_loss_pct:.1%})"
            )

        return True

    def record_trade(self, pnl: float = None) -> None:
        """
        Record a trade execution.

        Args:
            pnl: Profit/loss of the trade (if known)
        """
        self._daily_trades += 1

        # Check trade frequency breaker
        if self._daily_trades >= self.max_daily_trades:
            self._trip_breaker(
                "trade_frequency",
                f"Daily trade limit reached: {self._daily_trades}/{self.max_daily_trades}",
                reset_hours=24
            )

        # Check consecutive loss breaker
        if pnl is not None:
            if pnl < 0:
                self._consecutive_losses += 1
                logger.debug(f"Consecutive losses: {self._consecutive_losses}")

                if self._consecutive_losses >= self.consecutive_loss_limit:
                    self._trip_breaker(
                        "consecutive_loss",
                        f"{self._consecutive_losses} consecutive losing trades",
                        reset_on_win=True
                    )
            else:
                # Winning trade - reset counter
                self._consecutive_losses = 0

                # Reset consecutive loss breaker if tripped
                if self._breakers["consecutive_loss"].triggered:
                    self._breakers["consecutive_loss"].triggered = False
                    logger.info("Consecutive loss breaker reset (winning trade)")

    def check_volatility(
        self,
        pair: str,
        price_change_1h_pct: float
    ) -> bool:
        """
        Check volatility threshold.

        Args:
            pair: Trading pair
            price_change_1h_pct: Price change percentage over 1 hour

        Returns:
            True if safe, False if too volatile
        """
        if abs(price_change_1h_pct) >= self.volatility_threshold_pct:
            self._trip_breaker(
                "volatility",
                f"{pair} volatility too high: {price_change_1h_pct:+.1%} in 1 hour",
                reset_hours=1
            )
            return False

        return True

    def _trip_breaker(
        self,
        name: str,
        reason: str,
        reset_tomorrow: bool = False,
        reset_hours: int = None,
        reset_on_win: bool = False
    ) -> None:
        """
        Trip a circuit breaker.

        Args:
            name: Breaker name
            reason: Why it was tripped
            reset_tomorrow: Reset at midnight tomorrow
            reset_hours: Reset after N hours
            reset_on_win: Reset on next winning trade
        """
        now = datetime.now(timezone.utc)

        # Calculate reset time
        reset_at = None
        if reset_tomorrow:
            tomorrow = now.date() + timedelta(days=1)
            reset_at = datetime.combine(tomorrow, datetime.min.time(), timezone.utc)
        elif reset_hours:
            reset_at = now + timedelta(hours=reset_hours)

        # Update breaker state
        self._breakers[name] = BreakerState(
            triggered=True,
            triggered_at=now,
            reason=reason,
            reset_at=reset_at
        )

        logger.warning(f"🔴 CIRCUIT BREAKER TRIPPED: {name} - {reason}")
        if reset_at:
            logger.warning(f"   Will reset at: {reset_at.strftime('%Y-%m-%d %H:%M UTC')}")

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters at midnight UTC"""
        now = datetime.now(timezone.utc)

        if now.date() != self._last_reset.date():
            # New day - reset daily counters
            self._daily_trades = 0
            self._day_start_value = None
            self._last_reset = now

            # Reset daily loss breaker
            self._breakers["daily_loss"].triggered = False

            logger.info("Daily circuit breakers reset (new day)")

    def get_status(self) -> Dict:
        """Get current status of all breakers"""
        return {
            "daily_trades": self._daily_trades,
            "consecutive_losses": self._consecutive_losses,
            "day_start_value": self._day_start_value,
            "breakers": {
                name: {
                    "triggered": breaker.triggered,
                    "reason": breaker.reason,
                    "triggered_at": breaker.triggered_at.isoformat() if breaker.triggered_at else None,
                    "reset_at": breaker.reset_at.isoformat() if breaker.reset_at else None
                }
                for name, breaker in self._breakers.items()
            }
        }

    def reset_breaker(self, name: str) -> bool:
        """Manually reset a specific breaker"""
        if name in self._breakers:
            self._breakers[name].triggered = False
            logger.info(f"Manually reset breaker: {name}")
            return True
        return False

    def reset_all(self) -> None:
        """Manually reset all breakers (emergency use only)"""
        for breaker in self._breakers.values():
            breaker.triggered = False

        logger.warning("⚠️  ALL circuit breakers manually reset!")
