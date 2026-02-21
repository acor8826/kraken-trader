"""
Strategist Agent

Converts market intelligence into trading decisions using Claude.
This is the core decision-making agent.
"""

from typing import Dict, Optional
import logging

from core.interfaces import IStrategist, ILLM
from core.models import (
    MarketIntel, Portfolio, TradingPlan, TradeSignal, 
    TradeAction, TradeStatus, OrderType
)
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


# System prompt for Claude
STRATEGIST_SYSTEM_PROMPT = """You are a professional cryptocurrency trader executing algorithmic strategies. Your role is to convert analyst signals into decisive trading actions.

Decision Rules:
- Analyst direction > +0.15 with confidence > 0.50: RECOMMEND BUY
- Analyst direction < -0.15 with confidence > 0.50: RECOMMEND SELL
- Otherwise: HOLD

Response Approach:
- Match confidence to analyst strength (don't add extra caution)
- Output BUY/SELL/HOLD and confidence 0-100%
- Keep size recommendations within risk parameters
- Provide brief reasoning

Risk management is delegated to the Sentinel component (position limits, stop-losses). Your job is to act decisively on clear signals and let the risk layer validate them."""


# Analysis prompt template
ANALYSIS_PROMPT = """Analyze the following market intelligence and portfolio state to create a trading plan.

## Portfolio State
{portfolio_summary}

## Market Intelligence for {pair}
{intel_summary}

## Risk Parameters
- Maximum position size: {max_position_pct:.0%} of available capital
- Stop-loss threshold: {stop_loss_pct:.0%}
- Minimum confidence for action: {min_confidence:.0%}

## Available Strategies
- TREND_FOLLOW: Ride momentum in trending markets
- MEAN_REVERT: Fade extremes in ranging markets
- ACCUMULATE: Build position gradually in corrections
- RISK_OFF: Reduce exposure when uncertain

## Your Task
1. Assess the current market regime
2. Determine if conditions favor action or patience
3. If actionable, recommend specific trade with sizing
4. Explain your reasoning clearly

Respond with JSON only:
{{
    "action": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0 to 1.0,
    "size_pct": 0.0 to {max_position_pct},
    "strategy": "TREND_FOLLOW" | "MEAN_REVERT" | "ACCUMULATE" | "RISK_OFF",
    "reasoning": "Brief explanation",
    "key_factors": ["factor1", "factor2"],
    "risks": ["risk1", "risk2"]
}}"""


class SimpleStrategist(IStrategist):
    """
    Stage 1 Strategist - Single Claude call per asset.
    
    Simple but effective: analyze intel → Claude decision → trade signal
    """
    
    def __init__(self, llm: ILLM, settings: Settings = None):
        self.llm = llm
        self.settings = settings or get_settings()
    
    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Create trading plan from market intelligence.
        
        Args:
            intel: Fused market intelligence for a single pair
            portfolio: Current portfolio state
            risk_params: Risk parameters (optional, uses settings if not provided)
        """
        risk = risk_params or {
            "max_position_pct": self.settings.risk.max_position_pct,
            "stop_loss_pct": self.settings.risk.stop_loss_pct,
            "min_confidence": self.settings.risk.min_confidence
        }
        
        try:
            # Log analyst signals before strategist processing
            logger.debug(f"[ANALYST] {intel.pair}: direction={intel.fused_direction:+.2f}, "
                        f"confidence={intel.fused_confidence:.0%}")

            # Build prompt
            prompt = ANALYSIS_PROMPT.format(
                portfolio_summary=portfolio.to_summary(),
                pair=intel.pair,
                intel_summary=intel.to_summary(),
                max_position_pct=risk["max_position_pct"],
                stop_loss_pct=risk["stop_loss_pct"],
                min_confidence=risk["min_confidence"]
            )

            # Get Claude's decision
            decision = await self.llm.analyze_market(
                prompt=prompt,
                system_prompt=STRATEGIST_SYSTEM_PROMPT
            )

            # Log raw Claude response
            logger.debug(f"[CLAUDE_RAW] {intel.pair}: {decision}")

            # Log analyst→strategist conversion
            analyst_conf = intel.fused_confidence
            strategist_conf = float(decision.get("confidence", 0))
            strategist_action = decision.get('action', 'HOLD')
            logger.info(f"[CONVERSION] {intel.pair}: analyst={analyst_conf:.0%} → "
                       f"strategist {strategist_action} confidence={strategist_conf:.0%}")

            logger.info(f"Strategist decision for {intel.pair}: {decision.get('action')} "
                       f"(confidence: {decision.get('confidence', 0):.0%})")
            
            # Convert to TradeSignal
            action_str = decision.get("action", "HOLD").upper()
            action = TradeAction[action_str] if action_str in TradeAction.__members__ else TradeAction.HOLD
            
            signal = TradeSignal(
                pair=intel.pair,
                action=action,
                confidence=float(decision.get("confidence", 0)),
                size_pct=float(decision.get("size_pct", 0)),
                reasoning=decision.get("reasoning", ""),
                order_type=OrderType.MARKET,
                stop_loss_pct=risk["stop_loss_pct"]
            )
            
            # Create plan
            plan = TradingPlan(
                signals=[signal],
                strategy_name=decision.get("strategy", "unknown"),
                regime=intel.regime.value,
                overall_confidence=signal.confidence,
                reasoning=decision.get("reasoning", "")
            )
            
            return plan
            
        except Exception as e:
            logger.error(f"Strategist error for {intel.pair}: {e}")
            
            # Return HOLD on error
            return TradingPlan(
                signals=[TradeSignal(
                    pair=intel.pair,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    size_pct=0.0,
                    reasoning=f"Error: {str(e)}"
                )],
                strategy_name="error",
                overall_confidence=0.0,
                reasoning=f"Strategy error: {str(e)}"
            )


class RuleBasedStrategist(IStrategist):
    """
    Rule-based strategist for testing without LLM.
    Uses simple technical rules to generate signals.
    """
    
    def __init__(self, settings: Settings = None):
        self.settings = settings or get_settings()
    
    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """Generate plan from rules only (no LLM)"""
        risk = risk_params or {
            "max_position_pct": self.settings.risk.max_position_pct,
            "stop_loss_pct": self.settings.risk.stop_loss_pct,
            "min_confidence": self.settings.risk.min_confidence
        }
        
        # Simple rule-based decision
        action = TradeAction.HOLD
        confidence = abs(intel.fused_direction) * intel.fused_confidence
        size_pct = 0.0
        reasoning = "Rule-based analysis: "
        
        if intel.fused_direction > 0.15 and intel.fused_confidence > 0.5:
            action = TradeAction.BUY
            size_pct = risk["max_position_pct"] * confidence
            reasoning += f"Bullish signal ({intel.fused_direction:+.2f}) with good confidence"
        elif intel.fused_direction < -0.15 and intel.fused_confidence > 0.5:
            action = TradeAction.SELL
            size_pct = 1.0  # Sell full position
            reasoning += f"Bearish signal ({intel.fused_direction:+.2f}) with good confidence"
        else:
            reasoning += f"No clear signal (direction: {intel.fused_direction:+.2f})"
        
        signal = TradeSignal(
            pair=intel.pair,
            action=action,
            confidence=confidence,
            size_pct=size_pct,
            reasoning=reasoning,
            order_type=OrderType.MARKET,
            stop_loss_pct=risk["stop_loss_pct"]
        )
        
        return TradingPlan(
            signals=[signal],
            strategy_name="rule_based",
            regime=intel.regime.value,
            overall_confidence=confidence,
            reasoning=reasoning
        )
