import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PopulationArchive:
    """CRUD operations for the DGM variant population archive."""

    def __init__(self, db_pool):
        self.pool = db_pool

    async def create_variant(self, parent_id, config_yaml, mutation_description=None,
                             patches_applied=None, generation=0, lineage_depth=0,
                             branch_reason=None):
        """Insert new variant, return its id."""
        config_hash = hashlib.sha256(config_yaml.encode()).hexdigest()
        row = await self.pool.fetchrow(
            """INSERT INTO dgm_variants
               (parent_id, generation, config_yaml, config_hash, mutation_description,
                patches_applied, lineage_depth, branch_reason)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING id""",
            parent_id, generation, config_yaml, config_hash,
            mutation_description, json.dumps(patches_applied) if patches_applied else None,
            lineage_depth, branch_reason
        )
        logger.info(f"Created variant {row['id']} (gen={generation}, parent={parent_id})")
        return row['id']

    async def get_variant(self, variant_id):
        """Get single variant by id."""
        row = await self.pool.fetchrow(
            "SELECT * FROM dgm_variants WHERE id = $1", variant_id
        )
        return dict(row) if row else None

    async def get_active_variant(self):
        """Get variant with status='active'."""
        row = await self.pool.fetchrow(
            "SELECT * FROM dgm_variants WHERE status = 'active' ORDER BY deployed_at DESC LIMIT 1"
        )
        return dict(row) if row else None

    async def get_root_variant(self):
        """Get the root variant (generation 0, no parent)."""
        row = await self.pool.fetchrow(
            "SELECT * FROM dgm_variants WHERE parent_id IS NULL AND generation = 0 ORDER BY created_at LIMIT 1"
        )
        return dict(row) if row else None

    async def update_status(self, variant_id, status, **kwargs):
        """Update variant status and optional fields."""
        sets = ["status = $2", "updated_at = NOW()"]
        params = [variant_id, status]
        idx = 3
        for key in ('deployed_at', 'evaluation_start', 'evaluation_end', 'deploy_revision_id'):
            if key in kwargs:
                sets.append(f"{key} = ${idx}")
                params.append(kwargs[key])
                idx += 1
        query = f"UPDATE dgm_variants SET {', '.join(sets)} WHERE id = $1"
        await self.pool.execute(query, *params)
        logger.info(f"Variant {variant_id} status -> {status}")

    async def get_evaluated_variants(self):
        """All variants that have fitness scores."""
        rows = await self.pool.fetch(
            """SELECT v.*, f.fitness_score, f.computed_at as fitness_computed_at
               FROM dgm_variants v
               JOIN dgm_fitness_scores f ON f.variant_id = v.id
               WHERE f.id = (SELECT MAX(f2.id) FROM dgm_fitness_scores f2 WHERE f2.variant_id = v.id)
               ORDER BY f.fitness_score DESC"""
        )
        return [dict(r) for r in rows]

    async def get_lineage(self, variant_id):
        """Walk parent_id chain up to root, return ancestry list (child to root)."""
        lineage = []
        current_id = variant_id
        while current_id is not None:
            row = await self.pool.fetchrow(
                "SELECT * FROM dgm_variants WHERE id = $1", current_id
            )
            if row is None:
                break
            lineage.append(dict(row))
            current_id = row['parent_id']
        return lineage

    async def get_children(self, variant_id):
        """Direct children of a variant."""
        rows = await self.pool.fetch(
            "SELECT * FROM dgm_variants WHERE parent_id = $1 ORDER BY created_at", variant_id
        )
        return [dict(r) for r in rows]

    async def get_failed_siblings(self, parent_id):
        """Variants with same parent that failed or were rolled back."""
        if parent_id is None:
            return []
        rows = await self.pool.fetch(
            """SELECT * FROM dgm_variants
               WHERE parent_id = $1 AND status IN ('failed', 'rolled_back')
               ORDER BY created_at""",
            parent_id
        )
        return [dict(r) for r in rows]

    async def get_archive_size(self):
        """Count all variants."""
        row = await self.pool.fetchrow("SELECT COUNT(*) as cnt FROM dgm_variants")
        return row['cnt']

    async def prune_archive(self, max_size, best_variant_id=None):
        """Remove oldest non-ancestor variants. Never prune ancestors of best."""
        size = await self.get_archive_size()
        if size <= max_size:
            return 0

        # Get ancestor IDs of best variant (protected from pruning)
        protected_ids = set()
        if best_variant_id:
            lineage = await self.get_lineage(best_variant_id)
            protected_ids = {v['id'] for v in lineage}

        # Also protect active variant and its lineage
        active = await self.get_active_variant()
        if active:
            active_lineage = await self.get_lineage(active['id'])
            protected_ids.update(v['id'] for v in active_lineage)

        # Find candidates for pruning: oldest, non-protected, non-active
        to_prune = size - max_size
        if not protected_ids:
            protected_ids = {0}  # Dummy to avoid empty IN clause

        rows = await self.pool.fetch(
            f"""SELECT id FROM dgm_variants
               WHERE id != ALL($1::int[])
               AND status NOT IN ('active', 'candidate')
               ORDER BY created_at ASC
               LIMIT $2""",
            list(protected_ids), to_prune
        )

        pruned = 0
        for row in rows:
            await self.pool.execute(
                "UPDATE dgm_variants SET status = 'retired' WHERE id = $1", row['id']
            )
            pruned += 1

        logger.info(f"Pruned {pruned} variants (archive size was {size}, max {max_size})")
        return pruned

    async def snapshot_config_as_root(self, config_yaml):
        """Create generation-0 root variant from current config."""
        existing = await self.get_root_variant()
        if existing:
            logger.info(f"Root variant already exists: {existing['id']}")
            return existing['id']

        variant_id = await self.create_variant(
            parent_id=None,
            config_yaml=config_yaml,
            mutation_description="Initial config snapshot (root)",
            generation=0,
            lineage_depth=0,
            branch_reason="bootstrap"
        )
        # Mark as evaluated immediately (it's the baseline)
        await self.update_status(variant_id, 'evaluated')
        logger.info(f"Created root variant {variant_id}")
        return variant_id
