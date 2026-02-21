"""
Meme Sentinel

Isolated risk manager for meme trades with its own budget,
position limits, and circuit breaker.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

from core.interfaces import ISentinel
from core.models import TradingPlan, Portfolio, Trade, TradeAction, TradeStatus
from agents.memetrader.config import MemeConfig

logger = logging.getLogger(__name__)


class MemeSentinel(ISentinel):
    """
    Isolated risk sentinel for meme coin trading.
    Enforces allocation caps, position limits, daily loss limits,
    and circuit breaker on consecutive losses.
    """

    def __init__(self, config: MemeConfig = None):
        self.config = config or MemeConfig()

        # Portfolio context (updated by orchestrator)
        self._total_portfolio_value: float = 0.0
        self._meme_exposure: float = 0.0  # Current value in meme positions
        self._active_positions: int = 0

        # Daily tracking
        self._daily_meme_pnl: float = 0.0
        self._last_reset_date: datetime = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Circuit breaker
        self._consecutive_losses: int = 0
        self._pause_until: Optional[datetime] = None
        self._emergency_stopped: bool = False

        # Stats
        self._total_validations: int = 0
        self._rejections: int = 0
        self._modifications: int = 0

    def update_portfolio_context(
        self,
        total_portfolio_value: float,
        meme_exposure: float,
        active_positions: int,
    ):
        """Update portfolio context for validation decisions."""
        self._total_portfolio_value = total_portfolio_value
        self._meme_exposure = meme_exposure
        self._active_positions = active_positions

    async def validate_plan(
        self, plan: TradingPlan, portfolio: Portfolio
    ) -> TradingPlan:
        """Validate meme trading plan against risk rules."""
        self._check_daily_reset()
        self._total_validations += 1

        for signal in plan.signals:
            # SELL and HOLD always allowed
            if signal.action in (TradeAction.SELL, TradeAction.HOLD):
                signal.approve()
                continue

            # BUY validation
            if signal.action == TradeAction.BUY:
                rejection = self._validate_buy(signal, portfolio)
                if rejection:
                    signal.reject(rejection)
                    self._rejections += 1
                    logger.info(f"[MEME_SENTINEL] Rejected {signal.pair}: {rejection}")
                else:
                    # Check if size needs reduction
                    max_value = self._total_portfolio_value * self.config.max_per_coin_pct
                    trade_value = portfolio.available_quote * signal.size_pct
                    if trade_value > max_value and max_value > 0:
                        original_size = signal.size_pct
                        signal.size_pct = max_value / portfolio.available_quote if portfolio.available_quote > 0 else 0
                        self._modifications += 1
                        logger.info(
                            f"[MEME_SENTINEL] Reduced {signal.pair} size: "
                            f"{original_size:.2%} -> {signal.size_pct:.2%}"
                        )
                    signal.approve()

        return plan

    def _validate_buy(self, signal, portfolio: Portfolio) -> Optional[str]:
        """Validate a BUY signal. Returns rejection reason or None."""
        # Circuit breaker check
        if self._emergency_stopped:
            return "Emergency stop active"

        if self._pause_until:
            if datetime.now(timezone.utc) < self._pause_until:
                remaining = (self._pause_until - datetime.now(timezone.utc)).seconds
                return f"Circuit breaker active ({remaining}s remaining)"
            else:
                # Pause expired
                self._pause_until = None
                self._consecutive_losses = 0
                logger.info("[MEME_SENTINEL] Circuit breaker expired, resuming")

        # Position limit
        if self._active_positions >= self.config.max_simultaneous_positions:
            return f"Max positions reached ({self._active_positions}/{self.config.max_simultaneous_positions})"

        # Allocation cap
        trade_value = portfolio.available_quote * signal.size_pct
        if self._total_portfolio_value > 0:
            max_allocation = self._total_portfolio_value * self.config.max_meme_allocation_pct
            if self._meme_exposure + trade_value > max_allocation:
                return (
                    f"Allocation cap: ${self._meme_exposure:.0f} + ${trade_value:.0f} "
                    f"> ${max_allocation:.0f} ({self.config.max_meme_allocation_pct:.0%})"
                )

        # Daily loss limit
        if self._total_portfolio_value > 0:
            max_daily_loss = self._total_portfolio_value * self.config.daily_meme_loss_limit_pct
            if self._daily_meme_pnl <= -max_daily_loss:
                return f"Daily meme loss limit: ${self._daily_meme_pnl:.0f} <= -${max_daily_loss:.0f}"

        # Minimum trade size
        if trade_value < self.config.min_trade_size_aud:
            return f"Below minimum trade size: ${trade_value:.2f} < ${self.config.min_trade_size_aud}"

        return None

    def record_meme_trade_result(self, pnl: float):
        """Record a meme trade result for circuit breaker tracking."""
        self._check_daily_reset()
        self._daily_meme_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
            logger.info(f"[MEME_SENTINEL] Consecutive losses: {self._consecutive_losses}")

            if self._consecutive_losses >= self.config.consecutive_loss_trigger:
                self._pause_until = datetime.now(timezone.utc) + timedelta(
                    seconds=self.config.circuit_breaker_pause_seconds
                )
                logger.warning(
                    f"[MEME_SENTINEL] Circuit breaker triggered! "
                    f"{self._consecutive_losses} consecutive losses. "
                    f"Pausing until {self._pause_until.isoformat()}"
                )
        else:
            self._consecutive_losses = 0

    async def check_stop_losses(self, positions: Dict) -> List[Trade]:
        """Not used for meme - trailing stops handled by strategist."""
        return []

    async def system_healthy(self) -> bool:
        """Check if meme trading is allowed."""
        if self._emergency_stopped:
            return False

        if self._pause_until and datetime.now(timezone.utc) < self._pause_until:
            return False

        return True

    async def emergency_stop(self) -> None:
        """Permanently pause meme trading until manual resume."""
        self._emergency_stopped = True
        logger.warning("[MEME_SENTINEL] Emergency stop activated!")

    def pause(self):
        """Manually pause meme trading."""
        self._pause_until = datetime.max.replace(tzinfo=timezone.utc)
        logger.info("[MEME_SENTINEL] Manually paused")

    def resume(self):
        """Resume meme trading and reset circuit breaker."""
        self._pause_until = None
        self._emergency_stopped = False
        self._consecutive_losses = 0
        logger.info("[MEME_SENTINEL] Resumed, circuit breaker reset")

    def _check_daily_reset(self):
        """Reset daily counters at midnight UTC."""
        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if today_midnight > self._last_reset_date:
            self._daily_meme_pnl = 0.0
            self._last_reset_date = today_midnight
            logger.info("[MEME_SENTINEL] Daily counters reset")

    def get_status(self) -> Dict:
        """Get complete sentinel status."""
        is_healthy = not self._emergency_stopped
        if self._pause_until and datetime.now(timezone.utc) < self._pause_until:
            is_healthy = False

        return {
            "healthy": is_healthy,
            "emergency_stopped": self._emergency_stopped,
            "paused_until": self._pause_until.isoformat() if self._pause_until else None,
            "consecutive_losses": self._consecutive_losses,
            "daily_meme_pnl": self._daily_meme_pnl,
            "active_positions": self._active_positions,
            "meme_exposure": self._meme_exposure,
            "total_portfolio_value": self._total_portfolio_value,
            "stats": {
                "total_validations": self._total_validations,
                "rejections": self._rejections,
                "modifications": self._modifications,
            },
        }
