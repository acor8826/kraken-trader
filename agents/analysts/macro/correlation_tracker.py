"""
Cross-Market Correlation Tracker

Tracks correlations between crypto and traditional markets:
- BTC vs S&P500, NASDAQ
- BTC vs Gold
- BTC vs DXY (US Dollar Index)

High correlation with equities = crypto follows stocks
DXY strength = typically bearish for crypto
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from integrations.data.fred import FREDClient

logger = logging.getLogger(__name__)


@dataclass
class CorrelationSignal:
    """Signal from correlation analysis"""
    direction: float  # -1 (risk-off) to +1 (risk-on)
    confidence: float  # 0 to 1
    dxy_impact: str  # "bullish", "bearish", "neutral"
    correlation_regime: str  # "high_equity", "high_gold", "decoupled"
    vix_level: str  # "extreme", "high", "normal", "low"
    reasoning: str


class CorrelationTracker:
    """
    Tracks cross-market correlations for crypto trading signals.

    Key relationships:
    - Strong DXY = bearish for crypto (inverse relationship)
    - High VIX = risk-off = typically bearish for crypto
    - Fed policy tightening = risk-off = bearish for crypto
    """

    def __init__(self, fred_client: FREDClient):
        """
        Initialize correlation tracker.

        Args:
            fred_client: FRED API client for market data
        """
        self.fred = fred_client
        logger.info("CorrelationTracker initialized")

    async def analyze(self) -> CorrelationSignal:
        """
        Analyze cross-market conditions for crypto signal.

        Returns:
            CorrelationSignal with direction, confidence, and reasoning
        """
        # Fetch market data
        dxy = await self.fred.get_dollar_index()
        vix = await self.fred.get_vix()

        # If no data available, return neutral
        if not dxy and not vix:
            return CorrelationSignal(
                direction=0.0,
                confidence=0.0,
                dxy_impact="unknown",
                correlation_regime="unknown",
                vix_level="unknown",
                reasoning="No cross-market data available"
            )

        direction = 0.0
        confidence = 0.0
        reasons = []

        # Analyze DXY (dollar strength)
        dxy_impact = "neutral"
        if dxy:
            dxy_direction = dxy.get("direction", "stable")
            dxy_change = dxy.get("change_pct", 0)

            # Weakening dollar = bullish for crypto
            if dxy_direction == "weakening":
                direction += 0.4
                dxy_impact = "bullish"
                reasons.append(f"DXY weakening ({dxy_change*100:+.1f}%): bullish for crypto")
            elif dxy_direction == "strengthening":
                direction -= 0.4
                dxy_impact = "bearish"
                reasons.append(f"DXY strengthening ({dxy_change*100:+.1f}%): bearish for crypto")
            else:
                reasons.append(f"DXY stable at {dxy.get('value', 'N/A')}")

            confidence += 0.4

        # Analyze VIX (volatility/fear)
        vix_level = "unknown"
        if vix:
            vix_value = vix.get("value", 20)
            vix_level = vix.get("level", "normal")

            # High VIX = fear = risk-off = bearish for crypto
            if vix_level in ["extreme_fear", "high_fear"]:
                direction -= 0.3
                reasons.append(f"VIX high ({vix_value}): risk-off environment")
            elif vix_level == "complacent":
                direction += 0.2
                reasons.append(f"VIX low ({vix_value}): risk-on environment")
            else:
                reasons.append(f"VIX at normal levels ({vix_value})")

            confidence += 0.3

        # Determine correlation regime based on overall conditions
        correlation_regime = self._classify_regime(direction, dxy_impact, vix_level)

        # Clamp values
        direction = max(-1.0, min(1.0, direction))
        confidence = min(1.0, confidence)

        return CorrelationSignal(
            direction=round(direction, 4),
            confidence=round(confidence, 4),
            dxy_impact=dxy_impact,
            correlation_regime=correlation_regime,
            vix_level=vix_level,
            reasoning="; ".join(reasons) if reasons else "Cross-market conditions neutral"
        )

    def _classify_regime(
        self,
        direction: float,
        dxy_impact: str,
        vix_level: str
    ) -> str:
        """Classify the current correlation regime"""
        if vix_level in ["extreme_fear", "high_fear"]:
            return "risk_off"
        elif vix_level == "complacent" and dxy_impact == "bullish":
            return "risk_on"
        elif dxy_impact == "bearish":
            return "dollar_driven"
        else:
            return "neutral"

    async def get_market_summary(self) -> Dict:
        """Get summary of cross-market conditions"""
        dxy = await self.fred.get_dollar_index()
        vix = await self.fred.get_vix()

        return {
            "dxy": {
                "value": dxy.get("value") if dxy else None,
                "change_pct": dxy.get("change_pct") if dxy else None,
                "direction": dxy.get("direction") if dxy else None
            },
            "vix": {
                "value": vix.get("value") if vix else None,
                "level": vix.get("level") if vix else None,
                "change_1w": vix.get("change_1w") if vix else None
            },
            "interpretation": self._interpret_conditions(dxy, vix)
        }

    def _interpret_conditions(
        self,
        dxy: Optional[Dict],
        vix: Optional[Dict]
    ) -> str:
        """Generate human-readable interpretation of market conditions"""
        conditions = []

        if dxy:
            if dxy.get("direction") == "strengthening":
                conditions.append("dollar strength pressuring risk assets")
            elif dxy.get("direction") == "weakening":
                conditions.append("weakening dollar supportive for crypto")

        if vix:
            level = vix.get("level", "normal")
            if level in ["extreme_fear", "high_fear"]:
                conditions.append("elevated volatility suggests caution")
            elif level == "complacent":
                conditions.append("low volatility may indicate complacency")

        if not conditions:
            return "Market conditions relatively neutral"

        return "; ".join(conditions).capitalize()
