"""
Anomaly Detection Model

Statistical anomaly detection for unusual market conditions:
- Volume spikes
- Price deviations
- Spread widening
- Unusual volatility

Uses a simple statistical approach (z-score based) that
can be replaced with Isolation Forest or other ML models.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import math

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    """Result of anomaly detection"""
    is_anomaly: bool
    score: float  # 0 to 1, >0.8 is anomaly
    anomaly_type: Optional[str]
    features: Dict[str, float]
    description: str
    timestamp: datetime


class AnomalyDetector:
    """
    Statistical anomaly detector for market conditions.

    Detects unusual patterns that may indicate:
    - Flash crashes or pumps
    - Liquidity issues
    - Market manipulation
    - System errors

    Uses z-score based detection with configurable thresholds.
    """

    # Anomaly threshold (z-score)
    ANOMALY_THRESHOLD = 2.5

    # Score thresholds
    HIGH_ANOMALY_SCORE = 0.8
    MEDIUM_ANOMALY_SCORE = 0.6

    def __init__(self, lookback_periods: int = 30):
        """
        Initialize anomaly detector.

        Args:
            lookback_periods: Number of periods for baseline calculation
        """
        self.lookback = lookback_periods
        self._history: Dict[str, List[Dict]] = {}
        self._trained = False

        logger.info(f"AnomalyDetector initialized (lookback: {lookback_periods})")

    def fit(self, historical_data: List[Dict]) -> None:
        """
        Train detector on historical data.

        Args:
            historical_data: List of {volume, price, spread, volatility} dicts
        """
        if len(historical_data) < self.lookback:
            logger.warning("Insufficient data for training")
            return

        self._history["training"] = historical_data[-self.lookback * 2:]
        self._trained = True
        logger.info(f"AnomalyDetector trained on {len(historical_data)} samples")

    def detect(
        self,
        current: Dict,
        pair: str = None
    ) -> AnomalyResult:
        """
        Detect anomalies in current market conditions.

        Args:
            current: Current market data with volume, price, spread
            pair: Optional pair identifier

        Returns:
            AnomalyResult with anomaly score and type
        """
        features = {}
        anomaly_scores = []
        anomaly_types = []

        # Extract features
        volume = current.get("volume", 0)
        price = current.get("price", 0)
        spread = current.get("spread", 0)
        volatility = current.get("volatility", 0)
        price_change = current.get("price_change", 0)

        # Get historical baseline
        history = self._history.get(pair, self._history.get("training", []))

        if not history:
            # No history - can't detect anomalies
            return AnomalyResult(
                is_anomaly=False,
                score=0.0,
                anomaly_type=None,
                features={},
                description="Insufficient history for anomaly detection",
                timestamp=datetime.now(timezone.utc)
            )

        # Check volume anomaly
        if volume > 0:
            vol_score = self._check_volume_anomaly(volume, history)
            features["volume_zscore"] = vol_score
            if vol_score > self.ANOMALY_THRESHOLD:
                anomaly_scores.append(vol_score / 4)  # Normalize
                anomaly_types.append("volume_spike")

        # Check price deviation
        if price_change:
            price_score = self._check_price_anomaly(price_change, history)
            features["price_zscore"] = price_score
            if price_score > self.ANOMALY_THRESHOLD:
                anomaly_scores.append(price_score / 4)
                anomaly_types.append("price_deviation")

        # Check spread widening
        if spread > 0:
            spread_score = self._check_spread_anomaly(spread, price, history)
            features["spread_zscore"] = spread_score
            if spread_score > self.ANOMALY_THRESHOLD:
                anomaly_scores.append(spread_score / 4)
                anomaly_types.append("spread_widening")

        # Check volatility spike
        if volatility > 0:
            vol_score = self._check_volatility_anomaly(volatility, history)
            features["volatility_zscore"] = vol_score
            if vol_score > self.ANOMALY_THRESHOLD:
                anomaly_scores.append(vol_score / 4)
                anomaly_types.append("volatility_spike")

        # Calculate overall anomaly score
        if anomaly_scores:
            overall_score = min(1.0, max(anomaly_scores))
        else:
            overall_score = 0.0

        is_anomaly = overall_score >= self.HIGH_ANOMALY_SCORE
        primary_type = anomaly_types[0] if anomaly_types else None

        # Build description
        if is_anomaly:
            description = f"Anomaly detected: {', '.join(anomaly_types)}"
        elif overall_score >= self.MEDIUM_ANOMALY_SCORE:
            description = f"Elevated anomaly score: {', '.join(anomaly_types)}"
        else:
            description = "Normal market conditions"

        # Update history for this pair
        if pair:
            if pair not in self._history:
                self._history[pair] = []
            self._history[pair].append(current)
            # Keep only recent history
            if len(self._history[pair]) > self.lookback * 2:
                self._history[pair] = self._history[pair][-self.lookback * 2:]

        return AnomalyResult(
            is_anomaly=is_anomaly,
            score=round(overall_score, 4),
            anomaly_type=primary_type,
            features=features,
            description=description,
            timestamp=datetime.now(timezone.utc)
        )

    def _check_volume_anomaly(self, current: float, history: List[Dict]) -> float:
        """Calculate z-score for volume"""
        volumes = [h.get("volume", 0) for h in history if h.get("volume", 0) > 0]
        return self._calculate_zscore(current, volumes)

    def _check_price_anomaly(self, change: float, history: List[Dict]) -> float:
        """Calculate z-score for price change"""
        changes = [h.get("price_change", 0) for h in history]
        return self._calculate_zscore(abs(change), [abs(c) for c in changes])

    def _check_spread_anomaly(self, spread: float, price: float, history: List[Dict]) -> float:
        """Calculate z-score for spread (as % of price)"""
        spread_pct = spread / price if price > 0 else 0
        spreads = []
        for h in history:
            h_spread = h.get("spread", 0)
            h_price = h.get("price", 1)
            if h_price > 0:
                spreads.append(h_spread / h_price)
        return self._calculate_zscore(spread_pct, spreads)

    def _check_volatility_anomaly(self, volatility: float, history: List[Dict]) -> float:
        """Calculate z-score for volatility"""
        vols = [h.get("volatility", 0) for h in history if h.get("volatility", 0) > 0]
        return self._calculate_zscore(volatility, vols)

    def _calculate_zscore(self, value: float, baseline: List[float]) -> float:
        """Calculate z-score for a value against baseline"""
        if not baseline or len(baseline) < 2:
            return 0.0

        mean = sum(baseline) / len(baseline)
        variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
        std = math.sqrt(variance) if variance > 0 else 1

        if std == 0:
            return 0.0

        return abs((value - mean) / std)

    def save_model(self, path: str) -> None:
        """Save trained model to disk"""
        import json
        with open(path, 'w') as f:
            json.dump({
                "history": self._history,
                "trained": self._trained,
                "lookback": self.lookback
            }, f)
        logger.info(f"Model saved to {path}")

    def load_model(self, path: str) -> None:
        """Load trained model from disk"""
        import json
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self._history = data.get("history", {})
            self._trained = data.get("trained", False)
            self.lookback = data.get("lookback", 30)
            logger.info(f"Model loaded from {path}")
        except FileNotFoundError:
            logger.warning(f"Model file not found: {path}")
