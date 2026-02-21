"""
On-Chain Analyst

Analyzes blockchain data to generate trading signals based on:
- Whale activity (40% weight)
- Exchange flows (35% weight)
- Network metrics (25% weight)

This analyst implements the IAnalyst interface for integration
with the intelligence fusion system.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models.signals import AnalystSignal
from agents.analysts.onchain.whale_tracker import WhaleTracker
from agents.analysts.onchain.exchange_flows import ExchangeFlowAnalyzer
from integrations.data.glassnode import GlassnodeClient

logger = logging.getLogger(__name__)


class OnChainAnalyst(IAnalyst):
    """
    On-chain analyst that generates signals from blockchain data.

    Combines multiple on-chain metrics:
    - Whale activity: Large transaction tracking
    - Exchange flows: Supply pressure analysis
    - Network metrics: Active addresses, etc.
    """

    # Component weights in final signal
    WHALE_WEIGHT = 0.40
    EXCHANGE_FLOW_WEIGHT = 0.35
    NETWORK_WEIGHT = 0.25

    def __init__(
        self,
        glassnode_client: GlassnodeClient = None,
        cache=None
    ):
        """
        Initialize on-chain analyst.

        Args:
            glassnode_client: Optional pre-configured Glassnode client
            cache: Optional Redis cache for caching
        """
        # Create Glassnode client if not provided
        self.glassnode = glassnode_client or GlassnodeClient(cache=cache)

        # Initialize sub-components
        self.whale_tracker = WhaleTracker(self.glassnode)
        self.exchange_flow_analyzer = ExchangeFlowAnalyzer(self.glassnode)

        logger.info("OnChainAnalyst initialized with Glassnode integration")

    @property
    def name(self) -> str:
        """Analyst identifier"""
        return "onchain"

    @property
    def weight(self) -> float:
        """Default weight in intelligence fusion"""
        return 0.20  # 20% weight

    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        """
        Analyze on-chain metrics for a trading pair.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            market_data: Additional market data (optional)

        Returns:
            AnalystSignal with direction, confidence, and reasoning
        """
        # Extract base asset
        base_asset = pair.split("/")[0] if "/" in pair else pair

        # Collect signals from sub-components
        whale_signal = await self.whale_tracker.analyze(base_asset)
        flow_signal = await self.exchange_flow_analyzer.analyze(base_asset)
        network_signal = await self._analyze_network(base_asset)

        # Calculate weighted signal
        direction = 0.0
        confidence = 0.0
        active_components = 0
        reasons = []

        # Add whale signal
        if whale_signal.confidence > 0:
            direction += whale_signal.direction * self.WHALE_WEIGHT
            confidence += whale_signal.confidence * self.WHALE_WEIGHT
            active_components += 1
            reasons.append(f"Whale: {whale_signal.net_flow_direction}")

        # Add exchange flow signal
        if flow_signal.confidence > 0:
            direction += flow_signal.direction * self.EXCHANGE_FLOW_WEIGHT
            confidence += flow_signal.confidence * self.EXCHANGE_FLOW_WEIGHT
            active_components += 1
            reasons.append(f"Exchange flows: {flow_signal.flow_trend}")

        # Add network signal
        if network_signal and network_signal.get("confidence", 0) > 0:
            direction += network_signal["direction"] * self.NETWORK_WEIGHT
            confidence += network_signal["confidence"] * self.NETWORK_WEIGHT
            active_components += 1
            if network_signal.get("active_addr_change"):
                reasons.append(f"Active addresses: {network_signal['active_addr_change']:+.1%}")

        # Handle case where no data is available
        if active_components == 0:
            logger.warning(f"No on-chain data available for {pair}")
            return AnalystSignal(
                source=self.name,
                pair=pair,
                direction=0.0,
                confidence=0.0,
                reasoning="No on-chain data available - Glassnode API may not be configured",
                metadata={"data_available": False}
            )

        # Normalize confidence based on active components
        # If we only have 1 of 3 components, reduce confidence
        data_completeness = active_components / 3.0
        confidence = confidence * (0.5 + 0.5 * data_completeness)  # 50-100% of raw confidence

        # Clamp values
        direction = max(-1.0, min(1.0, direction))
        confidence = min(1.0, confidence)

        # Build reasoning string
        reasoning = self._build_reasoning(
            direction=direction,
            whale_signal=whale_signal,
            flow_signal=flow_signal,
            network_signal=network_signal,
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
                "whale_direction": whale_signal.direction,
                "whale_flow": whale_signal.net_flow_direction,
                "exchange_flow_direction": flow_signal.direction,
                "exchange_flow_trend": flow_signal.flow_trend,
                "network_signal": network_signal
            }
        )

    async def _analyze_network(self, asset: str) -> Optional[Dict]:
        """
        Analyze network metrics (active addresses, etc.)

        Returns dictionary with direction, confidence, and metrics.
        """
        try:
            active_addr = await self.glassnode.get_active_addresses(asset)

            if not active_addr:
                return None

            # Increasing active addresses = bullish (more adoption)
            change = active_addr.get("change_24h", 0)

            # Convert change to signal
            # >10% increase = strongly bullish (+0.8)
            # >5% increase = bullish (+0.4)
            # etc.
            if change > 0.10:
                direction = 0.8
            elif change > 0.05:
                direction = 0.4
            elif change > 0.02:
                direction = 0.2
            elif change < -0.10:
                direction = -0.8
            elif change < -0.05:
                direction = -0.4
            elif change < -0.02:
                direction = -0.2
            else:
                direction = 0.0

            # Confidence based on data freshness and significance
            confidence = 0.6 if abs(change) > 0.03 else 0.4

            return {
                "direction": direction,
                "confidence": confidence,
                "active_addresses": active_addr.get("value"),
                "active_addr_change": change
            }

        except Exception as e:
            logger.error(f"Error analyzing network metrics for {asset}: {e}")
            return None

    def _build_reasoning(
        self,
        direction: float,
        whale_signal,
        flow_signal,
        network_signal: Optional[Dict],
        reasons: list
    ) -> str:
        """Build human-readable reasoning string"""
        # Overall sentiment
        if direction > 0.5:
            sentiment = "Strongly bullish"
        elif direction > 0.2:
            sentiment = "Moderately bullish"
        elif direction < -0.5:
            sentiment = "Strongly bearish"
        elif direction < -0.2:
            sentiment = "Moderately bearish"
        else:
            sentiment = "Neutral"

        # Key points
        points = []

        if whale_signal.confidence > 0:
            if whale_signal.direction > 0.3:
                points.append("whales accumulating")
            elif whale_signal.direction < -0.3:
                points.append("whales distributing")

        if flow_signal.confidence > 0:
            if flow_signal.direction > 0.3:
                points.append("exchange outflows (supply squeeze)")
            elif flow_signal.direction < -0.3:
                points.append("exchange inflows (selling pressure)")

        if network_signal and network_signal.get("confidence", 0) > 0:
            change = network_signal.get("active_addr_change", 0)
            if change > 0.05:
                points.append("network activity increasing")
            elif change < -0.05:
                points.append("network activity decreasing")

        if points:
            return f"{sentiment} on-chain signal: {', '.join(points)}"
        else:
            return f"{sentiment} on-chain signal based on available data"

    async def close(self):
        """Cleanup resources"""
        if self.glassnode:
            await self.glassnode.close()
