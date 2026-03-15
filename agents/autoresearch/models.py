"""Autoresearch data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class Objective:
    """An improvement objective identified from daily performance."""

    description: str
    target_file: str
    metric: str
    current_value: float
    target_direction: str  # "increase" | "decrease"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "target_file": self.target_file,
            "metric": self.metric,
            "current_value": self.current_value,
            "target_direction": self.target_direction,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Objective:
        return cls(
            description=data.get("description", ""),
            target_file=data.get("target_file", ""),
            metric=data.get("metric", ""),
            current_value=float(data.get("current_value", 0)),
            target_direction=data.get("target_direction", "increase"),
        )


@dataclass
class Experiment:
    """A single autoresearch code experiment."""

    id: Optional[str] = None
    date: Optional[date] = None
    objective: str = ""
    target_file: str = ""
    commit_hash: Optional[str] = None
    status: str = "PENDING"
    # PENDING, COMMITTED, VALIDATED, KEPT, REVERTED, FAILED
    code_diff: Optional[str] = None
    metrics_before: Dict[str, Any] = field(default_factory=dict)
    metrics_after: Dict[str, Any] = field(default_factory=dict)
    llm_reasoning: Optional[str] = None
    evaluation_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "objective": self.objective,
            "target_file": self.target_file,
            "commit_hash": self.commit_hash,
            "status": self.status,
            "code_diff": self.code_diff,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "llm_reasoning": self.llm_reasoning,
            "evaluation_notes": self.evaluation_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_row(cls, row: Any) -> Experiment:
        """Create from a database row (asyncpg Record or dict)."""
        data = dict(row) if not isinstance(row, dict) else row
        return cls(
            id=str(data.get("id", "")),
            date=data.get("date"),
            objective=data.get("objective", ""),
            target_file=data.get("target_file", ""),
            commit_hash=data.get("commit_hash"),
            status=data.get("status", "PENDING"),
            code_diff=data.get("code_diff"),
            metrics_before=data.get("metrics_before") or {},
            metrics_after=data.get("metrics_after") or {},
            llm_reasoning=data.get("llm_reasoning"),
            evaluation_notes=data.get("evaluation_notes"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
