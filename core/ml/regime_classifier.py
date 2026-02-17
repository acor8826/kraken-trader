"""
Market Regime Classifier

Classifies market conditions into regimes:
- TRENDING_UP: Strong upward momentum
- TRENDING_DOWN: Strong downward momentum
- RANGING: Sideways, mean-reverting
- VOLATILE: High volatility, uncertain direction

Uses technical indicators:
- ADX (Average Directional Index) for trend strength
- ATR (Average True Range) for volatility
- Bollinger Band Width for volatility
- Momentum (ROC) for direction

This is a rule-based classifier that can be replaced with
an ML model (e.g., Random Forest, SVM) for better accuracy.
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classifications"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


@dataclass
class RegimeClassification:
    """Result of regime classification"""
    regime: MarketRegime
    confidence: float  # 0 to 1
    features: Dict[str, float]  # Indicator values used
    reasoning: str
    timestamp: datetime


class RegimeClassifier:
    """
    Classifies market conditions into regimes.

    Uses rule-based classification on technical indicators.
    Can be extended to use ML models for improved accuracy.
    """

    # ADX thresholds for trend strength
    ADX_STRONG_TREND = 25
    ADX_WEAK_TREND = 15

    # ATR/Price ratio thresholds for volatility
    VOLATILITY_HIGH = 0.03  # 3% ATR/price
    VOLATILITY_LOW = 0.01   # 1% ATR/price

    # Bollinger width thresholds
    BB_WIDTH_HIGH = 0.06  # 6% width = high volatility
    BB_WIDTH_LOW = 0.02   # 2% width = low volatility (squeeze)

    # Momentum thresholds
    MOMENTUM_STRONG = 0.03  # 3% change = strong momentum
    MOMENTUM_WEAK = 0.01    # 1% change = weak momentum

    def __init__(self):
        """Initialize regime classifier"""
        logger.info("RegimeClassifier initialized (rule-based)")

    def predict(
        self,
        ohlcv: List[List],
        indicators: Dict[str, float] = None
    ) -> RegimeClassification:
        """
        Predict market regime from price data.

        Args:
            ohlcv: List of [timestamp, open, high, low, close, volume]
            indicators: Optional pre-calculated indicators

        Returns:
            RegimeClassification with regime, confidence, and features
        """
        if not ohlcv or len(ohlcv) < 14:
            return RegimeClassification(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                features={},
                reasoning="Insufficient data for regime classification",
                timestamp=datetime.now(timezone.utc)
            )

        # Calculate indicators if not provided
        if indicators is None:
            indicators = self._calculate_indicators(ohlcv)

        # Extract features
        adx = indicators.get("adx", 20)
        atr_pct = indicators.get("atr_pct", 0.02)
        bb_width = indicators.get("bb_width", 0.04)
        momentum = indicators.get("momentum", 0)
        rsi = indicators.get("rsi", 50)

        features = {
            "adx": adx,
            "atr_pct": atr_pct,
            "bb_width": bb_width,
            "momentum": momentum,
            "rsi": rsi
        }

        # Classify regime
        regime, confidence, reasoning = self._classify(features)

        return RegimeClassification(
            regime=regime,
            confidence=round(confidence, 4),
            features=features,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc)
        )

    def _classify(
        self,
        features: Dict[str, float]
    ) -> Tuple[MarketRegime, float, str]:
        """
        Apply classification rules to determine regime.

        Returns:
            (regime, confidence, reasoning)
        """
        adx = features.get("adx", 20)
        atr_pct = features.get("atr_pct", 0.02)
        bb_width = features.get("bb_width", 0.04)
        momentum = features.get("momentum", 0)
        rsi = features.get("rsi", 50)

        reasons = []

        # Check for high volatility first
        if atr_pct > self.VOLATILITY_HIGH or bb_width > self.BB_WIDTH_HIGH:
            # High volatility - check if trending or chaotic
            if adx > self.ADX_STRONG_TREND:
                # Trending with high volatility
                if momentum > 0:
                    regime = MarketRegime.TRENDING_UP
                    reasons.append(f"Strong uptrend (ADX={adx:.1f})")
                else:
                    regime = MarketRegime.TRENDING_DOWN
                    reasons.append(f"Strong downtrend (ADX={adx:.1f})")
                reasons.append(f"High volatility (ATR={atr_pct*100:.1f}%)")
                confidence = 0.7
            else:
                # High volatility without clear trend = volatile/chaotic
                regime = MarketRegime.VOLATILE
                reasons.append(f"High volatility (ATR={atr_pct*100:.1f}%)")
                reasons.append(f"Weak trend (ADX={adx:.1f})")
                confidence = 0.8

        # Check for strong trend
        elif adx > self.ADX_STRONG_TREND:
            if momentum > self.MOMENTUM_STRONG or (momentum > 0 and rsi > 60):
                regime = MarketRegime.TRENDING_UP
                reasons.append(f"Strong uptrend (ADX={adx:.1f}, momentum={momentum*100:+.1f}%)")
                confidence = 0.85
            elif momentum < -self.MOMENTUM_STRONG or (momentum < 0 and rsi < 40):
                regime = MarketRegime.TRENDING_DOWN
                reasons.append(f"Strong downtrend (ADX={adx:.1f}, momentum={momentum*100:+.1f}%)")
                confidence = 0.85
            else:
                # ADX high but momentum unclear
                regime = MarketRegime.TRENDING_UP if momentum > 0 else MarketRegime.TRENDING_DOWN
                reasons.append(f"Moderate trend (ADX={adx:.1f})")
                confidence = 0.6

        # Check for weak trend (ranging)
        elif adx < self.ADX_WEAK_TREND:
            regime = MarketRegime.RANGING
            reasons.append(f"Weak trend (ADX={adx:.1f})")
            if bb_width < self.BB_WIDTH_LOW:
                reasons.append("Bollinger squeeze (potential breakout)")
                confidence = 0.75
            else:
                reasons.append("Range-bound market")
                confidence = 0.8

        # Moderate ADX - could be either
        else:
            if abs(momentum) > self.MOMENTUM_WEAK:
                if momentum > 0:
                    regime = MarketRegime.TRENDING_UP
                    reasons.append(f"Emerging uptrend (momentum={momentum*100:+.1f}%)")
                else:
                    regime = MarketRegime.TRENDING_DOWN
                    reasons.append(f"Emerging downtrend (momentum={momentum*100:+.1f}%)")
                confidence = 0.6
            else:
                regime = MarketRegime.RANGING
                reasons.append("Uncertain direction, favoring range")
                confidence = 0.5

        return regime, confidence, "; ".join(reasons)

    def _calculate_indicators(self, ohlcv: List[List]) -> Dict[str, float]:
        """
        Calculate technical indicators from OHLCV data.

        Args:
            ohlcv: List of [timestamp, open, high, low, close, volume]

        Returns:
            Dictionary of indicator values
        """
        if len(ohlcv) < 14:
            return {}

        closes = [candle[4] for candle in ohlcv]
        highs = [candle[2] for candle in ohlcv]
        lows = [candle[3] for candle in ohlcv]

        indicators = {}

        # ATR (Average True Range) as percentage of price
        atr = self._calculate_atr(highs, lows, closes, period=14)
        current_price = closes[-1]
        indicators["atr"] = atr
        indicators["atr_pct"] = atr / current_price if current_price > 0 else 0

        # ADX (simplified calculation)
        indicators["adx"] = self._calculate_adx(highs, lows, closes, period=14)

        # Bollinger Band Width
        indicators["bb_width"] = self._calculate_bb_width(closes, period=20)

        # Momentum (Rate of Change)
        if len(closes) >= 10:
            indicators["momentum"] = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
        else:
            indicators["momentum"] = 0

        # RSI
        indicators["rsi"] = self._calculate_rsi(closes, period=14)

        return indicators

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> float:
        """Calculate Average True Range"""
        if len(closes) < period + 1:
            return 0

        true_ranges = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0

        return sum(true_ranges[-period:]) / period

    def _calculate_adx(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> float:
        """
        Calculate simplified ADX (Average Directional Index).

        Full ADX calculation is complex; this is a simplified version
        that estimates trend strength from price action.
        """
        if len(closes) < period + 1:
            return 20  # Default neutral value

        # Calculate directional movements
        plus_dm = []
        minus_dm = []

        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]

            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
                minus_dm.append(0)
            elif down_move > up_move and down_move > 0:
                plus_dm.append(0)
                minus_dm.append(down_move)
            else:
                plus_dm.append(0)
                minus_dm.append(0)

        if len(plus_dm) < period:
            return 20

        # Smooth the DM values
        plus_dm_avg = sum(plus_dm[-period:]) / period
        minus_dm_avg = sum(minus_dm[-period:]) / period

        # Calculate ATR for normalization
        atr = self._calculate_atr(highs, lows, closes, period)
        if atr == 0:
            return 20

        # Calculate +DI and -DI
        plus_di = (plus_dm_avg / atr) * 100
        minus_di = (minus_dm_avg / atr) * 100

        # Calculate DX
        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 20

        dx = abs(plus_di - minus_di) / di_sum * 100

        # ADX is smoothed DX (simplified: just return DX)
        return min(100, max(0, dx))

    def _calculate_bb_width(self, closes: List[float], period: int = 20) -> float:
        """Calculate Bollinger Band width as percentage"""
        if len(closes) < period:
            return 0.04  # Default moderate width

        recent = closes[-period:]
        sma = sum(recent) / period
        variance = sum((x - sma) ** 2 for x in recent) / period
        std = variance ** 0.5

        # BB width = (upper - lower) / middle = 4 * std / sma
        if sma == 0:
            return 0.04

        return (4 * std) / sma

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index"""
        if len(closes) < period + 1:
            return 50  # Neutral

        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]

        gains = [max(0, c) for c in changes[-period:]]
        losses = [max(0, -c) for c in changes[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100 if avg_gain > 0 else 50

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi
