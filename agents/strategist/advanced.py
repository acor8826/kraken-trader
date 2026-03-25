"""
Advanced Strategist

Stage 3 strategist with:
- Strategy library (TREND_FOLLOW, MEAN_REVERT, BREAKOUT, ACCUMULATE, RISK_OFF)
- Regime-aware strategy selection
- Dynamic position sizing
- Advanced risk management
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum
import logging

from core.interfaces import IStrategist, ILLM
from core.models import (
    MarketIntel, Portfolio, TradingPlan, TradeSignal,
    TradeAction, OrderType, Regime
)
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class Strategy(Enum):
    """Trading strategy types"""
    TREND_FOLLOW = "trend_follow"      # Ride momentum in trends
    MEAN_REVERT = "mean_revert"        # Fade extremes in ranges
    BREAKOUT = "breakout"              # Trade volatility expansions
    ACCUMULATE = "accumulate"          # DCA into positions
    RISK_OFF = "risk_off"              # Reduce exposure


@dataclass
class StrategyConfig:
    """Configuration for a trading strategy"""
    name: str
    description: str
    preferred_regimes: List[Regime]
    min_confidence: float
    position_sizing: str  # "aggressive", "moderate", "conservative"
    stop_loss_multiplier: float
    take_profit_multiplier: float


# Strategy library
STRATEGY_LIBRARY = {
    Strategy.TREND_FOLLOW: StrategyConfig(
        name="Trend Follow",
        description="Ride momentum in established trends with trailing stops",
        preferred_regimes=[Regime.TRENDING_UP, Regime.TRENDING_DOWN],
        min_confidence=0.45,
        position_sizing="aggressive",
        stop_loss_multiplier=1.5,
        take_profit_multiplier=2.5
    ),
    Strategy.MEAN_REVERT: StrategyConfig(
        name="Mean Reversion",
        description="Fade extremes with tight stops, expecting return to mean",
        preferred_regimes=[Regime.RANGING],
        min_confidence=0.50,
        position_sizing="moderate",
        stop_loss_multiplier=0.75,
        take_profit_multiplier=1.5
    ),
    Strategy.BREAKOUT: StrategyConfig(
        name="Breakout",
        description="Trade volatility expansion with momentum confirmation",
        preferred_regimes=[Regime.VOLATILE],
        min_confidence=0.55,
        position_sizing="conservative",
        stop_loss_multiplier=2.0,
        take_profit_multiplier=2.5
    ),
    Strategy.ACCUMULATE: StrategyConfig(
        name="Accumulate",
        description="DCA into position during uncertainty or corrections",
        preferred_regimes=[Regime.UNKNOWN, Regime.RANGING],
        min_confidence=0.40,
        position_sizing="conservative",
        stop_loss_multiplier=1.0,
        take_profit_multiplier=2.0
    ),
    Strategy.RISK_OFF: StrategyConfig(
        name="Risk Off",
        description="Reduce exposure and wait for clarity",
        preferred_regimes=[Regime.VOLATILE, Regime.UNKNOWN],
        min_confidence=0.40,
        position_sizing="minimal",
        stop_loss_multiplier=0.5,
        take_profit_multiplier=1.0
    )
}


class BayesianConfidence:
    """Lightweight Bayesian prior/posterior for trade confidence.

    Uses Beta distribution: prior Beta(alpha, beta) per strategy per pair.
    alpha = successes + 1, beta = failures + 1 (uniform prior).
    """

    def __init__(self):
        self._priors: Dict[str, Dict[str, list]] = {}  # {strategy: {pair: [alpha, beta]}}

    def get_posterior(self, strategy: str, pair: str) -> float:
        """Return posterior mean = alpha / (alpha + beta)."""
        prior = self._priors.get(strategy, {}).get(pair, [1, 1])
        return prior[0] / (prior[0] + prior[1])

    def update(self, strategy: str, pair: str, success: bool):
        """Update Beta distribution with trade outcome."""
        if strategy not in self._priors:
            self._priors[strategy] = {}
        if pair not in self._priors[strategy]:
            self._priors[strategy][pair] = [1, 1]
        if success:
            self._priors[strategy][pair][0] += 1
        else:
            self._priors[strategy][pair][1] += 1

    def adjust_confidence(self, base_confidence: float, strategy: str, pair: str) -> float:
        """Blend heuristic confidence with Bayesian posterior.

        70% heuristic + 30% Bayesian posterior.
        """
        posterior = self.get_posterior(strategy, pair)
        return base_confidence * 0.7 + posterior * 0.3


# Advanced system prompt for Claude
ADVANCED_SYSTEM_PROMPT = """You are a sophisticated cryptocurrency trading strategist managing a multi-strategy portfolio. You select and configure trading strategies based on market conditions.

