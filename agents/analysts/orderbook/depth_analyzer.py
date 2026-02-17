"""
Order Book Depth Analyzer

Analyzes order book depth to identify:
- Bid/ask spread
- Order book imbalance (buy vs sell pressure)
- Large support/resistance walls
- Liquidity conditions
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DepthAnalysis:
    """Results from order book depth analysis"""
    spread_pct: float  # Bid-ask spread as percentage
    imbalance: float  # -1 (sell pressure) to +1 (buy pressure)
    bid_depth: float  # Total bid volume
    ask_depth: float  # Total ask volume
    largest_bid_wall: Optional[Tuple[float, float]]  # (price, volume)
    largest_ask_wall: Optional[Tuple[float, float]]  # (price, volume)
    liquidity_score: float  # 0 to 1, higher = more liquid
    mid_price: float


class DepthAnalyzer:
    """
    Analyzes order book depth for microstructure signals.

    Signals:
    - High bid imbalance = buy pressure = bullish
    - High ask imbalance = sell pressure = bearish
    - Large bid walls = support levels
    - Large ask walls = resistance levels
    - Tight spread = high liquidity
    - Wide spread = low liquidity / uncertainty
    """

    # Wall detection threshold: volume > X times average
    WALL_THRESHOLD = 3.0

    # Spread thresholds for liquidity scoring
    TIGHT_SPREAD = 0.001  # 0.1%
    WIDE_SPREAD = 0.01    # 1%

    def __init__(self, exchange=None):
        """
        Initialize depth analyzer.

        Args:
            exchange: Exchange instance for fetching order books
        """
        self.exchange = exchange
        logger.info("DepthAnalyzer initialized")

    async def analyze(self, pair: str, order_book: Dict = None) -> DepthAnalysis:
        """
        Analyze order book depth for a trading pair.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            order_book: Optional pre-fetched order book data

        Returns:
            DepthAnalysis with spread, imbalance, and liquidity metrics
        """
        # Fetch order book if not provided
        if order_book is None:
            if self.exchange is None:
                raise ValueError("No exchange or order book provided")
            order_book = await self.exchange.get_order_book(pair, depth=25)

        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        if not bids or not asks:
            return DepthAnalysis(
                spread_pct=0.0,
                imbalance=0.0,
                bid_depth=0.0,
                ask_depth=0.0,
                largest_bid_wall=None,
                largest_ask_wall=None,
                liquidity_score=0.0,
                mid_price=0.0
            )

        # Calculate basic metrics
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        spread_pct = spread / mid_price

        # Calculate depth (volume within 2% of mid price)
        bid_depth = self._calculate_depth(bids, mid_price, side="bid", pct_range=0.02)
        ask_depth = self._calculate_depth(asks, mid_price, side="ask", pct_range=0.02)

        # Calculate imbalance
        total_depth = bid_depth + ask_depth
        if total_depth > 0:
            imbalance = (bid_depth - ask_depth) / total_depth
        else:
            imbalance = 0.0

        # Find largest walls
        largest_bid_wall = self._find_wall(bids)
        largest_ask_wall = self._find_wall(asks)

        # Calculate liquidity score
        liquidity_score = self._calculate_liquidity_score(spread_pct, total_depth)

        return DepthAnalysis(
            spread_pct=round(spread_pct, 6),
            imbalance=round(imbalance, 4),
            bid_depth=round(bid_depth, 4),
            ask_depth=round(ask_depth, 4),
            largest_bid_wall=largest_bid_wall,
            largest_ask_wall=largest_ask_wall,
            liquidity_score=round(liquidity_score, 4),
            mid_price=mid_price
        )

    def _calculate_depth(
        self,
        levels: List[List],
        mid_price: float,
        side: str,
        pct_range: float = 0.02
    ) -> float:
        """Calculate total volume within percentage range of mid price"""
        total_volume = 0.0

        for level in levels:
            price = level[0]
            volume = level[1]

            # Check if within range
            if side == "bid":
                if price >= mid_price * (1 - pct_range):
                    total_volume += volume
            else:  # ask
                if price <= mid_price * (1 + pct_range):
                    total_volume += volume

        return total_volume

    def _find_wall(self, levels: List[List]) -> Optional[Tuple[float, float]]:
        """Find the largest order wall in the order book levels"""
        if not levels:
            return None

        # Calculate average volume
        volumes = [level[1] for level in levels]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0

        # Find levels significantly larger than average
        largest_wall = None
        largest_volume = avg_volume * self.WALL_THRESHOLD

        for level in levels:
            price, volume = level[0], level[1]
            if volume > largest_volume:
                largest_volume = volume
                largest_wall = (price, volume)

        return largest_wall

    def _calculate_liquidity_score(self, spread_pct: float, total_depth: float) -> float:
        """
        Calculate liquidity score based on spread and depth.

        Score from 0 (illiquid) to 1 (highly liquid).
        """
        # Spread component (0 to 0.5)
        if spread_pct <= self.TIGHT_SPREAD:
            spread_score = 0.5
        elif spread_pct >= self.WIDE_SPREAD:
            spread_score = 0.0
        else:
            # Linear interpolation
            spread_score = 0.5 * (self.WIDE_SPREAD - spread_pct) / (self.WIDE_SPREAD - self.TIGHT_SPREAD)

        # Depth component (0 to 0.5)
        # Normalize depth - this is asset-specific, using simple thresholds
        if total_depth > 100:  # Significant depth
            depth_score = 0.5
        elif total_depth > 10:
            depth_score = 0.3
        elif total_depth > 1:
            depth_score = 0.15
        else:
            depth_score = 0.0

        return spread_score + depth_score

    def get_spread_analysis(self, order_book: Dict) -> Dict:
        """Get detailed spread analysis"""
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        if not bids or not asks:
            return {"error": "Empty order book"}

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid_price = (best_bid + best_ask) / 2

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
            "spread_absolute": best_ask - best_bid,
            "spread_pct": (best_ask - best_bid) / mid_price * 100,
            "bid_volume_at_best": bids[0][1],
            "ask_volume_at_best": asks[0][1]
        }
