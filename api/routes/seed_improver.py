"""
Seed Improver API Routes

Endpoints for triggering and querying seed improver runs.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any

router = APIRouter(prefix="/internal/seed-improver", tags=["seed-improver"])

# Set by app.py during initialization
_seed_improver = None
_memory = None


def set_seed_improver(si, mem=None) -> None:
    """Set the seed improver service and memory instances."""
    global _seed_improver, _memory
    _seed_improver = si
    _memory = mem


@router.post("/run")
async def seed_improver_run(payload: Optional[dict] = None):
    """Trigger seed improver cycle (scheduled/manual)."""
    if not _seed_improver:
        raise HTTPException(status_code=503, detail="Seed improver not initialized")

    body = payload or {}
    trigger_type = body.get("trigger_type", "manual")
    context = body.get("context", {})
    result = await _seed_improver.run(trigger_type, context)
    return {
        "status": result.status,
        "run_id": result.run_id,
        "trigger_type": result.trigger_type,
        "summary": result.summary,
    }


@router.post("/loss")
async def seed_improver_loss(payload: Optional[dict] = None):
    """Event-driven trigger for losing trade analysis."""
    if not _seed_improver:
        raise HTTPException(status_code=503, detail="Seed improver not initialized")

    body = payload or {}
    trade = body.get("trade", body)
    result = await _seed_improver.run("losing_trade", {"trade": trade})
    return {
        "status": result.status,
        "run_id": result.run_id,
        "trigger_type": result.trigger_type,
        "summary": result.summary,
    }


@router.get("/runs")
async def list_runs(limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """List seed improver runs with pagination."""
    if not _memory or not hasattr(_memory, "_connection"):
        return {"runs": [], "total": 0}

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    try:
        async with _memory._connection() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM seed_improver_runs")
            rows = await conn.fetch(
                """
                SELECT id, trigger_type, status, summary, context,
                       recommendations_count, created_at, finished_at
                FROM seed_improver_runs
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            runs = []
            for r in rows:
                runs.append({
                    "id": r["id"],
                    "trigger_type": r["trigger_type"],
                    "status": r["status"],
                    "summary": r["summary"],
                    "recommendations_count": r.get("recommendations_count", 0),
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                })
            return {"runs": runs, "total": total}
    except Exception as e:
        return {"runs": [], "total": 0, "error": str(e)}


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: int) -> Dict[str, Any]:
    """Get detailed info about a specific run including changes."""
    if not _memory or not hasattr(_memory, "_connection"):
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        async with _memory._connection() as conn:
            run = await conn.fetchrow(
                """
                SELECT id, trigger_type, status, summary, context, error,
                       recommendations_count, created_at, finished_at
                FROM seed_improver_runs WHERE id = $1
                """,
                run_id,
            )
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")

            changes = await conn.fetch(
                """
                SELECT id, change_type, description, details, status, created_at
                FROM seed_improver_changes
                WHERE run_id = $1
                ORDER BY created_at
                """,
                run_id,
            )

            return {
                "run": {
                    "id": run["id"],
                    "trigger_type": run["trigger_type"],
                    "status": run["status"],
                    "summary": run["summary"],
                    "context": run["context"],
                    "error": run.get("error"),
                    "recommendations_count": run.get("recommendations_count", 0),
                    "created_at": run["created_at"].isoformat() if run["created_at"] else None,
                    "finished_at": run["finished_at"].isoformat() if run["finished_at"] else None,
                },
                "changes": [
                    {
                        "id": c["id"],
                        "change_type": c["change_type"],
                        "description": c["description"],
                        "details": c["details"],
                        "status": c["status"],
                        "created_at": c["created_at"].isoformat() if c["created_at"] else None,
                    }
                    for c in changes
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{run_id}")
async def get_run_status(run_id: int) -> Dict[str, Any]:
    """Quick status check for a specific run."""
    if not _memory or not hasattr(_memory, "_connection"):
        raise HTTPException(status_code=503, detail="Memory not initialized")

    try:
        async with _memory._connection() as conn:
            row = await conn.fetchrow(
                "SELECT id, status, summary FROM seed_improver_runs WHERE id = $1",
                run_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Run not found")
            return {"id": row["id"], "status": row["status"], "summary": row["summary"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
