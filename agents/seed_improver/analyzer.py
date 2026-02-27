"""
Seed Improver Analyzer

LLM-powered analysis engine that examines trade history, identifies
systematic weaknesses, and produces actionable recommendations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import AnalysisResult, PatternMatch, Recommendation
from .prompts import SYSTEM_PROMPT, build_analysis_prompt

logger = logging.getLogger(__name__)


class SeedImproverAnalyzer:
    """Builds context from trade data, calls LLM, parses recommendations."""

    def __init__(self, llm: Any):
        self.llm = llm

    async def analyze(
        self,
        trades: List[Any],
        stats: Dict[str, Any],
        config: Dict[str, Any],
        known_patterns: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisResult:
        """Run LLM analysis on recent trade data.

        Args:
            trades: List of Trade objects (or dicts) from memory.
            stats: Performance summary dict (win_rate, total_pnl, etc.).
            config: Current trading/risk configuration snapshot.
            known_patterns: Previously detected patterns from DB.

        Returns:
            AnalysisResult with recommendations and detected patterns.
        """
        trade_dicts = self._trades_to_dicts(trades)
        prompt = build_analysis_prompt(trade_dicts, stats, config, known_patterns)

        logger.info(
            "Running seed improver analysis: %d trades, %d known patterns",
            len(trade_dicts),
            len(known_patterns or []),
        )

        raw = await self.llm.analyze_market(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=2000,
        )

        result = self._parse_response(raw)

        model_name = getattr(self.llm, "model", "unknown")
        result.model_used = model_name

        logger.info(
            "Analysis complete: %d recommendations, %d patterns detected",
            len(result.recommendations),
            len(result.patterns_detected),
        )

        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _trades_to_dicts(trades: List[Any]) -> List[Dict[str, Any]]:
        """Convert Trade objects to dicts for prompt building."""
        dicts: List[Dict[str, Any]] = []
        for t in trades:
            if isinstance(t, dict):
                dicts.append(t)
            elif hasattr(t, "to_dict"):
                dicts.append(t.to_dict())
            else:
                dicts.append(
                    {
                        "pair": getattr(t, "pair", "?"),
                        "action": getattr(t, "action", "?"),
                        "realized_pnl": getattr(t, "realized_pnl", None),
                        "realized_pnl_after_fees": getattr(t, "realized_pnl_after_fees", None),
                        "signal_confidence": getattr(t, "signal_confidence", None),
                        "reasoning": getattr(t, "reasoning", ""),
                        "entry_price": getattr(t, "entry_price", None),
                        "exit_price": getattr(t, "exit_price", None),
                        "latency_decision_to_fill_ms": getattr(t, "latency_decision_to_fill_ms", None),
                        "id": getattr(t, "id", ""),
                    }
                )
        return dicts

    @staticmethod
    def _parse_response(raw: Dict[str, Any]) -> AnalysisResult:
        """Parse the LLM JSON response into an AnalysisResult."""
        try:
            return AnalysisResult.from_dict(raw)
        except Exception as e:
            logger.warning("Failed to fully parse LLM response, using partial: %s", e)
            return AnalysisResult(
                summary=str(raw.get("analysis_summary", raw.get("summary", "Parse error"))),
                recommendations=[
                    Recommendation.from_dict(r)
                    for r in raw.get("recommendations", [])
                    if isinstance(r, dict)
                ],
                patterns_detected=[
                    PatternMatch.from_dict(p)
                    for p in raw.get("patterns_detected", [])
                    if isinstance(p, dict)
                ],
            )
