"""
Exchange Flow Analyzer

Monitors cryptocurrency flows to and from exchanges to predict
supply pressure and potential price movements.

High inflows = bearish (coins available for selling)
High outflows = bullish (coins moving to cold storage/accumulation)
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass

from integrations.data.glassnode import GlassnodeClient

logger = logging.getLogger(__name__)


@dataclass
class ExchangeFlowSignal:
    """Signal from exchange flow analysis"""
    direction: float  # -1 (bearish/inflows) to +1 (bullish/outflows)
    confidence: float  # 0 to 1
    net_flow: Optional[float]  # Net coins (negative = outflows)
    flow_trend: str  # "strong_outflow", "outflow", "neutral", "inflow", "strong_inflow"
    exchange_balance_change: Optional[float]  # 7-day % change
    reasoning: str


class ExchangeFlowAnalyzer:
    """
    Analyzes exchange flows to generate trading signals.

    Exchange flow signals:
    - Increasing exchange balance = bearish (more supply available)
    - Decreasing exchange balance = bullish (supply squeeze)
    - Large inflows = potential selling pressure incoming
    - Large outflows = potential accumulation phase
    """

    def __init__(self, glassnode_client: GlassnodeClient):
        """
        Initialize exchange flow analyzer.

        Args:
            glassnode_client: Glassnode API client for on-chain data
        """
        self.glassnode = glassnode_client
        logger.info("ExchangeFlowAnalyzer initialized")

    async def analyze(self, asset: str) -> ExchangeFlowSignal:
        """
        Analyze exchange flows for an asset.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", or "BTC/AUD")

        Returns:
            ExchangeFlowSignal with direction, confidence, and reasoning
        """
        # Extract base asset from pair
        base_asset = asset.split("/")[0] if "/" in asset else asset

        # Fetch exchange netflow data (24h)
        netflow_data = await self.glassnode.get_exchange_netflow(base_asset)

        # Fetch exchange balance data (7d trend)
        balance_data = await self.glassnode.get_supply_on_exchanges(base_asset)

        # If no data available, return neutral signal with low confidence
        if not netflow_data and not balance_data:
            return ExchangeFlowSignal(
                direction=0.0,
                confidence=0.0,
                net_flow=None,
                flow_trend="unknown",
                exchange_balance_change=None,
                reasoning="No exchange flow data available"
            )

        direction = 0.0
        confidence = 0.0
        reasons = []

        # Weights for each component
        NETFLOW_WEIGHT = 0.6  # 24h flow is more actionable
        BALANCE_WEIGHT = 0.4  # 7d trend provides context

        # Analyze 24h netflow
        if netflow_data:
            netflow_signal = netflow_data.get("signal", 0)
            netflow_value = netflow_data.get("netflow", 0)
            netflow_direction = netflow_data.get("direction", "neutral")

            direction += netflow_signal * NETFLOW_WEIGHT
            confidence += 0.5

            if netflow_direction == "outflow":
                if abs(netflow_value) > 1000:  # Significant outflows
                    reasons.append(f"Strong outflows: {abs(netflow_value):.0f} {base_asset}")
                else:
                    reasons.append("Moderate exchange outflows")
            elif netflow_direction == "inflow":
                if abs(netflow_value) > 1000:
                    reasons.append(f"Strong inflows: {netflow_value:.0f} {base_asset}")
                else:
                    reasons.append("Moderate exchange inflows")
            else:
                reasons.append("Exchange flows balanced")

        # Analyze 7-day balance trend
        exchange_balance_change = None
        if balance_data:
            balance_signal = balance_data.get("signal", 0)
            balance_change = balance_data.get("change_7d", 0)
            exchange_balance_change = balance_change

            direction += balance_signal * BALANCE_WEIGHT
            confidence += 0.4

            if balance_change < -0.02:  # More than 2% decrease
                reasons.append(f"Exchange reserves down {abs(balance_change)*100:.1f}% over 7d")
            elif balance_change > 0.02:  # More than 2% increase
                reasons.append(f"Exchange reserves up {balance_change*100:.1f}% over 7d")
            else:
                reasons.append("Exchange reserves stable")

        # Determine flow trend classification
        flow_trend = self._classify_flow_trend(direction)

        # Clamp values
        direction = max(-1.0, min(1.0, direction))
        confidence = min(1.0, confidence)

        return ExchangeFlowSignal(
            direction=round(direction, 4),
            confidence=round(confidence, 4),
            net_flow=netflow_data.get("netflow") if netflow_data else None,
            flow_trend=flow_trend,
            exchange_balance_change=exchange_balance_change,
            reasoning="; ".join(reasons) if reasons else "No significant flow activity"
        )

    def _classify_flow_trend(self, direction: float) -> str:
        """Classify the flow trend based on direction strength"""
        if direction > 0.6:
            return "strong_outflow"
        elif direction > 0.2:
            return "outflow"
        elif direction < -0.6:
            return "strong_inflow"
        elif direction < -0.2:
            return "inflow"
        else:
            return "neutral"

    async def get_flow_summary(self, asset: str) -> Dict:
        """
        Get a summary of exchange flow metrics for an asset.

        Returns comprehensive flow data for display/logging.
        """
        signal = await self.analyze(asset)

        return {
            "asset": asset,
            "signal_direction": signal.direction,
            "confidence": signal.confidence,
            "flow_trend": signal.flow_trend,
            "net_flow_24h": signal.net_flow,
            "balance_change_7d": signal.exchange_balance_change,
            "interpretation": self._interpret_signal(signal),
            "reasoning": signal.reasoning
        }

    def _interpret_signal(self, signal: ExchangeFlowSignal) -> str:
        """Generate human-readable interpretation of the signal"""
        if signal.direction > 0.5:
            return "Bullish: Significant outflows indicate accumulation"
        elif signal.direction > 0.2:
            return "Slightly bullish: Outflows suggest reduced selling pressure"
        elif signal.direction < -0.5:
            return "Bearish: Significant inflows indicate potential selling"
        elif signal.direction < -0.2:
            return "Slightly bearish: Inflows suggest increased supply"
        else:
            return "Neutral: Exchange flows balanced"
