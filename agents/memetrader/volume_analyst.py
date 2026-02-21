"""
Volume Momentum Analyst

Pure math analyst - no LLM cost. Detects unusual volume spikes,
price momentum, and order book pressure for meme coins.
"""

import logging
import statistics
from typing import Dict, List, Optional
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models import AnalystSignal
from agents.memetrader.models import MomentumSnapshot

logger = logging.getLogger(__name__)


def _clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, value))


class VolumeMomentumAnalyst(IAnalyst):
    """
    Analyzes volume Z-scores, price momentum, and order book pressure.
    Pure math - zero LLM cost.
    """

    def __init__(self):
        self._snapshots: Dict[str, MomentumSnapshot] = {}

    @property
    def name(self) -> str:
        return "volume_momentum"

    @property
    def weight(self) -> float:
        return 0.45

    def get_snapshot(self, symbol: str) -> Optional[MomentumSnapshot]:
        return self._snapshots.get(symbol)

    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        """
        Analyze volume and momentum for a meme coin.

        market_data expected keys:
            ticker: Dict with bid, ask, last, volume
            ohlcv_5m: List of [timestamp, open, high, low, close, volume] candles
            ohlcv_15m: List of [timestamp, open, high, low, close, volume] candles
            order_book: Dict with bids and asks lists of [price, volume]
        """
        symbol = pair.split("/")[0]

        try:
            ohlcv_5m = market_data.get("ohlcv_5m", [])
            ohlcv_15m = market_data.get("ohlcv_15m", [])
            order_book = market_data.get("order_book", {})
            ticker = market_data.get("ticker", {})

            # 1. Volume Z-score from 5m candles
            vol_z = self._compute_volume_z_score(ohlcv_5m)

            # 2. Price momentum
            mom_5m = self._compute_price_momentum(ohlcv_5m)
            mom_15m = self._compute_price_momentum(ohlcv_15m)

            # 3. Buy/sell ratio from order book
            bs_ratio = self._compute_buy_sell_ratio(order_book)

            # 4. Spread
            spread_pct = self._compute_spread(ticker)

            # Normalize signals to [-1, 1]
            vol_z_signal = _clamp(vol_z / 3.0)
            price_mom_signal = _clamp((mom_5m * 0.6 + mom_15m * 0.4) / 5.0)
            buy_sell_signal = _clamp(bs_ratio - 1.0)

            # Weighted direction
            direction = (
                vol_z_signal * 0.35 +
                price_mom_signal * 0.35 +
                buy_sell_signal * 0.30
            )

            # Confidence based on signal strength
            confidence = min(0.9, abs(direction) * 1.2 + 0.2)

            # Reduce confidence for wide spreads (illiquid)
            if spread_pct > 3.0:
                confidence *= 0.7

            # Store snapshot
            snapshot = MomentumSnapshot(
                symbol=symbol,
                volume_z_score=vol_z,
                price_momentum_5m=mom_5m,
                price_momentum_15m=mom_15m,
                buy_sell_ratio=bs_ratio if bs_ratio != 1.0 else self._raw_bs_ratio,
                spread_pct=spread_pct,
            )
            self._snapshots[symbol] = snapshot

            reasoning_parts = []
            if abs(vol_z) > 1.5:
                reasoning_parts.append(f"vol_z={vol_z:+.1f}")
            if abs(mom_5m) > 1.0:
                reasoning_parts.append(f"mom5m={mom_5m:+.1f}%")
            if abs(bs_ratio - 1.0) > 0.2:
                reasoning_parts.append(f"B/S={bs_ratio:.2f}")
            reasoning = "Volume: " + (", ".join(reasoning_parts) if reasoning_parts else "no significant signals")

            return AnalystSignal(
                source=self.name,
                pair=pair,
                direction=_clamp(direction),
                confidence=confidence,
                reasoning=reasoning,
                timeframe="5m",
                metadata={
                    "volume_z_score": vol_z,
                    "price_momentum_5m": mom_5m,
                    "price_momentum_15m": mom_15m,
                    "buy_sell_ratio": bs_ratio,
                    "spread_pct": spread_pct,
                },
            )

        except Exception as e:
            logger.warning(f"[VOL_ANALYST] Error analyzing {pair}: {e}")
            return AnalystSignal(
                source=self.name,
                pair=pair,
                direction=0.0,
                confidence=0.0,
                reasoning=f"Error: {e}",
                timeframe="5m",
            )

    def _compute_volume_z_score(self, ohlcv: List) -> float:
        """Compute Z-score of latest volume vs historical."""
        if len(ohlcv) < 3:
            return 0.0

        volumes = [candle[5] if len(candle) > 5 else 0 for candle in ohlcv]
        volumes = [v for v in volumes if v > 0]

        if len(volumes) < 3:
            return 0.0

        latest = volumes[-1]
        hist = volumes[:-1]

        mean = statistics.mean(hist)
        stdev = statistics.stdev(hist) if len(hist) > 1 else 0.0

        if stdev == 0:
            return 0.0

        return (latest - mean) / stdev

    def _compute_price_momentum(self, ohlcv: List) -> float:
        """Compute price momentum as percentage change."""
        if len(ohlcv) < 2:
            return 0.0

        # Close prices
        latest_close = ohlcv[-1][4] if len(ohlcv[-1]) > 4 else 0
        first_close = ohlcv[0][4] if len(ohlcv[0]) > 4 else 0

        if first_close == 0:
            return 0.0

        return ((latest_close - first_close) / first_close) * 100

    def _compute_buy_sell_ratio(self, order_book: Dict) -> float:
        """Compute bid/ask volume ratio from top 10 levels."""
        bids = order_book.get("bids", [])[:10]
        asks = order_book.get("asks", [])[:10]

        bid_volume = sum(float(b[1]) if len(b) > 1 else 0 for b in bids)
        ask_volume = sum(float(a[1]) if len(a) > 1 else 0 for a in asks)

        self._raw_bs_ratio = 1.0

        if ask_volume == 0:
            self._raw_bs_ratio = 2.0
            return 2.0

        ratio = bid_volume / ask_volume
        self._raw_bs_ratio = ratio
        return ratio

    def _compute_spread(self, ticker: Dict) -> float:
        """Compute spread as percentage of price."""
        bid = float(ticker.get("bid", 0) or 0)
        ask = float(ticker.get("ask", 0) or 0)

        if bid == 0 or ask == 0:
            return 0.0

        mid = (bid + ask) / 2
        if mid == 0:
            return 0.0

        return ((ask - bid) / mid) * 100
