"""
Self-Reflection Agent

Claude-powered agent that analyzes past trading decisions to identify
patterns, learn from mistakes, and generate improvement insights.
"""

import os
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.interfaces import ILLM
from memory.trade_journal import ITradeJournal, TradeJournalEntry

logger = logging.getLogger(__name__)


REFLECTION_SYSTEM_PROMPT = """You are a trading performance analyst reviewing past trade decisions. Your goal is to:

1. Identify PATTERNS in winning trades (what signals/conditions led to success)
2. Identify PATTERNS in losing trades (what signals/conditions led to failure)
3. Detect SYSTEMATIC BIASES (overconfidence, regime blindness, timing issues)
4. Suggest PARAMETER IMPROVEMENTS (confidence thresholds, position sizing)
5. Recommend PROMPT IMPROVEMENTS for the strategist agent

Be specific and actionable. Focus on patterns, not individual trades.
When analyzing, look for:
- Analyst agreement/disagreement patterns
- Confidence calibration (high confidence = better outcomes?)
- Regime-specific performance (trending vs ranging)
- Time-of-day patterns
- Pair-specific patterns

Output your analysis as valid JSON."""


REFLECTION_PROMPT_TEMPLATE = """Analyze these trading records from the past {days} days:

## Summary Statistics
- Total trades: {total_trades}
- Win rate: {win_rate:.1%}
- Average win: ${avg_win:.2f} ({avg_win_pct:.1%})
- Average loss: ${avg_loss:.2f} ({avg_loss_pct:.1%})
- Profit factor: {profit_factor:.2f}

## Winning Trades Analysis
{winning_trades_summary}

## Losing Trades Analysis
{losing_trades_summary}

## Pattern Questions to Answer:
1. What analyst signals were present in most winning trades?
2. What analyst signals were present in most losing trades?
3. Were there confidence level patterns? (e.g., high confidence = worse outcome)
4. Were there regime patterns? (e.g., trending markets = better/worse)
5. Were there specific pair patterns?
6. Were there disagreement patterns? (analysts disagreed = good/bad?)
7. What risk management improvements would help?

Provide your analysis as JSON:
{{
    "winning_patterns": ["pattern1", "pattern2", ...],
    "losing_patterns": ["pattern1", "pattern2", ...],
    "confidence_insights": "observation about confidence vs outcome",
    "regime_insights": "observation about market regime impact",
    "disagreement_insights": "observation about analyst disagreement",
    "biases_detected": ["bias1", "bias2", ...],
    "parameter_recommendations": {{
        "min_confidence": 0.XX,
        "position_sizing": "recommendation text",
        "stop_loss": "recommendation text"
    }},
    "prompt_improvements": [
        "suggestion1",
        "suggestion2"
    ],
    "pair_specific_notes": {{
        "PAIR/QUOTE": "observation"
    }},
    "action_items": [
        "immediate action 1",
        "immediate action 2"
    ]
}}"""


