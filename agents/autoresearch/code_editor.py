"""LLM-powered code editor for autoresearch experiments."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .models import Objective
from .prompts import CODE_EDIT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def edit_code(
    llm: Any,
    objective: Objective,
    repo_root: Path,
    performance: Dict[str, Any],
) -> Optional[str]:
    """Read target file, send to LLM with objective, return modified content.

    Args:
        llm: LLM instance with analyze_market() method.
        objective: The improvement objective.
        repo_root: Repository root path.
        performance: Current performance metrics.

    Returns:
        Modified file content as string, or None if editing failed.
    """
    target_path = repo_root / objective.target_file
    if not target_path.is_file():
        logger.error("Target file does not exist: %s", target_path)
        return None

    try:
        original_content = target_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Failed to read target file: %s", e)
        return None

    prompt = (
        f"## Objective\n{objective.description}\n\n"
        f"## Target Metric\n"
        f"- Metric: {objective.metric}\n"
        f"- Current value: {objective.current_value}\n"
        f"- Direction: {objective.target_direction}\n\n"
        f"## Current Performance\n"
        f"- Win rate (7d): {performance.get('win_rate_7d', 'N/A')}%\n"
        f"- Profit factor: {performance.get('profit_factor', 'N/A')}\n"
        f"- Net P&L (7d): ${performance.get('total_pnl_7d', 0):.6f}\n"
        f"- Closed trades (7d): {performance.get('closed_trades_7d', 0)}\n\n"
        f"## File: {objective.target_file}\n"
        f"```python\n{original_content}\n```"
    )

    try:
        raw = await llm.analyze_market(
            prompt=prompt,
            system_prompt=CODE_EDIT_SYSTEM_PROMPT,
            max_tokens=4000,
        )

        # The LLM should return the full file content as a string
        if isinstance(raw, str):
            new_content = raw
        elif isinstance(raw, dict):
            # Some LLM wrappers return structured responses
            new_content = raw.get("content", raw.get("code", ""))
        elif isinstance(raw, list) and raw:
            new_content = str(raw[0])
        else:
            logger.warning("Unexpected LLM response type: %s", type(raw).__name__)
            return None

        # Strip markdown code fences if present
        new_content = _strip_code_fences(new_content)

        if not new_content.strip():
            logger.warning("LLM returned empty content")
            return None

        logger.info(
            "Code edit generated: %d → %d chars for %s",
            len(original_content),
            len(new_content),
            objective.target_file,
        )
        return new_content

    except Exception as e:
        logger.error("Code editing failed: %s", e)
        return None


def _strip_code_fences(content: str) -> str:
    """Remove markdown code fences wrapping the content."""
    stripped = content.strip()
    if stripped.startswith("```python"):
        stripped = stripped[len("```python"):]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()
