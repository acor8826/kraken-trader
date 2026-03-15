"""Objective selector — analyses daily trades to pick improvement targets."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .file_policy import MODIFIABLE_FILES
from .models import Objective
from .prompts import OBJECTIVE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def select_objective(
    llm: Any,
    store: Any,
    daily_context: Dict[str, Any],
    performance: Dict[str, Any],
) -> Optional[Objective]:
    """Use LLM to identify the highest-impact improvement objective.

    Args:
        llm: LLM instance with analyze_market() method.
        store: PostgresStore for DB access.
        daily_context: Today's daily ledger data.
        performance: Performance summary dict.

    Returns:
        An Objective or None if selection failed.
    """
    # Gather recent trade context
    recent_trades: List[Dict[str, Any]] = []
    if hasattr(store, "get_trade_history"):
        try:
            trades = await store.get_trade_history(50)
            for t in trades:
                recent_trades.append({
                    "pair": getattr(t, "pair", "?"),
                    "action": str(getattr(t, "action", "?")),
                    "realized_pnl": getattr(t, "realized_pnl", None),
                    "signal_confidence": getattr(t, "signal_confidence", None),
                    "reasoning": (getattr(t, "reasoning", "") or "")[:100],
                })
        except Exception as e:
            logger.warning("Failed to fetch trade history for objective: %s", e)

    # Gather recent ledger entries
    ledger_entries: List[Dict[str, Any]] = []
    if hasattr(store, "get_daily_ledger"):
        try:
            entries = await store.get_daily_ledger(7)
            for e in entries:
                ledger_entries.append({
                    "date": str(e.get("date", "")),
                    "daily_pnl": float(e.get("daily_pnl", 0)),
                    "status": e.get("status", ""),
                    "total_trades": e.get("total_trades", 0),
                    "win_rate": float(e.get("win_rate", 0)),
                })
        except Exception as e:
            logger.warning("Failed to fetch ledger for objective: %s", e)

    prompt = json.dumps({
        "daily_context": daily_context,
        "performance_summary": performance,
        "recent_trades": recent_trades[:20],
        "daily_ledger_7d": ledger_entries,
        "modifiable_files": MODIFIABLE_FILES,
    }, indent=2, default=str)

    try:
        raw = await llm.analyze_market(
            prompt=prompt,
            system_prompt=OBJECTIVE_SYSTEM_PROMPT,
            max_tokens=500,
        )

        if isinstance(raw, list) and raw:
            raw = raw[0]
        if not isinstance(raw, dict):
            logger.warning("Objective LLM returned non-dict: %s", type(raw).__name__)
            return None

        objective = Objective.from_dict(raw)

        # Validate the target file is in the allowlist
        if objective.target_file not in MODIFIABLE_FILES:
            logger.warning(
                "LLM selected non-modifiable file %s, rejecting", objective.target_file
            )
            return None

        logger.info(
            "Selected objective: %s → %s (metric=%s, direction=%s)",
            objective.target_file,
            objective.description[:80],
            objective.metric,
            objective.target_direction,
        )
        return objective

    except Exception as e:
        logger.error("Objective selection failed: %s", e)
        return None
