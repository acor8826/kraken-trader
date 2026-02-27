"""
Seed Improver LLM Prompts

System prompt, analysis prompt builder, and response schema for the
seed improver analysis engine.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


SYSTEM_PROMPT = """\
You are the Seed Improver, an autonomous meta-agent for a live crypto trading bot.
Your role is to analyze recent trade history, identify systematic weaknesses,
and produce actionable recommendations to improve the bot's trading strategy.

Principles:
- Be evidence-based: every recommendation must cite specific trades or patterns.
- Be conservative: prefer small, safe changes over sweeping rewrites.
- Prioritize risk reduction over profit maximization.
- Never recommend removing stop losses or circuit breakers.
- Consider the cost of being wrong: high-risk changes need very high confidence.

You will receive trade history, performance stats, current configuration,
and any previously detected patterns. Respond with structured JSON only.\
"""

RESPONSE_SCHEMA = {
    "analysis_summary": "string - 1-3 sentence overview of findings",
    "recommendations": [
        {
            "priority": "critical | strategy | observability | quality",
            "category": "stop_loss | entry_timing | position_sizing | exit_timing | pair_selection | risk_management | fee_optimization | data_coverage | other",
            "hypothesis": "string - what you believe is happening and why",
            "change_summary": "string - concrete change to make",
            "expected_impact": {
                "metric": "string - which metric improves (e.g. win_rate, avg_pnl, max_drawdown)",
                "direction": "increase | decrease",
                "magnitude": "small | medium | large",
            },
            "risk_assessment": "low | medium | high",
            "confidence": "float 0.0-1.0",
            "evidence": ["string - specific trade IDs, stats, or observations"],
        }
    ],
    "patterns_detected": [
        {
            "key": "string - unique snake_case identifier",
            "title": "string - short human-readable title",
            "description": "string - detailed description",
        }
    ],
}


def build_analysis_prompt(
    trades: List[Dict[str, Any]],
    stats: Dict[str, Any],
    config: Dict[str, Any],
    known_patterns: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build the user prompt for the LLM analysis call."""

    sections = []

    # Trade history
    sections.append("## Recent Trade History (most recent first)")
    if trades:
        for t in trades[:50]:
            line_parts = [
                f"  pair={t.get('pair', '?')}",
                f"action={t.get('action', '?')}",
                f"pnl={t.get('realized_pnl', t.get('pnl', 'N/A'))}",
                f"pnl_after_fees={t.get('realized_pnl_after_fees', 'N/A')}",
                f"confidence={t.get('signal_confidence', t.get('confidence', 'N/A'))}",
                f"entry={t.get('entry_price', 'N/A')}",
                f"exit={t.get('exit_price', 'N/A')}",
            ]
            reasoning = t.get("reasoning", "")
            if reasoning:
                line_parts.append(f"reasoning={reasoning[:120]}")
            latency = t.get("latency_decision_to_fill_ms")
            if latency is not None:
                line_parts.append(f"latency_ms={latency}")
            trade_id = t.get("id", "")
            if trade_id:
                line_parts.insert(0, f"id={trade_id}")
            sections.append("- " + ", ".join(line_parts))
    else:
        sections.append("No trades available.")

    # Performance stats
    sections.append("\n## Performance Statistics")
    if stats:
        for k, v in stats.items():
            sections.append(f"- {k}: {v}")
    else:
        sections.append("No stats available.")

    # Current config
    sections.append("\n## Current Configuration")
    if config:
        sections.append(f"```json\n{json.dumps(config, indent=2, default=str)}\n```")
    else:
        sections.append("No config available.")

    # Known patterns
    if known_patterns:
        sections.append("\n## Previously Detected Patterns")
        for p in known_patterns:
            sections.append(f"- [{p.get('key', '?')}] {p.get('title', '?')}: {p.get('description', '')}")

    # Response instruction
    sections.append("\n## Your Task")
    sections.append(
        "Analyze the trade history and stats above. Identify systematic issues "
        "and produce actionable recommendations. Respond with JSON matching this schema:"
    )
    sections.append(f"```json\n{json.dumps(RESPONSE_SCHEMA, indent=2)}\n```")

    return "\n".join(sections)
