"""
Adaptive Risk Manager

Dynamically adjusts risk parameters based on recent performance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import logging
from collections import deque

logger = logging.getLogger(__name__)


class RiskMode(Enum):
    """Risk adjustment modes"""
    NORMAL = "normal"
    CAUTIOUS = "cautious"
    DEFENSIVE = "defensive"
    RECOVERY = "recovery"


@dataclass
class TradeResult:
    """Record of a trade result for tracking"""
    timestamp: datetime
    pair: str
    pnl: float
    pnl_percent: float
    is_win: bool


@dataclass
class RiskAdjustment:
    """Record of a risk adjustment"""
    timestamp: datetime
    mode: RiskMode
    reason: str
    position_size_multiplier: float
    confidence_threshold_adjustment: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "mode": self.mode.value,
            "reason": self.reason,
            "position_size_multiplier": self.position_size_multiplier,
            "confidence_threshold_adjustment": self.confidence_threshold_adjustment
        }


@dataclass
class AdaptiveRiskConfig:
    """Configuration for adaptive risk management"""
    enabled: bool = True

    # Consecutive loss thresholds
    cautious_after_losses: int = 2  # 25% reduction
    defensive_after_losses: int = 3  # 50% reduction

    # Position size multipliers
    cautious_multiplier: float = 0.75  # 25% reduction
    defensive_multiplier: float = 0.50  # 50% reduction

    # Confidence adjustments
    drawdown_confidence_increase: float = 0.10  # +10% threshold during drawdown
    drawdown_threshold: float = 0.05  # 5% portfolio drawdown triggers adjustment

    # Recovery settings
    recovery_steps: int = 3  # Gradual recovery over 3 winning trades

    # Lookback window
    lookback_hours: int = 24


class AdaptiveRiskManager:
    """
    Manages dynamic risk adjustments based on recent performance.

    Features:
    - Tracks rolling 24-hour performance
    - Reduces position sizes after consecutive losses
    - Increases confidence threshold during drawdowns
    - Gradual recovery after winning trades
    - Full audit trail of adjustments
    """

    def __init__(self, config: Optional[AdaptiveRiskConfig] = None):
        self.config = config or AdaptiveRiskConfig()
        self.trade_results: deque = deque(maxlen=1000)  # Rolling history
        self.adjustment_history: List[RiskAdjustment] = []

        # Current state
        self._current_mode = RiskMode.NORMAL
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._peak_value = 0.0
        self._current_drawdown = 0.0
        self._recovery_step = 0

    @property
    def current_mode(self) -> RiskMode:
        """Current risk mode"""
        return self._current_mode

    @property
    def position_size_multiplier(self) -> float:
        """Get current position size multiplier"""
        if not self.config.enabled:
            return 1.0

        if self._current_mode == RiskMode.DEFENSIVE:
            return self.config.defensive_multiplier
        elif self._current_mode == RiskMode.CAUTIOUS:
            return self.config.cautious_multiplier
        elif self._current_mode == RiskMode.RECOVERY:
            # Gradual recovery
            base = self.config.cautious_multiplier
            recovery_pct = self._recovery_step / self.config.recovery_steps
            return base + (1.0 - base) * recovery_pct
        return 1.0

    @property
    def confidence_adjustment(self) -> float:
        """Get current confidence threshold adjustment"""
        if not self.config.enabled:
            return 0.0

        if self._current_drawdown > self.config.drawdown_threshold:
            return self.config.drawdown_confidence_increase
        return 0.0

    def record_trade(self, pair: str, pnl: float, pnl_percent: float) -> None:
        """
        Record a trade result and adjust risk if needed.

        Args:
            pair: Trading pair
            pnl: Absolute P&L
            pnl_percent: P&L as percentage
        """
        is_win = pnl > 0
        result = TradeResult(
            timestamp=datetime.now(timezone.utc),
            pair=pair,
            pnl=pnl,
            pnl_percent=pnl_percent,
            is_win=is_win
        )
        self.trade_results.append(result)

        # Update consecutive counts
        if is_win:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            self._consecutive_wins = 0

        # Check for mode changes
        self._update_risk_mode()

        logger.info(
            f"Trade recorded: {pair} pnl={pnl:.2f} ({pnl_percent:.2f}%) | "
            f"Mode: {self._current_mode.value} | "
            f"Consecutive: W={self._consecutive_wins} L={self._consecutive_losses}"
        )

    def update_portfolio_value(self, current_value: float) -> None:
        """
        Update portfolio value for drawdown calculation.

        Args:
            current_value: Current portfolio value
        """
        if current_value > self._peak_value:
            self._peak_value = current_value
            self._current_drawdown = 0.0
        elif self._peak_value > 0:
            self._current_drawdown = (self._peak_value - current_value) / self._peak_value

            if self._current_drawdown > self.config.drawdown_threshold:
                logger.warning(
                    f"Drawdown detected: {self._current_drawdown * 100:.1f}% | "
                    f"Confidence threshold increased by {self.confidence_adjustment * 100:.0f}%"
                )

    def _update_risk_mode(self) -> None:
        """Update risk mode based on recent performance"""
        old_mode = self._current_mode
        new_mode = old_mode
        reason = ""
        recovery_incremented = False

        # Check for defensive mode (3+ consecutive losses)
        if self._consecutive_losses >= self.config.defensive_after_losses:
            new_mode = RiskMode.DEFENSIVE
            reason = f"{self._consecutive_losses} consecutive losses"

        # Check for cautious mode (2 consecutive losses)
        elif self._consecutive_losses >= self.config.cautious_after_losses:
            new_mode = RiskMode.CAUTIOUS
            reason = f"{self._consecutive_losses} consecutive losses"

        # Check for recovery (winning after losses)
        elif self._consecutive_wins > 0 and old_mode in [RiskMode.CAUTIOUS, RiskMode.DEFENSIVE, RiskMode.RECOVERY]:
            self._recovery_step += 1
            recovery_incremented = True

            if self._recovery_step >= self.config.recovery_steps:
                new_mode = RiskMode.NORMAL
                self._recovery_step = 0
                reason = "Recovery complete"
            else:
                new_mode = RiskMode.RECOVERY
                reason = f"Recovery step {self._recovery_step}/{self.config.recovery_steps}"

        # Normal mode
        elif self._consecutive_losses == 0 and old_mode == RiskMode.NORMAL:
            new_mode = RiskMode.NORMAL

        # Record adjustment if mode changed or recovery step incremented
        if new_mode != old_mode or recovery_incremented:
            self._current_mode = new_mode
            adjustment = RiskAdjustment(
                timestamp=datetime.now(timezone.utc),
                mode=new_mode,
                reason=reason,
                position_size_multiplier=self.position_size_multiplier,
                confidence_threshold_adjustment=self.confidence_adjustment
            )
            self.adjustment_history.append(adjustment)

            logger.warning(
                f"Risk mode changed: {old_mode.value} -> {new_mode.value} | "
                f"Reason: {reason} | "
                f"Position multiplier: {self.position_size_multiplier:.2f}"
            )

    def get_adjusted_position_size(self, base_size_pct: float) -> float:
        """
        Get adjusted position size based on current risk mode.

        Args:
            base_size_pct: Base position size as percentage (0.0-1.0)

        Returns:
            Adjusted position size percentage
        """
        return base_size_pct * self.position_size_multiplier

    def get_adjusted_confidence_threshold(self, base_threshold: float) -> float:
        """
        Get adjusted confidence threshold based on drawdown.

        Args:
            base_threshold: Base confidence threshold (0.0-1.0)

        Returns:
            Adjusted confidence threshold
        """
        return min(1.0, base_threshold + self.confidence_adjustment)

    def get_24h_performance(self) -> Dict[str, Any]:
        """
        Get rolling 24-hour performance metrics.

        Returns:
            Dictionary with performance metrics
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.config.lookback_hours)
        recent_trades = [t for t in self.trade_results if t.timestamp > cutoff]

        if not recent_trades:
            return {
                "period_hours": self.config.lookback_hours,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0
            }

        wins = sum(1 for t in recent_trades if t.is_win)
        losses = len(recent_trades) - wins
        total_pnl = sum(t.pnl for t in recent_trades)

        return {
            "period_hours": self.config.lookback_hours,
            "total_trades": len(recent_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(recent_trades) * 100, 1) if recent_trades else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / len(recent_trades), 2) if recent_trades else 0
        }

    def get_status(self) -> Dict[str, Any]:
        """
        Get current adaptive risk status.

        Returns:
            Dictionary with current status
        """
        return {
            "enabled": self.config.enabled,
            "current_mode": self._current_mode.value,
            "position_size_multiplier": round(self.position_size_multiplier, 2),
            "confidence_adjustment": round(self.confidence_adjustment, 2),
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "current_drawdown": round(self._current_drawdown * 100, 1),
            "peak_value": round(self._peak_value, 2),
            "recovery_step": self._recovery_step,
            "recovery_steps_total": self.config.recovery_steps,
            "performance_24h": self.get_24h_performance(),
            "recent_adjustments": [
                a.to_dict() for a in self.adjustment_history[-10:]
            ]
        }

    def reset(self) -> None:
        """Reset to normal mode (use with caution)"""
        self._current_mode = RiskMode.NORMAL
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._recovery_step = 0

        logger.warning("Adaptive risk manager reset to normal mode")
