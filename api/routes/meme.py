"""Meme Trading Module API Routes"""

import logging
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meme", tags=["meme"])

# Module reference (set by app.py on startup)
_meme_orchestrator = None


def set_meme_orchestrator(orchestrator):
    global _meme_orchestrator
    _meme_orchestrator = orchestrator


def _check_meme_enabled():
    if _meme_orchestrator is None:
        raise HTTPException(status_code=404, detail="Meme trading module not enabled. Set ENABLE_MEME_TRADING=true")


@router.get("/status")
async def meme_status():
    """Get meme trading module status"""
    _check_meme_enabled()
    return {"enabled": True, "status": _meme_orchestrator.get_status()}


@router.get("/budget")
async def meme_budget():
    """Get Twitter API budget state"""
    _check_meme_enabled()
    return _meme_orchestrator.twitter_analyst.budget.to_dict()


@router.post("/trigger")
async def meme_trigger():
    """Manually trigger one meme trading cycle"""
    _check_meme_enabled()
    result = await _meme_orchestrator.run_cycle()
    return {"status": "completed", "result": result}


@router.post("/pause")
async def meme_pause():
    """Pause meme trading"""
    _check_meme_enabled()
    _meme_orchestrator.sentinel.pause()
    return {"status": "paused"}


@router.post("/resume")
async def meme_resume():
    """Resume meme trading"""
    _check_meme_enabled()
    _meme_orchestrator.sentinel.resume()
    return {"status": "resumed"}
