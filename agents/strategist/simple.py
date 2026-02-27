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
STRATEGIST_SYSTEM_PROMPT = """Crypto trading strategist. Convert analyst signals to trades.

Rules:
- BUY when direction > +0.25 AND confidence > 0.50 AND no existing position in this pair.
- SELL when direction < -0.25 AND confidence > 0.45.
- In extreme fear conditions (high disagreement but positive direction), be willing to accumulate.
- Otherwise HOLD.
- Never recommend BUY for a pair we already hold. Prefer HOLD.
Match confidence to signal strength. Risk management handled separately.
Respond with JSON only."""


# Analysis prompt template
ANALYSIS_PROMPT = """Portfolio: {portfolio_summary}

{pair} Intel: {intel_summary}
Current positions: {positions_summary}

Risk: max_position={max_position_pct:.0%}, stop_loss={stop_loss_pct:.0%}, min_confidence={min_confidence:.0%}
Strategies: TREND_FOLLOW, MEAN_REVERT, RISK_OFF

IMPORTANT: Do NOT recommend BUY if we already hold a position in {pair}. BUY when direction > +0.25 and confidence > 0.50.

JSON response:
{{"action":"BUY|SELL|HOLD","confidence":0.0-1.0,"size_pct":0.0-{max_position_pct},"strategy":"...","reasoning":"brief","key_factors":["..."],"risks":["..."]}}"""


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

            # Build positions summary for context
            base_asset = intel.pair.split("/")[0]
            if portfolio.positions:
                held = [f"{s}: {p.amount:.6f}" for s, p in portfolio.positions.items() if p.amount > 0]
                positions_summary = ", ".join(held) if held else "None"
            else:
                positions_summary = "None"

            # Build prompt
            prompt = ANALYSIS_PROMPT.format(
                portfolio_summary=portfolio.to_summary(),
                pair=intel.pair,
                intel_summary=intel.to_summary(),
                positions_summary=positions_summary,
                max_position_pct=risk["max_position_pct"],
                stop_loss_pct=risk["stop_loss_pct"],
                min_confidence=risk["min_confidence"]
            )

            # Get Claude's decision
            decision = await self.llm.analyze_market(
                prompt=prompt,
                system_prompt=STRATEGIST_SYSTEM_PROMPT,
                max_tokens=300
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
        
        # Rule-based decision with tighter thresholds to reduce over-trading
        action = TradeAction.HOLD
        size_pct = 0.0
        reasoning = "Rule-based analysis: "

        # Check if we already hold this pair
        base_asset = intel.pair.split("/")[0]
        already_holding = (
            portfolio.positions
            and base_asset in portfolio.positions
            and portfolio.positions[base_asset].amount > 0
        )

        # FEAR_BUY: Contrarian accumulation when analysts agree on direction
        # but disagree on magnitude (e.g. extreme fear)
        is_fear_buy = (
            intel.fused_direction > 0.15
            and intel.fused_confidence > 0.40
            and intel.disagreement > 0.3
            and not already_holding
        )

        if is_fear_buy:
            action = TradeAction.BUY
            confidence = intel.fused_confidence * 0.85  # Discount for uncertainty
            size_pct = risk["max_position_pct"] * 0.6 * min(1.0, abs(intel.fused_direction))
            reasoning += (f"FEAR_BUY: Contrarian accumulation "
                         f"(direction: {intel.fused_direction:+.2f}, "
                         f"disagreement: {intel.disagreement:.2f})")
        elif intel.fused_direction > 0.25 and intel.fused_confidence > 0.50 and not already_holding:
            action = TradeAction.BUY
            confidence = intel.fused_confidence
            size_pct = risk["max_position_pct"] * min(1.0, abs(intel.fused_direction))
            reasoning += f"Bullish signal ({intel.fused_direction:+.2f}) with confidence {intel.fused_confidence:.0%}"
        elif intel.fused_direction < -0.25 and intel.fused_confidence > 0.45:
            action = TradeAction.SELL
            confidence = intel.fused_confidence
            size_pct = 1.0  # Sell full position
            reasoning += f"Bearish signal ({intel.fused_direction:+.2f}) with confidence {intel.fused_confidence:.0%}"
        elif already_holding:
            confidence = intel.fused_confidence * 0.5
            reasoning += f"Already holding {base_asset}, waiting for exit signal"
        else:
            confidence = intel.fused_confidence * 0.5
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
