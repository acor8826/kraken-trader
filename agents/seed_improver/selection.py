import logging
import math
import random

import yaml

logger = logging.getLogger(__name__)


class ParentSelector:
    """Fitness-proportional parent selection with diversity bonus.

    Selects from the FULL archive, not just current best.
    Key DGM insight: "worse" variants may have descendants that outperform everything.
    """

    def __init__(self, population, temperature=1.0, diversity_weight=0.1):
        self.population = population
        self.temperature = temperature
        self.diversity_weight = diversity_weight

    async def select_parent(self):
        """Select a parent variant using fitness-proportional selection."""
        variants = await self.population.get_evaluated_variants()

        if not variants:
            logger.info("No evaluated variants in archive, need bootstrap")
            return None

        if len(variants) == 1:
            logger.info(f"Single variant in archive, selecting {variants[0]['id']}")
            return variants[0]

        # Extract numeric config values for diversity computation
        all_configs = []
        for v in variants:
            try:
                cfg = yaml.safe_load(v['config_yaml']) or {}
                all_configs.append(self._extract_numeric_values(cfg))
            except Exception:
                all_configs.append({})

        # Compute centroid
        centroid = self._compute_centroid(all_configs)

        # Compute selection probabilities
        scores = []
        for i, v in enumerate(variants):
            fitness = float(v.get('fitness_score', 0))

            # Temperature-scaled fitness
            if self.temperature == 0:
                base_score = 1.0 if fitness == max(float(x.get('fitness_score', 0)) for x in variants) else 0.0
            else:
                base_score = max(fitness, 0.001) ** self.temperature

            # Diversity bonus
            diversity = self._config_distance(all_configs[i], centroid)
            adjusted = base_score + self.diversity_weight * diversity
            scores.append(max(adjusted, 1e-10))

        # Normalize and sample
        total = sum(scores)
        if total == 0:
            selected = random.choice(variants)
        else:
            selected = random.choices(variants, weights=scores, k=1)[0]

        logger.info(f"Selected parent variant {selected['id']} "
                     f"(fitness={selected.get('fitness_score', 'N/A')}, gen={selected.get('generation', '?')})")
        return selected

    def _extract_numeric_values(self, d, prefix=''):
        """Recursively extract numeric values from nested dict."""
        result = {}
        if not isinstance(d, dict):
            return result
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (int, float)):
                result[key] = float(v)
            elif isinstance(v, dict):
                result.update(self._extract_numeric_values(v, key))
        return result

    def _compute_centroid(self, all_configs):
        """Compute mean of all config numeric values."""
        if not all_configs:
            return {}
        all_keys = set()
        for cfg in all_configs:
            all_keys.update(cfg.keys())

        centroid = {}
        for key in all_keys:
            values = [cfg.get(key, 0) for cfg in all_configs]
            centroid[key] = sum(values) / len(values)
        return centroid

    def _config_distance(self, config_values, centroid):
        """Euclidean distance from centroid, normalized."""
        if not config_values or not centroid:
            return 0.0
        all_keys = set(config_values.keys()) | set(centroid.keys())
        if not all_keys:
            return 0.0

        sq_sum = 0.0
        for key in all_keys:
            a = config_values.get(key, 0)
            b = centroid.get(key, 0)
            # Normalize by centroid value to make distances comparable
            norm = abs(b) if b != 0 else 1.0
            sq_sum += ((a - b) / norm) ** 2

        distance = math.sqrt(sq_sum / len(all_keys))
        # Clamp to [0, 1]
        return min(distance, 1.0)
