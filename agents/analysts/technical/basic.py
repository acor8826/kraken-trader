"""
Technical Analyst Agent

Analyzes price action and technical indicators to generate trading signals.
This is the core analyst for Stage 1.
"""

from typing import Dict, List, Optional
import logging
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models import AnalystSignal, MarketData

logger = logging.getLogger(__name__)


class TechnicalAnalyst(IAnalyst):
    """
    Technical analysis agent.
    
    Stage 1: Basic indicators (SMA, RSI, price action)
    Stage 3: Advanced patterns, multiple timeframes, ML signals
    """
    
    def __init__(self):
        self._weight = 0.40  # 40% weight in fusion
    
    @property
    def name(self) -> str:
        return "technical"
    
    @property
    def weight(self) -> float:
        return self._weight
    
    async def analyze(self, pair: str, market_data: MarketData) -> AnalystSignal:
        """
        Analyze market data and return signal.
        
        Uses:
        - SMA crossovers (12/24)
        - RSI (oversold/overbought)
        - Price momentum
        - Volume confirmation
        """
        # Calculate indicators
        closes = self._extract_closes(market_data.ohlcv)
        volumes = self._extract_volumes(market_data.ohlcv)
        
        sma_12 = self._calculate_sma(closes, 12)
        sma_24 = self._calculate_sma(closes, 24)
        rsi = self._calculate_rsi(closes, 14)
        momentum = self._calculate_momentum(closes, 6)
        volume_trend = self._calculate_volume_trend(volumes)
        
        # Store in market_data for downstream use
        market_data.indicators = {
            "sma_12": sma_12,
            "sma_24": sma_24,
            "rsi": rsi,
            "momentum": momentum,
            "volume_trend": volume_trend
        }
        
        # Generate signal
        direction, confidence, reasoning = self._evaluate_signals(
            price=market_data.current_price,
            sma_12=sma_12,
            sma_24=sma_24,
            rsi=rsi,
            momentum=momentum,
            volume_trend=volume_trend
        )
        
        logger.info(f"[{self.name}] {pair}: direction={direction:+.2f}, confidence={confidence:.2f}")
        
        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            metadata=market_data.indicators
        )
    
    def _extract_closes(self, ohlcv: List) -> List[float]:
        """Extract close prices from OHLCV data"""
        if not ohlcv:
            return []
        return [candle[4] for candle in ohlcv]  # [ts, o, h, l, c, v]
    
    def _extract_volumes(self, ohlcv: List) -> List[float]:
        """Extract volumes from OHLCV data"""
        if not ohlcv:
            return []
        return [candle[5] for candle in ohlcv]
    
    def _calculate_sma(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return None
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return None
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_momentum(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate price momentum (rate of change)"""
        if len(prices) < period:
            return None
        
        old_price = prices[-period]
        current_price = prices[-1]
        
        if old_price == 0:
            return None
        
        return ((current_price - old_price) / old_price) * 100
    
    def _calculate_volume_trend(self, volumes: List[float]) -> Optional[float]:
        """Calculate volume trend (-1 to +1)"""
        if len(volumes) < 6:
            return None
        
        recent_avg = sum(volumes[-3:]) / 3
        older_avg = sum(volumes[-6:-3]) / 3
        
        if older_avg == 0:
            return 0
        
        change = (recent_avg - older_avg) / older_avg
        return max(-1, min(1, change))  # Clamp to [-1, 1]
    
    def _evaluate_signals(
        self,
        price: float,
        sma_12: Optional[float],
        sma_24: Optional[float],
        rsi: Optional[float],
        momentum: Optional[float],
        volume_trend: Optional[float]
    ) -> tuple[float, float, str]:
        """
        Evaluate all signals and return direction, confidence, reasoning.
        
        Returns:
            direction: -1.0 (bearish) to +1.0 (bullish)
            confidence: 0.0 to 1.0
            reasoning: Human-readable explanation
        """
        signals = []
        reasons = []
        
        # 1. SMA Crossover
        if sma_12 is not None and sma_24 is not None:
            if sma_12 > sma_24:
                # Bullish: short-term above long-term
                strength = min((sma_12 - sma_24) / sma_24 * 100, 5) / 5  # Normalize
                signals.append(("sma", 0.5 + strength * 0.5, 0.3))
                reasons.append(f"SMA12 > SMA24 (bullish crossover)")
            else:
                # Bearish
                strength = min((sma_24 - sma_12) / sma_24 * 100, 5) / 5
                signals.append(("sma", -0.5 - strength * 0.5, 0.3))
                reasons.append(f"SMA12 < SMA24 (bearish crossover)")
        
        # 2. Price vs SMAs
        if sma_12 is not None and price > 0:
            if price > sma_12:
                strength = min((price - sma_12) / sma_12 * 100, 3) / 3
                signals.append(("price_sma", 0.4 + strength * 0.5, 0.2))
                reasons.append(f"Price above SMA12")
            else:
                strength = min((sma_12 - price) / sma_12 * 100, 3) / 3
                signals.append(("price_sma", -0.4 - strength * 0.5, 0.2))
                reasons.append(f"Price below SMA12")
        
        # 3. RSI
        if rsi is not None:
            if rsi < 30:
                # Oversold - bullish signal
                strength = (30 - rsi) / 30
                signals.append(("rsi", 0.6 + strength * 0.4, 0.25))
                reasons.append(f"RSI oversold ({rsi:.0f})")
            elif rsi > 70:
                # Overbought - bearish signal
                strength = (rsi - 70) / 30
                signals.append(("rsi", -0.6 - strength * 0.4, 0.25))
                reasons.append(f"RSI overbought ({rsi:.0f})")
            else:
                # Neutral
                signals.append(("rsi", 0, 0.1))
                reasons.append(f"RSI neutral ({rsi:.0f})")
        
        # 4. Momentum
        if momentum is not None:
            if momentum > 3:
                signals.append(("momentum", 0.6, 0.15))
                reasons.append(f"Strong upward momentum ({momentum:+.1f}%)")
            elif momentum < -3:
                signals.append(("momentum", -0.6, 0.15))
                reasons.append(f"Strong downward momentum ({momentum:+.1f}%)")
            else:
                signals.append(("momentum", momentum / 5, 0.1))  # Scale to [-0.6, 0.6]
        
        # 5. Volume confirmation
        if volume_trend is not None:
            if volume_trend > 0.2:
                signals.append(("volume", 0.2, 0.1))
                reasons.append("Increasing volume")
            elif volume_trend < -0.2:
                signals.append(("volume", -0.1, 0.1))
                reasons.append("Decreasing volume")
        
        # Aggregate signals
        if not signals:
            return 0.0, 0.3, "Insufficient data for analysis"

        # Weighted average of directions
        total_weight = sum(s[2] for s in signals)
        direction = sum(s[1] * s[2] for s in signals) / total_weight if total_weight > 0 else 0

        # Confidence based on signal agreement and strength
        signal_values = [s[1] for s in signals]
        avg_magnitude = sum(abs(v) for v in signal_values) / len(signal_values)
        agreement = 1 - (max(signal_values) - min(signal_values)) / 2 if len(signal_values) > 1 else 0.5

        # Require strong directional alignment for high confidence.
        # Count how many signals agree with the overall direction.
        agreeing = sum(1 for v in signal_values if (v > 0.1) == (direction > 0.1)) if abs(direction) > 0.1 else 0
        alignment_ratio = agreeing / len(signal_values) if signal_values else 0

        # Lower base confidence (was +0.25, now +0.10) to reduce spurious BUYs.
        # Weak/mixed signals should fall below the 0.55-0.70 threshold.
        confidence = min(0.9, avg_magnitude * 0.5 + agreement * 0.3 + alignment_ratio * 0.2 + 0.10)

        # Penalize low-magnitude signals -- if no indicator is strongly directional,
        # cap confidence to prevent weak signals from crossing the threshold.
        if avg_magnitude < 0.3:
            confidence = min(confidence, 0.50)

        reasoning = "; ".join(reasons)

        return direction, confidence, reasoning
