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

from core.interfaces import IStrategist, ILLM, IExchange
from core.models import (
    MarketIntel, Portfolio, TradingPlan, TradeSignal,
    TradeAction, OrderType, Regime
)
from core.config import Settings, get_settings
from core.risk import VolatilityCalculator, VolatilityConfig

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
        min_confidence=0.55,
        position_sizing="aggressive",
        stop_loss_multiplier=1.5,  # Wider stops for trends
        take_profit_multiplier=3.0
    ),
    Strategy.MEAN_REVERT: StrategyConfig(
        name="Mean Reversion",
        description="Fade extremes with tight stops, expecting return to mean",
        preferred_regimes=[Regime.RANGING],
        min_confidence=0.65,
        position_sizing="moderate",
        stop_loss_multiplier=0.75,  # Tighter stops
        take_profit_multiplier=1.5
    ),
    Strategy.BREAKOUT: StrategyConfig(
        name="Breakout",
        description="Trade volatility expansion with momentum confirmation",
        preferred_regimes=[Regime.VOLATILE],
        min_confidence=0.70,
        position_sizing="conservative",
        stop_loss_multiplier=2.0,  # Wide stops for volatility
        take_profit_multiplier=2.5
    ),
    Strategy.ACCUMULATE: StrategyConfig(
        name="Accumulate",
        description="DCA into position during uncertainty or corrections",
        preferred_regimes=[Regime.UNKNOWN, Regime.RANGING],
        min_confidence=0.50,
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

    def __init__(self, llm: ILLM = None, settings: Settings = None, exchange: IExchange = None):
        self.llm = llm
        self.settings = settings or get_settings()
        self.exchange = exchange
        self._last_strategy = None
        
        # Initialize volatility-based risk management
        self.volatility_enabled = self.settings.config.get("volatility_risk", {}).get("enabled", True)
        if self.volatility_enabled and exchange:
            volatility_config = self._load_volatility_config()
            self.volatility_calculator = VolatilityCalculator(volatility_config)
            logger.info("AdvancedStrategist initialized with volatility-aware take-profits")
        else:
            self.volatility_calculator = None
            logger.info("AdvancedStrategist initialized with fixed take-profits")
        
        logger.info("AdvancedStrategist initialized with strategy library")

    def _load_volatility_config(self) -> VolatilityConfig:
        """Load volatility configuration from settings"""
        vol_config = self.settings.config.get("volatility_risk", {})
        
        return VolatilityConfig(
            atr_period=vol_config.get("atr_period", 14),
            volatility_lookback=vol_config.get("volatility_lookback", 20),
            base_stop_multiplier=vol_config.get("base_stop_multiplier", 2.0),
            base_tp_multiplier=vol_config.get("base_tp_multiplier", 3.0),
            low_volatility_threshold=vol_config.get("low_volatility_threshold", 0.02),
            high_volatility_threshold=vol_config.get("high_volatility_threshold", 0.06),
            low_vol_stop_multiplier=vol_config.get("low_vol_stop_multiplier", 1.5),
            medium_vol_stop_multiplier=vol_config.get("medium_vol_stop_multiplier", 2.0),
            high_vol_stop_multiplier=vol_config.get("high_vol_stop_multiplier", 2.5),
            low_vol_tp_multiplier=vol_config.get("low_vol_tp_multiplier", 2.0),
            medium_vol_tp_multiplier=vol_config.get("medium_vol_tp_multiplier", 3.0),
            high_vol_tp_multiplier=vol_config.get("high_vol_tp_multiplier", 4.0),
            fallback_stop_loss_pct=vol_config.get("fallback_stop_loss_pct", 0.05),
            fallback_take_profit_pct=vol_config.get("fallback_take_profit_pct", 0.10),
            min_candles_required=vol_config.get("min_candles_required", 14)
        )

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

        # Select strategy based on regime
        strategy = self._select_strategy(intel)
        strategy_config = STRATEGY_LIBRARY[strategy]

        logger.info(f"[{intel.pair}] Regime: {intel.regime.value} → Strategy: {strategy.value}")

        # Try LLM-based decision first
        if self.llm:
            try:
                decision = await self._llm_decision(intel, portfolio, risk, strategy)
                return await self._build_plan(intel, decision, strategy_config, risk)
            except Exception as e:
                logger.warning(f"LLM decision failed, using rule-based: {e}")

        # Fall back to rule-based decision
        decision = self._rule_based_decision(intel, strategy, risk)
        return await self._build_plan(intel, decision, strategy_config, risk)

    def _select_strategy(self, intel: MarketIntel) -> Strategy:
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

        return decision

    def _rule_based_decision(
        self,
        intel: MarketIntel,
        strategy: Strategy,
        risk: Dict
    ) -> Dict:
        """Generate decision using rules (LLM fallback)"""
        config = STRATEGY_LIBRARY[strategy]

        # Determine action based on signal and strategy
        action = "HOLD"
        confidence = 0.0
        size_pct = 0.0
        stop_distance = risk["stop_loss_pct"] * config.stop_loss_multiplier

        # Strategy-specific logic
        if strategy == Strategy.TREND_FOLLOW:
            if intel.regime == Regime.TRENDING_UP and intel.fused_direction > 0.3:
                action = "BUY"
                confidence = min(0.9, intel.fused_confidence * 1.1)
                size_pct = risk["max_position_pct"] * 0.8
            elif intel.regime == Regime.TRENDING_DOWN and intel.fused_direction < -0.3:
                action = "SELL"
                confidence = min(0.9, intel.fused_confidence * 1.1)
                size_pct = 1.0  # Full exit in downtrend

        elif strategy == Strategy.MEAN_REVERT:
            # Look for extremes to fade
            if intel.fused_direction < -0.5 and intel.fused_confidence > 0.6:
                action = "BUY"  # Buy the dip
                confidence = intel.fused_confidence * 0.9
                size_pct = risk["max_position_pct"] * 0.5
            elif intel.fused_direction > 0.5 and intel.fused_confidence > 0.6:
                action = "SELL"  # Sell the rip
                confidence = intel.fused_confidence * 0.9
                size_pct = 1.0

        elif strategy == Strategy.BREAKOUT:
            # Trade strong moves in volatile conditions
            if abs(intel.fused_direction) > 0.6 and intel.fused_confidence > 0.65:
                action = "BUY" if intel.fused_direction > 0 else "SELL"
                confidence = intel.fused_confidence
                size_pct = risk["max_position_pct"] * 0.4

        elif strategy == Strategy.ACCUMULATE:
            # Gradual entry on moderate signals
            if intel.fused_direction > 0.2 and intel.fused_confidence > 0.5:
                action = "BUY"
                confidence = intel.fused_confidence * 0.8
                size_pct = risk["max_position_pct"] * 0.25  # Small bites

        elif strategy == Strategy.RISK_OFF:
            # Reduce exposure or stay out
            if intel.fused_direction < -0.2:
                action = "SELL"
                confidence = 0.7
                size_pct = 0.5  # Partial exit

        reasoning = f"{strategy.value}: {config.description}. "
        if action != "HOLD":
            reasoning += f"Signal strength {intel.fused_direction:+.2f} with {intel.fused_confidence:.0%} confidence."
        else:
            reasoning += "Conditions don't favor action."

        return {
            "action": action,
            "strategy": strategy.value,
            "confidence": confidence,
            "size_pct": size_pct,
            "stop_distance_pct": stop_distance,
            "reasoning": reasoning,
            "regime_assessment": intel.regime.value,
            "key_signals": []
        }

    async def _build_plan(
        self,
        intel: MarketIntel,
        decision: Dict,
        strategy_config: StrategyConfig,
        risk: Dict
    ) -> TradingPlan:
        """Build TradingPlan from decision with volatility-aware risk levels"""
        action_str = decision.get("action", "HOLD").upper()
        action = TradeAction[action_str] if action_str in TradeAction.__members__ else TradeAction.HOLD

        # Calculate stop loss and take profit with volatility awareness
        stop_loss_pct, take_profit_pct = await self._calculate_risk_levels(
            intel.pair, decision, strategy_config, risk
        )

        signal = TradeSignal(
            pair=intel.pair,
            action=action,
            confidence=float(decision.get("confidence", 0)),
            size_pct=float(decision.get("size_pct", 0)),
            reasoning=decision.get("reasoning", ""),
            order_type=OrderType.LIMIT if self.settings.features.enable_limit_orders else OrderType.MARKET,
            stop_loss_pct=stop_loss_pct
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
                "volatility_risk": {
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct,
                    "volatility_enabled": self.volatility_enabled
                },
                "regime_assessment": decision.get("regime_assessment", ""),
                "key_signals": decision.get("key_signals", [])
            }
        )

    async def _calculate_risk_levels(
        self,
        pair: str,
        decision: Dict,
        strategy_config: StrategyConfig,
        risk: Dict
    ) -> tuple[float, float]:
        """
        Calculate stop-loss and take-profit levels using volatility if available.
        
        Returns (stop_loss_pct, take_profit_pct)
        """
        # Start with base levels
        base_stop = risk["stop_loss_pct"]
        base_tp = base_stop * 2.0  # Default 2:1 reward/risk ratio
        
        # Try volatility-based calculation
        if self.volatility_calculator and self.exchange:
            try:
                # Get volatility profile
                profile = await self.volatility_calculator.get_volatility_profile(
                    pair, self.exchange
                )
                
                # Use volatility-suggested levels as base
                vol_stop = profile.suggested_stop_loss_pct
                vol_tp = profile.suggested_take_profit_pct
                
                # Apply strategy multipliers on top of volatility-based levels
                strategy_multipliers = {
                    'stop_loss_multiplier': strategy_config.stop_loss_multiplier,
                    'take_profit_multiplier': strategy_config.take_profit_multiplier
                }
                
                # Calculate final levels
                final_stop = vol_stop * strategy_config.stop_loss_multiplier
                final_tp = vol_tp * strategy_config.take_profit_multiplier
                
                # Apply reasonable bounds
                final_stop = max(0.01, min(0.15, final_stop))  # 1% to 15%
                final_tp = max(0.02, min(0.30, final_tp))      # 2% to 30%
                
                logger.debug(
                    f"[STRATEGIST] Volatility risk for {pair}: "
                    f"SL={final_stop:.2%} (vol: {vol_stop:.2%}, mult: {strategy_config.stop_loss_multiplier}x), "
                    f"TP={final_tp:.2%} (vol: {vol_tp:.2%}, mult: {strategy_config.take_profit_multiplier}x), "
                    f"Rank={profile.volatility_rank}"
                )
                
                return final_stop, final_tp
                
            except Exception as e:
                logger.warning(f"[STRATEGIST] Failed to calculate volatility risk for {pair}: {e}")
        
        # Fallback to strategy-multiplied fixed levels
        decision_stop = decision.get("stop_distance_pct", base_stop * strategy_config.stop_loss_multiplier)
        calculated_tp = base_tp * strategy_config.take_profit_multiplier
        
        logger.debug(
            f"[STRATEGIST] Fixed risk for {pair}: "
            f"SL={decision_stop:.2%}, TP={calculated_tp:.2%} (fallback)"
        )
        
        return decision_stop, calculated_tp
