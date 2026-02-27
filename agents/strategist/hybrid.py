"""
Hybrid Strategist

Intelligently routes decisions between rule-based and Claude-based strategies.
Uses rules for clear signals (free), Claude for uncertain situations (paid).

Cost savings: 30-70% depending on market conditions.
- Stable markets with clear signals = higher savings
- Volatile markets with mixed signals = lower savings
"""

from typing import Dict, Optional, List
import logging
from dataclasses import dataclass

from core.interfaces import IStrategist, ILLM
from core.models import MarketIntel, Portfolio, TradingPlan, TradeSignal, TradeAction
from core.config import Settings, get_settings, HybridThresholds
from .simple import RuleBasedStrategist

logger = logging.getLogger(__name__)


@dataclass
class HybridStats:
    """Statistics for hybrid strategist usage."""
    total_decisions: int = 0
    rule_based_decisions: int = 0
    claude_decisions: int = 0
    cost_savings_estimate: float = 0.0  # Estimated $ saved

    @property
    def rule_based_pct(self) -> float:
        """Percentage of decisions made by rules."""
        if self.total_decisions == 0:
            return 0.0
        return self.rule_based_decisions / self.total_decisions * 100

    def to_dict(self) -> dict:
        return {
            "total_decisions": self.total_decisions,
            "rule_based": self.rule_based_decisions,
            "claude": self.claude_decisions,
            "rule_based_pct": f"{self.rule_based_pct:.1f}%",
            "estimated_savings": f"${self.cost_savings_estimate:.2f}"
        }


