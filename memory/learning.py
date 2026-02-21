"""
Analyst Performance Tracker

Tracks analyst signal accuracy for adaptive learning.
Records signals with subsequent trade outcomes to measure effectiveness.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class SignalOutcome(Enum):
    """Outcome of a signal vs actual price movement."""
    CORRECT = "correct"
    INCORRECT = "incorrect"
    NEUTRAL = "neutral"  # Signal was HOLD or price unchanged
    PENDING = "pending"  # Not yet evaluated


@dataclass
class SignalRecord:
    """Record of an analyst signal with outcome tracking."""

    analyst: str
    pair: str
    direction: float  # -1 to +1
    confidence: float
    regime: Optional[str]
    timestamp: datetime
    price_at_signal: float

    # Filled in later
    outcome: SignalOutcome = SignalOutcome.PENDING
    price_at_evaluation: Optional[float] = None
    actual_return: Optional[float] = None
    evaluation_timestamp: Optional[datetime] = None

    def evaluate(self, current_price: float) -> None:
        """Evaluate signal accuracy based on current price."""
        if self.price_at_signal <= 0:
            self.outcome = SignalOutcome.NEUTRAL
            return

        self.price_at_evaluation = current_price
        self.actual_return = (current_price - self.price_at_signal) / self.price_at_signal
        self.evaluation_timestamp = datetime.now(timezone.utc)

        # Small moves are neutral
        if abs(self.actual_return) < 0.001:
            self.outcome = SignalOutcome.NEUTRAL
            return

        # Check if direction matched
        price_went_up = self.actual_return > 0
        predicted_up = self.direction > 0

        if price_went_up == predicted_up:
            self.outcome = SignalOutcome.CORRECT
        else:
            self.outcome = SignalOutcome.INCORRECT


@dataclass
class AccuracyMetrics:
    """Accuracy metrics for an analyst."""

    analyst: str
    total_signals: int
    correct_signals: int
    incorrect_signals: int
    neutral_signals: int
    pending_signals: int

    # Per-regime breakdown
    regime_accuracy: Dict[str, float] = field(default_factory=dict)

    # Time-weighted accuracy (recent signals weighted more)
    weighted_accuracy: float = 0.0

    @property
    def accuracy(self) -> float:
        """Overall accuracy (correct / evaluated)."""
        evaluated = self.correct_signals + self.incorrect_signals
        if evaluated == 0:
            return 0.0
        return self.correct_signals / evaluated

    @property
    def evaluated_count(self) -> int:
        """Number of evaluated signals."""
        return self.correct_signals + self.incorrect_signals


class AnalystPerformanceTracker:
    """
    Tracks analyst signal performance for adaptive learning.

    Features:
    - Records all signals with price at signal time
    - Evaluates accuracy after configurable time window
    - Tracks accuracy per analyst per regime
    - Provides accuracy reports for weight optimization
    """

    DEFAULT_EVALUATION_HOURS = 24  # Time to wait before evaluating
    MAX_HISTORY_DAYS = 90  # Keep 90 days of history

    def __init__(
        self,
        evaluation_hours: int = DEFAULT_EVALUATION_HOURS,
        storage=None
    ):
        """
        Initialize performance tracker.

        Args:
            evaluation_hours: Hours to wait before evaluating signals
            storage: Optional persistent storage (IMemory implementation)
        """
        self.evaluation_hours = evaluation_hours
        self.storage = storage

        self._signals: List[SignalRecord] = []
        self._lock = asyncio.Lock()

        logger.info(f"AnalystPerformanceTracker initialized (eval window: {evaluation_hours}h)")

    async def record_signal(
        self,
        analyst: str,
        pair: str,
        direction: float,
        confidence: float,
        price: float,
        regime: Optional[str] = None
    ) -> None:
        """
        Record a new signal for tracking.

        Args:
            analyst: Name of the analyst
            pair: Trading pair
            direction: Signal direction (-1 to +1)
            confidence: Signal confidence (0 to 1)
            price: Current price at signal time
            regime: Current market regime
        """
        async with self._lock:
            record = SignalRecord(
                analyst=analyst,
                pair=pair,
                direction=direction,
                confidence=confidence,
                regime=regime,
                timestamp=datetime.now(timezone.utc),
                price_at_signal=price
            )
            self._signals.append(record)

            # Persist to storage if available
            if self.storage:
                await self._persist_signal(record)

            logger.debug(f"Recorded signal: {analyst} {pair} dir={direction:.2f}")

    async def evaluate_pending_signals(self, price_fetcher) -> int:
        """
        Evaluate pending signals that have passed evaluation window.

        Args:
            price_fetcher: Async function(pair) -> current_price

        Returns:
            Number of signals evaluated
        """
        async with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=self.evaluation_hours)
            evaluated = 0

            for signal in self._signals:
                if signal.outcome != SignalOutcome.PENDING:
                    continue

                if signal.timestamp > cutoff:
                    continue  # Too recent

                try:
                    current_price = await price_fetcher(signal.pair)
                    signal.evaluate(current_price)
                    evaluated += 1

                    if self.storage:
                        await self._update_signal(signal)

                    logger.debug(
                        f"Evaluated {signal.analyst} {signal.pair}: "
                        f"{signal.outcome.value} (return: {signal.actual_return:.2%})"
                    )

                except Exception as e:
                    logger.warning(f"Failed to evaluate signal for {signal.pair}: {e}")

            return evaluated

    def get_accuracy(self, analyst: str, regime: Optional[str] = None) -> float:
        """
        Get accuracy for a specific analyst.

        Args:
            analyst: Analyst name
            regime: Optional regime filter

        Returns:
            Accuracy as float (0 to 1), or 0 if no data
        """
        correct = 0
        total = 0

        for signal in self._signals:
            if signal.analyst != analyst:
                continue
            if regime and signal.regime != regime:
                continue
            if signal.outcome == SignalOutcome.PENDING:
                continue
            if signal.outcome == SignalOutcome.NEUTRAL:
                continue

            total += 1
            if signal.outcome == SignalOutcome.CORRECT:
                correct += 1

        if total == 0:
            return 0.0

        return correct / total

    def get_weighted_accuracy(
        self,
        analyst: str,
        decay_factor: float = 0.95,
        min_signals: int = 10
    ) -> float:
        """
        Get exponentially-weighted accuracy (recent signals weighted more).

        Args:
            analyst: Analyst name
            decay_factor: Weight decay per day (0.95 = 5% decay/day)
            min_signals: Minimum signals required

        Returns:
            Weighted accuracy (0 to 1)
        """
        now = datetime.now(timezone.utc)
        weighted_correct = 0.0
        total_weight = 0.0

        analyst_signals = [
            s for s in self._signals
            if s.analyst == analyst
            and s.outcome not in (SignalOutcome.PENDING, SignalOutcome.NEUTRAL)
        ]

        if len(analyst_signals) < min_signals:
            return 0.0

        for signal in analyst_signals:
            days_old = (now - signal.timestamp).days
            weight = decay_factor ** days_old

            total_weight += weight
            if signal.outcome == SignalOutcome.CORRECT:
                weighted_correct += weight

        if total_weight == 0:
            return 0.0

        return weighted_correct / total_weight

    def get_accuracy_report(self) -> Dict[str, AccuracyMetrics]:
        """
        Get comprehensive accuracy report for all analysts.

        Returns:
            Dict mapping analyst name to AccuracyMetrics
        """
        # Group signals by analyst
        by_analyst: Dict[str, List[SignalRecord]] = {}
        for signal in self._signals:
            if signal.analyst not in by_analyst:
                by_analyst[signal.analyst] = []
            by_analyst[signal.analyst].append(signal)

        # Calculate metrics for each analyst
        report = {}
        for analyst, signals in by_analyst.items():
            correct = sum(1 for s in signals if s.outcome == SignalOutcome.CORRECT)
            incorrect = sum(1 for s in signals if s.outcome == SignalOutcome.INCORRECT)
            neutral = sum(1 for s in signals if s.outcome == SignalOutcome.NEUTRAL)
            pending = sum(1 for s in signals if s.outcome == SignalOutcome.PENDING)

            # Per-regime accuracy
            regime_accuracy = {}
            regimes = set(s.regime for s in signals if s.regime)
            for regime in regimes:
                regime_accuracy[regime] = self.get_accuracy(analyst, regime)

            report[analyst] = AccuracyMetrics(
                analyst=analyst,
                total_signals=len(signals),
                correct_signals=correct,
                incorrect_signals=incorrect,
                neutral_signals=neutral,
                pending_signals=pending,
                regime_accuracy=regime_accuracy,
                weighted_accuracy=self.get_weighted_accuracy(analyst)
            )

        return report

    def get_signal_count(self, analyst: Optional[str] = None) -> int:
        """Get total signal count, optionally filtered by analyst."""
        if analyst:
            return sum(1 for s in self._signals if s.analyst == analyst)
        return len(self._signals)

    async def prune_old_signals(self) -> int:
        """Remove signals older than MAX_HISTORY_DAYS."""
        async with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_HISTORY_DAYS)
            original_count = len(self._signals)

            self._signals = [s for s in self._signals if s.timestamp > cutoff]

            pruned = original_count - len(self._signals)
            if pruned > 0:
                logger.info(f"Pruned {pruned} old signals")

            return pruned

    async def _persist_signal(self, signal: SignalRecord) -> None:
        """Persist signal to storage."""
        if not self.storage:
            return

        try:
            await self.storage.save_signal({
                "analyst": signal.analyst,
                "pair": signal.pair,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "regime": signal.regime,
                "timestamp": signal.timestamp.isoformat(),
                "price_at_signal": signal.price_at_signal,
                "outcome": signal.outcome.value
            })
        except Exception as e:
            logger.error(f"Failed to persist signal: {e}")

    async def _update_signal(self, signal: SignalRecord) -> None:
        """Update signal outcome in storage."""
        if not self.storage:
            return

        try:
            await self.storage.update_signal(
                analyst=signal.analyst,
                timestamp=signal.timestamp,
                outcome=signal.outcome.value,
                actual_return=signal.actual_return
            )
        except Exception as e:
            logger.error(f"Failed to update signal: {e}")

    async def load_from_storage(self) -> int:
        """Load historical signals from storage."""
        if not self.storage:
            return 0

        try:
            records = await self.storage.get_signals(
                limit=10000,
                days=self.MAX_HISTORY_DAYS
            )

            for record in records:
                signal = SignalRecord(
                    analyst=record["analyst"],
                    pair=record["pair"],
                    direction=record["direction"],
                    confidence=record["confidence"],
                    regime=record.get("regime"),
                    timestamp=datetime.fromisoformat(record["timestamp"]),
                    price_at_signal=record["price_at_signal"],
                    outcome=SignalOutcome(record.get("outcome", "pending"))
                )
                self._signals.append(signal)

            logger.info(f"Loaded {len(records)} signals from storage")
            return len(records)

        except Exception as e:
            logger.error(f"Failed to load signals: {e}")
            return 0

    def get_recent_signals(
        self,
        analyst: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent signals as dicts."""
        signals = self._signals
        if analyst:
            signals = [s for s in signals if s.analyst == analyst]

        signals = sorted(signals, key=lambda s: s.timestamp, reverse=True)[:limit]

        return [
            {
                "analyst": s.analyst,
                "pair": s.pair,
                "direction": s.direction,
                "confidence": s.confidence,
                "regime": s.regime,
                "timestamp": s.timestamp.isoformat(),
                "outcome": s.outcome.value,
                "actual_return": s.actual_return
            }
            for s in signals
        ]
