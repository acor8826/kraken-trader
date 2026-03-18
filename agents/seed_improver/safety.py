"""
Safety Validator

Validates config patches against hard bounds, protected keys,
rate limits, and cooldown periods before allowing auto-apply.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import ConfigPatch

logger = logging.getLogger(__name__)


# Hard bounds for modifiable parameters: (min, max)
PARAMETER_BOUNDS: Dict[str, Tuple[float, float]] = {
    # Risk parameters
    "risk.stop_loss_pct": (0.005, 0.05),
    "risk.min_confidence": (0.30, 0.90),
    "risk.max_position_pct": (0.05, 0.50),
    "risk.max_total_exposure_pct": (0.30, 0.95),
    "risk.take_profit_multiplier": (1.0, 5.0),
    "risk.max_daily_loss_pct": (0.05, 0.20),
    "risk.max_daily_trades": (5, 50),
    # Aggressive risk parameters
    "aggressive_risk.stop_loss_pct": (0.005, 0.05),
    "aggressive_risk.min_confidence": (0.20, 0.90),
    "aggressive_risk.max_position_pct": (0.05, 0.50),
    "aggressive_risk.max_total_exposure_pct": (0.30, 0.95),
    "aggressive_risk.take_profit_multiplier": (1.0, 5.0),
    "aggressive_risk.max_daily_loss_pct": (0.05, 0.25),
    "aggressive_risk.max_daily_trades": (5, 60),
    # Trading parameters
    "trading.check_interval_minutes": (5, 120),
    "trading.initial_capital": (100.0, 100000.0),
    "trading.target_capital": (500.0, 1000000.0),
    # Fusion weights (individual)
    "fusion.analyst_weights.technical": (0.0, 1.0),
    "fusion.analyst_weights.sentiment": (0.0, 1.0),
    "fusion.analyst_weights.onchain": (0.0, 1.0),
    "fusion.analyst_weights.macro": (0.0, 1.0),
    # Sentiment weights
    "sentiment.fear_greed_weight": (0.0, 1.0),
    "sentiment.news_weight": (0.0, 1.0),
    "sentiment.social_weight": (0.0, 1.0),
    # Circuit breakers
    "circuit_breakers.max_daily_loss_pct": (0.05, 0.25),
    "circuit_breakers.max_daily_trades": (5, 60),
    "circuit_breakers.consecutive_loss_limit": (2, 10),
    # Exit management
    "exit_management.trailing_stop.activation_pct": (0.003, 0.05),
    "exit_management.trailing_stop.distance_pct": (0.003, 0.03),
    "exit_management.breakeven.activation_pct": (0.002, 0.03),
    "exit_management.breakeven.buffer_pct": (0.0005, 0.01),
    # Portfolio protection
    "portfolio_protection.hwm_drawdown_pct": (0.02, 0.10),
    "portfolio_protection.hwm_critical_drawdown_pct": (0.04, 0.15),
    "portfolio_protection.hwm_tighten_trail_pct": (0.003, 0.015),
    # Hybrid thresholds
    "cost_optimization.hybrid.direction_threshold": (0.10, 0.60),
    "cost_optimization.hybrid.confidence_threshold": (0.30, 0.80),
    "cost_optimization.hybrid.disagreement_threshold": (0.15, 0.60),
    # DGM evolutionary parameters — agent can tune these, bounded to prevent
    # degenerate configs. Fitness function (raw PnL after fees) is hardcoded
    # in Python and cannot be modified via config.
    "seed_improver.dgm.evaluation_window_hours": (6, 168),       # 6h to 1 week
    "seed_improver.dgm.max_evaluation_hours": (12, 336),         # 12h to 2 weeks
    "seed_improver.dgm.min_trades_for_eval": (1, 20),            # at least 1 trade required
    "seed_improver.dgm.archive_max_size": (5, 200),              # keep archive manageable
    "seed_improver.dgm.selection_temperature": (0.1, 5.0),       # can't zero out selection pressure
    "seed_improver.dgm.diversity_weight": (0.0, 1.0),            # full range ok
    "seed_improver.dgm.rollback_tolerance": (0.0, 0.30),         # can't exceed 30% tolerance
}

# Keys that must never be modified by auto-apply
PROTECTED_KEYS = {
    "stage",
    "database",
    "database.url",
    "database.pool_min",
    "database.pool_max",
    "redis",
    "redis.url",
    "features.simulation_mode",
    "features.enable_postgres",
    "features.enable_event_bus",
    "log_level",
    "seed_improver.auto_apply",
    "seed_improver.min_confidence",
    "seed_improver.max_risk",
    "seed_improver.max_patches_per_run",
    "seed_improver.cooldown_hours",
    "seed_improver.gcs_config_bucket",
    "seed_improver.dgm.enabled",  # agent cannot turn DGM on/off
}


def _get_nested(data: Dict[str, Any], dotpath: str) -> Any:
    """Get a value from a nested dict using dot-notation path."""
    keys = dotpath.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


_MISSING = object()


class SafetyValidator:
    """Validates ConfigPatch objects against safety bounds."""

    def __init__(
        self,
        max_patches_per_run: int = 3,
        cooldown_hours: float = 2.0,
    ):
        self.max_patches_per_run = max_patches_per_run
        self.cooldown_hours = cooldown_hours
        self._last_apply_timestamp: float = 0.0

    def validate_batch(
        self,
        patches: List[ConfigPatch],
        current_config: Dict[str, Any],
    ) -> Tuple[List[ConfigPatch], List[Dict[str, Any]]]:
        """Validate a batch of patches.

        Returns:
            Tuple of (approved_patches, rejected_patches_with_reasons)
        """
        approved: List[ConfigPatch] = []
        rejected: List[Dict[str, Any]] = []

        # Rate limit check
        if len(patches) > self.max_patches_per_run:
            logger.warning(
                "Too many patches (%d > %d), truncating",
                len(patches),
                self.max_patches_per_run,
            )
            overflow = patches[self.max_patches_per_run:]
            patches = patches[:self.max_patches_per_run]
            for p in overflow:
                rejected.append({
                    "patch": p.to_dict(),
                    "reason": f"Rate limit: max {self.max_patches_per_run} patches per run",
                })

        # Cooldown check
        elapsed = time.time() - self._last_apply_timestamp
        cooldown_seconds = self.cooldown_hours * 3600
        if self._last_apply_timestamp > 0 and elapsed < cooldown_seconds:
            remaining = (cooldown_seconds - elapsed) / 60
            reason = f"Cooldown active: {remaining:.0f} minutes remaining"
            for p in patches:
                rejected.append({"patch": p.to_dict(), "reason": reason})
            return [], rejected

        # Validate each patch individually
        for patch in patches:
            ok, reason = self._validate_single(patch, current_config)
            if ok:
                approved.append(patch)
            else:
                rejected.append({"patch": patch.to_dict(), "reason": reason})

        return approved, rejected

    def _validate_single(
        self,
        patch: ConfigPatch,
        current_config: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Validate a single ConfigPatch.

        Returns:
            (is_valid, rejection_reason)
        """
        path = patch.yaml_path

        # 1. Protected key check
        if path in PROTECTED_KEYS:
            return False, f"Protected key: {path}"

        # Check if any parent is protected
        for protected in PROTECTED_KEYS:
            if path.startswith(protected + "."):
                return False, f"Under protected key: {protected}"

        # 2. Parameter bounds check
        if path in PARAMETER_BOUNDS:
            lo, hi = PARAMETER_BOUNDS[path]
            try:
                new_val = float(patch.new_value)
            except (TypeError, ValueError):
                return False, f"Cannot convert new_value to float for bounds check: {patch.new_value}"
            if new_val < lo or new_val > hi:
                return False, f"Out of bounds: {path}={new_val} not in [{lo}, {hi}]"

        # 3. Old value verification (ensure patch is based on current config)
        current_val = _get_nested(current_config, path)
        if current_val is _MISSING:
            return False, f"Key not found in current config: {path}"

        # Type-aware comparison
        try:
            if isinstance(current_val, float):
                if abs(float(patch.old_value) - current_val) > 1e-9:
                    return False, (
                        f"Stale old_value for {path}: "
                        f"expected {current_val}, got {patch.old_value}"
                    )
            elif isinstance(current_val, int):
                if int(patch.old_value) != current_val:
                    return False, (
                        f"Stale old_value for {path}: "
                        f"expected {current_val}, got {patch.old_value}"
                    )
            elif isinstance(current_val, bool):
                if bool(patch.old_value) != current_val:
                    return False, (
                        f"Stale old_value for {path}: "
                        f"expected {current_val}, got {patch.old_value}"
                    )
            else:
                if str(patch.old_value) != str(current_val):
                    return False, (
                        f"Stale old_value for {path}: "
                        f"expected {current_val}, got {patch.old_value}"
                    )
        except (TypeError, ValueError) as e:
            return False, f"Old value comparison failed for {path}: {e}"

        # 4. Type preservation check
        try:
            if isinstance(current_val, float):
                float(patch.new_value)
            elif isinstance(current_val, int):
                int(patch.new_value)
            elif isinstance(current_val, bool):
                if not isinstance(patch.new_value, bool):
                    return False, f"Type mismatch for {path}: expected bool"
        except (TypeError, ValueError):
            return False, f"Type mismatch for {path}: cannot convert {patch.new_value} to {type(current_val).__name__}"

        return True, ""

    def mark_applied(self) -> None:
        """Record that patches were applied (for cooldown tracking)."""
        self._last_apply_timestamp = time.time()