class HybridStrategist(IStrategist):
    """
    Cost-optimized strategist that uses rules for clear signals
    and Claude only when the signal is uncertain.

    Clear Signal Criteria (all must be true for rules):
    - |direction| >= direction_threshold (default 0.6)
    - confidence >= confidence_threshold (default 0.75)
    - disagreement <= disagreement_threshold (default 0.2)

    If any criterion fails, the signal is considered uncertain
    and Claude is consulted for a more nuanced decision.
    """

    def __init__(
        self,
        llm_strategist: IStrategist,
        rule_strategist: Optional[RuleBasedStrategist] = None,
        thresholds: Optional[HybridThresholds] = None,
        settings: Optional[Settings] = None,
        cost_per_claude_call: float = 0.002  # ~$0.002 per Sonnet call
    ):
        """
        Initialize hybrid strategist.

        Args:
            llm_strategist: Claude-based strategist for uncertain signals
            rule_strategist: Rule-based strategist for clear signals
            thresholds: Thresholds for clear signal determination
            settings: Settings object
            cost_per_claude_call: Estimated cost per Claude API call
        """
        self.llm_strategist = llm_strategist
        self.rule_strategist = rule_strategist or RuleBasedStrategist()
        self.settings = settings or get_settings()
        self.thresholds = thresholds or self.settings.cost_optimization.hybrid
        self.cost_per_call = cost_per_claude_call

        # Statistics
        self.stats = HybridStats()

    def is_clear_signal(self, intel: MarketIntel) -> bool:
        """
        Determine if the signal is clear enough for rule-based decision.

        Returns True if:
        - |direction| >= direction_threshold
        - confidence >= confidence_threshold
        - disagreement <= disagreement_threshold (if available)

        A clear signal means we can confidently use rules without
        needing Claude's more nuanced analysis.
        """
        direction_clear = abs(intel.fused_direction) >= self.thresholds.direction_clear
        confidence_clear = intel.fused_confidence >= self.thresholds.confidence_clear

        # Check disagreement if available
        disagreement_ok = True
        if hasattr(intel, 'disagreement') and intel.disagreement is not None:
            disagreement_ok = intel.disagreement <= self.thresholds.disagreement_max

        is_clear = direction_clear and confidence_clear and disagreement_ok
        logger.debug(f"[HYBRID] {intel.pair}: |dir|={abs(intel.fused_direction):.3f} vs {self.thresholds.direction_clear}, "
                    f"conf={intel.fused_confidence:.3f} vs {self.thresholds.confidence_clear}, "
                    f"clear={is_clear}")
        return is_clear

    def get_signal_clarity_reason(self, intel: MarketIntel) -> str:
        """Get human-readable reason for signal clarity assessment."""
        reasons = []

        if abs(intel.fused_direction) < self.thresholds.direction_clear:
            reasons.append(f"direction {intel.fused_direction:+.2f} below threshold {self.thresholds.direction_clear}")

        if intel.fused_confidence < self.thresholds.confidence_clear:
            reasons.append(f"confidence {intel.fused_confidence:.0%} below threshold {self.thresholds.confidence_clear:.0%}")

        if hasattr(intel, 'disagreement') and intel.disagreement is not None:
            if intel.disagreement > self.thresholds.disagreement_max:
                reasons.append(f"disagreement {intel.disagreement:.0%} above threshold {self.thresholds.disagreement_max:.0%}")

        if not reasons:
            return "Signal is clear (direction, confidence, agreement all pass thresholds)"

        return "Uncertain: " + "; ".join(reasons)

    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Create trading plan using either rules or Claude based on signal clarity.

        Args:
            intel: Market intelligence for a trading pair
            portfolio: Current portfolio state
            risk_params: Risk parameters

        Returns:
            TradingPlan with decision and reasoning
        """
        self.stats.total_decisions += 1

        # Assess signal clarity
        is_clear = self.is_clear_signal(intel)
        clarity_reason = self.get_signal_clarity_reason(intel)

        if is_clear:
            # Use rule-based (free)
            logger.info(f"[HYBRID] {intel.pair}: Using RULES - {clarity_reason}")
            self.stats.rule_based_decisions += 1
            self.stats.cost_savings_estimate += self.cost_per_call

            plan = await self.rule_strategist.create_plan(intel, portfolio, risk_params)

            # Tag the plan as rule-based
            plan.reasoning = f"[RULE-BASED] {plan.reasoning}"

            return plan
        else:
            # Use Claude (paid)
            logger.info(f"[HYBRID] {intel.pair}: Using CLAUDE - {clarity_reason}")
            self.stats.claude_decisions += 1

            plan = await self.llm_strategist.create_plan(intel, portfolio, risk_params)

            # Tag the plan as Claude-based
            plan.reasoning = f"[CLAUDE] {plan.reasoning}"

            return plan

    async def create_batch_plan(
        self,
        intel_list: List[MarketIntel],
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Process multiple pairs with hybrid routing.

        Splits pairs into clear (rules) and uncertain (Claude batch).
        Only sends uncertain pairs to Claude.
        """
        if not intel_list:
            return TradingPlan(
                signals=[],
                strategy_name="hybrid_batch",
                overall_confidence=0.0,
                reasoning="No pairs to analyze"
            )

        # Separate clear and uncertain signals
        clear_intel = []
        uncertain_intel = []

        for intel in intel_list:
            if self.is_clear_signal(intel):
                clear_intel.append(intel)
                self.stats.rule_based_decisions += 1
                self.stats.cost_savings_estimate += self.cost_per_call
            else:
                uncertain_intel.append(intel)
                self.stats.claude_decisions += 1

        self.stats.total_decisions += len(intel_list)

        all_signals = []

        # Process clear signals with rules (free)
        if clear_intel:
            logger.info(f"[HYBRID_BATCH] Processing {len(clear_intel)} pairs with RULES")
            for intel in clear_intel:
                plan = await self.rule_strategist.create_plan(intel, portfolio, risk_params)
                for signal in plan.signals:
                    signal.reasoning = f"[RULE-BASED] {signal.reasoning}"
                all_signals.extend(plan.signals)

        # Process uncertain signals with Claude batch (if batch strategist available)
        if uncertain_intel:
            logger.info(f"[HYBRID_BATCH] Processing {len(uncertain_intel)} pairs with CLAUDE")

            # Check if LLM strategist supports batch
            if hasattr(self.llm_strategist, 'create_batch_plan'):
                plan = await self.llm_strategist.create_batch_plan(
                    uncertain_intel, portfolio, risk_params
                )
            else:
                # Fall back to individual calls
                signals = []
                for intel in uncertain_intel:
                    p = await self.llm_strategist.create_plan(intel, portfolio, risk_params)
                    signals.extend(p.signals)
                plan = TradingPlan(signals=signals, strategy_name="hybrid")

            for signal in plan.signals:
                signal.reasoning = f"[CLAUDE] {signal.reasoning}"
            all_signals.extend(plan.signals)

        # Calculate overall confidence
        active_signals = [s for s in all_signals if s.action != TradeAction.HOLD]
        overall_confidence = (
            sum(s.confidence for s in active_signals) / len(active_signals)
            if active_signals else 0.0
        )

        return TradingPlan(
            signals=all_signals,
            strategy_name="hybrid_batch",
            regime="mixed",
            overall_confidence=overall_confidence,
            reasoning=f"Hybrid: {len(clear_intel)} rules, {len(uncertain_intel)} Claude"
        )

    def get_stats(self) -> dict:
        """Get hybrid strategist statistics."""
        return self.stats.to_dict()

    def reset_stats(self):
        """Reset statistics."""
        self.stats = HybridStats()


