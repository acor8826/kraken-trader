"""
Intelligence Fusion

Combines signals from multiple analysts into unified market intelligence.
Stage 1: Passthrough (single analyst)
Stage 2+: Weighted fusion with disagreement detection
Stage 3: Regime-aware adaptive weights
"""

from typing import List, Dict, Optional
import logging
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models import AnalystSignal, MarketIntel, MarketData, Regime
from core.ml.regime_classifier import RegimeClassifier, MarketRegime

logger = logging.getLogger(__name__)


class IntelligenceFusion:
    """
    Fuses signals from multiple analysts into unified intelligence.

    Features:
    - Weighted combination of signals
    - Disagreement detection
    - Regime detection (Stage 3)
    - Regime-aware adaptive weights (Stage 3)
    """

    # Default regime-specific weight adjustments
    REGIME_WEIGHTS = {
        MarketRegime.TRENDING_UP: {
            "technical": 0.50,  # Increased in trends
            "sentiment": 0.20,
            "onchain": 0.15,
            "macro": 0.10,
            "orderbook": 0.05
        },
        MarketRegime.TRENDING_DOWN: {
            "technical": 0.50,
            "sentiment": 0.20,
            "onchain": 0.15,
            "macro": 0.10,
            "orderbook": 0.05
        },
        MarketRegime.RANGING: {
            "technical": 0.25,
            "sentiment": 0.25,
            "onchain": 0.20,
            "macro": 0.10,
            "orderbook": 0.20  # Increased for timing
        },
        MarketRegime.VOLATILE: {
            "technical": 0.25,
            "sentiment": 0.20,
            "onchain": 0.25,  # Increased for whale activity
            "macro": 0.15,
            "orderbook": 0.15
        }
    }

    def __init__(self, analysts: List[IAnalyst] = None, enable_regime_weights: bool = True):
        self.analysts = analysts or []
        self._custom_weights: Dict[str, float] = {}
        self._enable_regime_weights = enable_regime_weights
        self._regime_classifier = RegimeClassifier()
        self._current_regime = MarketRegime.UNKNOWN
    
    def add_analyst(self, analyst: IAnalyst) -> None:
        """Add an analyst to the fusion"""
        self.analysts.append(analyst)
        logger.info(f"Added analyst: {analyst.name} (weight: {analyst.weight})")
    
    def set_weight(self, analyst_name: str, weight: float) -> None:
        """Override weight for an analyst"""
        self._custom_weights[analyst_name] = weight
    
    def _get_weight(self, analyst: IAnalyst, regime: MarketRegime = None) -> float:
        """
        Get weight for an analyst.

        Priority:
        1. Custom weights (manually set)
        2. Regime-specific weights (if regime detection enabled)
        3. Default analyst weight
        """
        # Check custom weights first
        if analyst.name in self._custom_weights:
            return self._custom_weights[analyst.name]

        # Check regime-specific weights
        if self._enable_regime_weights and regime and regime in self.REGIME_WEIGHTS:
            regime_weights = self.REGIME_WEIGHTS[regime]
            if analyst.name in regime_weights:
                return regime_weights[analyst.name]

        # Fall back to default
        return analyst.weight
    
    async def analyze(self, pair: str, market_data: MarketData) -> MarketIntel:
        """
        Run all analysts and fuse their signals.
        """
        if not self.analysts:
            logger.warning("No analysts configured")
            return MarketIntel(
                pair=pair,
                signals=[],
                fused_direction=0.0,
                fused_confidence=0.0
            )

        # Detect regime FIRST (Stage 3) - affects fusion weights
        regime = self._detect_regime(market_data)
        self._current_regime = self._regime_to_market_regime(regime)

        if self._enable_regime_weights and self._current_regime != MarketRegime.UNKNOWN:
            logger.info(f"[{pair}] Regime: {self._current_regime.value} - adjusting analyst weights")

        # Collect signals from all analysts
        signals: List[AnalystSignal] = []
        for analyst in self.analysts:
            try:
                signal = await analyst.analyze(pair, market_data)
                signals.append(signal)
                logger.debug(f"[{analyst.name}] {pair}: {signal.direction:+.2f}")
            except Exception as e:
                logger.error(f"Analyst {analyst.name} failed: {e}")

        if not signals:
            return MarketIntel(
                pair=pair,
                signals=[],
                fused_direction=0.0,
                fused_confidence=0.0
            )

        # Fuse signals with regime-aware weights
        fused = self._fuse_signals(signals, regime=self._current_regime)

        return MarketIntel(
            pair=pair,
            signals=signals,
            fused_direction=fused["direction"],
            fused_confidence=fused["confidence"],
            disagreement=fused["disagreement"],
            regime=regime
        )

    def _regime_to_market_regime(self, regime: Regime) -> MarketRegime:
        """Convert core Regime enum to ML MarketRegime enum"""
        mapping = {
            Regime.TRENDING_UP: MarketRegime.TRENDING_UP,
            Regime.TRENDING_DOWN: MarketRegime.TRENDING_DOWN,
            Regime.RANGING: MarketRegime.RANGING,
            Regime.VOLATILE: MarketRegime.VOLATILE,
            Regime.UNKNOWN: MarketRegime.UNKNOWN
        }
        return mapping.get(regime, MarketRegime.UNKNOWN)
    
    def _fuse_signals(
        self,
        signals: List[AnalystSignal],
        regime: MarketRegime = None
    ) -> Dict:
        """
        Fuse multiple signals using weighted average.

        Args:
            signals: List of analyst signals
            regime: Current market regime for weight adjustment

        Returns:
            {
                "direction": float (-1 to 1),
                "confidence": float (0 to 1),
                "disagreement": float (0 to 1)
            }
        """
        if not signals:
            return {"direction": 0.0, "confidence": 0.0, "disagreement": 0.0}

        if len(signals) == 1:
            # Single analyst - passthrough
            return {
                "direction": signals[0].direction,
                "confidence": signals[0].confidence,
                "disagreement": 0.0
            }

        # Get weights for each signal (regime-aware)
        weights = []
        weight_log = []
        for signal in signals:
            # Find analyst and get regime-aware weight
            analyst_weight = next(
                (self._get_weight(a, regime) for a in self.analysts if a.name == signal.source),
                0.25  # Default weight
            )
            # Adjust by signal confidence (effective weight)
            effective_weight = analyst_weight * signal.confidence
            weights.append(effective_weight)
            weight_log.append(f"{signal.source}:{analyst_weight:.2f}")

        if self._enable_regime_weights and regime:
            logger.debug(f"Regime {regime.value} weights: {', '.join(weight_log)}")

        total_weight = sum(weights)
        if total_weight == 0:
            return {"direction": 0.0, "confidence": 0.0, "disagreement": 1.0}

        # Weighted direction
        fused_direction = sum(
            signal.direction * weight
            for signal, weight in zip(signals, weights)
        ) / total_weight

        # Calculate disagreement (variance of directions)
        directions = [s.direction for s in signals]
        mean_dir = sum(directions) / len(directions)
        variance = sum((d - mean_dir) ** 2 for d in directions) / len(directions)
        disagreement = min(1.0, variance ** 0.5)  # Std dev, clamped to [0,1]

        # Confidence: average of confidences, penalized by disagreement
        avg_confidence = sum(s.confidence for s in signals) / len(signals)
        fused_confidence = avg_confidence * (1 - disagreement * 0.5)

        return {
            "direction": max(-1, min(1, fused_direction)),
            "confidence": max(0, min(1, fused_confidence)),
            "disagreement": disagreement
        }
    
    def _detect_regime(self, market_data: MarketData) -> Regime:
        """
        Detect current market regime using RegimeClassifier.

        Stage 3 feature - uses ML-based classification.
        """
        # Use OHLCV data for regime classification
        ohlcv = market_data.ohlcv if hasattr(market_data, 'ohlcv') else []

        if not ohlcv or len(ohlcv) < 14:
            # Fall back to indicator-based detection
            return self._detect_regime_from_indicators(market_data)

        try:
            # Use the regime classifier
            classification = self._regime_classifier.predict(
                ohlcv=ohlcv,
                indicators=market_data.indicators if hasattr(market_data, 'indicators') else None
            )

            # Map MarketRegime to Regime
            regime_map = {
                MarketRegime.TRENDING_UP: Regime.TRENDING_UP,
                MarketRegime.TRENDING_DOWN: Regime.TRENDING_DOWN,
                MarketRegime.RANGING: Regime.RANGING,
                MarketRegime.VOLATILE: Regime.VOLATILE,
                MarketRegime.UNKNOWN: Regime.UNKNOWN
            }

            result = regime_map.get(classification.regime, Regime.UNKNOWN)
            logger.debug(f"Regime classified: {result.value} (confidence: {classification.confidence:.2f})")
            return result

        except Exception as e:
            logger.warning(f"Regime classification failed: {e}")
            return self._detect_regime_from_indicators(market_data)

    def _detect_regime_from_indicators(self, market_data: MarketData) -> Regime:
        """
        Fallback regime detection using simple indicators.
        Used when OHLCV data is insufficient.
        """
        indicators = market_data.indicators if hasattr(market_data, 'indicators') else {}

        if not indicators:
            return Regime.UNKNOWN

        sma_12 = indicators.get("sma_12")
        sma_24 = indicators.get("sma_24")
        rsi = indicators.get("rsi")
        momentum = indicators.get("momentum")

        # Simple regime detection
        if sma_12 and sma_24:
            sma_diff_pct = (sma_12 - sma_24) / sma_24 * 100 if sma_24 else 0

            if sma_diff_pct > 2:
                return Regime.TRENDING_UP
            elif sma_diff_pct < -2:
                return Regime.TRENDING_DOWN

        # Check for high volatility
        if momentum and abs(momentum) > 5:
            return Regime.VOLATILE

        # Check RSI extremes
        if rsi:
            if rsi < 25 or rsi > 75:
                return Regime.VOLATILE

        return Regime.RANGING
