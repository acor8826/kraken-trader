import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class VariantJudge:
    """Evaluate active variants and decide: keep, rollback, or extend.

    Compares variant fitness against parent fitness with configurable tolerance.
    """

    def __init__(self, db_pool, fitness_evaluator, population,
                 rollback_tolerance=0.05, min_trades=3, max_evaluation_hours=72):
        self.pool = db_pool
        self.fitness = fitness_evaluator
        self.population = population
        self.rollback_tolerance = rollback_tolerance
        self.min_trades = min_trades
        self.max_evaluation_hours = max_evaluation_hours

    async def evaluate_active_variant(self):
        """Evaluate the currently active variant. Returns verdict dict or None."""
        active = await self.population.get_active_variant()
        if not active:
            logger.info("No active variant to evaluate")
            return None

        variant_id = active['id']
        now = datetime.now(timezone.utc)
        eval_start = active.get('evaluation_start')
        eval_end = active.get('evaluation_end')

        if not eval_start or not eval_end:
            logger.warning(f"Variant {variant_id} has no evaluation window set")
            return None

        # Check if evaluation window is complete
        window_complete = now >= eval_end

        if not window_complete:
            # Check trade count so far
            trade_count = await self._count_trades(variant_id, eval_start)
            logger.info(f"Variant {variant_id}: window not complete, {trade_count} trades so far")
            return {
                'status': 'waiting',
                'variant_id': variant_id,
                'trades_so_far': trade_count,
                'window_ends': eval_end.isoformat(),
                'hours_remaining': (eval_end - now).total_seconds() / 3600,
            }

        # Window complete - compute fitness
        fitness_result = await self.fitness.evaluate(
            variant_id, eval_start, eval_end, min_trades=self.min_trades
        )

        if fitness_result is None:
            # Not enough trades - extend or fail
            total_hours = (now - eval_start).total_seconds() / 3600
            if total_hours < self.max_evaluation_hours:
                # Extend window by 12 hours
                new_end = eval_end + timedelta(hours=12)
                await self.population.update_status(
                    variant_id, 'active', evaluation_end=new_end
                )
                verdict = 'extend'
                reasoning = (f"Only {await self._count_trades(variant_id, eval_start)} trades "
                             f"in {total_hours:.1f}h. Extending window to {new_end.isoformat()}")
                await self._log_verdict(variant_id, active.get('parent_id'),
                                        verdict, reasoning, None, None, 'extended_window')
                logger.info(f"Variant {variant_id}: {reasoning}")
                return {
                    'status': 'extend',
                    'variant_id': variant_id,
                    'verdict': verdict,
                    'reasoning': reasoning,
                    'new_window_end': new_end.isoformat(),
                }
            else:
                # Max evaluation time exceeded - mark failed
                await self.population.update_status(variant_id, 'failed')
                verdict = 'rollback'
                reasoning = (f"Insufficient trades after {total_hours:.1f}h "
                             f"(max {self.max_evaluation_hours}h). Marking failed.")
                await self._log_verdict(variant_id, active.get('parent_id'),
                                        verdict, reasoning, None, None, 'marked_failed')
                logger.warning(f"Variant {variant_id}: {reasoning}")
                return {
                    'status': 'failed',
                    'variant_id': variant_id,
                    'verdict': verdict,
                    'reasoning': reasoning,
                }

        # We have fitness - compare against parent
        variant_fitness = float(fitness_result['fitness_score'])
        parent_id = active.get('parent_id')
        parent_fitness = await self._get_parent_fitness(parent_id)

        # Determine verdict
        if parent_fitness is None:
            # Root variant or parent has no fitness - always keep
            verdict = 'keep'
            reasoning = (f"No parent fitness to compare against. "
                         f"Variant fitness={variant_fitness:.6f}. Keeping.")
            fitness_delta = None
        else:
            fitness_delta = variant_fitness - parent_fitness

            # Simple comparison: did the variant make at least as much as
            # the parent (minus a small absolute tolerance)?
            # rollback_tolerance is treated as a fraction of |parent_fitness|
            # to allow for noise, but floored at 0 so negative parents
            # don't invert the threshold.
            tolerance_abs = max(abs(parent_fitness) * self.rollback_tolerance, 0)
            threshold = parent_fitness - tolerance_abs

            if variant_fitness >= threshold:
                verdict = 'keep'
                reasoning = (f"Variant PnL {variant_fitness:.4f} >= "
                             f"threshold {threshold:.4f} "
                             f"(parent {parent_fitness:.4f} - tolerance {tolerance_abs:.4f}). "
                             f"Delta: {fitness_delta:+.4f}")
            else:
                verdict = 'rollback'
                reasoning = (f"Variant PnL {variant_fitness:.4f} < "
                             f"threshold {threshold:.4f} "
                             f"(parent {parent_fitness:.4f} - tolerance {tolerance_abs:.4f}). "
                             f"Delta: {fitness_delta:+.4f}. Rolling back.")

        # Execute verdict
        if verdict == 'keep':
            await self.population.update_status(variant_id, 'evaluated')
            action = 'marked_evaluated'
        else:  # rollback
            await self.population.update_status(variant_id, 'rolled_back')
            action = 'rolled_back'
            # Note: actual config rollback (deploying parent) handled by DGMService

        await self._log_verdict(
            variant_id, parent_id, verdict, reasoning,
            variant_fitness, parent_fitness, action
        )

        logger.info(f"Variant {variant_id} verdict: {verdict} - {reasoning}")

        return {
            'status': verdict,
            'variant_id': variant_id,
            'verdict': verdict,
            'reasoning': reasoning,
            'variant_fitness': variant_fitness,
            'parent_fitness': parent_fitness,
            'fitness_delta': float(fitness_delta) if fitness_delta is not None else None,
            'action_taken': action,
        }

    async def _count_trades(self, variant_id, since):
        """Count trades for a variant since a given time."""
        row = await self.pool.fetchrow(
            """SELECT COUNT(*) as cnt FROM trades
               WHERE dgm_variant_id = $1 AND created_at >= $2 AND status = 'filled'""",
            variant_id, since
        )
        return row['cnt'] if row else 0

    async def _get_parent_fitness(self, parent_id):
        """Get latest fitness score for parent variant."""
        if parent_id is None:
            return None
        row = await self.pool.fetchrow(
            """SELECT fitness_score FROM dgm_fitness_scores
               WHERE variant_id = $1 ORDER BY computed_at DESC LIMIT 1""",
            parent_id
        )
        return float(row['fitness_score']) if row else None

    async def _log_verdict(self, variant_id, parent_id, verdict, reasoning,
                           variant_fitness, parent_fitness, action_taken):
        """Insert verdict into dgm_evaluation_log."""
        fitness_delta = None
        if variant_fitness is not None and parent_fitness is not None:
            fitness_delta = variant_fitness - parent_fitness

        await self.pool.execute(
            """INSERT INTO dgm_evaluation_log
               (variant_id, parent_variant_id, verdict, judge_reasoning,
                variant_fitness, parent_fitness, fitness_delta, action_taken)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            variant_id, parent_id, verdict, reasoning,
            variant_fitness, parent_fitness, fitness_delta, action_taken
        )
