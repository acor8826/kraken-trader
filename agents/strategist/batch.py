"""
Batch Strategist Agent

Analyzes multiple trading pairs in a single Claude API call.
Reduces API costs by ~66% (3 calls -> 1 call for 3 pairs).
"""

from typing import Dict, List, Optional
import logging
import json

from core.interfaces import IStrategist, ILLM
from core.models import (
    MarketIntel, Portfolio, TradingPlan, TradeSignal,
    TradeAction, TradeStatus, OrderType
)
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


# System prompt for batch analysis
BATCH_SYSTEM_PROMPT = """Crypto trading strategist. Analyze MULTIPLE pairs, return JSON array of decisions.

Rules per pair: direction>+0.3 & confidence>0.55→BUY, direction<-0.3 & confidence>0.55→SELL, else HOLD.
Match confidence to signal strength. Consider portfolio-wide exposure for sizing. Respond with JSON only."""


# Batch analysis prompt template
BATCH_ANALYSIS_PROMPT = """Portfolio: {portfolio_summary}

All Pairs Intel:
{all_intel_summaries}

Risk: max_position={max_position_pct:.0%}, max_exposure={max_exposure_pct:.0%}, stop_loss={stop_loss_pct:.0%}, min_confidence={min_confidence:.0%}
Strategies: TREND_FOLLOW, MEAN_REVERT, ACCUMULATE, RISK_OFF

Return JSON array, one per pair:
[{{"pair":"...","action":"BUY|SELL|HOLD","confidence":0.0-1.0,"size_pct":0.0-{max_position_pct},"strategy":"...","reasoning":"brief","key_factors":["..."]}}]
Return decisions for ALL pairs."""


