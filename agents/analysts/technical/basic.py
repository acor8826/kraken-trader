"""
Technical Analyst Agent — Multi-Timeframe + Expanded Charting Signals

Analyzes price action across 1m, 3m, 5m, 15m, and 1h candles.
Includes candlestick pattern recognition, chart structure patterns,
MACD, Bollinger Bands, EMA, VWAP, and Stochastic RSI.
Timeframe agreement boosts confidence; disagreement lowers it.
"""

from typing import Dict, List, Optional, Tuple
import logging
import math
from datetime import datetime, timezone

from core.interfaces import IAnalyst
from core.models import AnalystSignal, MarketData

logger = logging.getLogger(__name__)

# Timeframe weights: higher timeframes get more weight for trend confirmation
TF_WEIGHTS = {"1h": 0.30, "15m": 0.25, "5m": 0.20, "3m": 0.13, "1m": 0.12}


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

        # New indicators
        ema_fast = self._calculate_ema(closes, sma_fast)
        ema_slow = self._calculate_ema(closes, sma_slow)
        macd_line, macd_signal, macd_hist = self._calculate_macd(closes)
        bb_upper, bb_mid, bb_lower, bb_pct = self._calculate_bollinger(closes)
        stoch_k, stoch_d = self._calculate_stochastic_rsi(closes, rsi_period)

        # Detect candlestick patterns (expanded library)
        candle_pattern = None
        if candles and len(candles) >= 3:
            candle_pattern = self._detect_candle_patterns(candles)

        direction, confidence, reasoning = self._evaluate_signals(
            price, sma_f, sma_s, rsi, momentum, vol_trend,
            candle_pattern=candle_pattern,
            ema_fast=ema_fast, ema_slow=ema_slow,
            macd_hist=macd_hist, bb_pct=bb_pct,
            stoch_k=stoch_k, stoch_d=stoch_d,
        )

        indicators = {
            "sma_fast": sma_f,
            "sma_slow": sma_s,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi,
            "momentum": momentum,
            "volume_trend": vol_trend,
            "macd_hist": macd_hist,
            "bb_pct": bb_pct,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
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
        Detect candlestick patterns from recent OHLC candles.

        Each candle is [timestamp, open, high, low, close, volume].
        Returns dict with 'name' and 'signal' (-1.0 to +1.0), or None.
        Patterns checked strongest-first so first match wins.
        """
        if len(candles) < 3:
            return None

        # Extract OHLC helper
        def ohlc(c):
            return c[1], c[2], c[3], c[4]

        # Get last 5 candles (or fewer)
        recent = candles[-5:] if len(candles) >= 5 else candles[-3:]
        c1 = candles[-1]  # most recent
        c2 = candles[-2]
        c3 = candles[-3]

        o1, h1, l1, cl1 = ohlc(c1)
        o2, h2, l2, cl2 = ohlc(c2)
        o3, h3, l3, cl3 = ohlc(c3)

        body1 = abs(cl1 - o1)
        range1 = h1 - l1
        body2 = abs(cl2 - o2)
        range2 = h2 - l2
        body3 = abs(cl3 - o3)
        range3 = h3 - l3

        if range1 == 0 or range2 == 0 or range3 == 0:
            return None

        is_green1 = cl1 > o1
        is_red1 = cl1 < o1
        is_green2 = cl2 > o2
        is_red2 = cl2 < o2
        is_green3 = cl3 > o3
        is_red3 = cl3 < o3
        is_small2 = body2 < range2 * 0.3
        upper_wick1 = h1 - max(o1, cl1)
        lower_wick1 = min(o1, cl1) - l1
        body_mid1 = (o1 + cl1) / 2
        range_mid1 = (h1 + l1) / 2

        # ── 3-candle patterns (strongest) ──

        # Morning Star: big red + small body + big green
        if (is_red3 and body3 > range3 * 0.5 and
                is_small2 and is_green1 and body1 > range1 * 0.5):
            return {"name": "morning_star", "signal": 0.8}

        # Evening Star: big green + small body + big red
        if (is_green3 and body3 > range3 * 0.5 and
                is_small2 and is_red1 and body1 > range1 * 0.5):
            return {"name": "evening_star", "signal": -0.8}

        # Three White Soldiers: 3 consecutive green candles with higher closes
        if (is_green3 and is_green2 and is_green1 and
                cl2 > cl3 and cl1 > cl2 and
                body3 > range3 * 0.5 and body2 > range2 * 0.5 and body1 > range1 * 0.5):
            return {"name": "three_white_soldiers", "signal": 0.85}

        # Three Black Crows: 3 consecutive red candles with lower closes
        if (is_red3 and is_red2 and is_red1 and
                cl2 < cl3 and cl1 < cl2 and
                body3 > range3 * 0.5 and body2 > range2 * 0.5 and body1 > range1 * 0.5):
            return {"name": "three_black_crows", "signal": -0.85}

        # Three-Bar Reversal (bullish): lower low + higher close
        if (l2 < l3 and l2 < l1 and is_green1 and cl1 > h3):
            return {"name": "three_bar_reversal_bull", "signal": 0.75}

        # Three-Bar Reversal (bearish): higher high + lower close
        if (h2 > h3 and h2 > h1 and is_red1 and cl1 < l3):
            return {"name": "three_bar_reversal_bear", "signal": -0.75}

        # ── 2-candle patterns ──

        # Bullish Engulfing
        if (is_red2 and is_green1 and o1 <= cl2 and cl1 >= o2):
            return {"name": "bullish_engulfing", "signal": 0.7}

        # Bearish Engulfing
        if (is_green2 and is_red1 and o1 >= cl2 and cl1 <= o2):
            return {"name": "bearish_engulfing", "signal": -0.7}

        # Piercing Line: red candle + green candle closing above midpoint of red
        red2_mid = (o2 + cl2) / 2
        if (is_red2 and is_green1 and o1 < cl2 and cl1 > red2_mid and cl1 < o2):
            return {"name": "piercing_line", "signal": 0.65}

        # Dark Cloud Cover: green candle + red candle closing below midpoint of green
        green2_mid = (o2 + cl2) / 2
        if (is_green2 and is_red1 and o1 > cl2 and cl1 < green2_mid and cl1 > o2):
            return {"name": "dark_cloud_cover", "signal": -0.65}

        # Bullish Harami: big red + small green inside it
        if (is_red2 and body2 > range2 * 0.5 and is_green1 and
                o1 > cl2 and cl1 < o2 and body1 < body2 * 0.5):
            return {"name": "bullish_harami", "signal": 0.55}

        # Bearish Harami: big green + small red inside it
        if (is_green2 and body2 > range2 * 0.5 and is_red1 and
                o1 < cl2 and cl1 > o2 and body1 < body2 * 0.5):
            return {"name": "bearish_harami", "signal": -0.55}

        # Tweezer Bottom: two candles with matching lows (within 0.1%)
        if (is_red2 and is_green1 and abs(l1 - l2) / max(l1, l2, 1e-10) < 0.001):
            return {"name": "tweezer_bottom", "signal": 0.60}

        # Tweezer Top: two candles with matching highs
        if (is_green2 and is_red1 and abs(h1 - h2) / max(h1, h2, 1e-10) < 0.001):
            return {"name": "tweezer_top", "signal": -0.60}

        # ── 1-candle patterns ──

        # Hammer
        if (body1 < range1 * 0.35 and lower_wick1 > body1 * 2 and body_mid1 > range_mid1):
            return {"name": "hammer", "signal": 0.6}

        # Inverted Hammer (bullish, after downtrend)
        if (body1 < range1 * 0.35 and upper_wick1 > body1 * 2 and
                body_mid1 < range_mid1 and is_red2):
            return {"name": "inverted_hammer", "signal": 0.5}

        # Shooting Star
        if (body1 < range1 * 0.35 and upper_wick1 > body1 * 2 and body_mid1 < range_mid1):
            return {"name": "shooting_star", "signal": -0.6}

        # Hanging Man (bearish hammer after uptrend)
        if (body1 < range1 * 0.35 and lower_wick1 > body1 * 2 and
                body_mid1 > range_mid1 and is_green2):
            return {"name": "hanging_man", "signal": -0.5}

        # Marubozu (full body, no wicks — strong conviction)
        if (body1 > range1 * 0.90):
            if is_green1:
                return {"name": "bullish_marubozu", "signal": 0.65}
            else:
                return {"name": "bearish_marubozu", "signal": -0.65}

        # Doji
        if body1 < range1 * 0.10:
            # Dragonfly Doji: long lower wick, no upper wick
            if lower_wick1 > range1 * 0.6 and upper_wick1 < range1 * 0.1:
                return {"name": "dragonfly_doji", "signal": 0.55}
            # Gravestone Doji: long upper wick, no lower wick
            if upper_wick1 > range1 * 0.6 and lower_wick1 < range1 * 0.1:
                return {"name": "gravestone_doji", "signal": -0.55}
            # Regular Doji
            if cl2 > o2:
                return {"name": "doji", "signal": -0.2}
            else:
                return {"name": "doji", "signal": 0.2}

        # ── Multi-candle structure patterns (need 5+ candles) ──
        if len(candles) >= 5:
            c4 = candles[-4]
            c5 = candles[-5]
            o4, h4, l4, cl4 = ohlc(c4)
            o5, h5, l5, cl5 = ohlc(c5)

            # Double Bottom: two lows within 0.2%, with a higher middle
            if (abs(l5 - l1) / max(l5, l1, 1e-10) < 0.002 and
                    h3 > max(h5, h1) * 0.998 and is_green1):
                return {"name": "double_bottom", "signal": 0.75}

            # Double Top: two highs within 0.2%, with a lower middle
            if (abs(h5 - h1) / max(h5, h1, 1e-10) < 0.002 and
                    l3 < min(l5, l1) * 1.002 and is_red1):
                return {"name": "double_top", "signal": -0.75}

            # Bull Flag: strong up move (c5→c4) then consolidation (c3→c1)
            move_up = (cl4 - o5) / max(o5, 1e-10)
            consol_range = max(h3, h2, h1) - min(l3, l2, l1)
            up_range = h4 - l5
            if (move_up > 0.02 and up_range > 0 and
                    consol_range < up_range * 0.5 and is_green1):
                return {"name": "bull_flag", "signal": 0.70}

            # Bear Flag: strong down move then consolidation
            move_down = (o5 - cl4) / max(o5, 1e-10)
            if (move_down > 0.02 and up_range > 0 and
                    consol_range < up_range * 0.5 and is_red1):
                return {"name": "bear_flag", "signal": -0.70}

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

        # Pattern-driven confidence floor: patterns guarantee minimum confidence
        if best_pattern_tf and abs(best_pattern_signal) >= 0.5:
            pattern_floor = 0.48 + abs(best_pattern_signal) * 0.20  # 0.58-0.64 for 0.5-0.8 signals
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

    @staticmethod
    def _calculate_ema(prices: List[float], period: int) -> Optional[float]:
        """Exponential Moving Average — more responsive than SMA."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p - ema) * multiplier + ema
        return ema

    @staticmethod
    def _calculate_macd(
        prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """MACD line, signal line, and histogram."""
        if len(prices) < slow + signal:
            return None, None, None

        def ema_series(data, period):
            mult = 2 / (period + 1)
            result = [sum(data[:period]) / period]
            for p in data[period:]:
                result.append((p - result[-1]) * mult + result[-1])
            return result

        ema_fast = ema_series(prices, fast)
        ema_slow = ema_series(prices, slow)
        # Align lengths
        offset = len(ema_fast) - len(ema_slow)
        macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]
        if len(macd_line) < signal:
            return None, None, None
        sig_line = ema_series(macd_line, signal)
        offset2 = len(macd_line) - len(sig_line)
        hist = macd_line[-1] - sig_line[-1]
        return macd_line[-1], sig_line[-1], hist

    @staticmethod
    def _calculate_bollinger(
        prices: List[float], period: int = 20, num_std: float = 2.0
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Bollinger Bands: upper, middle, lower, %B."""
        if len(prices) < period:
            return None, None, None, None
        window = prices[-period:]
        mid = sum(window) / period
        variance = sum((p - mid) ** 2 for p in window) / period
        std = math.sqrt(variance)
        upper = mid + num_std * std
        lower = mid - num_std * std
        band_width = upper - lower
        bb_pct = (prices[-1] - lower) / band_width if band_width > 0 else 0.5
        return upper, mid, lower, bb_pct

    @staticmethod
    def _calculate_stochastic_rsi(
        prices: List[float], rsi_period: int = 14, stoch_period: int = 14, smooth_k: int = 3, smooth_d: int = 3
    ) -> Tuple[Optional[float], Optional[float]]:
        """Stochastic RSI: %K and %D."""
        needed = rsi_period + stoch_period + smooth_k + smooth_d
        if len(prices) < needed:
            return None, None

        # Compute RSI series using exponential moving average (O(1) per step)
        rsi_values = []
        ag = al = 0.0
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            gain = max(change, 0)
            loss = abs(min(change, 0))
            if i <= rsi_period:
                ag += gain / rsi_period
                al += loss / rsi_period
                if i == rsi_period:
                    if al == 0:
                        rsi_values.append(100.0)
                    else:
                        rsi_values.append(100 - (100 / (1 + ag / al)))
            else:
                ag = (ag * (rsi_period - 1) + gain) / rsi_period
                al = (al * (rsi_period - 1) + loss) / rsi_period
                if al == 0:
                    rsi_values.append(100.0)
                else:
                    rsi_values.append(100 - (100 / (1 + ag / al)))

        if len(rsi_values) < stoch_period:
            return None, None

        # Stochastic of RSI
        stoch_k_values = []
        for i in range(stoch_period - 1, len(rsi_values)):
            window = rsi_values[i - stoch_period + 1: i + 1]
            low = min(window)
            high = max(window)
            if high == low:
                stoch_k_values.append(50.0)
            else:
                stoch_k_values.append((rsi_values[i] - low) / (high - low) * 100)

        if len(stoch_k_values) < smooth_k:
            return None, None

        # Smooth %K
        smoothed_k = []
        for i in range(smooth_k - 1, len(stoch_k_values)):
            smoothed_k.append(sum(stoch_k_values[i - smooth_k + 1: i + 1]) / smooth_k)

        if len(smoothed_k) < smooth_d:
            return None, None

        # %D = SMA of smoothed %K
        k = smoothed_k[-1]
        d = sum(smoothed_k[-smooth_d:]) / smooth_d
        return k, d

    def _evaluate_signals(
        self,
        price: float,
        sma_fast: Optional[float],
        sma_slow: Optional[float],
        rsi: Optional[float],
        momentum: Optional[float],
        volume_trend: Optional[float],
        candle_pattern: Optional[Dict] = None,
        ema_fast: Optional[float] = None,
        ema_slow: Optional[float] = None,
        macd_hist: Optional[float] = None,
        bb_pct: Optional[float] = None,
        stoch_k: Optional[float] = None,
        stoch_d: Optional[float] = None,
    ) -> Tuple[float, float, str]:
        """Evaluate indicators for a single timeframe."""

        signals = []
        reasons = []

        # 1. EMA/SMA Crossover (weight 0.18)
        fast = ema_fast if ema_fast is not None else sma_fast
        slow = ema_slow if ema_slow is not None else sma_slow
        if fast is not None and slow is not None:
            if fast > slow:
                strength = min((fast - slow) / slow * 100, 5) / 5
                signals.append(("ema", 0.5 + strength * 0.5, 0.18))
                reasons.append("EMA bullish")
            else:
                strength = min((slow - fast) / slow * 100, 5) / 5
                signals.append(("ema", -0.5 - strength * 0.5, 0.18))
                reasons.append("EMA bearish")

        # 2. Price vs fast EMA (weight 0.10)
        ref = ema_fast if ema_fast is not None else sma_fast
        if ref is not None and price > 0:
            if price > ref:
                strength = min((price - ref) / ref * 100, 3) / 3
                signals.append(("price_ema", 0.4 + strength * 0.5, 0.10))
            else:
                strength = min((ref - price) / ref * 100, 3) / 3
                signals.append(("price_ema", -0.4 - strength * 0.5, 0.10))

        # 3. RSI (weight 0.14) — wider zones for more signals
        if rsi is not None:
            if rsi < 35:
                strength = (35 - rsi) / 35
                signals.append(("rsi", 0.5 + strength * 0.5, 0.14))
                reasons.append(f"RSI oversold ({rsi:.0f})")
            elif rsi > 65:
                strength = (rsi - 65) / 35
                signals.append(("rsi", -0.5 - strength * 0.5, 0.14))
                reasons.append(f"RSI overbought ({rsi:.0f})")
            else:
                # Midrange RSI contributes weak directional signal
                rsi_dir = (rsi - 50) / 50
                signals.append(("rsi", rsi_dir * 0.3, 0.06))

        # 4. MACD Histogram (weight 0.12)
        if macd_hist is not None:
            if price > 0:
                macd_norm = macd_hist / price * 1000  # normalize
                sig = max(-1.0, min(1.0, macd_norm))
                w = 0.12 if abs(sig) > 0.3 else 0.06
                signals.append(("macd", sig, w))
                if abs(sig) > 0.3:
                    reasons.append(f"MACD {'bull' if sig > 0 else 'bear'}")

        # 5. Bollinger Band %B (weight 0.10)
        if bb_pct is not None:
            if bb_pct < 0.1:
                signals.append(("bb", 0.6, 0.10))
                reasons.append("BB oversold")
            elif bb_pct > 0.9:
                signals.append(("bb", -0.6, 0.10))
                reasons.append("BB overbought")
            else:
                bb_dir = (bb_pct - 0.5) * -0.4  # mean-revert bias
                signals.append(("bb", bb_dir, 0.05))

        # 6. Stochastic RSI (weight 0.08)
        if stoch_k is not None and stoch_d is not None:
            if stoch_k < 20 and stoch_d < 20:
                signals.append(("stoch", 0.6, 0.08))
                reasons.append("StochRSI oversold")
            elif stoch_k > 80 and stoch_d > 80:
                signals.append(("stoch", -0.6, 0.08))
                reasons.append("StochRSI overbought")
            elif stoch_k > stoch_d:
                signals.append(("stoch", 0.2, 0.04))
            else:
                signals.append(("stoch", -0.2, 0.04))

        # 7. Momentum (weight 0.08)
        if momentum is not None:
            if momentum > 2:
                signals.append(("momentum", min(0.8, momentum / 5), 0.08))
                reasons.append(f"Mom {momentum:+.1f}%")
            elif momentum < -2:
                signals.append(("momentum", max(-0.8, momentum / 5), 0.08))
                reasons.append(f"Mom {momentum:+.1f}%")
            else:
                signals.append(("momentum", momentum / 5, 0.04))

        # 8. Volume (weight 0.06)
        if volume_trend is not None:
            if volume_trend > 0.3:
                signals.append(("volume", 0.3, 0.06))
                reasons.append("Vol surge")
            elif volume_trend < -0.3:
                signals.append(("volume", -0.15, 0.06))

        # 9. Candlestick Pattern (weight 0.35 — primary signal source)
        if candle_pattern is not None:
            signals.append(("candle_pattern", candle_pattern["signal"], 0.35))
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

        confidence = min(0.92, avg_mag * 0.5 + agreement * 0.3 + alignment_ratio * 0.2 + 0.12)

        # Pattern confirmation bonus: patterns (|signal| >= 0.5) that align
        if candle_pattern is not None and abs(candle_pattern["signal"]) >= 0.5:
            pattern_aligns = (candle_pattern["signal"] > 0) == (direction > 0)
            if pattern_aligns and abs(direction) > 0.03:
                confidence = min(0.94, confidence + 0.15)
                reasons.append("Pattern-confirmed")

        # Multi-indicator confluence bonus: 3+ indicators agreeing strongly
        strong_agree = sum(1 for v in signal_values if abs(v) > 0.4 and (v > 0) == (direction > 0))
        if strong_agree >= 3:
            confidence = min(0.95, confidence + 0.08)
            reasons.append(f"Confluence({strong_agree})")

        # Only cap weak signals if no pattern AND no confluence
        if avg_mag < 0.25 and (candle_pattern is None or abs(candle_pattern["signal"]) < 0.5) and strong_agree < 2:
            confidence = min(confidence, 0.45)

        return direction, confidence, "; ".join(reasons)
