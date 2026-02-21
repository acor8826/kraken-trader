"""
Validation Agent

Secondary validation layer that reviews trades before execution.
Uses past trade patterns and insights to catch potential mistakes.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.interfaces import ILLM
from core.models import Portfolio, MarketIntel, TradeSignal
from memory.trade_journal import ITradeJournal, TradeJournalEntry

logger = logging.getLogger(__name__)


VALIDATION_SYSTEM_PROMPT = """You are a risk validator for a crypto trading system. Your job is to catch mistakes before they happen by:

1. Comparing this trade to historical patterns of losses
2. Checking for overconfidence signals
3. Validating position sizing against current exposure
4. Identifying correlation risks with existing positions

You can:
- APPROVE: Trade looks good, proceed as planned
- MODIFY: Reduce position size (specify multiplier like 0.5 for half)
- REJECT: Do not execute this trade

Be decisive but not overly cautious. The goal is to catch CLEAR mistakes, not prevent all trading.
A rejected trade means missed opportunity, so only reject when you see strong red flags.

Output ONLY valid JSON."""


VALIDATION_PROMPT_TEMPLATE = """Validate this proposed trade:

## Proposed Trade
- Pair: {pair}
- Action: {action}
- Confidence: {confidence:.0%}
- Position Size: {size_pct:.0%} of available (${size_aud:.2f})
- Reasoning: {reasoning}

## Market Intelligence
- Fused Direction: {direction:+.2f}
- Analyst Disagreement: {disagreement:.0%}
- Regime: {regime}
- Analyst Signals:
{analyst_signals}

## Current Portfolio
- Total Value: ${total_value:.2f}
- Available Cash: ${available:.2f}
- Current Exposure: {exposure:.0%}
- Existing Positions: {positions}

## Historical Insights
{insights}

## Similar Past Trades (same pair, similar conditions)
{similar_trades}

## Risk Assessment
- This trade's confidence ({confidence:.0%}) vs historical win rate at this level
- Analyst disagreement level ({disagreement:.0%})
- Position correlation with existing holdings