class AdaptiveHybridStrategist(HybridStrategist):
    """
    Extended hybrid strategist that adapts thresholds based on performance.

    Tracks win rates for rule-based vs Claude decisions and adjusts
    thresholds to optimize the cost/accuracy tradeoff.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rule_wins = 0
        self._rule_losses = 0
        self._claude_wins = 0
        self._claude_losses = 0

    def record_outcome(self, was_rule_based: bool, was_profitable: bool):
        """Record the outcome of a trade for adaptation."""
        if was_rule_based:
            if was_profitable:
                self._rule_wins += 1
            else:
                self._rule_losses += 1
        else:
            if was_profitable:
                self._claude_wins += 1
            else:
                self._claude_losses += 1

        # Adapt thresholds based on relative performance
        self._adapt_thresholds()

    def _adapt_thresholds(self):
        """Adjust thresholds based on performance metrics."""
        rule_total = self._rule_wins + self._rule_losses
        claude_total = self._claude_wins + self._claude_losses

        if rule_total < 10 or claude_total < 10:
            return  # Need more data

        rule_win_rate = self._rule_wins / rule_total
        claude_win_rate = self._claude_wins / claude_total

        # If rules are performing worse than Claude, tighten thresholds
        # (more signals go to Claude)
        if rule_win_rate < claude_win_rate - 0.1:
            self.thresholds.direction_clear = min(0.8, self.thresholds.direction_clear + 0.05)
            self.thresholds.confidence_clear = min(0.9, self.thresholds.confidence_clear + 0.05)
            logger.info(f"[ADAPTIVE] Tightened thresholds: dir={self.thresholds.direction_clear}, conf={self.thresholds.confidence_clear}")

        # If rules are performing as well as Claude, relax thresholds
        # (more signals use rules, saving costs)
        elif rule_win_rate >= claude_win_rate:
            self.thresholds.direction_clear = max(0.4, self.thresholds.direction_clear - 0.05)
            self.thresholds.confidence_clear = max(0.6, self.thresholds.confidence_clear - 0.05)
            logger.info(f"[ADAPTIVE] Relaxed thresholds: dir={self.thresholds.direction_clear}, conf={self.thresholds.confidence_clear}")

    def get_stats(self) -> dict:
        """Get extended statistics including adaptation metrics."""
        stats = super().get_stats()
        rule_total = self._rule_wins + self._rule_losses
        claude_total = self._claude_wins + self._claude_losses

        stats["rule_win_rate"] = f"{self._rule_wins / rule_total * 100:.1f}%" if rule_total > 0 else "N/A"
        stats["claude_win_rate"] = f"{self._claude_wins / claude_total * 100:.1f}%" if claude_total > 0 else "N/A"
        stats["current_thresholds"] = {
            "direction": self.thresholds.direction_clear,
            "confidence": self.thresholds.confidence_clear
        }

        return stats
