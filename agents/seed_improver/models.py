"""
Seed Improver Data Models

Dataclasses for recommendations, analysis results, and pattern matches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ExpectedImpact:
    metric: str
    direction: str  # "increase" | "decrease"
    magnitude: str  # "small" | "medium" | "large"

    def to_dict(self) -> Dict[str, str]:
        return {"metric": self.metric, "direction": self.direction, "magnitude": self.magnitude}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExpectedImpact:
        return cls(
            metric=data.get("metric", ""),
            direction=data.get("direction", ""),
            magnitude=data.get("magnitude", ""),
        )


@dataclass
class Recommendation:
    priority: str  # "critical" | "strategy" | "observability" | "quality"
    category: str  # "stop_loss" | "entry_timing" | "position_sizing" | ...
    hypothesis: str
    change_summary: str
    expected_impact: ExpectedImpact
    risk_assessment: str  # "low" | "medium" | "high"
    confidence: float  # 0.0 - 1.0
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority,
            "category": self.category,
            "hypothesis": self.hypothesis,
            "change_summary": self.change_summary,
            "expected_impact": self.expected_impact.to_dict(),
            "risk_assessment": self.risk_assessment,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Recommendation:
        impact_data = data.get("expected_impact", {})
        return cls(
            priority=data.get("priority", "quality"),
            category=data.get("category", "unknown"),
            hypothesis=data.get("hypothesis", ""),
            change_summary=data.get("change_summary", ""),
            expected_impact=ExpectedImpact.from_dict(impact_data) if isinstance(impact_data, dict) else ExpectedImpact("", "", ""),
            risk_assessment=data.get("risk_assessment", "medium"),
            confidence=float(data.get("confidence", 0.5)),
            evidence=data.get("evidence", []),
        )


@dataclass
class PatternMatch:
    key: str
    title: str
    description: str

    def to_dict(self) -> Dict[str, str]:
        return {"key": self.key, "title": self.title, "description": self.description}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PatternMatch:
        return cls(
            key=data.get("key", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
        )


@dataclass
class AnalysisResult:
    summary: str
    recommendations: List[Recommendation] = field(default_factory=list)
    patterns_detected: List[PatternMatch] = field(default_factory=list)
    model_used: str = ""
    tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "patterns_detected": [p.to_dict() for p in self.patterns_detected],
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AnalysisResult:
        return cls(
            summary=data.get("analysis_summary", data.get("summary", "")),
            recommendations=[
                Recommendation.from_dict(r) for r in data.get("recommendations", [])
            ],
            patterns_detected=[
                PatternMatch.from_dict(p) for p in data.get("patterns_detected", [])
            ],
        )


@dataclass
class ConfigPatch:
    """A single YAML config change proposed by the LLM."""
    yaml_path: str          # Dot-notation path e.g. "risk.stop_loss_pct"
    old_value: Any          # Expected current value (for verification)
    new_value: Any          # Proposed new value
    reasoning: str          # Why this change helps
    recommendation_idx: int = 0  # Index into the recommendation list

    def to_dict(self) -> Dict[str, Any]:
        return {
            "yaml_path": self.yaml_path,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reasoning": self.reasoning,
            "recommendation_idx": self.recommendation_idx,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigPatch":
        return cls(
            yaml_path=data.get("yaml_path", ""),
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            reasoning=data.get("reasoning", ""),
            recommendation_idx=data.get("recommendation_idx", 0),
        )


@dataclass
class AutoApplyResult:
    """Result of the Phase 2 auto-apply pipeline."""
    patches_proposed: List[ConfigPatch] = field(default_factory=list)
    patches_applied: List[ConfigPatch] = field(default_factory=list)
    patches_rejected: List[Dict[str, Any]] = field(default_factory=list)  # {patch, reason}
    deploy_status: str = "skipped"  # skipped | deployed | rolled_back | failed
    revision_id: str = ""
    health_check_passed: bool = False
    rolled_back: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patches_proposed": [p.to_dict() for p in self.patches_proposed],
            "patches_applied": [p.to_dict() for p in self.patches_applied],
            "patches_rejected": self.patches_rejected,
            "deploy_status": self.deploy_status,
            "revision_id": self.revision_id,
            "health_check_passed": self.health_check_passed,
            "rolled_back": self.rolled_back,
            "error": self.error,
        }
