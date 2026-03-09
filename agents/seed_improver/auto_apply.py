"""
Auto-Apply Pipeline (Phase 2)

Orchestrates: filter → patch generation → safety validation →
YAML apply → GCS upload → Cloud Run deploy → health check → rollback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .config_patch import ConfigPatchGenerator
from .deployer import SelfDeployer
from .models import AnalysisResult, AutoApplyResult, ConfigPatch, Recommendation
from .safety import SafetyValidator

logger = logging.getLogger(__name__)


def _set_nested(data: dict, dotpath: str, value: Any) -> None:
    """Set a value in a nested dict using dot-notation path."""
    keys = dotpath.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def _coerce_type(value: Any, reference: Any) -> Any:
    """Coerce value to match the type of reference."""
    if isinstance(reference, float):
        return float(value)
    elif isinstance(reference, int):
        return int(value)
    elif isinstance(reference, bool):
        return bool(value)
    elif isinstance(reference, str):
        return str(value)
    return value


class AutoApplyPipeline:
    """Orchestrates the full auto-apply cycle."""

    def __init__(
        self,
        llm: Any,
        safety: SafetyValidator,
        deployer: SelfDeployer,
        config_path: Optional[Path] = None,
        min_confidence: float = 0.70,
        max_risk: str = "low",
    ):
        self.patch_generator = ConfigPatchGenerator(llm)
        self.safety = safety
        self.deployer = deployer
        self.config_path = config_path or Path(__file__).resolve().parents[2] / "config" / "stage2.yaml"
        self.min_confidence = min_confidence
        self.max_risk = max_risk

    async def apply(self, analysis: AnalysisResult) -> AutoApplyResult:
        """Run the full auto-apply pipeline.

        Args:
            analysis: The Phase 1 AnalysisResult with recommendations.

        Returns:
            AutoApplyResult with details of what was applied/rejected.
        """
        result = AutoApplyResult()

        # 1. Filter recommendations by confidence and risk
        eligible = self._filter_recommendations(analysis.recommendations)
        if not eligible:
            logger.info("No eligible recommendations for auto-apply "
                       "(need confidence >= %.2f, risk <= %s)",
                       self.min_confidence, self.max_risk)
            result.deploy_status = "skipped"
            return result

        logger.info("Auto-apply: %d eligible recommendations out of %d total",
                    len(eligible), len(analysis.recommendations))

        # 2. Load current YAML
        current_yaml = self._read_yaml()
        if not current_yaml:
            result.deploy_status = "failed"
            result.error = "Could not read current config YAML"
            return result

        current_config = yaml.safe_load(current_yaml)

        # 3. Generate config patches via LLM
        try:
            patches = await self.patch_generator.generate_patches(eligible, current_yaml)
        except Exception as e:
            logger.error("Config patch generation failed: %s", e)
            result.deploy_status = "failed"
            result.error = f"Patch generation failed: {e}"
            return result

        result.patches_proposed = patches

        if not patches:
            logger.info("LLM produced no config patches")
            result.deploy_status = "skipped"
            return result

        # 4. Validate patches through safety validator
        approved, rejected = self.safety.validate_batch(patches, current_config)
        result.patches_rejected = rejected

        if rejected:
            for r in rejected:
                logger.info("Patch rejected: %s — %s",
                          r["patch"].get("yaml_path", "?"), r["reason"])

        if not approved:
            logger.info("All patches rejected by safety validator")
            result.deploy_status = "skipped"
            return result

        # 5. Apply patches to YAML in memory
        new_config = dict(current_config)  # shallow copy is fine, we set nested
        for patch in approved:
            # Get the reference value to coerce the type
            keys = patch.yaml_path.split(".")
            ref = current_config
            for k in keys:
                if isinstance(ref, dict):
                    ref = ref.get(k, ref)
            new_value = _coerce_type(patch.new_value, ref)
            _set_nested(new_config, patch.yaml_path, new_value)

        new_yaml = yaml.dump(new_config, default_flow_style=False, sort_keys=False)
        result.patches_applied = approved

        logger.info("Applied %d patches to config. Deploying...", len(approved))

        # 6. Deploy via GCS + Cloud Run
        deploy_result = await self.deployer.deploy(new_yaml, current_yaml)
        result.deploy_status = deploy_result.status
        result.revision_id = deploy_result.revision_id
        result.health_check_passed = deploy_result.health_check_passed
        result.rolled_back = deploy_result.rolled_back

        if deploy_result.error:
            result.error = deploy_result.error

        if deploy_result.status == "deployed":
            self.safety.mark_applied()
            logger.info("Auto-apply deployed successfully: revision=%s, patches=%d",
                       deploy_result.revision_id, len(approved))
        elif deploy_result.rolled_back:
            logger.warning("Auto-apply rolled back: %s", deploy_result.error)
            result.patches_applied = []  # Clear since rollback undid them

        return result

    async def apply_to_variant(
        self, analysis: AnalysisResult, parent_config_yaml: str
    ) -> Optional[Dict[str, Any]]:
        """Run the patch pipeline against a provided config (for DGM).

        Same logic as apply() but uses the given config YAML instead of
        reading from disk, and does NOT deploy.

        Args:
            analysis: Phase 1 AnalysisResult with recommendations.
            parent_config_yaml: The parent variant's config YAML string.

        Returns:
            Dict with 'patches' (list of ConfigPatch) and 'new_config_yaml' (str),
            or None if no patches were produced/approved.
        """
        # 1. Filter recommendations
        eligible = self._filter_recommendations(analysis.recommendations)
        if not eligible:
            return None

        current_config = yaml.safe_load(parent_config_yaml)

        # 2. Generate patches
        try:
            patches = await self.patch_generator.generate_patches(eligible, parent_config_yaml)
        except Exception as e:
            logger.error("Patch generation failed for variant: %s", e)
            return None

        if not patches:
            return None

        # 3. Validate through safety
        approved, rejected = self.safety.validate_batch(patches, current_config)
        if rejected:
            for r in rejected:
                logger.info("Variant patch rejected: %s -- %s",
                          r["patch"].get("yaml_path", "?"), r["reason"])

        if not approved:
            return None

        # 4. Apply patches to config in memory
        new_config = dict(current_config)
        for patch in approved:
            keys = patch.yaml_path.split(".")
            ref = current_config
            for k in keys:
                if isinstance(ref, dict):
                    ref = ref.get(k, ref)
            new_value = _coerce_type(patch.new_value, ref)
            _set_nested(new_config, patch.yaml_path, new_value)

        new_yaml = yaml.dump(new_config, default_flow_style=False, sort_keys=False)

        return {
            "patches": approved,
            "new_config_yaml": new_yaml,
        }

    def _filter_recommendations(
        self, recommendations: List[Recommendation]
    ) -> List[Recommendation]:
        """Filter recommendations by confidence and risk level."""
        risk_levels = {"low": 0, "medium": 1, "high": 2}
        max_risk_level = risk_levels.get(self.max_risk, 0)

        eligible = []
        for rec in recommendations:
            if rec.confidence < self.min_confidence:
                continue
            rec_risk = risk_levels.get(rec.risk_assessment, 2)
            if rec_risk > max_risk_level:
                continue
            eligible.append(rec)

        return eligible

    def _read_yaml(self) -> Optional[str]:
        """Read the current stage2.yaml content."""
        try:
            return self.config_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Cannot read config at %s: %s", self.config_path, e)
            return None
