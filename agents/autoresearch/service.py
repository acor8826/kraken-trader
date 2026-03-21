"""Autoresearch service — recursive self-improvement via LLM code edits.

Runs after market close, reviews the day's trades, identifies an improvement
objective, edits code, validates changes, commits, and records the experiment.
Next day: evaluate results and keep or revert.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import code_editor, git_ops, objective_selector
from .file_policy import is_modifiable
from .models import Experiment, Objective
from .prompts import EVALUATION_PROMPT
from .validator import validate_modified_code

logger = logging.getLogger(__name__)

MAX_EXPERIMENTS_PER_SESSION = 3


class AutoresearchService:
    """Orchestrates the autoresearch experiment lifecycle."""

    def __init__(
        self,
        store: Any,
        llm: Any,
        repo_root: Optional[Path] = None,
    ):
        self.store = store
        self.llm = llm
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, daily_context: Dict[str, Any]) -> Dict[str, Any]:
        """Run one autoresearch session.

        Flow:
        1. Evaluate previous experiments (next-day evaluation).
        2. Select an improvement objective.
        3. Edit code, validate, commit, record.

        Returns summary dict.
        """
        results: Dict[str, Any] = {
            "evaluations": [],
            "experiments": [],
            "errors": [],
        }

        # Phase 1: Evaluate previous experiments
        try:
            evals = await self._evaluate_pending_experiments()
            results["evaluations"] = evals
        except Exception as e:
            logger.error("Experiment evaluation failed: %s", e)
            results["errors"].append(f"evaluation: {e}")

        # Phase 2: Run new experiments
        if not self.llm:
            logger.info("No LLM available, skipping new experiments")
            return results

        # Get performance metrics
        performance = {}
        if hasattr(self.store, "get_performance_summary"):
            try:
                performance = await self.store.get_performance_summary()
            except Exception as e:
                logger.warning("Failed to get performance: %s", e)

        # Check rate limit
        today_count = await self._count_today_experiments()
        remaining = MAX_EXPERIMENTS_PER_SESSION - today_count
        if remaining <= 0:
            logger.info("Rate limit reached (%d experiments today)", today_count)
            return results

        # Select objective and run experiment
        for i in range(min(remaining, 1)):  # One experiment per run for safety
            try:
                experiment = await self._run_single_experiment(
                    daily_context, performance
                )
                if experiment:
                    results["experiments"].append(experiment.to_dict())
            except Exception as e:
                logger.error("Experiment %d failed: %s", i + 1, e)
                results["errors"].append(f"experiment_{i+1}: {e}")

        return results

    # ------------------------------------------------------------------
    # Single experiment flow
    # ------------------------------------------------------------------

    async def _run_single_experiment(
        self,
        daily_context: Dict[str, Any],
        performance: Dict[str, Any],
    ) -> Optional[Experiment]:
        """Run a single experiment: objective → edit → validate → commit."""

        # 1. Select objective
        objective = await objective_selector.select_objective(
            self.llm, self.store, daily_context, performance
        )
        if not objective:
            logger.info("No objective selected, skipping experiment")
            return None

        # 2. Validate file is modifiable
        if not is_modifiable(objective.target_file, self.repo_root):
            logger.warning("File not modifiable: %s", objective.target_file)
            return None

        target_path = self.repo_root / objective.target_file

        # 3. Record experiment as PENDING
        experiment = Experiment(
            date=date.today(),
            objective=objective.description,
            target_file=objective.target_file,
            status="PENDING",
            metrics_before=performance,
        )
        experiment.id = await self._save_experiment(experiment)

        # 4. Read original content
        try:
            original_content = target_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Cannot read %s: %s", target_path, e)
            experiment.status = "FAILED"
            await self._update_experiment_status(experiment.id, "FAILED", notes=str(e))
            return experiment

        # 5. LLM code edit
        new_content = await code_editor.edit_code(
            self.llm, objective, self.repo_root, performance
        )
        if not new_content:
            experiment.status = "FAILED"
            await self._update_experiment_status(
                experiment.id, "FAILED", notes="LLM returned no content"
            )
            return experiment

        # 6. Validate
        is_valid, errors = validate_modified_code(
            original_content, new_content, target_path
        )
        if not is_valid:
            experiment.status = "FAILED"
            await self._update_experiment_status(
                experiment.id, "FAILED", notes=f"Validation failed: {errors}"
            )
            return experiment

        # 7. Write file
        try:
            target_path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            experiment.status = "FAILED"
            await self._update_experiment_status(
                experiment.id, "FAILED", notes=f"Write failed: {e}"
            )
            return experiment

        # 8. Get diff before commit
        diff = git_ops.get_diff(objective.target_file, self.repo_root)
        experiment.code_diff = diff

        # 9. Commit
        commit_msg = (
            f"autoresearch: {objective.description[:60]}\n\n"
            f"Target: {objective.target_file}\n"
            f"Metric: {objective.metric} ({objective.target_direction})\n"
            f"Experiment ID: {experiment.id}"
        )
        success, commit_hash = git_ops.commit_experiment(
            objective.target_file, commit_msg, self.repo_root
        )

        if not success:
            # Restore original file
            try:
                target_path.write_text(original_content, encoding="utf-8")
            except Exception:
                pass
            experiment.status = "FAILED"
            await self._update_experiment_status(
                experiment.id, "FAILED", notes="Git commit failed"
            )
            return experiment

        experiment.commit_hash = commit_hash
        experiment.status = "COMMITTED"
        experiment.llm_reasoning = objective.description
        await self._update_experiment(experiment)

        logger.info(
            "Experiment committed: %s → %s (%s)",
            experiment.id,
            objective.target_file,
            commit_hash[:8] if commit_hash else "?",
        )
        return experiment

    # ------------------------------------------------------------------
    # Next-day evaluation
    # ------------------------------------------------------------------

    async def _evaluate_pending_experiments(self) -> List[Dict[str, Any]]:
        """Evaluate experiments from previous days that are in COMMITTED status."""
        results = []
        pending = await self._get_pending_evaluations()

        if not pending:
            return results

        # Get current performance for comparison
        current_performance = {}
        if hasattr(self.store, "get_performance_summary"):
            try:
                current_performance = await self.store.get_performance_summary()
            except Exception:
                pass

        for exp in pending:
            try:
                verdict = await self._evaluate_single(exp, current_performance)
                results.append(verdict)
            except Exception as e:
                logger.error("Failed to evaluate experiment %s: %s", exp.id, e)

        return results

    async def _evaluate_single(
        self, experiment: Experiment, current_performance: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate a single experiment and either keep or revert."""
        result = {
            "experiment_id": experiment.id,
            "objective": experiment.objective,
            "verdict": "KEEP",
            "reasoning": "",
        }

        if self.llm:
            try:
                prompt = json.dumps({
                    "objective": experiment.objective,
                    "target_file": experiment.target_file,
                    "metrics_before": experiment.metrics_before,
                    "metrics_after": current_performance,
                    "code_diff": (experiment.code_diff or "")[:2000],
                }, indent=2, default=str)

                raw = await self.llm.analyze_market(
                    prompt=prompt,
                    system_prompt=EVALUATION_PROMPT,
                    max_tokens=500,
                )

                if isinstance(raw, list) and raw:
                    raw = raw[0]
                if isinstance(raw, dict):
                    result["verdict"] = raw.get("verdict", "KEEP").upper()
                    result["reasoning"] = raw.get("reasoning", "")
            except Exception as e:
                logger.warning("LLM evaluation failed, defaulting to KEEP: %s", e)
                result["reasoning"] = f"LLM evaluation failed: {e}"

        # Apply verdict
        if result["verdict"] == "REVERT" and experiment.commit_hash:
            reverted = git_ops.revert_experiment(
                experiment.commit_hash, self.repo_root
            )
            if reverted:
                experiment.status = "REVERTED"
                experiment.evaluation_notes = result["reasoning"]
            else:
                experiment.status = "FAILED"
                experiment.evaluation_notes = "Revert failed"
                result["verdict"] = "REVERT_FAILED"
        else:
            experiment.status = "KEPT" if result["verdict"] == "KEEP" else "VALIDATED"
            experiment.evaluation_notes = result["reasoning"]

        experiment.metrics_after = current_performance
        await self._update_experiment(experiment)

        logger.info(
            "Experiment %s evaluated: %s — %s",
            experiment.id,
            result["verdict"],
            result["reasoning"][:80],
        )
        return result

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def _save_experiment(self, experiment: Experiment) -> Optional[str]:
        """Save a new experiment to the database."""
        if not hasattr(self.store, "_connection"):
            return None
        try:
            async with self.store._connection() as conn:
                row_id = await conn.fetchval(
                    """
                    INSERT INTO autoresearch_experiments
                        (date, objective, target_file, status, metrics_before, llm_reasoning)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    experiment.date,
                    experiment.objective,
                    experiment.target_file,
                    experiment.status,
                    json.dumps(experiment.metrics_before, default=str),
                    experiment.llm_reasoning,
                )
                return str(row_id)
        except Exception as e:
            logger.error("Failed to save experiment: %s", e)
            return None

    async def _update_experiment(self, experiment: Experiment) -> None:
        """Update an experiment in the database."""
        if not hasattr(self.store, "_connection") or not experiment.id:
            return
        try:
            async with self.store._connection() as conn:
                await conn.execute(
                    """
                    UPDATE autoresearch_experiments
                    SET status = $2, commit_hash = $3, code_diff = $4,
                        metrics_before = $5, metrics_after = $6,
                        llm_reasoning = $7, evaluation_notes = $8,
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    experiment.id,
                    experiment.status,
                    experiment.commit_hash,
                    experiment.code_diff,
                    json.dumps(experiment.metrics_before, default=str),
                    json.dumps(experiment.metrics_after, default=str),
                    experiment.llm_reasoning,
                    experiment.evaluation_notes,
                )
        except Exception as e:
            logger.error("Failed to update experiment %s: %s", experiment.id, e)

    async def _update_experiment_status(
        self, exp_id: Optional[str], status: str, notes: Optional[str] = None
    ) -> None:
        """Update just the status (and optionally notes) of an experiment."""
        if not hasattr(self.store, "_connection") or not exp_id:
            return
        try:
            async with self.store._connection() as conn:
                await conn.execute(
                    """
                    UPDATE autoresearch_experiments
                    SET status = $2, evaluation_notes = COALESCE($3, evaluation_notes),
                        updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    exp_id,
                    status,
                    notes,
                )
        except Exception as e:
            logger.error("Failed to update experiment status: %s", e)

    async def _get_pending_evaluations(self) -> List[Experiment]:
        """Get experiments in COMMITTED status from previous days."""
        if not hasattr(self.store, "_connection"):
            return []
        try:
            async with self.store._connection() as conn:
                _syd_today = datetime.now(ZoneInfo("Australia/Sydney")).date()
                rows = await conn.fetch(
                    """
                    SELECT * FROM autoresearch_experiments
                    WHERE status = 'COMMITTED' AND date < $1
                    ORDER BY created_at ASC
                    LIMIT 10
                    """,
                    _syd_today,
                )
                return [Experiment.from_row(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get pending evaluations: %s", e)
            return []

    async def _count_today_experiments(self) -> int:
        """Count experiments created today."""
        if not hasattr(self.store, "_connection"):
            return 0
        try:
            async with self.store._connection() as conn:
                _syd_today = datetime.now(ZoneInfo("Australia/Sydney")).date()
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM autoresearch_experiments
                    WHERE date = $1
                    """,
                    _syd_today,
                )
                return int(count) if count else 0
        except Exception as e:
            logger.warning("Failed to count today's experiments: %s", e)
            return 0

    async def get_experiments(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get recent experiments for API endpoint."""
        if not hasattr(self.store, "_connection"):
            return []
        try:
            async with self.store._connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM autoresearch_experiments
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    days * 3,  # max 3 per day
                )
                return [Experiment.from_row(r).to_dict() for r in rows]
        except Exception as e:
            logger.error("Failed to get experiments: %s", e)
            return []

    async def get_latest_experiment(self) -> Optional[Dict[str, Any]]:
        """Get the most recent experiment."""
        if not hasattr(self.store, "_connection"):
            return None
        try:
            async with self.store._connection() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM autoresearch_experiments
                    ORDER BY created_at DESC LIMIT 1
                    """
                )
                if row:
                    return Experiment.from_row(row).to_dict()
                return None
        except Exception as e:
            logger.error("Failed to get latest experiment: %s", e)
            return None
