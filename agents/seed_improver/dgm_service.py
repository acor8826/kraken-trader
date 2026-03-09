"""
Darwinian Godel Machine (DGM) Service

Top-level orchestrator for the population-based evolutionary config optimization system.
Implements a 4-phase cycle: Evaluate → Select → Mutate → Deploy.

Replaces SeedImproverService.run() when dgm.enabled=true.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .fitness import FitnessEvaluator
from .judge import VariantJudge
from .population import PopulationArchive
from .selection import ParentSelector

logger = logging.getLogger(__name__)


class DGMService:
    """Orchestrates the Darwinian Godel Machine evolutionary cycle.

    Each cycle runs 4 phases:
      A. EVALUATE: Judge the active variant against its parent
      B. SELECT:   Pick a parent from the full archive (fitness-proportional)
      C. MUTATE:   Run seed improver analysis against the parent config
      D. DEPLOY:   Deploy the new variant and start evaluation window
    """

    def __init__(
        self,
        db_pool,
        seed_improver_service,
        deployer,
        dgm_config: Dict[str, Any],
    ):
        self.pool = db_pool
        self.seed_improver = seed_improver_service
        self.deployer = deployer
        self.config = dgm_config

        # Initialize components
        self.population = PopulationArchive(db_pool)
        self.fitness = FitnessEvaluator(db_pool)
        self.selector = ParentSelector(
            self.population,
            temperature=dgm_config.get('selection_temperature', 1.0),
            diversity_weight=dgm_config.get('diversity_weight', 0.1),
        )
        self.judge = VariantJudge(
            db_pool,
            self.fitness,
            self.population,
            rollback_tolerance=dgm_config.get('rollback_tolerance', 0.05),
            min_trades=dgm_config.get('min_trades_for_eval', 3),
            max_evaluation_hours=dgm_config.get('max_evaluation_hours', 72),
        )

        self.evaluation_window_hours = dgm_config.get('evaluation_window_hours', 24)
        self.archive_max_size = dgm_config.get('archive_max_size', 50)

    async def run_cycle(self) -> Dict[str, Any]:
        """Execute one full DGM evolutionary cycle.

        Returns a summary dict with results from each phase.
        """
        result = {
            'cycle_start': datetime.now(timezone.utc).isoformat(),
            'phases': {},
        }

        try:
            # ── PHASE A: EVALUATE ──────────────────────────────────
            logger.info("DGM Cycle: Phase A - Evaluate active variant")
            eval_result = await self._phase_a_evaluate()
            result['phases']['evaluate'] = eval_result

            if eval_result and eval_result.get('status') in ('waiting', 'extend'):
                # Active variant still being evaluated — skip rest of cycle
                logger.info("DGM Cycle: Active variant still under evaluation, skipping mutation")
                result['outcome'] = 'waiting_for_evaluation'
                return result

            # If rollback verdict, deploy parent config
            if eval_result and eval_result.get('verdict') == 'rollback':
                await self._deploy_parent_rollback(eval_result)

            # ── PHASE B: SELECT PARENT ─────────────────────────────
            logger.info("DGM Cycle: Phase B - Select parent")
            parent = await self._phase_b_select()
            result['phases']['select'] = {
                'parent_id': parent['id'] if parent else None,
                'parent_generation': parent.get('generation') if parent else None,
                'parent_fitness': float(parent.get('fitness_score', 0)) if parent else None,
            }

            if parent is None:
                result['outcome'] = 'bootstrap_failed'
                return result

            # ── PHASE C: MUTATE ────────────────────────────────────
            logger.info("DGM Cycle: Phase C - Mutate from parent %d", parent['id'])
            mutation_result = await self._phase_c_mutate(parent)
            result['phases']['mutate'] = mutation_result

            if mutation_result.get('status') == 'failed':
                result['outcome'] = 'mutation_failed'
                return result

            variant_id = mutation_result.get('variant_id')
            new_config_yaml = mutation_result.get('new_config_yaml')

            if not variant_id or not new_config_yaml:
                result['outcome'] = 'no_patches'
                return result

            # ── PHASE D: DEPLOY ────────────────────────────────────
            logger.info("DGM Cycle: Phase D - Deploy variant %d", variant_id)
            deploy_result = await self._phase_d_deploy(variant_id, new_config_yaml, parent)
            result['phases']['deploy'] = deploy_result

            if deploy_result.get('status') == 'deployed':
                # Prune archive if needed
                await self._prune_if_needed()
                result['outcome'] = 'variant_deployed'
            else:
                result['outcome'] = 'deploy_failed'

        except Exception as e:
            logger.exception("DGM Cycle failed: %s", e)
            result['outcome'] = 'error'
            result['error'] = str(e)
            result['traceback'] = traceback.format_exc()

        result['cycle_end'] = datetime.now(timezone.utc).isoformat()
        return result

    # ── Phase implementations ──────────────────────────────────────

    async def _phase_a_evaluate(self) -> Optional[Dict[str, Any]]:
        """Phase A: Evaluate the currently active variant."""
        try:
            return await self.judge.evaluate_active_variant()
        except Exception as e:
            logger.error("Phase A failed: %s", e)
            return {'status': 'error', 'error': str(e)}

    async def _phase_b_select(self) -> Optional[Dict[str, Any]]:
        """Phase B: Select a parent from the archive, bootstrapping if needed."""
        parent = await self.selector.select_parent()

        if parent is None:
            # First run — bootstrap from current config
            logger.info("No evaluated variants, bootstrapping root variant")
            parent = await self._bootstrap_root()

        return parent

    async def _phase_c_mutate(self, parent: Dict[str, Any]) -> Dict[str, Any]:
        """Phase C: Run seed improver mutation against parent config."""
        try:
            # Get context for enriched LLM prompt
            failed_siblings = await self.population.get_failed_siblings(parent.get('id'))
            lineage = await self.population.get_lineage(parent['id'])

            # Run seed improver analysis against parent config
            mutation = await self.seed_improver.run_for_variant(
                parent_variant=parent,
                lineage_context=lineage,
                failed_siblings=failed_siblings,
            )

            if not mutation or not mutation.get('patches'):
                logger.info("Phase C: No patches generated for parent %d", parent['id'])
                return {'status': 'no_patches', 'parent_id': parent['id']}

            # Build new config from parent + patches
            parent_config = yaml.safe_load(parent['config_yaml'])
            new_config = dict(parent_config)

            from .auto_apply import _set_nested, _coerce_type
            for patch in mutation['patches']:
                keys = patch.yaml_path.split(".")
                ref = parent_config
                for k in keys:
                    if isinstance(ref, dict):
                        ref = ref.get(k, ref)
                new_value = _coerce_type(patch.new_value, ref)
                _set_nested(new_config, patch.yaml_path, new_value)

            new_config_yaml = yaml.dump(new_config, default_flow_style=False, sort_keys=False)

            # Create variant record
            patches_data = [
                {'yaml_path': p.yaml_path, 'old_value': str(p.old_value),
                 'new_value': str(p.new_value), 'reasoning': p.reasoning}
                for p in mutation['patches']
            ]

            mutation_desc = "; ".join(
                f"{p.yaml_path}: {p.old_value} → {p.new_value}"
                for p in mutation['patches']
            )

            variant_id = await self.population.create_variant(
                parent_id=parent['id'],
                config_yaml=new_config_yaml,
                mutation_description=mutation_desc,
                patches_applied=patches_data,
                generation=parent.get('generation', 0) + 1,
                lineage_depth=parent.get('lineage_depth', 0) + 1,
                branch_reason='dgm_mutation',
            )

            return {
                'status': 'created',
                'variant_id': variant_id,
                'parent_id': parent['id'],
                'patches_count': len(mutation['patches']),
                'mutation_description': mutation_desc,
                'new_config_yaml': new_config_yaml,
            }

        except Exception as e:
            logger.error("Phase C failed: %s", e)
            return {'status': 'failed', 'error': str(e)}

    async def _phase_d_deploy(
        self, variant_id: int, new_config_yaml: str, parent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Phase D: Deploy the new variant."""
        try:
            parent_config_yaml = parent.get('config_yaml', '')

            # Deploy via GCS + Cloud Run
            deploy_result = await self.deployer.deploy(new_config_yaml, parent_config_yaml)

            if deploy_result.status == 'deployed':
                now = datetime.now(timezone.utc)
                eval_end = now + timedelta(hours=self.evaluation_window_hours)

                # Update variant status to active
                await self.population.update_status(
                    variant_id, 'active',
                    deployed_at=now,
                    evaluation_start=now,
                    evaluation_end=eval_end,
                    deploy_revision_id=deploy_result.revision_id,
                )

                # Also set DGM_VARIANT_ID env var on Cloud Run
                try:
                    from datetime import timezone as tz
                    config_version = now.strftime("%Y%m%d%H%M%S")
                    await self.deployer._update_cloud_run_env(
                        config_version, dgm_variant_id=variant_id
                    )
                except Exception as e:
                    logger.warning("Failed to set DGM_VARIANT_ID env var: %s", e)

                logger.info("Variant %d deployed, evaluation window: %s to %s",
                            variant_id, now.isoformat(), eval_end.isoformat())

                return {
                    'status': 'deployed',
                    'variant_id': variant_id,
                    'revision_id': deploy_result.revision_id,
                    'evaluation_start': now.isoformat(),
                    'evaluation_end': eval_end.isoformat(),
                }
            else:
                # Deploy failed
                await self.population.update_status(variant_id, 'failed')
                logger.warning("Variant %d deploy failed: %s", variant_id, deploy_result.error)
                return {
                    'status': 'failed',
                    'variant_id': variant_id,
                    'error': deploy_result.error,
                    'rolled_back': deploy_result.rolled_back,
                }

        except Exception as e:
            logger.error("Phase D failed: %s", e)
            await self.population.update_status(variant_id, 'failed')
            return {'status': 'failed', 'error': str(e)}

    # ── Helper methods ─────────────────────────────────────────────

    async def _bootstrap_root(self) -> Optional[Dict[str, Any]]:
        """Create root variant from current config file."""
        # Try to read current config
        config_path = self.seed_improver.repo_root / "config" / "stage2.yaml"
        if not config_path.exists():
            config_path = self.seed_improver.repo_root / "config" / "stage3.yaml"

        if not config_path.exists():
            logger.error("Cannot bootstrap: no config file found")
            return None

        config_yaml = config_path.read_text(encoding='utf-8')
        root_id = await self.population.snapshot_config_as_root(config_yaml)
        root = await self.population.get_variant(root_id)
        logger.info("Bootstrapped root variant %d from %s", root_id, config_path)
        return root

    async def _deploy_parent_rollback(self, eval_result: Dict[str, Any]) -> None:
        """Deploy the parent config after a rollback verdict."""
        variant_id = eval_result.get('variant_id')
        if not variant_id:
            return

        variant = await self.population.get_variant(variant_id)
        if not variant or not variant.get('parent_id'):
            return

        parent = await self.population.get_variant(variant['parent_id'])
        if not parent:
            return

        try:
            logger.info("Rolling back to parent variant %d config", parent['id'])
            await self.deployer.deploy(parent['config_yaml'], variant.get('config_yaml', ''))
        except Exception as e:
            logger.error("Failed to deploy parent rollback: %s", e)

    async def _prune_if_needed(self) -> None:
        """Prune archive if over max size."""
        try:
            # Find best variant for protection
            evaluated = await self.population.get_evaluated_variants()
            best_id = evaluated[0]['id'] if evaluated else None
            pruned = await self.population.prune_archive(self.archive_max_size, best_id)
            if pruned:
                logger.info("Pruned %d variants from archive", pruned)
        except Exception as e:
            logger.warning("Archive pruning failed: %s", e)

    async def get_status(self) -> Dict[str, Any]:
        """Get current DGM system status."""
        active = await self.population.get_active_variant()
        archive_size = await self.population.get_archive_size()

        # Get last evaluation
        last_eval = None
        try:
            row = await self.pool.fetchrow(
                "SELECT * FROM dgm_evaluation_log ORDER BY created_at DESC LIMIT 1"
            )
            if row:
                last_eval = dict(row)
        except Exception:
            pass

        return {
            'enabled': True,
            'active_variant': active,
            'archive_size': archive_size,
            'last_evaluation': last_eval,
            'config': {
                'evaluation_window_hours': self.evaluation_window_hours,
                'archive_max_size': self.archive_max_size,
                'selection_temperature': self.selector.temperature,
                'diversity_weight': self.selector.diversity_weight,
                'rollback_tolerance': self.judge.rollback_tolerance,
            },
        }
