"""
Seed Improver API Routes

Endpoints for triggering and querying seed improver runs.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any, List

router = APIRouter(prefix="/internal/seed-improver", tags=["seed-improver"])

# Set by app.py during initialization
_seed_improver = None
_memory = None

# In-memory run log (for when no DB is available)
_run_log: List[Dict[str, Any]] = []
_MAX_RUN_LOG = 50


def set_seed_improver(si, mem=None) -> None:
    """Set the seed improver service and memory instances."""
    global _seed_improver, _memory
    _seed_improver = si
    _memory = mem


def _store_run_in_memory(result) -> None:
    """Store a run result in the in-memory log."""
    entry = {
        "id": result.run_id,
        "trigger_type": result.trigger_type,
        "status": result.status,
        "summary": result.summary,
        "recommendations_count": len(result.analysis.recommendations) if result.analysis else 0,
        "recommendations": [r.to_dict() for r in result.analysis.recommendations] if result.analysis else [],
        "patterns_detected": [p.to_dict() for p in result.analysis.patterns_detected] if result.analysis else [],
        "analysis_summary": result.analysis.summary if result.analysis else None,
        "model_used": result.analysis.model_used if result.analysis else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    # Include auto-apply data if present
    auto_apply = getattr(result, "auto_apply", None)
    if auto_apply:
        entry["auto_apply"] = auto_apply.to_dict()
        entry["patches_applied"] = len(auto_apply.patches_applied)
        entry["deploy_status"] = auto_apply.deploy_status
    _run_log.insert(0, entry)
    if len(_run_log) > _MAX_RUN_LOG:
        _run_log.pop()


@router.post("/run")
async def seed_improver_run(payload: Optional[dict] = None):
    """Trigger seed improver cycle (scheduled/manual).

    When DGM is enabled, runs a full evolutionary cycle instead of the
    standard linear pipeline.
    """
    if not _seed_improver and not _dgm_service:
        raise HTTPException(status_code=503, detail="Seed improver not initialized")

    # DGM mode: run evolutionary cycle
    if _dgm_service:
        cycle_result = await _dgm_service.run_cycle()
        outcome = cycle_result.get("outcome", "unknown")

        # Log the DGM run so /runs endpoint shows it
        dgm_entry = {
            "id": f"dgm-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "trigger_type": "api_dgm",
            "status": "completed",
            "summary": f"DGM cycle: {outcome}",
            "recommendations_count": cycle_result.get("phases", {}).get("mutate", {}).get("patches_count", 0),
            "recommendations": [],
            "patterns_detected": [],
            "analysis_summary": None,
            "model_used": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "mode": "dgm",
            "outcome": outcome,
            "cycle_result": cycle_result,
        }
        _run_log.insert(0, dgm_entry)
        if len(_run_log) > _MAX_RUN_LOG:
            _run_log.pop()

        return {
            "status": "completed",
            "mode": "dgm",
            "outcome": outcome,
            "cycle_result": cycle_result,
        }

    # Legacy mode
    body = payload or {}
    trigger_type = body.get("trigger_type", "manual")
    context = body.get("context", {})
    result = await _seed_improver.run(trigger_type, context)
    _store_run_in_memory(result)
    return {
        "status": result.status,
        "run_id": result.run_id,
        "trigger_type": result.trigger_type,
        "summary": result.summary,
    }


@router.post("/loss")
async def seed_improver_loss(payload: Optional[dict] = None):
    """Event-driven trigger for losing trade analysis.

    When DGM is enabled, losing trades don't trigger an immediate cycle —
    they are captured by dgm_variant_id tagging and evaluated at the next
    scheduled cycle. This avoids reactive churn that undermines evaluation windows.
    """
    if not _seed_improver and not _dgm_service:
        raise HTTPException(status_code=503, detail="Seed improver not initialized")

    # DGM mode: losing trades are evaluated within the normal cycle window,
    # not as reactive triggers (would disrupt evaluation windows)
    if _dgm_service:
        return {
            "status": "acknowledged",
            "mode": "dgm",
            "message": "Trade recorded with dgm_variant_id; will be evaluated in next DGM cycle",
        }

    # Legacy mode
    body = payload or {}
    trade = body.get("trade", body)
    result = await _seed_improver.run("losing_trade", {"trade": trade})
    _store_run_in_memory(result)
    return {
        "status": result.status,
        "run_id": result.run_id,
        "trigger_type": result.trigger_type,
        "summary": result.summary,
    }


@router.get("/runs")
async def list_runs(limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """List seed improver runs with pagination."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    # Try DB first
    if _memory and hasattr(_memory, "_connection"):
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
        except Exception:
            pass

    # Fallback to in-memory log
    total = len(_run_log)
    runs = _run_log[offset:offset + limit]
    return {"runs": runs, "total": total}


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str) -> Dict[str, Any]:
    """Get detailed info about a specific run including changes."""
    # Try DB first
    if _memory and hasattr(_memory, "_connection"):
        try:
            async with _memory._connection() as conn:
                run = await conn.fetchrow(
                    """
                    SELECT id, trigger_type, status, summary, context, error,
                           recommendations_count, created_at, finished_at
                    FROM seed_improver_runs WHERE id = $1
                    """,
                    int(run_id),
                )
                if run:
                    changes = await conn.fetch(
                        """
                        SELECT id, change_type, description, details, status, created_at
                        FROM seed_improver_changes
                        WHERE run_id = $1
                        ORDER BY created_at
                        """,
                        int(run_id),
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
        except Exception:
            pass

    # Fallback to in-memory log
    for entry in _run_log:
        if str(entry["id"]) == str(run_id):
            return {"run": entry, "changes": entry.get("recommendations", [])}

    raise HTTPException(status_code=404, detail="Run not found")


@router.get("/status/{run_id}")
async def get_run_status(run_id: str) -> Dict[str, Any]:
    """Quick status check for a specific run."""
    # Try DB first
    if _memory and hasattr(_memory, "_connection"):
        try:
            async with _memory._connection() as conn:
                row = await conn.fetchrow(
                    "SELECT id, status, summary FROM seed_improver_runs WHERE id = $1",
                    int(run_id),
                )
                if row:
                    return {"id": row["id"], "status": row["status"], "summary": row["summary"]}
        except Exception:
            pass

    # Fallback to in-memory log
    for entry in _run_log:
        if str(entry["id"]) == str(run_id):
            return {"id": entry["id"], "status": entry["status"], "summary": entry["summary"]}

    raise HTTPException(status_code=404, detail="Run not found")


# ── DGM (Darwinian Godel Machine) endpoints ────────────────────

_dgm_service = None
_dgm_pool = None


def set_dgm_service(dgm_svc, pool=None) -> None:
    """Set the DGM service and DB pool instances."""
    global _dgm_service, _dgm_pool
    _dgm_service = dgm_svc
    _dgm_pool = pool


def _serialize_variant(v: dict) -> dict:
    """Serialize a variant dict for JSON response."""
    result = {}
    for k, val in v.items():
        if isinstance(val, datetime):
            result[k] = val.isoformat()
        elif hasattr(val, '__str__') and type(val).__name__ == 'Decimal':
            result[k] = float(val)
        else:
            result[k] = val
    return result


@router.get("/dgm/status")
async def dgm_status() -> Dict[str, Any]:
    """Get current DGM system status."""
    if not _dgm_service:
        return {"enabled": False, "message": "DGM not initialized"}
    try:
        status = await _dgm_service.get_status()
        if status.get('active_variant'):
            status['active_variant'] = _serialize_variant(status['active_variant'])
        if status.get('last_evaluation'):
            status['last_evaluation'] = _serialize_variant(status['last_evaluation'])
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dgm/variants")
async def dgm_list_variants(
    limit: int = 50, offset: int = 0, status: Optional[str] = None
) -> Dict[str, Any]:
    """List all variants in the population archive."""
    if not _dgm_pool:
        raise HTTPException(status_code=503, detail="DGM not initialized")

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    try:
        if status:
            total = await _dgm_pool.fetchval(
                "SELECT COUNT(*) FROM dgm_variants WHERE status = $1", status
            )
            rows = await _dgm_pool.fetch(
                """SELECT v.*, f.fitness_score
                   FROM dgm_variants v
                   LEFT JOIN dgm_fitness_scores f ON f.variant_id = v.id
                     AND f.id = (SELECT MAX(f2.id) FROM dgm_fitness_scores f2 WHERE f2.variant_id = v.id)
                   WHERE v.status = $1
                   ORDER BY v.created_at DESC LIMIT $2 OFFSET $3""",
                status, limit, offset,
            )
        else:
            total = await _dgm_pool.fetchval("SELECT COUNT(*) FROM dgm_variants")
            rows = await _dgm_pool.fetch(
                """SELECT v.*, f.fitness_score
                   FROM dgm_variants v
                   LEFT JOIN dgm_fitness_scores f ON f.variant_id = v.id
                     AND f.id = (SELECT MAX(f2.id) FROM dgm_fitness_scores f2 WHERE f2.variant_id = v.id)
                   ORDER BY v.created_at DESC LIMIT $1 OFFSET $2""",
                limit, offset,
            )

        variants = [_serialize_variant(dict(r)) for r in rows]
        return {"variants": variants, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dgm/fitness/{variant_id}")
async def dgm_fitness(variant_id: int) -> Dict[str, Any]:
    """Get fitness scores for a variant."""
    if not _dgm_pool:
        raise HTTPException(status_code=503, detail="DGM not initialized")

    try:
        rows = await _dgm_pool.fetch(
            """SELECT * FROM dgm_fitness_scores
               WHERE variant_id = $1 ORDER BY computed_at DESC""",
            variant_id,
        )
        scores = [_serialize_variant(dict(r)) for r in rows]
        return {
            "variant_id": variant_id,
            "fitness_scores": scores,
            "latest": scores[0] if scores else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dgm/lineage/{variant_id}")
async def dgm_lineage(variant_id: int) -> Dict[str, Any]:
    """Get full lineage tree for a variant."""
    if not _dgm_service:
        raise HTTPException(status_code=503, detail="DGM not initialized")

    try:
        lineage = await _dgm_service.population.get_lineage(variant_id)
        children = await _dgm_service.population.get_children(variant_id)
        return {
            "variant_id": variant_id,
            "lineage": [_serialize_variant(v) for v in lineage],
            "children": [_serialize_variant(c) for c in children],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dgm/cycle")
async def dgm_trigger_cycle() -> Dict[str, Any]:
    """Manually trigger a DGM evolutionary cycle."""
    if not _dgm_service:
        raise HTTPException(status_code=503, detail="DGM not initialized")

    try:
        result = await _dgm_service.run_cycle()
        return {"status": "completed", "cycle_result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
