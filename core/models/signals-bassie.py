"""
Signal and Market Intelligence Models

These models represent the output of analysts and the fused intelligence
that feeds into the strategist.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from enum import Enum


class Direction(Enum):
    """Market direction"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Regime(Enum):
    """Market regime"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


@dataclass
class AnalystSignal:
    """
    Standardized output from any analyst.
    All analysts produce this same format, enabling fusion.
    """
    source: str                          # Analyst name (e.g., "technical", "sentiment")
    pair: str                            # Trading pair (e.g., "BTC/AUD")
    direction: float                     # -1.0 (bearish) to +1.0 (bullish)
    confidence: float                    # 0.0 to 1.0
    reasoning: str                       # Human-readable explanation
    timeframe: str = "1h"                # Signal timeframe
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)  # Analyst-specific data
    
    @property
    def is_bullish(self) -> bool:
        return self.direction > 0.2
    
    @property
    def is_bearish(self) -> bool:
        return self.direction < -0.2
    
    @property
    def is_neutral(self) -> bool:
        return -0.2 <= self.direction <= 0.2
    
    def to_dict(self) -> Dict:
        return {
            "source": self.source,
            "pair": self.pair,
            "direction": self.direction,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class MarketData:
    """
    Raw market data for a trading pair.
    Fetched from exchange and passed to analysts.
    """
    pair: str
    current_price: float
    high_24h: float
    low_24h: float
    volume_24h: float
    vwap_24h: Optional[float] = None
    trades_24h: Optional[int] = None
    ohlcv: List[List] = field(default_factory=list)  # [timestamp, o, h, l, c, v]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Computed indicators (populated by technical analyst)
    indicators: Dict[str, float] = field(default_factory=dict)
    
    @property
    def price_change_24h(self) -> Optional[float]:
        if self.ohlcv and len(self.ohlcv) > 0:
            first_close = self.ohlcv[0][4]
            if first_close > 0:
                return ((self.current_price - first_close) / first_close) * 100
        return None
    
    def to_dict(self) -> Dict:
        return {
            "pair": self.pair,
            "current_price": self.current_price,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "volume_24h": self.volume_24h,
            "price_change_24h": self.price_change_24h,
            "indicators": self.indicators,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class MarketIntel:
    """
    Fused intelligence from all analysts.
    This is what the strategist uses to make decisions.
    """
    pair: str
    signals: List[AnalystSignal]
    fused_direction: float               # Weighted combination of signals
    fused_confidence: float              # Overall confidence
    regime: Regime = Regime.UNKNOWN
    disagreement: float = 0.0            # How much analysts disagree (0-1)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def is_actionable(self) -> bool:
        """Is the intel strong enough to act on?"""
        return (
            self.fused_confidence >= 0.5 and
            self.disagreement < 0.5 and
            abs(self.fused_direction) > 0.15
        )

    @property
    def suggested_action(self) -> str:
        if self.fused_direction > 0.15 and self.fused_confidence > 0.5:
            return "BUY"
        elif self.fused_direction < -0.15 and self.fused_confidence > 0.5:
            return "SELL"
        return "HOLD"
    
    def to_summary(self) -> str:
        """Human-readable summary for prompts"""
        signal_summaries = "\n".join([
            f"  - {s.source}: {s.direction:+.2f} (conf: {s.confidence:.0%}) - {s.reasoning}"
            for s in self.signals
        ])
        
        return f"""
Pair: {self.pair}
Regime: {self.regime.value}
Fused Direction: {self.fused_direction:+.2f} ({'bullish' if self.fused_direction > 0 else 'bearish'})
Fused Confidence: {self.fused_confidence:.0%}
Analyst Disagreement: {self.disagreement:.0%}

Individual Signals:
{signal_summaries}
"""
    
    def to_dict(self) -> Dict:
        return {
            "pair": self.pair,
            "fused_direction": self.fused_direction,
            "fused_confidence": self.fused_confidence,
            "regime": self.regime.value,
            "disagreement": self.disagreement,
            "signals": [s.to_dict() for s in self.signals],
            "timestamp": self.timestamp.isoformat()
        }
