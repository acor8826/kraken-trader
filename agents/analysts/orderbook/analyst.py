"""
Order Book Analyst

Analyzes order book microstructure to generate short-term trading signals:
- Imbalance analysis for direction
- Liquidity assessment for confidence
- Support/resistance identification

This analyst implements the IAnalyst interface for integration
with the intelligence fusion system.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models.signals import AnalystSignal
from agents.analysts.orderbook.depth_analyzer import DepthAnalyzer

logger = logging.getLogger(__name__)


class OrderBookAnalyst(IAnalyst):
    """
    Order book analyst that generates signals from market microstructure.

    Provides short-term directional signals based on:
    - Order book imbalance
    - Liquidity conditions
    - Support/resistance walls
    """

    def __init__(self, exchange=None):
        """
        Initialize order book analyst.

        Args:
            exchange: Exchange instance for fetching order books
        """
        self.exchange = exchange
        self.depth_analyzer = DepthAnalyzer(exchange=exchange)
        logger.info("OrderBookAnalyst initialized")

    @property
    def name(self) -> str:
        """Analyst identifier"""
        return "orderbook"

    @property
    def weight(self) -> float:
        """Default weight in intelligence fusion"""
        return 0.10  # 10% weight - short-term signal

    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        """
        Analyze order book for a trading pair.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            market_data: Additional market data (may contain order_book)

        Returns:
            AnalystSignal with direction, confidence, and reasoning
        """
        # Try to get order book from market_data or fetch from exchange
        order_book = market_data.get("order_book")

        if order_book is None and self.exchange is not None:
            try:
                order_book = await self.exchange.get_order_book(pair, depth=25)
            except Exception as e:
                logger.warning(f"Failed to fetch order book for {pair}: {e}")
                return self._no_data_signal(pair)

        if order_book is None:
            return self._no_data_signal(pair)

        # Analyze depth
        try:
            analysis = await self.depth_analyzer.analyze(pair, order_book)
        except Exception as e:
            logger.error(f"Error analyzing order book for {pair}: {e}")
            return self._no_data_signal(pair)

        # Calculate signal from analysis
        direction = self._calculate_direction(analysis)
        confidence = self._calculate_confidence(analysis)
        reasoning = self._build_reasoning(analysis)

        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=round(direction, 4),
            confidence=round(confidence, 4),
            reasoning=reasoning,
            timeframe="short",  # Order book signals are short-term
            metadata={
                "spread_pct": analysis.spread_pct,
                "imbalance": analysis.imbalance,
                "bid_depth": analysis.bid_depth,
                "ask_depth": analysis.ask_depth,
                "liquidity_score": analysis.liquidity_score,
                "mid_price": analysis.mid_price,
                "largest_bid_wall": analysis.largest_bid_wall,
                "largest_ask_wall": analysis.largest_ask_wall
            }
        )

    def _no_data_signal(self, pair: str) -> AnalystSignal:
        """Return neutral signal when no data available"""
        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=0.0,
            confidence=0.0,
            reasoning="No order book data available",
            metadata={"data_available": False}
        )

    def _calculate_direction(self, analysis) -> float:
        """
        Calculate direction signal from order book analysis.

        Imbalance-based signal:
        - Positive imbalance (more bids) = bullish
        - Negative imbalance (more asks) = bearish
        """
        # Primary signal from imbalance
        direction = analysis.imbalance

        # Adjust based on walls
        if analysis.largest_bid_wall and analysis.largest_ask_wall:
            bid_wall_price, bid_wall_vol = analysis.largest_bid_wall
            ask_wall_price, ask_wall_vol = analysis.largest_ask_wall

            # Strong bid wall close to mid = support = bullish
            bid_distance = (analysis.mid_price - bid_wall_price) / analysis.mid_price
            ask_distance = (ask_wall_price - analysis.mid_price) / analysis.mid_price

            # Closer, larger wall has more impact
            if bid_distance < 0.02 and bid_wall_vol > ask_wall_vol:
                direction += 0.1  # Strong support nearby
            elif ask_distance < 0.02 and ask_wall_vol > bid_wall_vol:
                direction -= 0.1  # Strong resistance nearby

        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, direction))

    def _calculate_confidence(self, analysis) -> float:
        """
        Calculate confidence based on liquidity and data quality.

        Low liquidity = lower confidence in signal
        High imbalance with high liquidity = higher confidence
        """
        # Base confidence from liquidity
        base_confidence = analysis.liquidity_score

        # Boost confidence if imbalance is significant
        imbalance_strength = abs(analysis.imbalance)
        if imbalance_strength > 0.3:
            base_confidence += 0.2
        elif imbalance_strength > 0.1:
            base_confidence += 0.1

        # Reduce confidence if spread is very wide
        if analysis.spread_pct > 0.01:  # > 1%
            base_confidence *= 0.7

        return min(1.0, base_confidence)

    def _build_reasoning(self, analysis) -> str:
        """Build human-readable reasoning string"""
        parts = []

        # Spread assessment
        if analysis.spread_pct < 0.001:
            parts.append("Tight spread (high liquidity)")
        elif analysis.spread_pct > 0.005:
            parts.append(f"Wide spread ({analysis.spread_pct*100:.2f}%)")

        # Imbalance assessment
        if analysis.imbalance > 0.3:
            parts.append("Strong buy pressure (bid imbalance)")
        elif analysis.imbalance > 0.1:
            parts.append("Moderate buy pressure")
        elif analysis.imbalance < -0.3:
            parts.append("Strong sell pressure (ask imbalance)")
        elif analysis.imbalance < -0.1:
            parts.append("Moderate sell pressure")
        else:
            parts.append("Balanced order book")

        # Wall assessment
        if analysis.largest_bid_wall:
            price, vol = analysis.largest_bid_wall
            distance_pct = (analysis.mid_price - price) / analysis.mid_price * 100
            parts.append(f"Bid wall at {distance_pct:.1f}% below")

        if analysis.largest_ask_wall:
            price, vol = analysis.largest_ask_wall
            distance_pct = (price - analysis.mid_price) / analysis.mid_price * 100
            parts.append(f"Ask wall at {distance_pct:.1f}% above")

        return "; ".join(parts) if parts else "Neutral order book"
