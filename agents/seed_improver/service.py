from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class SeedImproverResult:
    run_id: str
    trigger_type: str
    status: str
    summary: str


class SeedImproverService:
    """Phase 0 seed improver service.

    This is intentionally conservative: observability-first and additive.
    It audits data coverage and records run memory. Strategy/code mutation loops
    can be layered on top in later phases.
    """

    def __init__(self, memory: Any, repo_root: Optional[Path] = None):
        self.memory = memory
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        preferred = self.repo_root / "memory" / "seed_improver"

        try:
            preferred.mkdir(parents=True, exist_ok=True)
            self.memory_dir = preferred
        except Exception:
            # Cloud Run container filesystem under /app may be non-writable for non-root user.
            fallback = Path("/tmp") / "seed_improver_memory"
            fallback.mkdir(parents=True, exist_ok=True)
            self.memory_dir = fallback
            logger.warning("SeedImprover using fallback writable dir: %s", self.memory_dir)

    async def run(self, trigger_type: str, context: Optional[Dict[str, Any]] = None) -> SeedImproverResult:
        context = context or {}
        started_at = datetime.now(timezone.utc)

        run_id = await self._record_run_start(trigger_type, context)
        try:
            audit = await self._phase0_observability_audit()
            summary = self._write_markdown_run_log(run_id, trigger_type, started_at, context, audit)

            await self._record_run_complete(run_id, summary)
            return SeedImproverResult(run_id=run_id, trigger_type=trigger_type, status="completed", summary=summary)
        except Exception as e:
            err = f"Seed improver failed: {e}"
            logger.exception(err)
            await self._record_run_failed(run_id, err)
            return SeedImproverResult(run_id=run_id, trigger_type=trigger_type, status="failed", summary=err)

    async def _phase0_observability_audit(self) -> Dict[str, Any]:
        trades = []
        if hasattr(self.memory, "get_trade_history"):
            trades = await self.memory.get_trade_history(200)

        has_after_fees = any(getattr(t, "realized_pnl_after_fees", None) is not None for t in trades)
        has_reasoning = any(bool(getattr(t, "reasoning", "")) for t in trades)
        has_latency = any(getattr(t, "latency_decision_to_fill_ms", None) is not None for t in trades)

        audit = {
            "trade_count_sampled": len(trades),
            "coverage": {
                "realized_pnl_after_fees": has_after_fees,
                "reasoning": has_reasoning,
                "latency_decision_to_fill_ms": has_latency,
            },
            "gaps": [],
        }

        if not has_after_fees:
            audit["gaps"].append("Missing realized_pnl_after_fees in sampled trades")
        if not has_reasoning:
            audit["gaps"].append("Missing strategy reasoning in sampled trades")
        if not has_latency:
            audit["gaps"].append("Missing decision/submit/fill latency metrics")

        return audit

    def _write_markdown_run_log(
        self,
        run_id: str,
        trigger_type: str,
        started_at: datetime,
        context: Dict[str, Any],
        audit: Dict[str, Any],
    ) -> str:
        day_file = self.memory_dir / f"{started_at.date().isoformat()}.md"
        summary = (
            f"Phase0 audit complete. sampled={audit['trade_count_sampled']}, "
            f"gaps={len(audit['gaps'])}"
        )

        with day_file.open("a", encoding="utf-8") as f:
            f.write(f"\n## Run {run_id}\n")
            f.write(f"- Trigger: {trigger_type}\n")
            f.write(f"- Started: {started_at.isoformat()}\n")
            f.write(f"- Context: `{json.dumps(context, ensure_ascii=False)}`\n")
            f.write(f"- Summary: {summary}\n")
            f.write(f"- Coverage: `{json.dumps(audit['coverage'])}`\n")
            if audit["gaps"]:
                for gap in audit["gaps"]:
                    f.write(f"  - GAP: {gap}\n")

        # update stable docs
        codebase_summary = self.memory_dir / "codebase-summary.md"
        if not codebase_summary.exists():
            codebase_summary.write_text(
                "# Seed Improver Codebase Summary\n\n"
                "- Runtime: FastAPI on Cloud Run\n"
                "- Scheduler: APScheduler internal loop + Cloud Scheduler for seed improver\n"
                "- Persistence: PostgresStore for trades/signals/events\n"
                "- Trigger paths: /internal/seed-improver/run, /internal/seed-improver/loss\n",
                encoding="utf-8",
            )

        pattern_library = self.memory_dir / "pattern-library.md"
        if not pattern_library.exists():
            pattern_library.write_text("# Pattern Library\n\n", encoding="utf-8")

        return summary

    async def _record_run_start(self, trigger_type: str, context: Dict[str, Any]) -> str:
        if hasattr(self.memory, "_connection"):
            async with self.memory._connection() as conn:
                run_id = await conn.fetchval(
                    """
                    INSERT INTO seed_improver_runs (trigger_type, status, context)
                    VALUES ($1, 'started', $2)
                    RETURNING id
                    """,
                    trigger_type,
                    json.dumps(context),
                )
                return str(run_id)

        run_id = f"local-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        return run_id

    async def _record_run_complete(self, run_id: str, summary: str) -> None:
        if hasattr(self.memory, "_connection"):
            async with self.memory._connection() as conn:
                await conn.execute(
                    """
                    UPDATE seed_improver_runs
                    SET status='completed', finished_at=NOW(), summary=$2
                    WHERE id::text=$1
                    """,
                    run_id,
                    summary,
                )

    async def _record_run_failed(self, run_id: str, error: str) -> None:
        if hasattr(self.memory, "_connection"):
            async with self.memory._connection() as conn:
                await conn.execute(
                    """
                    UPDATE seed_improver_runs
                    SET status='failed', finished_at=NOW(), error=$2
                    WHERE id::text=$1
                    """,
                    run_id,
                    error,
                )