class BatchStrategist(IStrategist):
    """
    Cost-optimized strategist that analyzes multiple pairs in a single API call.

    Reduces Claude API costs by batching all pair analyses into one request.
    Implements IStrategist but with a batch-oriented create_batch_plan method.
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
        Standard single-pair interface for compatibility.
        Delegates to create_batch_plan with a single intel.
        """
        plan = await self.create_batch_plan([intel], portfolio, risk_params)
        return plan

    async def create_batch_plan(
        self,
        intel_list: List[MarketIntel],
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Create trading plan for multiple pairs in a single Claude call.

        Args:
            intel_list: List of MarketIntel objects for all pairs to analyze
            portfolio: Current portfolio state
            risk_params: Risk parameters (optional, uses settings if not provided)

        Returns:
            TradingPlan with signals for all pairs
        """
        if not intel_list:
            return TradingPlan(
                signals=[],
                strategy_name="batch",
                overall_confidence=0.0,
                reasoning="No pairs to analyze"
            )

        risk = risk_params or {
            "max_position_pct": self.settings.risk.max_position_pct,
            "max_exposure_pct": self.settings.risk.max_total_exposure_pct,
            "stop_loss_pct": self.settings.risk.stop_loss_pct,
            "min_confidence": self.settings.risk.min_confidence
        }

        try:
            # Build combined intel summary for all pairs
            all_intel_summaries = self._build_batch_intel_summary(intel_list)

            # Log batch analysis start
            pairs_str = ", ".join([intel.pair for intel in intel_list])
            logger.info(f"[BATCH] Analyzing {len(intel_list)} pairs in single call: {pairs_str}")

            # Build batch prompt
            prompt = BATCH_ANALYSIS_PROMPT.format(
                portfolio_summary=portfolio.to_summary(),
                all_intel_summaries=all_intel_summaries,
                max_position_pct=risk["max_position_pct"],
                max_exposure_pct=risk.get("max_exposure_pct", 0.80),
                stop_loss_pct=risk["stop_loss_pct"],
                min_confidence=risk["min_confidence"]
            )

            # Single Claude API call for all pairs
            response = await self.llm.analyze_market(
                prompt=prompt,
                system_prompt=BATCH_SYSTEM_PROMPT,
                max_tokens=200 * len(intel_list) + 100
            )

            # Log raw response
            logger.debug(f"[BATCH_RAW] Response: {response}")

            # Parse batch response
            signals = self._parse_batch_response(response, intel_list, risk)

            # Calculate overall confidence
            confidences = [s.confidence for s in signals if s.action != TradeAction.HOLD]
            overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            # Log results
            for signal in signals:
                logger.info(f"[BATCH_RESULT] {signal.pair}: {signal.action.value} "
                           f"confidence={signal.confidence:.0%}")

            return TradingPlan(
                signals=signals,
                strategy_name="batch_analysis",
                regime="mixed",  # Multiple regimes possible
                overall_confidence=overall_confidence,
                reasoning=f"Batch analysis of {len(intel_list)} pairs"
            )

        except Exception as e:
            logger.error(f"Batch strategist error: {e}")

            # Return HOLD for all pairs on error
            signals = [
                TradeSignal(
                    pair=intel.pair,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    size_pct=0.0,
                    reasoning=f"Batch error: {str(e)}"
                )
                for intel in intel_list
            ]

            return TradingPlan(
                signals=signals,
                strategy_name="batch_error",
                overall_confidence=0.0,
                reasoning=f"Batch analysis error: {str(e)}"
            )

    def _build_batch_intel_summary(self, intel_list: List[MarketIntel]) -> str:
        """Build combined summary for all pairs."""
        summaries = []
        for i, intel in enumerate(intel_list, 1):
            summaries.append(f"### Pair {i}: {intel.pair}\n{intel.to_summary()}")
        return "\n\n".join(summaries)

    def _parse_batch_response(
        self,
        response: any,
        intel_list: List[MarketIntel],
        risk: Dict
    ) -> List[TradeSignal]:
        """
        Parse Claude's batch response into TradeSignals.

        Handles both list responses and dict responses.
        Falls back to HOLD if parsing fails for a pair.
        """
        signals = []

        # Handle different response formats
        decisions = []
        if isinstance(response, list):
            decisions = response
        elif isinstance(response, dict):
            # Single decision wrapped in dict, or dict with decisions key
            if "decisions" in response:
                decisions = response["decisions"]
            elif "pair" in response:
                decisions = [response]
            else:
                # Try to extract from numbered keys or other formats
                logger.warning(f"Unexpected dict response format: {response}")
                decisions = list(response.values()) if response else []
        elif isinstance(response, str):
            # Try to parse as JSON, handling code fences and extra text
            try:
                # Strip markdown code fences if present
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    # Remove opening fence (```json or ```)
                    lines = cleaned.split("\n")
                    start_idx = 1 if lines[0].startswith("```") else 0
                    # Find closing fence
                    end_idx = len(lines)
                    for i in range(len(lines) - 1, start_idx, -1):
                        if lines[i].strip() == "```":
                            end_idx = i
                            break
                    cleaned = "\n".join(lines[start_idx:end_idx])

                # Find JSON array in the response
                if "[" in cleaned:
                    # Extract from first [ to matching ]
                    start = cleaned.find("[")
                    bracket_count = 0
                    end = start
                    for i, char in enumerate(cleaned[start:], start):
                        if char == "[":
                            bracket_count += 1
                        elif char == "]":
                            bracket_count -= 1
                            if bracket_count == 0:
                                end = i + 1
                                break
                    cleaned = cleaned[start:end]

                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    decisions = parsed
                elif isinstance(parsed, dict):
                    decisions = parsed.get("decisions", [parsed])
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse response as JSON: {e}")

        # Create a map of pair -> decision for easier lookup
        decision_map = {}
        for d in decisions:
            if isinstance(d, dict) and "pair" in d:
                decision_map[d["pair"]] = d

        # Create signals for each intel, matching with decisions
        for intel in intel_list:
            decision = decision_map.get(intel.pair, {})

            try:
                action_str = decision.get("action", "HOLD").upper()
                action = TradeAction[action_str] if action_str in TradeAction.__members__ else TradeAction.HOLD

                signal = TradeSignal(
                    pair=intel.pair,
                    action=action,
                    confidence=float(decision.get("confidence", 0)),
                    size_pct=float(decision.get("size_pct", 0)),
                    reasoning=decision.get("reasoning", "Batch analysis"),
                    order_type=OrderType.MARKET,
                    stop_loss_pct=risk["stop_loss_pct"]
                )
            except Exception as e:
                logger.warning(f"Failed to parse decision for {intel.pair}: {e}")
                signal = TradeSignal(
                    pair=intel.pair,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    size_pct=0.0,
                    reasoning=f"Parse error: {str(e)}"
                )

            signals.append(signal)

        return signals


class RuleBasedBatchStrategist(IStrategist):
    """
    Rule-based batch strategist for when no LLM is available.
    Processes multiple pairs using simple rules (no API cost).
    """

    def __init__(self, settings: Settings = None):
        self.settings = settings or get_settings()

    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """Single-pair interface."""
        return await self.create_batch_plan([intel], portfolio, risk_params)

    async def create_batch_plan(
        self,
        intel_list: List[MarketIntel],
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """Process multiple pairs with rules only (no API cost)."""
        risk = risk_params or {
            "max_position_pct": self.settings.risk.max_position_pct,
            "stop_loss_pct": self.settings.risk.stop_loss_pct,
            "min_confidence": self.settings.risk.min_confidence
        }

        signals = []
        for intel in intel_list:
            action = TradeAction.HOLD
            size_pct = 0.0
            reasoning = "Rule-based batch: "

            if intel.fused_direction > 0.3 and intel.fused_confidence > 0.5:
                action = TradeAction.BUY
                confidence = intel.fused_confidence
                size_pct = risk["max_position_pct"] * min(1.0, abs(intel.fused_direction) + 0.2)
                reasoning += f"Bullish ({intel.fused_direction:+.2f})"
            elif intel.fused_direction < -0.3 and intel.fused_confidence > 0.5:
                action = TradeAction.SELL
                confidence = intel.fused_confidence
                size_pct = 1.0
                reasoning += f"Bearish ({intel.fused_direction:+.2f})"
            else:
                confidence = intel.fused_confidence * 0.5
                reasoning += f"No signal ({intel.fused_direction:+.2f})"

            signals.append(TradeSignal(
                pair=intel.pair,
                action=action,
                confidence=confidence,
                size_pct=size_pct,
                reasoning=reasoning,
                order_type=OrderType.MARKET,
                stop_loss_pct=risk["stop_loss_pct"]
            ))

        confidences = [s.confidence for s in signals if s.action != TradeAction.HOLD]
        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return TradingPlan(
            signals=signals,
            strategy_name="rule_based_batch",
            regime="mixed",
            overall_confidence=overall_confidence,
            reasoning=f"Rule-based analysis of {len(intel_list)} pairs"
        )