@dataclass
class ReflectionReport:
    """Output of a reflection analysis."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trades_analyzed: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # Pattern analysis
    winning_patterns: List[str] = field(default_factory=list)
    losing_patterns: List[str] = field(default_factory=list)

    # Insights
    confidence_insights: str = ""
    regime_insights: str = ""
    disagreement_insights: str = ""
    biases_detected: List[str] = field(default_factory=list)

    # Recommendations
    parameter_recommendations: Dict = field(default_factory=dict)
    prompt_improvements: List[str] = field(default_factory=list)
    pair_specific_notes: Dict = field(default_factory=dict)
    action_items: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "trades_analyzed": self.trades_analyzed,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "winning_patterns": self.winning_patterns,
            "losing_patterns": self.losing_patterns,
            "confidence_insights": self.confidence_insights,
            "regime_insights": self.regime_insights,
            "disagreement_insights": self.disagreement_insights,
            "biases_detected": self.biases_detected,
            "parameter_recommendations": self.parameter_recommendations,
            "prompt_improvements": self.prompt_improvements,
            "pair_specific_notes": self.pair_specific_notes,
            "action_items": self.action_items
        }

    def to_markdown(self) -> str:
        """Generate markdown report for insights file."""
        lines = [
            f"# Trading Insights - Updated {self.timestamp.strftime('%Y-%m-%d %H:%M')} UTC",
            "",
            "## Performance Summary",
            f"- Trades Analyzed: {self.trades_analyzed}",
            f"- Win Rate: {self.win_rate:.1%}",
            f"- Profit Factor: {self.profit_factor:.2f}",
            "",
            "## Winning Patterns",
        ]

        for pattern in self.winning_patterns:
            lines.append(f"- {pattern}")

        lines.extend(["", "## Losing Patterns"])
        for pattern in self.losing_patterns:
            lines.append(f"- {pattern}")

        lines.extend([
            "",
            "## Key Insights",
            f"**Confidence:** {self.confidence_insights}",
            "",
            f"**Regime:** {self.regime_insights}",
            "",
            f"**Disagreement:** {self.disagreement_insights}",
        ])

        if self.biases_detected:
            lines.extend(["", "## Detected Biases"])
            for bias in self.biases_detected:
                lines.append(f"- **{bias}**")

        if self.parameter_recommendations:
            lines.extend(["", "## Recommended Parameter Changes"])
            for key, value in self.parameter_recommendations.items():
                lines.append(f"- **{key}**: {value}")

        if self.prompt_improvements:
            lines.extend(["", "## Strategist Prompt Improvements"])
            for improvement in self.prompt_improvements:
                lines.append(f"- {improvement}")

        if self.pair_specific_notes:
            lines.extend(["", "## Pair-Specific Notes"])
            for pair, note in self.pair_specific_notes.items():
                lines.append(f"- **{pair}**: {note}")

        if self.action_items:
            lines.extend(["", "## Action Items"])
            for i, item in enumerate(self.action_items, 1):
                lines.append(f"{i}. {item}")

        return "\n".join(lines)


class SelfReflectionAgent:
    """
    Claude-powered self-reflection agent that analyzes past trades
    and generates learning insights.

    Runs on a configurable schedule (e.g., daily, after N trades).
    Outputs insights to a markdown file Claude can read in future sessions.
    """

    def __init__(
        self,
        llm: ILLM,
        journal: ITradeJournal,
        insights_path: str = "data/insights/trading_insights.md",
        min_trades_for_reflection: int = 10
    ):
        self.llm = llm
        self.journal = journal
        self.insights_path = Path(insights_path)
        self.min_trades = min_trades_for_reflection

        # Ensure insights directory exists
        self.insights_path.parent.mkdir(parents=True, exist_ok=True)

    async def reflect(self, days: int = 30, trades_limit: int = 100) -> Optional[ReflectionReport]:
        """
        Analyze recent trades and generate insights.

        Args:
            days: Number of days to analyze
            trades_limit: Maximum trades to include in analysis

        Returns:
            ReflectionReport with patterns and recommendations
        """
        logger.info(f"[REFLECT] Starting reflection analysis for past {days} days")

        # 1. Get trade data
        stats = await self.journal.get_summary_stats(days=days)

        if stats["executed_trades"] < self.min_trades:
            logger.info(f"[REFLECT] Not enough trades ({stats['executed_trades']}) for reflection")
            return None

        # 2. Get win/loss entries for pattern analysis
        wins = await self.journal.get_entries(outcome="win", limit=trades_limit // 2)
        losses = await self.journal.get_entries(outcome="loss", limit=trades_limit // 2)

        if not wins and not losses:
            logger.info("[REFLECT] No tracked outcomes available")
            return None

        # 3. Build analysis summaries
        winning_summary = self._summarize_trades(wins, "Winning")
        losing_summary = self._summarize_trades(losses, "Losing")

        # 4. Build reflection prompt
        prompt = REFLECTION_PROMPT_TEMPLATE.format(
            days=days,
            total_trades=stats["executed_trades"],
            win_rate=stats["win_rate"],
            avg_win=stats["avg_win"],
            avg_win_pct=stats["avg_win"] / 100 if stats["avg_win"] else 0,  # Rough estimate
            avg_loss=abs(stats["avg_loss"]),
            avg_loss_pct=abs(stats["avg_loss"]) / 100 if stats["avg_loss"] else 0,
            profit_factor=stats["profit_factor"] or 0,
            winning_trades_summary=winning_summary,
            losing_trades_summary=losing_summary
        )

        # 5. Get Claude's analysis
        try:
            analysis = await self.llm.analyze_market(
                prompt=prompt,
                system_prompt=REFLECTION_SYSTEM_PROMPT,
                max_tokens=2000
            )
        except Exception as e:
            logger.error(f"[REFLECT] Claude analysis failed: {e}")
            return None

        # 6. Parse and structure insights
        report = self._parse_reflection(analysis, stats)

        # 7. Write insights to file
        await self._write_insights_file(report)

        # 8. Tag entries based on patterns
        await self._tag_entries_from_patterns(wins + losses, report)

        logger.info(f"[REFLECT] Reflection complete: {len(report.winning_patterns)} winning patterns, "
                   f"{len(report.losing_patterns)} losing patterns")

        return report

    def _summarize_trades(self, entries: List[TradeJournalEntry], label: str) -> str:
        """Create a summary of trades for the prompt."""
        if not entries:
            return f"No {label.lower()} trades in this period."

        lines = [f"### {label} Trades ({len(entries)} total)\n"]

        # Group by pair
        by_pair = {}
        for e in entries:
            if e.pair not in by_pair:
                by_pair[e.pair] = []
            by_pair[e.pair].append(e)

        for pair, trades in by_pair.items():
            lines.append(f"\n**{pair}** ({len(trades)} trades):")

            for trade in trades[:3]:  # Limit to 3 examples per pair
                signals_summary = []
                for sig in trade.analyst_signals:
                    signals_summary.append(
                        f"{sig.get('source', 'unknown')}: {sig.get('direction', 0):+.2f} "
                        f"({sig.get('confidence', 0):.0%})"
                    )

                lines.append(f"  - Action: {trade.strategist_action}, "
                           f"Confidence: {trade.strategist_confidence:.0%}, "
                           f"Signals: [{', '.join(signals_summary)}]")
                if trade.strategist_reasoning:
                    # Truncate long reasoning
                    reasoning = trade.strategist_reasoning[:150]
                    if len(trade.strategist_reasoning) > 150:
                        reasoning += "..."
                    lines.append(f"    Reasoning: {reasoning}")

        return "\n".join(lines)

    def _parse_reflection(self, analysis: Dict, stats: Dict) -> ReflectionReport:
        """Parse Claude's analysis into a structured report."""
        report = ReflectionReport(
            trades_analyzed=stats["executed_trades"],
            win_rate=stats["win_rate"],
            profit_factor=stats["profit_factor"] or 0
        )

        # Extract fields with defaults
        report.winning_patterns = analysis.get("winning_patterns", [])
        report.losing_patterns = analysis.get("losing_patterns", [])
        report.confidence_insights = analysis.get("confidence_insights", "")
        report.regime_insights = analysis.get("regime_insights", "")
        report.disagreement_insights = analysis.get("disagreement_insights", "")
        report.biases_detected = analysis.get("biases_detected", [])
        report.parameter_recommendations = analysis.get("parameter_recommendations", {})
        report.prompt_improvements = analysis.get("prompt_improvements", [])
        report.pair_specific_notes = analysis.get("pair_specific_notes", {})
        report.action_items = analysis.get("action_items", [])

        return report

    async def _write_insights_file(self, report: ReflectionReport) -> None:
        """Write insights to markdown file for future reference."""
        try:
            content = report.to_markdown()
            self.insights_path.write_text(content, encoding="utf-8")
            logger.info(f"[REFLECT] Insights written to {self.insights_path}")
        except Exception as e:
            logger.error(f"[REFLECT] Failed to write insights file: {e}")

    async def _tag_entries_from_patterns(
        self,
        entries: List[TradeJournalEntry],
        report: ReflectionReport
    ) -> None:
        """Add learning tags to entries based on detected patterns."""
        # Simple pattern matching for tagging
        overconfidence_keywords = ["overconfident", "too confident", "high confidence"]
        regime_keywords = ["regime", "trending", "ranging", "volatile"]

        for entry in entries:
            # Check for overconfidence
            if any(kw in report.confidence_insights.lower() for kw in overconfidence_keywords):
                if entry.strategist_confidence > 0.85 and entry.actual_pnl and entry.actual_pnl < 0:
                    await self.journal.add_tag(entry.id, "overconfident")

            # Check for regime issues
            if any(kw in report.regime_insights.lower() for kw in regime_keywords):
                if entry.actual_pnl and entry.actual_pnl < 0:
                    await self.journal.add_tag(entry.id, "regime_mismatch")

    async def get_current_insights(self) -> Optional[str]:
        """Read current insights file content."""
        if self.insights_path.exists():
            return self.insights_path.read_text(encoding="utf-8")
        return None

    async def get_insights_age_hours(self) -> Optional[float]:
        """Get how old the current insights file is in hours."""
        if self.insights_path.exists():
            mtime = datetime.fromtimestamp(
                self.insights_path.stat().st_mtime,
                tz=timezone.utc
            )
            age = datetime.now(timezone.utc) - mtime
            return age.total_seconds() / 3600
        return None
