"""
Config Patch Generator

Uses the LLM to translate human-readable recommendations into
structured YAML config patches.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .models import ConfigPatch, Recommendation
from .prompts import CONFIG_PATCH_SYSTEM_PROMPT, build_config_patch_prompt

logger = logging.getLogger(__name__)


class ConfigPatchGenerator:
    """Converts LLM recommendations into concrete ConfigPatch objects."""

    def __init__(self, llm: Any):
        self.llm = llm

    async def generate_patches(
        self,
        recommendations: List[Recommendation],
        current_yaml: str,
    ) -> List[ConfigPatch]:
        """Ask the LLM to convert recommendations into config patches.

        Args:
            recommendations: Filtered recommendations to convert.
            current_yaml: The current stage2.yaml content as a string.

        Returns:
            List of ConfigPatch objects.
        """
        if not recommendations:
            return []

        prompt = build_config_patch_prompt(recommendations, current_yaml)

        logger.info(
            "Generating config patches for %d recommendations",
            len(recommendations),
        )

        raw = await self.llm.analyze_market(
            prompt=prompt,
            system_prompt=CONFIG_PATCH_SYSTEM_PROMPT,
            max_tokens=1500,
        )

        return self._parse_patches(raw)

    @staticmethod
    def _parse_patches(raw: Any) -> List[ConfigPatch]:
        """Parse the LLM response into ConfigPatch objects."""
        patches: List[ConfigPatch] = []

        # Handle list response (LLM may return a flat list of patches)
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("patches", [])
        else:
            logger.warning("Unexpected config patch response type: %s", type(raw).__name__)
            return []

        for item in items:
            if not isinstance(item, dict):
                continue
            yaml_path = item.get("yaml_path", "")
            if not yaml_path:
                continue
            patches.append(ConfigPatch.from_dict(item))

        logger.info("Parsed %d config patches from LLM response", len(patches))
        return patches
