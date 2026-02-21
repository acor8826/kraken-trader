"""
Adaptive Weight Optimizer

Optimizes analyst weights based on historical performance.
More accurate analysts get higher weights.
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

from memory.learning import AnalystPerformanceTracker

logger = logging.getLogger(__name__)


@dataclass
class WeightConfiguration:
    """Configuration for analyst weights."""

    weights: Dict[str, float] = field(default_factory=dict)
    last_optimized: Optional[datetime] = None
    optimization_reason: str = ""
    trades_at_optimization: int = 0

    def get_weight(self, analyst: str, default: float = 0.2) -> float:
        """Get weight for an analyst."""
        return self.weights.get(analyst, default)

    def normalize(self) -> None:
        """Ensure weights sum to 1.0."""
        total = sum(self.weights.values())
        if total > 0 and abs(total - 1.0) > 0.001:
            for analyst in self.weights:
                self.weights[analyst] /= total


@dataclass
class OptimizationResult:
    """Result of weight optimization."""

    success: bool
    old_weights: Dict[str, float]
    new_weights: Dict[str, float]
    reason: str
    trade_count: int
    accuracy_by_analyst: Dict[str, float] = field(default_factory=dict)


class WeightOptimizer:
    """
    Optimizes analyst weights based on performance.

    Features:
    - Requires minimum trades before optimization
    - Uses exponentially-weighted recent performance
    - Bounds weights within min/max range
    - Weights always sum to 1.0
    - Weekly optimization by default
    """

    MIN_TRADES_FOR_OPTIMIZATION = 50
    MIN_WEIGHT = 0.05  # Minimum 5% per analyst
    MAX_WEIGHT = 0.50  # Maximum 50% per analyst
    OPTIMIZATION_INTERVAL_DAYS = 7  # Weekly

    # Weight decay for recent performance
    DECAY_FACTOR = 0.95  # 5% decay per day

    def __init__(
        self,
        performance_tracker: AnalystPerformanceTracker,
        default_weights: Optional[Dict[str, float]] = None,
        min_trades: int = MIN_TRADES_FOR_OPTIMIZATION,
        optimization_interval_days: int = OPTIMIZATION_INTERVAL_DAYS
    ):
        """
        Initialize weight optimizer.

        Args:
            performance_tracker: Tracker for analyst performance
            default_weights: Initial weights per analyst
            min_trades: Minimum trades before optimization
            optimization_interval_days: Days between optimizations
        """
        self.tracker = performance_tracker
        self.min_trades = min_trades
        self.optimization_interval_days = optimization_interval_days

        # Default weights
        self._config = WeightConfiguration(
            weights=default_weights or {
                "technical": 0.30,
                "sentiment": 0.25,
                "onchain": 0.20,
                "macro": 0.15,
                "orderbook": 0.10
            }
        )
        self._config.normalize()

        logger.info(
            f"WeightOptimizer initialized (min_trades: {min_trades}, "
            f"interval: {optimization_interval_days}d)"
        )

    def get_weights(self) -> Dict[str, float]:
        """Get current analyst weights."""
        return self._config.weights.copy()

    def get_weight(self, analyst: str) -> float:
        """Get weight for a specific analyst."""
        return self._config.get_weight(analyst)

    def should_optimize(self) -> bool:
        """Check if optimization should run."""
        # Check trade count
        total_signals = self.tracker.get_signal_count()
        if total_signals < self.min_trades:
            logger.debug(
                f"Not enough trades for optimization: {total_signals}/{self.min_trades}"
            )
            return False

        # Check time since last optimization
        if self._config.last_optimized:
            days_since = (
                datetime.now(timezone.utc) - self._config.last_optimized
            ).days
            if days_since < self.optimization_interval_days:
                logger.debug(
                    f"Optimization not due: {days_since}/{self.optimization_interval_days} days"
                )
                return False

        return True

    def optimize(self, force: bool = False) -> OptimizationResult:
        """
        Optimize weights based on performance.

        Args:
            force: Force optimization even if conditions not met

        Returns:
            OptimizationResult with old/new weights
        """
        old_weights = self._config.weights.copy()
        total_signals = self.tracker.get_signal_count()

        # Check conditions
        if not force and not self.should_optimize():
            return OptimizationResult(
                success=False,
                old_weights=old_weights,
                new_weights=old_weights,
                reason="Conditions not met for optimization",
                trade_count=total_signals
            )

        # Get weighted accuracy for each analyst
        accuracy_by_analyst = {}
        for analyst in self._config.weights.keys():
            accuracy = self.tracker.get_weighted_accuracy(
                analyst=analyst,
                decay_factor=self.DECAY_FACTOR,
                min_signals=10
            )
            accuracy_by_analyst[analyst] = accuracy

        # Calculate new weights based on accuracy
        new_weights = self._calculate_new_weights(accuracy_by_analyst)

        # Update configuration
        self._config.weights = new_weights
        self._config.last_optimized = datetime.now(timezone.utc)
        self._config.trades_at_optimization = total_signals
        self._config.optimization_reason = "Performance-based optimization"

        logger.info(
            f"Weights optimized: {old_weights} -> {new_weights}"
        )

        return OptimizationResult(
            success=True,
            old_weights=old_weights,
            new_weights=new_weights,
            reason="Performance-based optimization",
            trade_count=total_signals,
            accuracy_by_analyst=accuracy_by_analyst
        )

    def _calculate_new_weights(
        self,
        accuracy_by_analyst: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Calculate new weights based on accuracy.

        Uses a formula that gives more weight to accurate analysts
        while respecting min/max bounds.
        """
        new_weights = {}

        # Handle case where all accuracies are 0 (keep current weights)
        total_accuracy = sum(accuracy_by_analyst.values())
        if total_accuracy == 0:
            return self._config.weights.copy()

        # Calculate raw weights proportional to accuracy
        for analyst, accuracy in accuracy_by_analyst.items():
            # Add baseline so all analysts get some weight
            # Formula: 30% baseline + 70% performance-based
            current_weight = self._config.get_weight(analyst)
            baseline = current_weight * 0.3

            if total_accuracy > 0:
                performance_weight = (accuracy / total_accuracy) * 0.7
            else:
                performance_weight = current_weight * 0.7

            raw_weight = baseline + performance_weight
            new_weights[analyst] = raw_weight

        # Apply bounds
        for analyst in new_weights:
            new_weights[analyst] = max(
                self.MIN_WEIGHT,
                min(self.MAX_WEIGHT, new_weights[analyst])
            )

        # Normalize to sum to 1.0
        total = sum(new_weights.values())
        if total > 0:
            for analyst in new_weights:
                new_weights[analyst] /= total

        return new_weights

    def set_weights(self, weights: Dict[str, float]) -> None:
        """
        Manually set weights (for overrides).

        Args:
            weights: New weights dict
        """
        self._config.weights = weights.copy()
        self._config.normalize()
        self._config.optimization_reason = "Manual override"
        logger.info(f"Weights manually set: {self._config.weights}")

    def get_config(self) -> WeightConfiguration:
        """Get current weight configuration."""
        return self._config

    def get_optimization_status(self) -> Dict:
        """Get status of weight optimization."""
        total_signals = self.tracker.get_signal_count()
        days_since = None

        if self._config.last_optimized:
            days_since = (
                datetime.now(timezone.utc) - self._config.last_optimized
            ).days

        return {
            "current_weights": self._config.weights,
            "last_optimized": (
                self._config.last_optimized.isoformat()
                if self._config.last_optimized else None
            ),
            "days_since_optimization": days_since,
            "total_signals": total_signals,
            "min_trades_for_optimization": self.min_trades,
            "optimization_interval_days": self.optimization_interval_days,
            "ready_to_optimize": self.should_optimize(),
            "last_reason": self._config.optimization_reason
        }

    async def run_scheduled_optimization(self) -> Optional[OptimizationResult]:
        """
        Run optimization if due.

        Returns:
            OptimizationResult if optimization ran, None otherwise
        """
        if self.should_optimize():
            return self.optimize()
        return None
