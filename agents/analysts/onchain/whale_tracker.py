"""
Whale Transaction Tracker

Tracks large cryptocurrency transactions (>$1M) to identify
institutional/whale activity and potential market impact.

Whales moving coins to exchanges = potential selling pressure
Whales moving coins to cold storage = accumulation/bullish
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass

from integrations.data.glassnode import GlassnodeClient

logger = logging.getLogger(__name__)


@dataclass
class WhaleSignal:
    """Signal from whale activity analysis"""
    direction: float  # -1 (bearish/selling) to +1 (bullish/accumulating)
    confidence: float  # 0 to 1
    whale_count: Optional[int]  # Number of whale transactions
    net_flow_direction: str  # "accumulating", "distributing", "neutral"
    reasoning: str


class WhaleTracker:
    """
    Tracks whale transactions (>$1M USD) and generates trading signals.

    Whale activity signals:
    - High volume of exchange inflows = bearish (selling pressure)
    - High volume of exchange outflows = bullish (accumulation)
    - Increasing whale transaction count = more institutional interest
    """

    # Threshold for whale transactions in USD
    WHALE_THRESHOLD = 1_000_000  # $1M

    def __init__(self, glassnode_client: GlassnodeClient):
        """
        Initialize whale tracker.

        Args:
            glassnode_client: Glassnode API client for on-chain data
        """
        self.glassnode = glassnode_client
        logger.info("WhaleTracker initialized")

    async def analyze(self, asset: str) -> WhaleSignal:
        """
        Analyze whale activity for an asset.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", or "BTC/AUD")

        Returns:
            WhaleSignal with direction, confidence, and reasoning
        """
        # Extract base asset from pair
        base_asset = asset.split("/")[0] if "/" in asset else asset

        # Fetch whale transaction data
        whale_data = await self.glassnode.get_whale_transactions(
            base_asset,
            min_value=self.WHALE_THRESHOLD
        )

        # Fetch exchange netflow to understand whale direction
        netflow_data = await self.glassnode.get_exchange_netflow(base_asset)

        # If no data available, return neutral signal with low confidence
        if not whale_data and not netflow_data:
            return WhaleSignal(
                direction=0.0,
                confidence=0.0,
                whale_count=None,
                net_flow_direction="unknown",
                reasoning="No whale activity data available"
            )

        # Calculate combined signal
        direction = 0.0
        confidence = 0.0
        reasons = []

        # Weight for each data source
        WHALE_VOLUME_WEIGHT = 0.4
        EXCHANGE_FLOW_WEIGHT = 0.6

        # Analyze whale volume changes
        if whale_data:
            volume_change = whale_data.get("change_24h", 0)
            volume_signal = whale_data.get("signal", 0)

            # Increasing whale volume can indicate more institutional interest
            # The direction depends on whether they're buying or selling
            direction += volume_signal * WHALE_VOLUME_WEIGHT
            confidence += 0.4

            if volume_change > 0.1:
                reasons.append(f"Whale volume up {volume_change*100:.1f}% in 24h")
            elif volume_change < -0.1:
                reasons.append(f"Whale volume down {abs(volume_change)*100:.1f}% in 24h")
            else:
                reasons.append("Whale volume stable")

        # Analyze exchange netflow
        if netflow_data:
            flow_signal = netflow_data.get("signal", 0)
            flow_direction = netflow_data.get("direction", "neutral")

            direction += flow_signal * EXCHANGE_FLOW_WEIGHT
            confidence += 0.5

            if flow_direction == "outflow":
                reasons.append("Net outflows from exchanges (accumulation)")
            elif flow_direction == "inflow":
                reasons.append("Net inflows to exchanges (selling pressure)")
            else:
                reasons.append("Exchange flows neutral")

        # Determine overall flow direction
        if direction > 0.2:
            net_flow_direction = "accumulating"
        elif direction < -0.2:
            net_flow_direction = "distributing"
        else:
            net_flow_direction = "neutral"

        # Clamp values
        direction = max(-1.0, min(1.0, direction))
        confidence = min(1.0, confidence)

        return WhaleSignal(
            direction=round(direction, 4),
            confidence=round(confidence, 4),
            whale_count=whale_data.get("count") if whale_data else None,
            net_flow_direction=net_flow_direction,
            reasoning="; ".join(reasons) if reasons else "No whale activity detected"
        )

    async def get_whale_alert(self, asset: str) -> Optional[Dict]:
        """
        Check for significant whale activity that warrants an alert.

        Returns alert data if whale activity exceeds thresholds,
        None otherwise.
        """
        signal = await self.analyze(asset)

        # Alert if confidence high and direction extreme
        if signal.confidence > 0.6 and abs(signal.direction) > 0.5:
            alert_type = "bullish_whale_activity" if signal.direction > 0 else "bearish_whale_activity"
            return {
                "type": alert_type,
                "asset": asset,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "flow": signal.net_flow_direction,
                "reasoning": signal.reasoning
            }

        return None