Provide validation as JSON:
{{
    "decision": "APPROVE" | "MODIFY" | "REJECT",
    "position_multiplier": 1.0,
    "reasoning": "Brief explanation (1-2 sentences)",
    "risk_flags": ["flag1", "flag2"],
    "confidence_in_validation": 0.XX
}}"""


@dataclass
class ValidationResult:
    """Result of secondary validation."""
    decision: str  # APPROVE, MODIFY, REJECT
    original_signal: TradeSignal
    modified_signal: Optional[TradeSignal] = None
    position_multiplier: float = 1.0
    reasoning: str = ""
    risk_flags: List[str] = field(default_factory=list)
    confidence: float = 0.0
    validation_time_ms: int = 0

    @property
    def final_signal(self) -> TradeSignal:
        """Get the signal to execute (modified if applicable)."""
        return self.modified_signal or self.original_signal

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "position_multiplier": self.position_multiplier,
            "reasoning": self.reasoning,
            "risk_flags": self.risk_flags,
            "confidence": self.confidence,
            "validation_time_ms": self.validation_time_ms
        }


@dataclass
class ValidationConfig:
    """Configuration for validation agent."""
    enabled: bool = True
    overconfidence_threshold: float = 0.85  # Flag if confidence > this
    max_loss_pattern_match: float = 0.6     # Reject if > 60% match with loss patterns
    min_validation_confidence: float = 0.7   # Skip validation if Claude unsure
    use_cached_insights: bool = True
    insights_cache_minutes: int = 60
    max_similar_trades: int = 5


class ValidationAgent:
    """
    Secondary validation layer that reviews trades before execution.

    Uses Claude to catch:
    - Overconfidence patterns (learned from reflection)
    - Correlation risks (multiple correlated positions)
    - Pattern matches with past losing trades
    - Position sizing adjustments based on conditions

    Can reduce position size or reject trades outright.
    """

    def __init__(
        self,
        llm: ILLM,
        journal: ITradeJournal,
        insights_path: str = "data/insights/trading_insights.md",
        config: ValidationConfig = None
    ):
        self.llm = llm
        self.journal = journal
        self.insights_path = Path(insights_path)
        self.config = config or ValidationConfig()

        self._insights_cache: Optional[str] = None
        self._insights_updated: Optional[datetime] = None
        self._validation_count = 0
        self._rejection_count = 0
        self._modification_count = 0

    async def validate_trade(
        self,
        signal: TradeSignal,
        intel: MarketIntel,
        portfolio: Portfolio
    ) -> ValidationResult:
        """
        Validate a proposed trade against learned patterns.

        Args:
            signal: The proposed trade signal
            intel: Market intelligence for the pair
            portfolio: Current portfolio state

        Returns:
            ValidationResult with approval/rejection/modification
        """
        import time
        start_time = time.time()

        self._validation_count += 1

        # Skip validation if disabled
        if not self.config.enabled:
            return ValidationResult(
                decision="APPROVE",
                original_signal=signal,
                reasoning="Validation disabled"
            )

        # 1. Load current insights
        insights = await self._load_insights()

        # 2. Get recent similar trades
        similar_trades = await self._find_similar_trades(signal.pair, intel)

        # 3. Calculate risk factors
        risk_flags = self._assess_risk_factors(signal, intel, portfolio)

        # 4. Build validation prompt
        prompt = self._build_validation_prompt(
            signal, intel, portfolio, insights, similar_trades
        )

        # 5. Get Claude's validation
        try:
            validation = await self.llm.analyze_market(
                prompt=prompt,
                system_prompt=VALIDATION_SYSTEM_PROMPT,
                max_tokens=200
            )
        except Exception as e:
            logger.warning(f"[VALIDATE] Claude validation failed: {e}, approving by default")
            return ValidationResult(
                decision="APPROVE",
                original_signal=signal,
                reasoning=f"Validation error: {e}"
            )

        # 6. Apply validation result
        result = self._apply_validation(signal, validation, risk_flags)
        result.validation_time_ms = int((time.time() - start_time) * 1000)

        # Track stats
        if result.decision == "REJECT":
            self._rejection_count += 1
        elif result.decision == "MODIFY":
            self._modification_count += 1

        logger.info(f"[VALIDATE] {signal.pair} {signal.action}: {result.decision} "
                   f"({result.reasoning[:50]}...)" if len(result.reasoning) > 50 else
                   f"[VALIDATE] {signal.pair} {signal.action}: {result.decision} "
                   f"({result.reasoning})")

        return result

    async def _load_insights(self) -> str:
        """Load insights from file with caching."""
        now = datetime.now(timezone.utc)

        # Check cache
        if self.config.use_cached_insights and self._insights_cache:
            cache_age = (now - self._insights_updated).total_seconds() / 60
            if cache_age < self.config.insights_cache_minutes:
                return self._insights_cache

        # Load from file
        if self.insights_path.exists():
            try:
                self._insights_cache = self.insights_path.read_text(encoding="utf-8")
                self._insights_updated = now
                return self._insights_cache
            except Exception as e:
                logger.warning(f"[VALIDATE] Could not load insights: {e}")

        return "No historical insights available yet."

    async def _find_similar_trades(
        self,
        pair: str,
        intel: MarketIntel
    ) -> List[TradeJournalEntry]:
        """Find similar past trades for comparison."""
        # Get recent trades for this pair
        entries = await self.journal.get_entries(
            pair=pair,
            limit=self.config.max_similar_trades * 2
        )

        if not entries:
            return []

        # Filter to similar conditions
        similar = []
        for entry in entries:
            if not entry.outcome_tracked:
                continue

            # Check if direction was similar
            direction_similar = abs(entry.fused_direction - intel.fused_direction) < 0.3

            # Check if confidence was similar
            confidence_similar = abs(entry.fused_confidence - intel.fused_confidence) < 0.2

            if direction_similar or confidence_similar:
                similar.append(entry)

            if len(similar) >= self.config.max_similar_trades:
                break

        return similar

    def _assess_risk_factors(
        self,
        signal: TradeSignal,
        intel: MarketIntel,
        portfolio: Portfolio
    ) -> List[str]:
        """Assess risk factors for the trade."""
        flags = []

        # Overconfidence check
        if signal.confidence > self.config.overconfidence_threshold:
            flags.append(f"High confidence ({signal.confidence:.0%})")

        # Disagreement check
        if intel.disagreement > 0.3:
            flags.append(f"High analyst disagreement ({intel.disagreement:.0%})")

        # Exposure check
        current_exposure = (portfolio.total_value - portfolio.available_quote) / portfolio.total_value
        if current_exposure > 0.7:
            flags.append(f"High current exposure ({current_exposure:.0%})")

        # Existing position check
        base_asset = signal.pair.split("/")[0]
        if base_asset in portfolio.positions:
            existing = portfolio.positions[base_asset]
            if existing.amount > 0 and signal.action.value == "BUY":
                flags.append(f"Adding to existing position in {base_asset}")

        # Weak direction
        if abs(intel.fused_direction) < 0.2:
            flags.append(f"Weak signal direction ({intel.fused_direction:+.2f})")

        return flags

    def _build_validation_prompt(
        self,
        signal: TradeSignal,
        intel: MarketIntel,
        portfolio: Portfolio,
        insights: str,
        similar_trades: List[TradeJournalEntry]
    ) -> str:
        """Build the validation prompt."""
        # Format analyst signals
        signals_str = ""
        for sig in intel.signals:
            signals_str += f"  - {sig.source}: direction={sig.direction:+.2f}, confidence={sig.confidence:.0%}\n"
            if sig.reasoning:
                signals_str += f"    Reasoning: {sig.reasoning[:100]}...\n" if len(sig.reasoning) > 100 else f"    Reasoning: {sig.reasoning}\n"

        # Format existing positions
        positions_str = []
        for asset, pos in portfolio.positions.items():
            value = pos.amount * pos.current_price
            positions_str.append(f"{asset}: ${value:.2f}")
        positions_formatted = ", ".join(positions_str) if positions_str else "None"

        # Calculate exposure
        invested = portfolio.total_value - portfolio.available_quote
        exposure = invested / portfolio.total_value if portfolio.total_value > 0 else 0

        # Format similar trades
        similar_str = ""
        if similar_trades:
            wins = [t for t in similar_trades if t.outcome_correct]
            losses = [t for t in similar_trades if t.outcome_correct is False]
            similar_str = f"{len(wins)} wins, {len(losses)} losses in similar conditions\n"
            for trade in similar_trades[:3]:
                similar_str += f"  - {trade.strategist_action}: {trade.get_outcome_summary()}\n"
        else:
            similar_str = "No similar past trades found."

        # Calculate position size
        size_pct = getattr(signal, 'size_pct', 0.2)  # Default 20%
        size_aud = portfolio.available_quote * size_pct

        return VALIDATION_PROMPT_TEMPLATE.format(
            pair=signal.pair,
            action=signal.action.value,
            confidence=signal.confidence,
            size_pct=size_pct,
            size_aud=size_aud,
            reasoning=signal.reasoning or "No reasoning provided",
            direction=intel.fused_direction,
            disagreement=intel.disagreement,
            regime=intel.regime.value if hasattr(intel.regime, 'value') else str(intel.regime),
            analyst_signals=signals_str,
            total_value=portfolio.total_value,
            available=portfolio.available_quote,
            exposure=exposure,
            positions=positions_formatted,
            insights=insights[:1500] if len(insights) > 1500 else insights,  # Truncate long insights
            similar_trades=similar_str
        )

    def _apply_validation(
        self,
        signal: TradeSignal,
        validation: Dict,
        risk_flags: List[str]
    ) -> ValidationResult:
        """Apply validation result to create ValidationResult."""
        decision = validation.get("decision", "APPROVE").upper()

        # Ensure valid decision
        if decision not in ["APPROVE", "MODIFY", "REJECT"]:
            decision = "APPROVE"

        result = ValidationResult(
            decision=decision,
            original_signal=signal,
            position_multiplier=validation.get("position_multiplier", 1.0),
            reasoning=validation.get("reasoning", ""),
            risk_flags=risk_flags + validation.get("risk_flags", []),
            confidence=validation.get("confidence_in_validation", 0.5)
        )

        # Create modified signal if needed
        if decision == "MODIFY" and result.position_multiplier != 1.0:
            # Clone signal with modified size
            modified = TradeSignal(
                pair=signal.pair,
                action=signal.action,
                confidence=signal.confidence,
                reasoning=f"{signal.reasoning} [Size reduced to {result.position_multiplier:.0%}]"
            )
            # Adjust size if signal has size attribute
            if hasattr(signal, 'size_pct'):
                modified.size_pct = signal.size_pct * result.position_multiplier
            result.modified_signal = modified

        return result

    def get_stats(self) -> Dict:
        """Get validation statistics."""
        return {
            "total_validations": self._validation_count,
            "rejections": self._rejection_count,
            "modifications": self._modification_count,
            "approval_rate": (self._validation_count - self._rejection_count) / self._validation_count
                            if self._validation_count > 0 else 1.0,
            "modification_rate": self._modification_count / self._validation_count
                                if self._validation_count > 0 else 0
        }
