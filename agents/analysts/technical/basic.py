"""
Technical Analyst Agent — Multi-Timeframe + Candlestick Patterns

Analyzes price action across 1m, 3m, 5m, 15m, and 1h candles.
Includes candlestick pattern recognition (hammer, doji, engulfing, etc.).
Timeframe agreement boosts confidence; disagreement lowers it.
"""

from typing import Dict, List, Optional, Tuple
import logging
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models import AnalystSignal, MarketData

logger = logging.getLogger(__name__)

# Timeframe weights: spread across 5 timeframes
TF_WEIGHTS = {"1h": 0.25, "15m": 0.25, "5m": 0.20, "3m": 0.15, "1m": 0.15}


class TechnicalAnalyst(IAnalyst):
    """
    Multi-timeframe technical analyst with candlestick pattern recognition.

    Calculates SMA, RSI, momentum, volume, and candle patterns on each timeframe,
    then aggregates with an alignment bonus/penalty.
    """

    def __init__(self):
        self._weight = 0.40  # 40% weight in fusion

    @property
    def name(self) -> str:
        return "technical"

    @property
    def weight(self) -> float:
        return self._weight

    @weight.setter
    def weight(self, value: float):
        self._weight = value

    async def analyze(self, pair: str, market_data: MarketData) -> AnalystSignal:
        """Analyze all available timeframes and return a fused signal."""

        # Gather candle sets per timeframe
        timeframes: Dict[str, List] = {}
        if market_data.ohlcv:
            timeframes["1h"] = market_data.ohlcv
        if getattr(market_data, "ohlcv_15m", None):
            timeframes["15m"] = market_data.ohlcv_15m
        if getattr(market_data, "ohlcv_5m", None):
            timeframes["5m"] = market_data.ohlcv_5m
        if getattr(market_data, "ohlcv_3m", None):
            timeframes["3m"] = market_data.ohlcv_3m
        if getattr(market_data, "ohlcv_1m", None):
            timeframes["1m"] = market_data.ohlcv_1m

        # Fallback: if no candles available
        if not timeframes:
            return self._empty_signal(pair)

        # Analyse each timeframe
        tf_results: Dict[str, dict] = {}
        for tf_name, candles in timeframes.items():
            closes = self._extract_closes(candles)
            volumes = self._extract_volumes(candles)
            if len(closes) < 6:
                continue
            tf_results[tf_name] = self._analyze_timeframe(
                market_data.current_price, closes, volumes, tf_name, candles
            )

        if not tf_results:
            return self._empty_signal(pair)

        # Aggregate across timeframes
        direction, confidence, reasoning = self._aggregate(tf_results)

        # Store per-timeframe indicators for downstream
        indicators = {}
        for tf_name, res in tf_results.items():
            for k, v in res["indicators"].items():
                indicators[f"{tf_name}_{k}"] = v
        indicators["mtf_direction"] = direction
        indicators["mtf_confidence"] = confidence
        market_data.indicators = indicators

        tf_parts = ", ".join(f"{tf}={r['direction']:+.2f}" for tf, r in tf_results.items())
        logger.info(
            f"[{self.name}] {pair}: direction={direction:+.2f}, confidence={confidence:.2f} [{tf_parts}]"
        )

        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            metadata=indicators,
        )

    # ------------------------------------------------------------------
    # Per-timeframe analysis
    # ------------------------------------------------------------------

    def _analyze_timeframe(
        self, price: float, closes: List[float], volumes: List[float],
        tf_name: str, candles: List = None
    ) -> dict:
        """Run indicators on a single timeframe and return result dict."""

        # Adapt periods to timeframe
        sma_fast, sma_slow, rsi_period, mom_period = self._periods_for(tf_name)

        sma_f = self._calculate_sma(closes, sma_fast)
        sma_s = self._calculate_sma(closes, sma_slow)
        rsi = self._calculate_rsi(closes, rsi_period)
        momentum = self._calculate_momentum(closes, mom_period)
        vol_trend = self._calculate_volume_trend(volumes)

        # Detect candlestick patterns
        candle_pattern = None
        if candles and len(candles) >= 3:
            candle_pattern = self._detect_candle_patterns(candles)

        direction, confidence, reasoning = self._evaluate_signals(
            price, sma_f, sma_s, rsi, momentum, vol_trend,
            candle_pattern=candle_pattern
        )

        indicators = {
            "sma_fast": sma_f,
            "sma_slow": sma_s,
            "rsi": rsi,
            "momentum": momentum,
            "volume_trend": vol_trend,
        }
        if candle_pattern:
            indicators["candle_pattern"] = candle_pattern["name"]
            indicators["candle_signal"] = candle_pattern["signal"]
            logger.info(f"Candle pattern: {candle_pattern['name']} ({candle_pattern['signal']:+.2f}) on {tf_name}")

        return {
            "direction": direction,
            "confidence": confidence,
            "reasoning": reasoning,
            "indicators": indicators,
        }

    @staticmethod
    def _periods_for(tf_name: str) -> Tuple[int, int, int, int]:
        """Return (sma_fast, sma_slow, rsi_period, momentum_period) per timeframe."""
        if tf_name == "1m":
            return 5, 12, 9, 5   # Fast signals for 1-min
        elif tf_name == "3m":
            return 6, 15, 10, 5  # Slightly slower for 3-min
        elif tf_name == "5m":
            return 8, 21, 14, 6
        elif tf_name == "15m":
            return 8, 21, 14, 6
        else:  # 1h
            return 12, 24, 14, 6

    # ------------------------------------------------------------------
    # Candlestick Pattern Recognition
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_candle_patterns(candles: List) -> Optional[Dict]:
        """
        Detect candlestick patterns from the last 3 OHLC candles.

        Each candle is [timestamp, open, high, low, close, volume].
        Returns dict with 'name' and 'signal' (-1.0 to +1.0), or None.
        """
        if len(candles) < 3:
            return None

        # Get last 3 candles
        c3 = candles[-3]  # oldest of the 3
        c2 = candles[-2]  # middle
        c1 = candles[-1]  # most recent

        # Extract OHLC for each candle
        def ohlc(c):
            return c[1], c[2], c[3], c[4]  # open, high, low, close

        o1, h1, l1, cl1 = ohlc(c1)
        o2, h2, l2, cl2 = ohlc(c2)
        o3, h3, l3, cl3 = ohlc(c3)

        body1 = abs(cl1 - o1)
        range1 = h1 - l1
        body2 = abs(cl2 - o2)
        range2 = h2 - l2
        body3 = abs(cl3 - o3)
        range3 = h3 - l3

        # Avoid division by zero
        if range1 == 0 or range2 == 0 or range3 == 0:
            return None

        # --- 3-candle patterns (check first, they're stronger) ---

        # Morning Star: big red + small body + big green
        is_red3 = cl3 < o3
        is_small2 = body2 < range2 * 0.3
        is_green1 = cl1 > o1
        if (is_red3 and body3 > range3 * 0.5 and
                is_small2 and
                is_green1 and body1 > range1 * 0.5):
            return {"name": "morning_star", "signal": 0.8}

        # Evening Star: big green + small body + big red
        is_green3 = cl3 > o3
        is_red1 = cl1 < o1
        if (is_green3 and body3 > range3 * 0.5 and
                is_small2 and
                is_red1 and body1 > range1 * 0.5):
            return {"name": "evening_star", "signal": -0.8}

        # --- 2-candle patterns ---

        # Bullish Engulfing: red candle then green candle that fully covers it
        is_red2 = cl2 < o2
        is_green1_2c = cl1 > o1
        if (is_red2 and is_green1_2c and
                o1 <= cl2 and cl1 >= o2):
            return {"name": "bullish_engulfing", "signal": 0.7}

        # Bearish Engulfing: green candle then red candle that fully covers it
        is_green2 = cl2 > o2
        is_red1_2c = cl1 < o1
        if (is_green2 and is_red1_2c and
                o1 >= cl2 and cl1 <= o2):
            return {"name": "bearish_engulfing", "signal": -0.7}

        # --- 1-candle patterns (most recent candle) ---

        upper_wick1 = h1 - max(o1, cl1)
        lower_wick1 = min(o1, cl1) - l1

        # Hammer: small body in top half, lower wick > 2x body
        body_mid1 = (o1 + cl1) / 2
        range_mid1 = (h1 + l1) / 2
        if (body1 < range1 * 0.35 and
                lower_wick1 > body1 * 2 and
                body_mid1 > range_mid1):
            return {"name": "hammer", "signal": 0.6}

        # Shooting Star: small body in bottom half, upper wick > 2x body
        if (body1 < range1 * 0.35 and
                upper_wick1 > body1 * 2 and
                body_mid1 < range_mid1):
            return {"name": "shooting_star", "signal": -0.6}

        # Doji: body < 10% of total range
        if body1 < range1 * 0.10:
            # Doji direction depends on context (preceding candle)
            if cl2 > o2:
                return {"name": "doji", "signal": -0.2}  # After green = bearish reversal
            else:
                return {"name": "doji", "signal": 0.2}  # After red = bullish reversal

        return None

    # ------------------------------------------------------------------
    # Multi-timeframe aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, tf_results: Dict[str, dict]) -> Tuple[float, float, str]:
        """Combine per-timeframe signals into one direction + confidence."""

        # Check for strong patterns on any timeframe
        best_pattern_tf = None
        best_pattern_signal = 0
        best_pattern_name = None
        for tf, res in tf_results.items():
            cp = res["indicators"].get("candle_pattern")
            cs = res["indicators"].get("candle_signal", 0)
            if cp and abs(cs) >= 0.6:
                if abs(cs) > abs(best_pattern_signal):
                    best_pattern_tf = tf
                    best_pattern_signal = cs
                    best_pattern_name = cp

        # Weighted direction — boost timeframes with strong patterns
        total_w = 0.0
        weighted_dir = 0.0
        for tf, res in tf_results.items():
            w = TF_WEIGHTS.get(tf, 0.15)
            # Boost weight of timeframe with strong pattern
            if tf == best_pattern_tf:
                w *= 1.5
            weighted_dir += res["direction"] * w
            total_w += w
        direction = weighted_dir / total_w if total_w else 0.0

        # Weighted confidence — pattern timeframes weighted higher
        weighted_conf = 0.0
        total_cw = 0.0
        for tf, res in tf_results.items():
            w = TF_WEIGHTS.get(tf, 0.15)
            if tf == best_pattern_tf:
                w *= 1.5
            weighted_conf += res["confidence"] * w
            total_cw += w
        base_confidence = weighted_conf / total_cw if total_cw else 0.3

        # Alignment bonus: if all timeframes agree on direction, boost confidence
        directions = [res["direction"] for res in tf_results.values()]
        all_bullish = all(d > 0.05 for d in directions)
        all_bearish = all(d < -0.05 for d in directions)

        if len(directions) >= 2 and (all_bullish or all_bearish):
            alignment_bonus = 0.15 * (len(directions) / 5)
            base_confidence = min(0.92, base_confidence + alignment_bonus)
        elif len(directions) >= 2:
            spread = max(directions) - min(directions)
            penalty = min(0.15, spread * 0.1)
            # Reduce penalty when a strong pattern exists — patterns are
            # timeframe-specific and shouldn't be penalized by neutral TFs
            if best_pattern_tf:
                penalty *= 0.4
            base_confidence = max(0.15, base_confidence - penalty)

        # Pattern-driven confidence floor: strong patterns guarantee minimum confidence
        if best_pattern_tf and abs(best_pattern_signal) >= 0.6:
            pattern_floor = 0.45 + abs(best_pattern_signal) * 0.15  # 0.54-0.57 for 0.6-0.8 signals
            base_confidence = max(base_confidence, pattern_floor)

        # Build reasoning
        tf_order = {"1h": 0, "15m": 1, "5m": 2, "3m": 3, "1m": 4}
        parts = []
        for tf, res in sorted(tf_results.items(), key=lambda x: tf_order.get(x[0], 5)):
            arrow = "↑" if res["direction"] > 0.05 else ("↓" if res["direction"] < -0.05 else "→")
            part = f"{tf}:{arrow}{res['direction']:+.2f}"
            if res["indicators"].get("candle_pattern"):
                part += f"({res['indicators']['candle_pattern']})"
            parts.append(part)

        alignment = "ALIGNED" if (all_bullish or all_bearish) else "MIXED"
        reasoning = f"MTF [{alignment}] {' | '.join(parts)}"

        return direction, base_confidence, reasoning

    # ------------------------------------------------------------------
    # Indicator calculations
    # ------------------------------------------------------------------

    def _empty_signal(self, pair: str) -> AnalystSignal:
        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=0.0,
            confidence=0.3,
            reasoning="Insufficient candle data",
            metadata={},
        )

    @staticmethod
    def _extract_closes(ohlcv: List) -> List[float]:
        if not ohlcv:
            return []
        return [candle[4] for candle in ohlcv]

    @staticmethod
    def _extract_volumes(ohlcv: List) -> List[float]:
        if not ohlcv:
            return []
        return [candle[5] for candle in ohlcv]

    @staticmethod
    def _calculate_sma(prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    @staticmethod
    def _calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))
        if len(gains) < period:
            return None
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calculate_momentum(prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        old = prices[-period]
        if old == 0:
            return None
        return ((prices[-1] - old) / old) * 100

    @staticmethod
    def _calculate_volume_trend(volumes: List[float]) -> Optional[float]:
        if len(volumes) < 6:
            return None
        recent = sum(volumes[-3:]) / 3
        older = sum(volumes[-6:-3]) / 3
        if older == 0:
            return 0.0
        return max(-1.0, min(1.0, (recent - older) / older))

    def _evaluate_signals(
        self,
        price: float,
        sma_fast: Optional[float],
        sma_slow: Optional[float],
        rsi: Optional[float],
        momentum: Optional[float],
        volume_trend: Optional[float],
        candle_pattern: Optional[Dict] = None,
    ) -> Tuple[float, float, str]:
        """Evaluate indicators for a single timeframe."""

        signals = []
        reasons = []

        # 1. SMA Crossover (weight 0.25)
        if sma_fast is not None and sma_slow is not None:
            if sma_fast > sma_slow:
                strength = min((sma_fast - sma_slow) / sma_slow * 100, 5) / 5
                signals.append(("sma", 0.5 + strength * 0.5, 0.25))
                reasons.append("SMA fast > slow")
            else:
                strength = min((sma_slow - sma_fast) / sma_slow * 100, 5) / 5
                signals.append(("sma", -0.5 - strength * 0.5, 0.25))
                reasons.append("SMA fast < slow")

        # 2. Price vs fast SMA (weight 0.15)
        if sma_fast is not None and price > 0:
            if price > sma_fast:
                strength = min((price - sma_fast) / sma_fast * 100, 3) / 3
                signals.append(("price_sma", 0.4 + strength * 0.5, 0.15))
            else:
                strength = min((sma_fast - price) / sma_fast * 100, 3) / 3
                signals.append(("price_sma", -0.4 - strength * 0.5, 0.15))

        # 3. RSI (weight 0.20)
        if rsi is not None:
            if rsi < 30:
                strength = (30 - rsi) / 30
                signals.append(("rsi", 0.6 + strength * 0.4, 0.20))
                reasons.append(f"RSI oversold ({rsi:.0f})")
            elif rsi > 70:
                strength = (rsi - 70) / 30
                signals.append(("rsi", -0.6 - strength * 0.4, 0.20))
                reasons.append(f"RSI overbought ({rsi:.0f})")
            else:
                signals.append(("rsi", 0, 0.08))

        # 4. Momentum (weight 0.12)
        if momentum is not None:
            if momentum > 3:
                signals.append(("momentum", 0.6, 0.12))
                reasons.append(f"Momentum {momentum:+.1f}%")
            elif momentum < -3:
                signals.append(("momentum", -0.6, 0.12))
                reasons.append(f"Momentum {momentum:+.1f}%")
            else:
                signals.append(("momentum", momentum / 5, 0.08))

        # 5. Volume (weight 0.08)
        if volume_trend is not None:
            if volume_trend > 0.2:
                signals.append(("volume", 0.2, 0.08))
            elif volume_trend < -0.2:
                signals.append(("volume", -0.1, 0.08))

        # 6. Candlestick Pattern (weight 0.30 — primary signal source)
        if candle_pattern is not None:
            signals.append(("candle_pattern", candle_pattern["signal"], 0.30))
            reasons.append(f"Pattern: {candle_pattern['name']}")

        if not signals:
            return 0.0, 0.3, "Insufficient data"

        total_weight = sum(s[2] for s in signals)
        direction = sum(s[1] * s[2] for s in signals) / total_weight if total_weight else 0

        signal_values = [s[1] for s in signals]
        avg_mag = sum(abs(v) for v in signal_values) / len(signal_values)
        agreement = 1 - (max(signal_values) - min(signal_values)) / 2 if len(signal_values) > 1 else 0.5

        agreeing = sum(1 for v in signal_values if (v > 0.1) == (direction > 0.1)) if abs(direction) > 0.1 else 0
        alignment_ratio = agreeing / len(signal_values) if signal_values else 0

        confidence = min(0.9, avg_mag * 0.5 + agreement * 0.3 + alignment_ratio * 0.2 + 0.10)

        # Pattern confirmation bonus: strong patterns (|signal| >= 0.6) that align
        # with the overall direction get a confidence boost
        if candle_pattern is not None and abs(candle_pattern["signal"]) >= 0.6:
            pattern_aligns = (candle_pattern["signal"] > 0) == (direction > 0)
            if pattern_aligns and abs(direction) > 0.05:
                confidence = min(0.92, confidence + 0.12)
                reasons.append("Pattern-confirmed")

        if avg_mag < 0.3 and (candle_pattern is None or abs(candle_pattern["signal"]) < 0.6):
            confidence = min(confidence, 0.50)

        return direction, confidence, "; ".join(reasons)
