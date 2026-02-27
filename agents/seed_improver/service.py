from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analyzer import SeedImproverAnalyzer
from .models import AnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class SeedImproverResult:
    run_id: str
    trigger_type: str
    status: str
    summary: str
    analysis: Optional[AnalysisResult] = None


class SeedImproverService:
    """Seed improver service with Phase 0 audit + Phase 1 LLM analysis.

    Phase 0: Observability audit (data coverage checks).
    Phase 1: LLM-powered analysis producing actionable recommendations.

    Graceful degradation: if no LLM is provided, Phase 1 is skipped.
    """

    def __init__(
        self,
        memory: Any,
        llm: Any = None,
        alert_manager: Any = None,
        repo_root: Optional[Path] = None,
    ):
        self.memory = memory
        self.llm = llm
        self.alert_manager = alert_manager
        self.analyzer = SeedImproverAnalyzer(llm) if llm else None
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        preferred = self.repo_root / "memory" / "seed_improver"

        try:
            preferred.mkdir(parents=True, exist_ok=True)
            self.memory_dir = preferred
        except Exception:
            fallback = Path("/tmp") / "seed_improver_memory"
            fallback.mkdir(parents=True, exist_ok=True)
            self.memory_dir = fallback
            logger.warning("SeedImprover using fallback writable dir: %s", self.memory_dir)

    async def run(self, trigger_type: str, context: Optional[Dict[str, Any]] = None) -> SeedImproverResult:
        context = context or {}
        started_at = datetime.now(timezone.utc)

        run_id = await self._record_run_start(trigger_type, context)
        try:
            # Phase 0: observability audit
            audit = await self._phase0_observability_audit()
            summary = self._write_markdown_run_log(run_id, trigger_type, started_at, context, audit)

            # Phase 1: LLM analysis (skipped if no LLM)
            analysis = None
            if self.analyzer:
                analysis = await self._phase1_analysis(run_id, audit)
                if analysis:
                    summary += f" | Phase1: {len(analysis.recommendations)} recommendations"

            await self._record_run_complete(run_id, summary)

            # Send notification
            await self._notify_run_complete(run_id, trigger_type, analysis)

            return SeedImproverResult(
                run_id=run_id,
                trigger_type=trigger_type,
                status="completed",
                summary=summary,
                analysis=analysis,
            )
        except Exception as e:
            err = f"Seed improver failed: {e}"
            logger.exception(err)
            await self._record_run_failed(run_id, err)
            return SeedImproverResult(run_id=run_id, trigger_type=trigger_type, status="failed", summary=err)

    # ------------------------------------------------------------------
    # Phase 0: Observability Audit
    # ------------------------------------------------------------------

    async def _phase0_observability_audit(self) -> Dict[str, Any]:
        trades: List[Any] = []
        if hasattr(self.memory, "get_trade_history"):
            trades = await self.memory.get_trade_history(200)

        has_after_fees = any(getattr(t, "realized_pnl_after_fees", None) is not None for t in trades)
        has_reasoning = any(bool(getattr(t, "reasoning", "")) for t in trades)
        has_latency = any(getattr(t, "latency_decision_to_fill_ms", None) is not None for t in trades)

        audit: Dict[str, Any] = {
            "trade_count_sampled": len(trades),
            "trades": trades,
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

    # ------------------------------------------------------------------
    # Phase 1: LLM Analysis
    # ------------------------------------------------------------------

    async def _phase1_analysis(self, run_id: str, audit: Dict[str, Any]) -> Optional[AnalysisResult]:
        """Run LLM analysis on trade data and store recommendations."""
        trades = audit.get("trades", [])
        if not trades:
            logger.info("Skipping Phase 1 analysis: no trades available")
            return None

        try:
            stats = await self._gather_stats()
            config = self._gather_config()
            known_patterns = await self._load_known_patterns()

            analysis = await self.analyzer.analyze(trades, stats, config, known_patterns)

            # Store recommendations in DB
            await self._store_recommendations(run_id, analysis)

            # Append to markdown log
            self._append_analysis_to_log(run_id, analysis)

            # Update pattern library
            await self._store_patterns(analysis.patterns_detected)

            return analysis
        except Exception as e:
            logger.warning("Phase 1 analysis failed (Phase 0 still succeeded): %s", e)
            return None

    async def _gather_stats(self) -> Dict[str, Any]:
        """Gather performance stats from memory."""
        stats: Dict[str, Any] = {}
        if not hasattr(self.memory, "_connection"):
            return stats

        try:
            async with self.memory._connection() as conn:
                # Win/loss stats
                row = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_trades,
                        COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                        COUNT(*) FILTER (WHERE realized_pnl <= 0) as losses,
                        COALESCE(SUM(realized_pnl), 0) as total_pnl,
                        COALESCE(AVG(realized_pnl), 0) as avg_pnl,
                        COALESCE(MAX(realized_pnl), 0) as best_trade,
                        COALESCE(MIN(realized_pnl), 0) as worst_trade
                    FROM trades
                    WHERE created_at > NOW() - INTERVAL '30 days'
                """)
                if row:
                    total = row["total_trades"]
                    stats["total_trades_30d"] = total
                    stats["wins"] = row["wins"]
                    stats["losses"] = row["losses"]
                    stats["win_rate"] = round(row["wins"] / total, 3) if total > 0 else 0
                    stats["total_pnl_30d"] = float(row["total_pnl"])
                    stats["avg_pnl"] = float(row["avg_pnl"])
                    stats["best_trade"] = float(row["best_trade"])
                    stats["worst_trade"] = float(row["worst_trade"])

                # Daily PnL
                daily = await conn.fetchval("""
                    SELECT COALESCE(SUM(realized_pnl), 0)
                    FROM trades WHERE created_at::date = CURRENT_DATE
                """)
                stats["daily_pnl"] = float(daily) if daily else 0.0
        except Exception as e:
            logger.warning("Failed to gather stats: %s", e)

        return stats

    def _gather_config(self) -> Dict[str, Any]:
        """Snapshot current trading config."""
        try:
            from core.config.settings import Settings
            s = Settings.from_env()
            return {
                "pairs": s.trading.pairs,
                "check_interval_minutes": s.trading.check_interval_minutes,
                "simulation_mode": s.features.simulation_mode,
                "stage": s.stage.value,
                "initial_capital": s.trading.initial_capital,
                "target_capital": s.trading.target_capital,
            }
        except Exception as e:
            logger.warning("Failed to gather config: %s", e)
            return {}

    async def _load_known_patterns(self) -> List[Dict[str, Any]]:
        """Load previously detected patterns from DB."""
        if not hasattr(self.memory, "_connection"):
            return []
        try:
            async with self.memory._connection() as conn:
                rows = await conn.fetch("""
                    SELECT pattern_key, title, description
                    FROM seed_improver_patterns
                    ORDER BY detected_at DESC
                    LIMIT 20
                """)
                return [
                    {"key": r["pattern_key"], "title": r["title"], "description": r["description"]}
                    for r in rows
                ]
        except Exception as e:
            logger.debug("Could not load patterns: %s", e)
            return []

    async def _store_recommendations(self, run_id: str, analysis: AnalysisResult) -> None:
        """Store recommendations in the seed_improver_changes table."""
        if not hasattr(self.memory, "_connection") or not analysis.recommendations:
            return
        try:
            async with self.memory._connection() as conn:
                for rec in analysis.recommendations:
                    await conn.execute(
                        """
                        INSERT INTO seed_improver_changes
                            (run_id, change_type, description, details, status)
                        VALUES ($1, $2, $3, $4, 'proposed')
                        """,
                        int(run_id) if run_id.isdigit() else None,
                        rec.category,
                        rec.change_summary,
                        json.dumps(rec.to_dict()),
                    )

                # Update run with recommendation count
                await conn.execute(
                    """
                    UPDATE seed_improver_runs
                    SET recommendations_count = $2
                    WHERE id::text = $1
                    """,
                    run_id,
                    len(analysis.recommendations),
                )
        except Exception as e:
            logger.warning("Failed to store recommendations: %s", e)

    async def _store_patterns(self, patterns: list) -> None:
        """Upsert detected patterns into seed_improver_patterns."""
        if not hasattr(self.memory, "_connection") or not patterns:
            return
        try:
            async with self.memory._connection() as conn:
                for p in patterns:
                    await conn.execute(
                        """
                        INSERT INTO seed_improver_patterns (pattern_key, title, description)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (pattern_key) DO UPDATE
                            SET title = EXCLUDED.title,
                                description = EXCLUDED.description,
                                detected_at = NOW()
                        """,
                        p.key,
                        p.title,
                        p.description,
                    )
        except Exception as e:
            logger.debug("Failed to store patterns: %s", e)

    def _append_analysis_to_log(self, run_id: str, analysis: AnalysisResult) -> None:
        """Append Phase 1 analysis results to the day's markdown log."""
        today = datetime.now(timezone.utc).date().isoformat()
        day_file = self.memory_dir / f"{today}.md"
        try:
            with day_file.open("a", encoding="utf-8") as f:
                f.write(f"\n### Phase 1 Analysis (Run {run_id})\n")
                f.write(f"- Model: {analysis.model_used}\n")
                f.write(f"- Summary: {analysis.summary}\n")
                f.write(f"- Recommendations: {len(analysis.recommendations)}\n")
                for i, rec in enumerate(analysis.recommendations, 1):
                    f.write(
                        f"  {i}. [{rec.priority}] {rec.category}: {rec.change_summary} "
                        f"(confidence={rec.confidence}, risk={rec.risk_assessment})\n"
                    )
                if analysis.patterns_detected:
                    f.write(f"- Patterns detected: {len(analysis.patterns_detected)}\n")
                    for p in analysis.patterns_detected:
                        f.write(f"  - [{p.key}] {p.title}\n")
        except Exception as e:
            logger.debug("Failed to append analysis to log: %s", e)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    async def _notify_run_complete(
        self, run_id: str, trigger_type: str, analysis: Optional[AnalysisResult]
    ) -> None:
        """Send notification about completed run via alert manager."""
        if not self.alert_manager:
            return

        try:
            rec_count = len(analysis.recommendations) if analysis else 0
            top_rec = ""
            if analysis and analysis.recommendations:
                r = analysis.recommendations[0]
                top_rec = f"\nTop: [{r.priority}] {r.change_summary}"

            msg = (
                f"Seed Improver run completed\n"
                f"Trigger: {trigger_type} | Run: {run_id}\n"
                f"Recommendations: {rec_count}{top_rec}"
            )
            await self.alert_manager.system_alert(msg, data={"run_id": run_id, "trigger": trigger_type})
        except Exception as e:
            logger.debug("Failed to send run notification: %s", e)

    # ------------------------------------------------------------------
    # Markdown logging (Phase 0)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # DB lifecycle
    # ------------------------------------------------------------------

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
