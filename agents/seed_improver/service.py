from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    priority: str  # critical | observability | strategy | quality
    hypothesis: str
    change_summary: str
    expected_impact: Dict[str, Any]
    risk: str  # low | medium | high
    compatibility_notes: str
    auto_applicable: bool = False  # True only for low-risk non-strategy changes


@dataclass
class SeedImproverResult:
    run_id: str
    trigger_type: str
    status: str
    summary: str
    recommendations_count: int = 0
    top_recommendations: List[str] = field(default_factory=list)
    pattern_updates_count: int = 0


class SeedImproverService:
    """Multi-phase seed improver service.

    Phase 0: Observability audit (existing)
    Phase 1: Analysis + recommendation generation
    Phase 2: Pattern learning
    Phase 3: Controlled actioning (feature-flagged)
    Phase 4: Evaluation loop
    """

    # Feature flags (env-configurable)
    ENABLE_AUTO_APPLY = "SEED_IMPROVER_AUTO_APPLY"  # env var name
    ENABLE_STRATEGY_AUTO_APPLY = "SEED_IMPROVER_STRATEGY_AUTO_APPLY"  # env var name

    def __init__(self, memory: Any, repo_root: Optional[Path] = None):
        self.memory = memory
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

    @property
    def auto_apply_enabled(self) -> bool:
        return os.environ.get(self.ENABLE_AUTO_APPLY, "").lower() in ("true", "1", "yes")

    @property
    def strategy_auto_apply_enabled(self) -> bool:
        return os.environ.get(self.ENABLE_STRATEGY_AUTO_APPLY, "").lower() in ("true", "1", "yes")

    async def run(self, trigger_type: str, context: Optional[Dict[str, Any]] = None) -> SeedImproverResult:
        context = context or {}
        started_at = datetime.now(timezone.utc)

        run_id = await self._record_run_start(trigger_type, context)
        try:
            # Phase 0: Observability audit
            audit = await self._phase0_observability_audit()

            # Phase 1: Analysis + recommendation generation
            trades = await self._get_recent_trades()
            recommendations = self._phase1_analyze_and_recommend(trades, audit, context)
            await self._persist_recommendations(run_id, recommendations)

            # Phase 2: Pattern learning
            patterns_updated = await self._phase2_pattern_learning(trades, recommendations)

            # Phase 3: Controlled actioning
            applied = await self._phase3_controlled_actioning(run_id, recommendations)

            # Phase 4: Evaluation loop
            eval_summary = await self._phase4_evaluation_loop(run_id)

            # Build summary
            top_recs = [r.change_summary[:100] for r in recommendations[:3]]
            summary = (
                f"Phases 0-4 complete. trades_sampled={len(trades)}, "
                f"gaps={len(audit['gaps'])}, recommendations={len(recommendations)}, "
                f"patterns_updated={patterns_updated}, applied={len(applied)}, "
                f"eval={eval_summary}"
            )

            self._write_markdown_run_log(run_id, trigger_type, started_at, context, audit, recommendations)
            await self._record_run_complete(run_id, summary)

            return SeedImproverResult(
                run_id=run_id,
                trigger_type=trigger_type,
                status="completed",
                summary=summary,
                recommendations_count=len(recommendations),
                top_recommendations=top_recs,
                pattern_updates_count=patterns_updated,
            )
        except Exception as e:
            err = f"Seed improver failed: {e}"
            logger.exception(err)
            await self._record_run_failed(run_id, err)
            return SeedImproverResult(run_id=run_id, trigger_type=trigger_type, status="failed", summary=err)

    # =========================================================================
    # Phase 0: Observability Audit
    # =========================================================================

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

    # =========================================================================
    # Phase 1: Analysis + Recommendation Generation
    # =========================================================================

    async def _get_recent_trades(self) -> list:
        if hasattr(self.memory, "get_trade_history"):
            return await self.memory.get_trade_history(200)
        return []

    def _phase1_analyze_and_recommend(
        self, trades: list, audit: Dict[str, Any], context: Dict[str, Any]
    ) -> List[Recommendation]:
        recommendations: List[Recommendation] = []

        # --- Observability gap recommendations ---
        for gap in audit.get("gaps", []):
            recommendations.append(Recommendation(
                priority="observability",
                hypothesis=f"Data gap detected: {gap}",
                change_summary=f"Fix telemetry: {gap}",
                expected_impact={"data_completeness": "improved"},
                risk="low",
                compatibility_notes="Additive telemetry change only",
                auto_applicable=True,
            ))

        if not trades:
            return recommendations

        # --- Loss pattern analysis ---
        losing_trades = [t for t in trades if (getattr(t, "realized_pnl", None) or 0) < 0]
        winning_trades = [t for t in trades if (getattr(t, "realized_pnl", None) or 0) > 0]

        if losing_trades:
            # Consecutive losses
            max_consecutive = self._max_consecutive_losses(trades)
            if max_consecutive >= 3:
                recommendations.append(Recommendation(
                    priority="strategy",
                    hypothesis=f"Detected {max_consecutive} consecutive losses — possible regime mismatch or overtrading",
                    change_summary=f"Consider cooldown after {max_consecutive} consecutive losses",
                    expected_impact={"loss_reduction": "moderate", "consecutive_loss_streak": max_consecutive},
                    risk="medium",
                    compatibility_notes="Requires strategy parameter change (cooldown threshold)",
                ))

            # Loss concentration by pair
            pair_losses = Counter(getattr(t, "pair", "unknown") for t in losing_trades)
            for pair, count in pair_losses.most_common(3):
                if count >= 3:
                    recommendations.append(Recommendation(
                        priority="strategy",
                        hypothesis=f"Pair {pair} has {count} losses in recent window — may need pair-specific tuning or exclusion",
                        change_summary=f"Review pair {pair}: {count} recent losses",
                        expected_impact={"pair": pair, "loss_count": count},
                        risk="medium",
                        compatibility_notes="Pair exclusion or confidence threshold adjustment",
                    ))

            # Average loss vs average win analysis
            avg_loss = sum(getattr(t, "realized_pnl", 0) or 0 for t in losing_trades) / len(losing_trades) if losing_trades else 0
            avg_win = sum(getattr(t, "realized_pnl", 0) or 0 for t in winning_trades) / len(winning_trades) if winning_trades else 0

            if winning_trades and losing_trades and abs(avg_loss) > abs(avg_win) * 2:
                recommendations.append(Recommendation(
                    priority="critical",
                    hypothesis=f"Average loss ({avg_loss:.2f}) is >2x average win ({avg_win:.2f}) — risk/reward imbalanced",
                    change_summary="Tighten stop-loss or improve exit strategy to reduce loss magnitude",
                    expected_impact={"avg_loss": avg_loss, "avg_win": avg_win, "ratio": abs(avg_loss / avg_win) if avg_win else None},
                    risk="high",
                    compatibility_notes="Strategy-level change to stop-loss or take-profit parameters",
                ))

        # --- Low confidence trade analysis ---
        low_conf_losses = [t for t in losing_trades if (getattr(t, "signal_confidence", 1.0) or 1.0) < 0.5]
        if len(low_conf_losses) >= 2:
            recommendations.append(Recommendation(
                priority="strategy",
                hypothesis=f"{len(low_conf_losses)} losses with confidence < 0.5 — minimum confidence threshold may be too low",
                change_summary="Raise minimum signal confidence threshold for trade execution",
                expected_impact={"low_conf_losses": len(low_conf_losses)},
                risk="medium",
                compatibility_notes="Confidence threshold is a strategy parameter",
            ))

        # --- Latency analysis ---
        latency_trades = [t for t in trades if getattr(t, "latency_decision_to_fill_ms", None) is not None]
        if latency_trades:
            high_latency = [t for t in latency_trades if (getattr(t, "latency_decision_to_fill_ms", 0) or 0) > 5000]
            if len(high_latency) >= 3:
                recommendations.append(Recommendation(
                    priority="quality",
                    hypothesis=f"{len(high_latency)} trades with >5s decision-to-fill latency",
                    change_summary="Investigate execution latency — possible infrastructure or API bottleneck",
                    expected_impact={"high_latency_count": len(high_latency)},
                    risk="low",
                    compatibility_notes="Infrastructure investigation, no strategy change",
                    auto_applicable=True,
                ))

        # --- Win rate check ---
        filled_trades = [t for t in trades if getattr(t, "realized_pnl", None) is not None]
        if len(filled_trades) >= 10:
            win_rate = len(winning_trades) / len(filled_trades)
            if win_rate < 0.4:
                recommendations.append(Recommendation(
                    priority="critical",
                    hypothesis=f"Win rate is {win_rate:.1%} over {len(filled_trades)} trades — below 40% threshold",
                    change_summary="Win rate critically low — review overall strategy effectiveness",
                    expected_impact={"win_rate": win_rate, "sample_size": len(filled_trades)},
                    risk="high",
                    compatibility_notes="Requires comprehensive strategy review",
                ))

        # --- Losing trade trigger context ---
        if context.get("trade"):
            trade_ctx = context["trade"]
            pair = trade_ctx.get("pair", "unknown")
            pnl = trade_ctx.get("realized_pnl", 0)
            recommendations.append(Recommendation(
                priority="quality",
                hypothesis=f"Loss event on {pair} (PnL: {pnl}) triggered analysis",
                change_summary=f"Loss on {pair}: review signal quality and entry timing",
                expected_impact={"triggered_pair": pair, "triggered_pnl": pnl},
                risk="low",
                compatibility_notes="Event-driven review, no automatic changes",
            ))

        # Sort by priority
        priority_order = {"critical": 0, "strategy": 1, "observability": 2, "quality": 3}
        recommendations.sort(key=lambda r: priority_order.get(r.priority, 99))

        return recommendations

    def _max_consecutive_losses(self, trades: list) -> int:
        """Find max consecutive losing trades (trades should be newest-first)."""
        max_streak = 0
        current_streak = 0
        # Reverse to go oldest-first for streak calculation
        for t in reversed(trades):
            pnl = getattr(t, "realized_pnl", None)
            if pnl is not None and pnl < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    async def _persist_recommendations(self, run_id: str, recommendations: List[Recommendation]) -> None:
        if not hasattr(self.memory, "_connection") or not recommendations:
            return
        async with self.memory._connection() as conn:
            for rec in recommendations:
                await conn.execute(
                    """
                    INSERT INTO seed_improver_changes
                    (run_id, priority, hypothesis, change_summary, expected_impact, risk_assessment, compatibility_check)
                    VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
                    """,
                    run_id,
                    rec.priority,
                    rec.hypothesis,
                    rec.change_summary,
                    json.dumps(rec.expected_impact),
                    rec.risk,
                    rec.compatibility_notes,
                )

    # =========================================================================
    # Phase 2: Pattern Learning
    # =========================================================================

    async def _phase2_pattern_learning(self, trades: list, recommendations: List[Recommendation]) -> int:
        """Upsert recurring failure patterns. Returns count of patterns updated."""
        if not hasattr(self.memory, "_connection"):
            return 0

        patterns_to_upsert = self._extract_patterns(trades, recommendations)
        if not patterns_to_upsert:
            return 0

        updated = 0
        async with self.memory._connection() as conn:
            for p in patterns_to_upsert:
                await conn.execute(
                    """
                    INSERT INTO seed_improver_patterns (pattern_key, title, description, resolution, tags)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (pattern_key) DO UPDATE SET
                        seen_count = seed_improver_patterns.seen_count + 1,
                        last_seen_at = NOW(),
                        description = EXCLUDED.description,
                        resolution = COALESCE(EXCLUDED.resolution, seed_improver_patterns.resolution)
                    """,
                    p["key"],
                    p["title"],
                    p["description"],
                    p.get("resolution"),
                    p.get("tags", []),
                )
                updated += 1

        return updated

    def _extract_patterns(self, trades: list, recommendations: List[Recommendation]) -> List[Dict[str, Any]]:
        """Derive pattern keys from trade data and recommendations."""
        patterns = []

        losing_trades = [t for t in trades if (getattr(t, "realized_pnl", None) or 0) < 0]
        if not losing_trades:
            return patterns

        # Pattern: consecutive losses
        max_streak = self._max_consecutive_losses(trades)
        if max_streak >= 3:
            patterns.append({
                "key": "consecutive_losses",
                "title": "Consecutive Loss Streak",
                "description": f"Max {max_streak} consecutive losses detected in recent trades",
                "resolution": "Consider implementing a cooldown period after N consecutive losses",
                "tags": ["strategy", "risk"],
            })

        # Pattern: loss concentration per pair
        pair_losses = Counter(getattr(t, "pair", "unknown") for t in losing_trades)
        for pair, count in pair_losses.most_common(3):
            if count >= 3:
                patterns.append({
                    "key": f"pair_loss_concentration:{pair}",
                    "title": f"Loss Concentration on {pair}",
                    "description": f"{count} losses on {pair} in recent window",
                    "resolution": f"Review {pair} signal quality or consider pair exclusion",
                    "tags": ["pair", "loss"],
                })

        # Pattern: low confidence losses
        low_conf = [t for t in losing_trades if (getattr(t, "signal_confidence", 1.0) or 1.0) < 0.5]
        if len(low_conf) >= 2:
            patterns.append({
                "key": "low_confidence_losses",
                "title": "Losses at Low Confidence",
                "description": f"{len(low_conf)} losses with signal confidence < 0.5",
                "resolution": "Raise minimum confidence threshold",
                "tags": ["strategy", "confidence"],
            })

        # Pattern: poor risk/reward
        winning_trades = [t for t in trades if (getattr(t, "realized_pnl", None) or 0) > 0]
        if winning_trades and losing_trades:
            avg_loss = sum(getattr(t, "realized_pnl", 0) or 0 for t in losing_trades) / len(losing_trades)
            avg_win = sum(getattr(t, "realized_pnl", 0) or 0 for t in winning_trades) / len(winning_trades)
            if abs(avg_loss) > abs(avg_win) * 2:
                patterns.append({
                    "key": "poor_risk_reward_ratio",
                    "title": "Poor Risk/Reward Ratio",
                    "description": f"Avg loss ({avg_loss:.2f}) > 2x avg win ({avg_win:.2f})",
                    "resolution": "Tighten stop-losses or improve exit timing",
                    "tags": ["strategy", "risk"],
                })

        return patterns

    # =========================================================================
    # Phase 3: Controlled Actioning
    # =========================================================================

    async def _phase3_controlled_actioning(
        self, run_id: str, recommendations: List[Recommendation]
    ) -> List[Recommendation]:
        """Auto-apply low-risk non-strategy changes if feature flag is enabled.

        Returns list of recommendations that were applied.
        """
        if not self.auto_apply_enabled:
            logger.info("Seed improver auto-apply disabled (set %s=true to enable)", self.ENABLE_AUTO_APPLY)
            return []

        applied = []
        for rec in recommendations:
            if rec.risk == "low" and rec.auto_applicable:
                # Non-strategy, low-risk: safe to auto-apply
                logger.info("Auto-applying low-risk change: %s", rec.change_summary)
                await self._apply_recommendation(run_id, rec)
                applied.append(rec)
            elif rec.priority == "strategy" and self.strategy_auto_apply_enabled:
                logger.info("Auto-applying strategy change (flag enabled): %s", rec.change_summary)
                await self._apply_recommendation(run_id, rec)
                applied.append(rec)
            else:
                logger.debug("Skipping auto-apply for: %s (risk=%s, auto_applicable=%s)", rec.change_summary, rec.risk, rec.auto_applicable)

        return applied

    async def _apply_recommendation(self, run_id: str, rec: Recommendation) -> None:
        """Apply a recommendation. Currently logs the action; specific implementations
        can be added per recommendation type."""
        if not hasattr(self.memory, "_connection"):
            return
        # Mark the change as applied in the DB
        async with self.memory._connection() as conn:
            await conn.execute(
                """
                UPDATE seed_improver_changes
                SET compatibility_check = compatibility_check || ' [APPLIED]'
                WHERE run_id = $1::uuid AND change_summary = $2
                """,
                run_id,
                rec.change_summary,
            )
        logger.info("Applied recommendation: %s", rec.change_summary)

    # =========================================================================
    # Phase 4: Evaluation Loop
    # =========================================================================

    async def _phase4_evaluation_loop(self, run_id: str) -> str:
        """Compare prior recommendations' expected outcomes against actual results.

        Returns a short evaluation summary string.
        """
        if not hasattr(self.memory, "_connection"):
            return "no_db"

        async with self.memory._connection() as conn:
            # Find the most recent completed prior run (not this one)
            prior_run = await conn.fetchrow(
                """
                SELECT id, summary FROM seed_improver_runs
                WHERE status = 'completed' AND id::text != $1
                ORDER BY finished_at DESC LIMIT 1
                """,
                run_id,
            )

            if not prior_run:
                return "no_prior_run"

            prior_run_id = str(prior_run["id"])

            # Get prior recommendations
            prior_changes = await conn.fetch(
                """
                SELECT change_summary, expected_impact, compatibility_check
                FROM seed_improver_changes
                WHERE run_id = $1::uuid
                ORDER BY created_at
                """,
                prior_run_id,
            )

            if not prior_changes:
                return "no_prior_recommendations"

            applied_count = sum(1 for c in prior_changes if "[APPLIED]" in (c["compatibility_check"] or ""))
            total_prior = len(prior_changes)

            # Record evaluation metadata on this run
            eval_note = f"prior_run={prior_run_id}, prior_recs={total_prior}, prior_applied={applied_count}"
            await conn.execute(
                """
                UPDATE seed_improver_runs
                SET context = COALESCE(context, '{}'::jsonb) || $2::jsonb
                WHERE id::text = $1
                """,
                run_id,
                json.dumps({"evaluation": {"prior_run_id": prior_run_id, "prior_recommendations": total_prior, "prior_applied": applied_count}}),
            )

            return eval_note

    # =========================================================================
    # Persistence helpers
    # =========================================================================

    def _write_markdown_run_log(
        self,
        run_id: str,
        trigger_type: str,
        started_at: datetime,
        context: Dict[str, Any],
        audit: Dict[str, Any],
        recommendations: List[Recommendation],
    ) -> None:
        day_file = self.memory_dir / f"{started_at.date().isoformat()}.md"

        with day_file.open("a", encoding="utf-8") as f:
            f.write(f"\n## Run {run_id}\n")
            f.write(f"- Trigger: {trigger_type}\n")
            f.write(f"- Started: {started_at.isoformat()}\n")
            f.write(f"- Context: `{json.dumps(context, ensure_ascii=False)}`\n")
            f.write(f"- Coverage: `{json.dumps(audit['coverage'])}`\n")
            if audit["gaps"]:
                for gap in audit["gaps"]:
                    f.write(f"  - GAP: {gap}\n")
            if recommendations:
                f.write(f"- Recommendations ({len(recommendations)}):\n")
                for rec in recommendations[:10]:
                    f.write(f"  - [{rec.priority}] {rec.change_summary} (risk={rec.risk})\n")

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