## Strategy Library
1. TREND_FOLLOW: For trending markets. Enter with momentum, wider stops, ride the trend.
2. MEAN_REVERT: For ranging markets. Fade extremes, tight stops, quick profits.
3. BREAKOUT: For volatile markets with expansion. Trade the move, accept wider risk.
4. ACCUMULATE: For uncertainty. Build positions gradually, average in.
5. RISK_OFF: When conditions are unfavorable. Reduce exposure, preserve capital.

## Decision Framework
1. Identify the market regime from analyst signals
2. Select the appropriate strategy for the regime
3. Size positions based on confidence and strategy rules
4. Set stops and targets based on strategy parameters

## Response Format (JSON only)
{
    "action": "BUY" | "SELL" | "HOLD",
    "strategy": "TREND_FOLLOW" | "MEAN_REVERT" | "BREAKOUT" | "ACCUMULATE" | "RISK_OFF",
    "confidence": 0.0 to 1.0,
    "size_pct": 0.0 to max_position_pct,
    "stop_distance_pct": suggested stop loss distance,
    "reasoning": "Brief explanation",
    "regime_assessment": "Description of current market conditions",
    "key_signals": ["signal1", "signal2"]
}"""


class AdvancedStrategist(IStrategist):
    """
    Stage 3 Advanced Strategist with strategy library.

    Features:
    - Regime-aware strategy selection
    - Dynamic position sizing
    - Strategy-specific risk parameters
    - LLM-powered decision making with fallback
    """

    def __init__(self, llm: ILLM = None, settings: Settings = None):
        self.llm = llm
        self.settings = settings or get_settings()
        self._last_strategy = None
        self.bayesian = BayesianConfidence()
        logger.info("AdvancedStrategist initialized with strategy library")

    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Create trading plan using strategy library.

        Args:
            intel: Fused market intelligence
            portfolio: Current portfolio state
            risk_params: Risk parameters (optional)

        Returns:
            TradingPlan with strategy metadata
        """
        risk = risk_params or {
            "max_position_pct": self.settings.risk.max_position_pct,
            "stop_loss_pct": self.settings.risk.stop_loss_pct,
            "min_confidence": self.settings.risk.min_confidence
        }

        # Select strategy based on regime (portfolio used for contrarian override)
        strategy = self._select_strategy(intel, portfolio)
        strategy_config = STRATEGY_LIBRARY[strategy]

        logger.info(f"[{intel.pair}] Regime: {intel.regime.value} → Strategy: {strategy.value}")

        decision = None

        # Try LLM-based decision first
        if self.llm:
            try:
                decision = await self._llm_decision(intel, portfolio, risk, strategy)
            except Exception as e:
                logger.warning(f"[{intel.pair}] LLM decision failed ({type(e).__name__}: {e}), using RULE-BASED fallback")
        else:
            logger.info(f"[{intel.pair}] No LLM configured, using RULE-BASED strategy")

        # Fall back to rule-based decision if LLM failed
        if decision is None:
            pair_rank = risk.get("pair_ranks", {}).get(intel.pair) if risk else None
            decision = self._rule_based_decision(intel, strategy, risk, pair_rank=pair_rank)
            logger.info(f"[{intel.pair}] Rule-based decision: {decision.get('action')} "
                         f"(confidence={decision.get('confidence', 0):.2f}, strategy={decision.get('strategy')}"
                         f"{f', rank={pair_rank}' if pair_rank else ''})")

        # Pattern override: if decision is HOLD, check for strong patterns
        # This applies regardless of whether LLM or rule-based made the decision
        decision = self._apply_pattern_override(intel, decision, risk)

        logger.info(f"[{intel.pair}] Final decision: {decision.get('action')} "
                     f"(conf={float(decision.get('confidence', 0)):.2f})")

        return self._build_plan(intel, decision, strategy_config, risk)

    def _select_strategy(self, intel: MarketIntel, portfolio: Portfolio = None) -> Strategy:
        """Select the best strategy for current conditions"""
        regime = intel.regime

        # Check each strategy's preferred regimes
        best_strategy = Strategy.RISK_OFF
        best_match = False

        for strategy, config in STRATEGY_LIBRARY.items():
            if regime in config.preferred_regimes:
                # Found a matching strategy
                if not best_match:
                    best_strategy = strategy
                    best_match = True
                # If multiple match, prefer based on confidence
                elif intel.fused_confidence >= config.min_confidence:
                    best_strategy = strategy

        # Override based on signal strength
        if abs(intel.fused_direction) > 0.5 and intel.fused_confidence > 0.7:
            if regime in [Regime.TRENDING_UP, Regime.TRENDING_DOWN]:
                best_strategy = Strategy.TREND_FOLLOW
        elif intel.disagreement > 0.5:
            # High analyst disagreement = uncertainty
            best_strategy = Strategy.RISK_OFF

        # Contrarian override: in bearish markets with few/no positions, switch
        # from TREND_FOLLOW/RISK_OFF to ACCUMULATE so the bot deploys capital
        # instead of sitting 100% cash indefinitely.
        if best_strategy in (Strategy.TREND_FOLLOW, Strategy.RISK_OFF):
            if regime in (Regime.TRENDING_DOWN, Regime.UNKNOWN):
                has_positions = (
                    portfolio and portfolio.positions and len(portfolio.positions) > 0
                ) if portfolio else False
                # Only switch to ACCUMULATE when mostly in cash
                if not has_positions and intel.fused_direction > -0.5:
                    logger.info(
                        f"[{intel.pair}] Contrarian override: {best_strategy.value} → accumulate "
                        f"(no positions, direction={intel.fused_direction:+.2f})"
                    )
                    best_strategy = Strategy.ACCUMULATE

        self._last_strategy = best_strategy
        return best_strategy

    async def _llm_decision(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk: Dict,
        strategy: Strategy
    ) -> Dict:
        """Get trading decision from LLM"""
        strategy_config = STRATEGY_LIBRARY[strategy]

        prompt = f"""Analyze and create a trading plan.

## Current Strategy: {strategy.value.upper()}
{strategy_config.description}

## Market Intelligence for {intel.pair}
{intel.to_summary()}

## Portfolio State
{portfolio.to_summary()}

## Risk Parameters
- Max position: {risk['max_position_pct']:.0%}
- Base stop-loss: {risk['stop_loss_pct']:.0%}
- Strategy stop multiplier: {strategy_config.stop_loss_multiplier}x

## Position Sizing Guide
- Aggressive: Up to max position on strong signals
- Moderate: 50-75% of max on good signals
- Conservative: 25-50% of max, gradual entry
- Minimal: <25%, capital preservation

Current sizing mode: {strategy_config.position_sizing}

Generate your decision as JSON."""

        decision = await self.llm.analyze_market(
            prompt=prompt,
            system_prompt=ADVANCED_SYSTEM_PROMPT
        )

        # LLM sometimes returns a list or string; normalize to dict
        if isinstance(decision, str):
            import json, re
            # Try direct parse first
            try:
                decision = json.loads(decision)
            except (json.JSONDecodeError, ValueError):
                # Try to extract JSON object from text
                m = re.search(r'\{[\s\S]*\}', decision)
                if m:
                    decision = json.loads(m.group())
                else:
                    raise ValueError(f"Could not extract JSON from LLM string response")
        if isinstance(decision, list):
            decision = decision[0] if decision else {}
        if not isinstance(decision, dict):
            raise ValueError(f"LLM returned unexpected type: {type(decision)}")

        return decision

    def _extract_patterns(self, intel: MarketIntel) -> list:
        """Extract candlestick patterns from analyst signal metadata."""
        patterns = []
        for sig in (intel.signals or []):
            if sig.source != "technical":
                continue
            meta = sig.metadata or {}
            for key, val in meta.items():
                if key.endswith("_candle_pattern") and val:
                    tf = key.replace("_candle_pattern", "")
                    signal_val = meta.get(f"{tf}_candle_signal", 0)
                    patterns.append({"name": val, "timeframe": tf, "signal": signal_val})
        return patterns

    def _strongest_pattern(self, patterns: list) -> dict | None:
        """Return the strongest pattern by absolute signal, or None."""
        if not patterns:
            return None
        return max(patterns, key=lambda p: abs(p.get("signal", 0)))

    def _rule_based_decision(
        self,
        intel: MarketIntel,
        strategy: Strategy,
        risk: Dict,
        pair_rank: int = None
    ) -> Dict:
        """Generate decision using rules (LLM fallback).

        Args:
            pair_rank: 1-based rank of this pair by signal strength (1=strongest).
                       Used to lower thresholds for top-ranked pairs.
        """
        config = STRATEGY_LIBRARY[strategy]

        # Determine action based on signal and strategy
        action = "HOLD"
        confidence = 0.0
        size_pct = 0.0
        stop_distance = risk["stop_loss_pct"] * config.stop_loss_multiplier

        # Lower direction threshold for top-ranked pairs
        buy_direction_threshold = 0.15  # default
        if pair_rank is not None and pair_rank <= 2:
            buy_direction_threshold = 0.05  # Very easy entry for top 2 pairs

        # ─── Check for strong candlestick patterns ─────────────────
        patterns = self._extract_patterns(intel)
        best_pattern = self._strongest_pattern(patterns)
        has_strong_pattern = best_pattern and abs(best_pattern["signal"]) >= 0.6
        pattern_bullish = has_strong_pattern and best_pattern["signal"] > 0
        pattern_bearish = has_strong_pattern and best_pattern["signal"] < 0

        # Strategy-specific logic
        if strategy == Strategy.TREND_FOLLOW:
            if intel.regime == Regime.TRENDING_UP and intel.fused_direction > buy_direction_threshold:
                action = "BUY"
                direction_boost = min(1.0, abs(intel.fused_direction) / 0.5)
                confidence = min(0.9, intel.fused_confidence * (0.9 + 0.2 * direction_boost))
                size_pct = risk["max_position_pct"] * 0.8
            elif intel.regime == Regime.TRENDING_DOWN and intel.fused_direction < -0.15:
                action = "SELL"
                confidence = min(0.9, intel.fused_confidence * 1.1)
                size_pct = 1.0

        elif strategy == Strategy.MEAN_REVERT:
            if intel.fused_direction < -0.3 and intel.fused_confidence > 0.45:
                action = "BUY"
                confidence = intel.fused_confidence * 0.9
                size_pct = risk["max_position_pct"] * 0.5
            elif intel.fused_direction > 0.3 and intel.fused_confidence > 0.45:
                action = "SELL"
                confidence = intel.fused_confidence * 0.9
                size_pct = 1.0

        elif strategy == Strategy.BREAKOUT:
            if abs(intel.fused_direction) > 0.4 and intel.fused_confidence > 0.50:
                action = "BUY" if intel.fused_direction > 0 else "SELL"
                confidence = intel.fused_confidence
                size_pct = risk["max_position_pct"] * 0.4

        elif strategy == Strategy.ACCUMULATE:
            # In bearish/fearful markets, allow contrarian accumulation:
            # - Top 2 pairs: buy even at direction -0.20 (oversold dip buying)
            # - Other pairs: buy at direction -0.10 (mild contrarian)
            # - Normal bull market: original threshold 0.10
            if pair_rank and pair_rank <= 2:
                dir_threshold = -0.20
            elif intel.fused_direction < -0.1:
                # Bearish market — contrarian accumulate with lower bar
                dir_threshold = -0.10
            else:
                dir_threshold = buy_direction_threshold if pair_rank and pair_rank <= 2 else 0.05
            if intel.fused_direction > dir_threshold and intel.fused_confidence > 0.38:
                action = "BUY"
                # Scale confidence and size down for contrarian entries
                if intel.fused_direction < 0:
                    # Contrarian entry — smaller size, lower confidence
                    confidence = intel.fused_confidence * 0.7
                    size_pct = risk["max_position_pct"] * 0.15
                    logger.info(f"[{intel.pair}] Contrarian accumulate: dir={intel.fused_direction:+.2f}")
                else:
                    confidence = intel.fused_confidence * 0.8
                    size_pct = risk["max_position_pct"] * 0.25

        elif strategy == Strategy.RISK_OFF:
            if intel.fused_direction < -0.15:
                action = "SELL"
                confidence = 0.7
                size_pct = 0.5

        # ─── Pattern-driven entries ─────────────────────────────────
        # Strong patterns can drive entries even when other signals are weak.
        # Higher timeframe patterns (15m, 1h) get stronger treatment.
        if action == "HOLD" and has_strong_pattern:
            pattern_tf = best_pattern.get("timeframe", "5m")
            pattern_strength = abs(best_pattern["signal"])

            # Higher timeframes require less directional agreement
            if pattern_tf in ("1h", "15m"):
                dir_threshold = -0.05  # Allow slightly opposing fused direction
                size_mult = 0.45
            elif pattern_tf in ("5m", "3m"):
                dir_threshold = 0.0    # Need at least neutral direction
                size_mult = 0.35
            else:
                dir_threshold = 0.03   # 1m needs weak confirmation
                size_mult = 0.25

            # Pattern confidence: blend pattern signal with fused confidence
            pattern_conf = min(0.88, intel.fused_confidence * 0.6 + pattern_strength * 0.45)

            if pattern_bullish and intel.fused_direction > dir_threshold:
                action = "BUY"
                confidence = pattern_conf
                size_pct = risk["max_position_pct"] * size_mult
                stop_distance = risk["stop_loss_pct"] * 1.2
                logger.info(f"[{intel.pair}] Pattern-driven BUY: {best_pattern['name']} "
                           f"({pattern_tf}, signal={best_pattern['signal']:+.2f}, conf={confidence:.2f})")
            elif pattern_bearish and intel.fused_direction < -dir_threshold:
                action = "SELL"
                confidence = pattern_conf
                size_pct = 0.5
                logger.info(f"[{intel.pair}] Pattern-driven SELL: {best_pattern['name']} "
                           f"({pattern_tf}, signal={best_pattern['signal']:+.2f}, conf={confidence:.2f})")

        # ─── Multi-pattern boost ──────────────────────────────────
        # Multiple patterns across timeframes = stronger signal
        if action == "HOLD" and len(patterns) >= 2:
            bullish_patterns = [p for p in patterns if p["signal"] > 0.3]
            bearish_patterns = [p for p in patterns if p["signal"] < -0.3]
            if len(bullish_patterns) >= 2 and intel.fused_direction > -0.10:
                action = "BUY"
                avg_signal = sum(p["signal"] for p in bullish_patterns) / len(bullish_patterns)
                confidence = min(0.85, intel.fused_confidence * 0.5 + avg_signal * 0.4 + 0.1)
                size_pct = risk["max_position_pct"] * 0.35
                stop_distance = risk["stop_loss_pct"] * 1.2
                logger.info(f"[{intel.pair}] Multi-pattern BUY: {len(bullish_patterns)} bullish patterns")
            elif len(bearish_patterns) >= 2 and intel.fused_direction < 0.10:
                action = "SELL"
                avg_signal = sum(abs(p["signal"]) for p in bearish_patterns) / len(bearish_patterns)
                confidence = min(0.85, intel.fused_confidence * 0.5 + avg_signal * 0.4 + 0.1)
                size_pct = 0.5
                logger.info(f"[{intel.pair}] Multi-pattern SELL: {len(bearish_patterns)} bearish patterns")

        # ─── Pattern confidence boost for existing decisions ───────
        if action != "HOLD" and has_strong_pattern:
            confirms = (action == "BUY" and pattern_bullish) or (action == "SELL" and pattern_bearish)
            if confirms:
                confidence = min(0.92, confidence + 0.10)

        # Boost sizing for top-ranked pairs when capital is idle
        if action == "BUY" and pair_rank is not None and pair_rank <= 2:
            if strategy in (Strategy.ACCUMULATE, Strategy.TREND_FOLLOW):
                size_pct = max(size_pct, risk["max_position_pct"] * 0.35)

        # ─── Idle capital trigger ─────────────────────────────────
        # If still HOLD and this is a top-ranked pair, force a small
        # accumulation buy to prevent sitting 100% cash indefinitely.
        # Only applies when direction isn't catastrophically bearish.
        if action == "HOLD" and pair_rank is not None and pair_rank <= 2:
            if intel.fused_direction > -0.35 and intel.fused_confidence > 0.30:
                action = "BUY"
                confidence = max(0.42, intel.fused_confidence * 0.6)
                size_pct = risk["max_position_pct"] * 0.10  # Very small position
                stop_distance = risk["stop_loss_pct"] * 1.5  # Wider stop for low-conviction
                logger.info(
                    f"[{intel.pair}] Idle capital trigger: forced small accumulate "
                    f"(rank={pair_rank}, dir={intel.fused_direction:+.2f}, conf={confidence:.2f})"
                )

        reasoning = f"{strategy.value}: {config.description}. "
        if action != "HOLD":
            reasoning += f"Signal strength {intel.fused_direction:+.2f} with {intel.fused_confidence:.0%} confidence."
            if has_strong_pattern:
                reasoning += f" Pattern: {best_pattern['name']} ({best_pattern['timeframe']})."
        else:
            reasoning += "Conditions don't favor action."
            if has_strong_pattern:
                reasoning += f" Pattern {best_pattern['name']}({best_pattern['timeframe']}) present but not triggered."

        logger.info(f"[{intel.pair}] Decision: {action} (conf={confidence:.2f}, dir={intel.fused_direction:+.2f}, "
                    f"patterns={len(patterns)}, strong={'yes' if has_strong_pattern else 'no'})")

        # Bayesian confidence adjustment
        adjusted_confidence = self.bayesian.adjust_confidence(
            confidence, strategy.value, intel.pair
        )
        if abs(adjusted_confidence - confidence) > 0.01:
            logger.info(f"[{intel.pair}] Bayesian adjustment: {confidence:.3f} → {adjusted_confidence:.3f}")
        confidence = adjusted_confidence

        return {
            "action": action,
            "strategy": strategy.value,
            "confidence": confidence,
            "size_pct": size_pct,
            "stop_distance_pct": stop_distance,
            "reasoning": reasoning,
            "regime_assessment": intel.regime.value,
            "key_signals": [best_pattern["name"]] if has_strong_pattern else []
        }

    def _apply_pattern_override(
        self,
        intel: MarketIntel,
        decision: Dict,
        risk: Dict
    ) -> Dict:
        """Override HOLD decisions with pattern-driven entries.

        Called after both LLM and rule-based decisions so that strong
        candlestick patterns can trigger trades even when the LLM says HOLD.
        Selects the best *direction-aligned* pattern rather than just the
        absolute strongest (which may oppose the fused direction).
        """
        # Ensure confidence is always a float (LLM may return string)
        try:
            decision["confidence"] = float(decision.get("confidence", 0))
        except (TypeError, ValueError):
            decision["confidence"] = 0.0

        patterns = self._extract_patterns(intel)
        if not patterns:
            return decision

        if decision.get("action", "HOLD").upper() != "HOLD":
            # Already has an action — only boost confidence if pattern confirms
            best = self._strongest_pattern(patterns)
            if best and abs(best["signal"]) >= 0.6:
                action = decision["action"].upper()
                confirms = (action == "BUY" and best["signal"] > 0) or \
                           (action == "SELL" and best["signal"] < 0)
                if confirms:
                    decision["confidence"] = min(0.92, decision["confidence"] + 0.10)
                    decision.setdefault("key_signals", []).append(best["name"])
            return decision

        # Decision is HOLD — find direction-aligned pattern to override with
        direction = intel.fused_direction
        strong = [p for p in patterns if abs(p["signal"]) >= 0.6]

        # Separate into bullish and bearish strong patterns
        bullish_strong = sorted([p for p in strong if p["signal"] > 0],
                                key=lambda p: p["signal"], reverse=True)
        bearish_strong = sorted([p for p in strong if p["signal"] < 0],
                                key=lambda p: abs(p["signal"]), reverse=True)

        # Try the best direction-aligned pattern first
        # If direction is positive or neutral, prefer bullish patterns
        # If direction is negative, prefer bearish patterns
        candidates = []
        if direction >= -0.05:
            candidates.extend([(p, "BUY") for p in bullish_strong])
        if direction <= 0.05:
            candidates.extend([(p, "SELL") for p in bearish_strong])
        # Also try opposing-direction patterns on higher TFs
        if direction < -0.05:
            candidates.extend([(p, "BUY") for p in bullish_strong
                              if p.get("timeframe") in ("1h", "15m")])
        if direction > 0.05:
            candidates.extend([(p, "SELL") for p in bearish_strong
                              if p.get("timeframe") in ("1h", "15m")])

        # TF-specific directional thresholds
        tf_params = {
            "1h":  {"dir": -0.10, "size": 0.45},
            "15m": {"dir": -0.05, "size": 0.45},
            "5m":  {"dir":  0.0,  "size": 0.35},
            "3m":  {"dir":  0.0,  "size": 0.35},
        }
        default_params = {"dir": 0.03, "size": 0.25}

        for pat, action in candidates:
            tf = pat.get("timeframe", "5m")
            params = tf_params.get(tf, default_params)
            strength = abs(pat["signal"])
            conf = min(0.88, intel.fused_confidence * 0.6 + strength * 0.45)

            if action == "BUY" and direction > params["dir"]:
                logger.info(f"[{intel.pair}] Pattern override → BUY: {pat['name']} "
                           f"({tf}, signal={pat['signal']:+.2f}, conf={conf:.2f})")
                return {
                    **decision,
                    "action": "BUY",
                    "confidence": conf,
                    "size_pct": risk["max_position_pct"] * params["size"],
                    "stop_distance_pct": risk["stop_loss_pct"] * 1.2,
                    "reasoning": f"Pattern override: {pat['name']} ({tf}). {decision.get('reasoning', '')}",
                    "key_signals": [pat["name"]],
                }
            elif action == "SELL" and direction < -params["dir"]:
                logger.info(f"[{intel.pair}] Pattern override → SELL: {pat['name']} "
                           f"({tf}, signal={pat['signal']:+.2f}, conf={conf:.2f})")
                return {
                    **decision,
                    "action": "SELL",
                    "confidence": conf,
                    "size_pct": 0.5,
                    "reasoning": f"Pattern override: {pat['name']} ({tf}). {decision.get('reasoning', '')}",
                    "key_signals": [pat["name"]],
                }

        # Multi-pattern override: 2+ bullish/bearish patterns across timeframes
        bullish_all = [p for p in patterns if p["signal"] > 0.3]
        bearish_all = [p for p in patterns if p["signal"] < -0.3]

        if len(bullish_all) >= 2 and direction > -0.10:
            avg = sum(p["signal"] for p in bullish_all) / len(bullish_all)
            conf = min(0.85, intel.fused_confidence * 0.5 + avg * 0.4 + 0.1)
            names = [p["name"] for p in bullish_all]
            logger.info(f"[{intel.pair}] Multi-pattern override → BUY: {names}")
            return {
                **decision,
                "action": "BUY",
                "confidence": conf,
                "size_pct": risk["max_position_pct"] * 0.35,
                "stop_distance_pct": risk["stop_loss_pct"] * 1.2,
                "reasoning": f"Multi-pattern override: {', '.join(names)}. {decision.get('reasoning', '')}",
                "key_signals": names,
            }
        elif len(bearish_all) >= 2 and direction < 0.10:
            avg = sum(abs(p["signal"]) for p in bearish_all) / len(bearish_all)
            conf = min(0.85, intel.fused_confidence * 0.5 + avg * 0.4 + 0.1)
            names = [p["name"] for p in bearish_all]
            logger.info(f"[{intel.pair}] Multi-pattern override → SELL: {names}")
            return {
                **decision,
                "action": "SELL",
                "confidence": conf,
                "size_pct": 0.5,
                "reasoning": f"Multi-pattern override: {', '.join(names)}. {decision.get('reasoning', '')}",
                "key_signals": names,
            }

        return decision

    def _build_plan(
        self,
        intel: MarketIntel,
        decision: Dict,
        strategy_config: StrategyConfig,
        risk: Dict
    ) -> TradingPlan:
        """Build TradingPlan from decision"""
        action_str = decision.get("action", "HOLD").upper()
        action = TradeAction[action_str] if action_str in TradeAction.__members__ else TradeAction.HOLD

        # Calculate stop loss with strategy multiplier
        base_stop = risk["stop_loss_pct"]
        stop_loss = decision.get("stop_distance_pct", base_stop * strategy_config.stop_loss_multiplier)

        signal = TradeSignal(
            pair=intel.pair,
            action=action,
            confidence=float(decision.get("confidence", 0)),
            size_pct=float(decision.get("size_pct", 0)),
            reasoning=decision.get("reasoning", ""),
            order_type=OrderType.LIMIT if self.settings.features.enable_limit_orders else OrderType.MARKET,
            stop_loss_pct=stop_loss
        )

        return TradingPlan(
            signals=[signal],
            strategy_name=decision.get("strategy", strategy_config.name),
            regime=intel.regime.value,
            overall_confidence=signal.confidence,
            reasoning=decision.get("reasoning", ""),
            metadata={
                "strategy_config": {
                    "position_sizing": strategy_config.position_sizing,
                    "stop_multiplier": strategy_config.stop_loss_multiplier,
                    "take_profit_multiplier": strategy_config.take_profit_multiplier
                },
                "regime_assessment": decision.get("regime_assessment", ""),
                "key_signals": decision.get("key_signals", [])
            }
        )
