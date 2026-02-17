"""
Macro Analyst

Analyzes macroeconomic conditions to generate trading signals based on:
- Fed policy (40% weight)
- Dollar Index / DXY (30% weight)
- Cross-market correlations (30% weight)

This analyst implements the IAnalyst interface for integration
with the intelligence fusion system.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models.signals import AnalystSignal
from agents.analysts.macro.fed_watcher import FedWatcher
from agents.analysts.macro.correlation_tracker import CorrelationTracker
from integrations.data.fred import FREDClient

logger = logging.getLogger(__name__)


class MacroAnalyst(IAnalyst):
    """
    Macro analyst that generates signals from economic data.

    Combines multiple macro indicators:
    - Fed policy: Rate direction and yield curve
    - DXY: Dollar strength/weakness
    - VIX: Market volatility/fear
    """

    # Component weights in final signal
    FED_POLICY_WEIGHT = 0.40
    DXY_WEIGHT = 0.30
    CORRELATION_WEIGHT = 0.30

    def __init__(
        self,
        fred_client: FREDClient = None,
        cache=None
    ):
        """
        Initialize macro analyst.

        Args:
            fred_client: Optional pre-configured FRED client
            cache: Optional Redis cache for caching
        """
        # Create FRED client if not provided
        self.fred = fred_client or FREDClient(cache=cache)

        # Initialize sub-components
        self.fed_watcher = FedWatcher(self.fred)
        self.correlation_tracker = CorrelationTracker(self.fred)

        logger.info("MacroAnalyst initialized with FRED integration")

    @property
    def name(self) -> str:
        """Analyst identifier"""
        return "macro"

    @property
    def weight(self) -> float:
        """Default weight in intelligence fusion"""
        return 0.15  # 15% weight

    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        """
        Analyze macroeconomic conditions for a trading pair.

        Note: Macro signals are generally asset-agnostic since they
        reflect broader risk sentiment. The signal applies to all
        crypto assets similarly.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            market_data: Additional market data (optional)

        Returns:
            AnalystSignal with direction, confidence, and reasoning
        """
        # Collect signals from sub-components
        fed_signal = await self.fed_watcher.analyze()
        correlation_signal = await self.correlation_tracker.analyze()

        # Calculate weighted signal
        direction = 0.0
        confidence = 0.0
        active_components = 0
        reasons = []

        # Add Fed policy signal
        if fed_signal.confidence > 0:
            direction += fed_signal.direction * self.FED_POLICY_WEIGHT
            confidence += fed_signal.confidence * self.FED_POLICY_WEIGHT
            active_components += 1
            reasons.append(f"Fed: {fed_signal.policy_stance}")
            if fed_signal.yield_curve_status == "inverted":
                reasons.append("Yield curve inverted")

        # Add correlation/DXY signal
        if correlation_signal.confidence > 0:
            # Split the correlation signal into DXY and general correlation
            dxy_contribution = correlation_signal.direction * self.DXY_WEIGHT
            corr_contribution = correlation_signal.direction * self.CORRELATION_WEIGHT

            direction += dxy_contribution + corr_contribution
            confidence += correlation_signal.confidence * (self.DXY_WEIGHT + self.CORRELATION_WEIGHT)
            active_components += 1

            if correlation_signal.dxy_impact != "neutral":
                reasons.append(f"DXY: {correlation_signal.dxy_impact}")
            if correlation_signal.vix_level in ["extreme_fear", "high_fear"]:
                reasons.append(f"VIX elevated: risk-off")
            elif correlation_signal.vix_level == "complacent":
                reasons.append("VIX low: risk-on")

        # Handle case where no data is available
        if active_components == 0:
            logger.warning(f"No macro data available for {pair}")
            return AnalystSignal(
                source=self.name,
                pair=pair,
                direction=0.0,
                confidence=0.0,
                reasoning="No macro data available - FRED API may not be configured",
                metadata={"data_available": False}
            )

        # Normalize confidence based on active components
        data_completeness = active_components / 2.0
        confidence = confidence * (0.5 + 0.5 * data_completeness)

        # Clamp values
        direction = max(-1.0, min(1.0, direction))
        confidence = min(1.0, confidence)

        # Build reasoning
        reasoning = self._build_reasoning(
            direction=direction,
            fed_signal=fed_signal,
            correlation_signal=correlation_signal,
            reasons=reasons
        )

        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=round(direction, 4),
            confidence=round(confidence, 4),
            reasoning=reasoning,
            metadata={
                "data_available": True,
                "active_components": active_components,
                "fed_direction": fed_signal.direction,
                "fed_stance": fed_signal.policy_stance,
                "yield_curve": fed_signal.yield_curve_status,
                "dxy_impact": correlation_signal.dxy_impact,
                "vix_level": correlation_signal.vix_level,
                "correlation_regime": correlation_signal.correlation_regime
            }
        )

    def _build_reasoning(
        self,
        direction: float,
        fed_signal,
        correlation_signal,
        reasons: list
    ) -> str:
        """Build human-readable reasoning string"""
        # Overall risk environment
        if direction > 0.4:
            environment = "Risk-on environment"
        elif direction > 0.1:
            environment = "Moderately risk-on"
        elif direction < -0.4:
            environment = "Risk-off environment"
        elif direction < -0.1:
            environment = "Moderately risk-off"
        else:
            environment = "Neutral macro environment"

        # Key drivers
        drivers = []

        if fed_signal.confidence > 0:
            if fed_signal.policy_stance == "dovish":
                drivers.append("dovish Fed policy")
            elif fed_signal.policy_stance == "hawkish":
                drivers.append("hawkish Fed policy")

            if fed_signal.yield_curve_status in ["inverted", "deeply_inverted"]:
                drivers.append("yield curve inversion")

        if correlation_signal.confidence > 0:
            if correlation_signal.dxy_impact == "bullish":
                drivers.append("weakening dollar")
            elif correlation_signal.dxy_impact == "bearish":
                drivers.append("strengthening dollar")

            if correlation_signal.vix_level in ["extreme_fear", "high_fear"]:
                drivers.append("elevated market fear")

        if drivers:
            return f"{environment}: {', '.join(drivers)}"
        else:
            return environment

    async def get_macro_summary(self) -> Dict:
        """Get comprehensive macro environment summary"""
        fed_summary = await self.fed_watcher.get_rate_summary()
        market_summary = await self.correlation_tracker.get_market_summary()
        signal = await self.analyze("MACRO", {})

        return {
            "signal": {
                "direction": signal.direction,
                "confidence": signal.confidence,
                "interpretation": signal.reasoning
            },
            "fed_policy": fed_summary,
            "markets": market_summary,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def close(self):
        """Cleanup resources"""
        if self.fred:
            await self.fred.close()
