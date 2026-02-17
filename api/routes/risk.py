"""
Risk Management API Routes

Endpoints for adaptive risk management.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from core.risk.adaptive import AdaptiveRiskManager

router = APIRouter(prefix="/api/risk", tags=["risk"])

# Will be set by app.py during initialization
risk_manager: AdaptiveRiskManager = None


def set_risk_manager(manager: AdaptiveRiskManager) -> None:
    """Set the risk manager for the routes"""
    global risk_manager
    risk_manager = manager


@router.get("/adaptive")
async def get_adaptive_status() -> Dict[str, Any]:
    """
    Get current adaptive risk status.

    Returns:
        Current mode, adjustments, and 24h performance
    """
    if risk_manager is None:
        return {
            "enabled": False,
            "current_mode": "normal",
            "position_size_multiplier": 1.0,
            "confidence_adjustment": 0.0,
            "message": "Adaptive risk manager not initialized"
        }

    return risk_manager.get_status()


@router.get("/performance")
async def get_rolling_performance() -> Dict[str, Any]:
    """
    Get rolling 24-hour performance metrics.

    Returns:
        Performance stats for the last 24 hours
    """
    if risk_manager is None:
        return {
            "period_hours": 24,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl": 0
        }

    return risk_manager.get_24h_performance()


@router.get("/adjustments")
async def get_risk_adjustments(limit: int = 50) -> Dict[str, Any]:
    """
    Get history of risk adjustments.

    Args:
        limit: Maximum number of adjustments to return

    Returns:
        List of recent risk adjustments
    """
    if risk_manager is None:
        return {"adjustments": [], "total": 0}

    adjustments = risk_manager.adjustment_history[-limit:]
    return {
        "adjustments": [a.to_dict() for a in adjustments],
        "total": len(risk_manager.adjustment_history)
    }


@router.get("/config")
async def get_risk_config() -> Dict[str, Any]:
    """
    Get adaptive risk configuration.

    Returns:
        Current configuration settings
    """
    if risk_manager is None:
        return {
            "enabled": False,
            "message": "Adaptive risk manager not initialized"
        }

    config = risk_manager.config
    return {
        "enabled": config.enabled,
        "cautious_after_losses": config.cautious_after_losses,
        "defensive_after_losses": config.defensive_after_losses,
        "cautious_multiplier": config.cautious_multiplier,
        "defensive_multiplier": config.defensive_multiplier,
        "drawdown_confidence_increase": config.drawdown_confidence_increase,
        "drawdown_threshold": config.drawdown_threshold,
        "recovery_steps": config.recovery_steps,
        "lookback_hours": config.lookback_hours
    }


@router.post("/reset")
async def reset_risk_mode() -> Dict[str, Any]:
    """
    Reset risk mode to normal (emergency use only).

    Returns:
        Confirmation of reset
    """
    if risk_manager is None:
        raise HTTPException(status_code=503, detail="Adaptive risk manager not initialized")

    risk_manager.reset()

    return {
        "status": "reset",
        "current_mode": risk_manager.current_mode.value,
        "position_size_multiplier": risk_manager.position_size_multiplier,
        "message": "Risk mode reset to normal"
    }
