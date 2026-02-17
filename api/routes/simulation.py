"""
Simulation API Routes

Endpoints for controlling simulation mode parameters.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# Will be set by app.py during initialization
simulation_exchange = None


class SlippageUpdate(BaseModel):
    """Request model for updating slippage"""
    slippage_pct: float


class FailureRateUpdate(BaseModel):
    """Request model for updating failure rate"""
    failure_rate: float


class ScenarioUpdate(BaseModel):
    """Request model for changing scenario"""
    scenario: str


def set_simulation_exchange(exchange) -> None:
    """Set the simulation exchange for the routes"""
    global simulation_exchange
    simulation_exchange = exchange


def _check_simulation():
    """Check if simulation exchange is available"""
    if simulation_exchange is None:
        raise HTTPException(
            status_code=503,
            detail="Simulation mode not active. Start with SIMULATION_MODE=true"
        )


@router.get("/status")
async def get_simulation_status() -> Dict[str, Any]:
    """
    Get simulation status and whether simulation is active.

    Returns:
        Simulation status and availability
    """
    if simulation_exchange is None:
        return {
            "active": False,
            "message": "Simulation mode not active"
        }

    return {
        "active": True,
        "exchange_name": getattr(simulation_exchange, "name", "unknown"),
        "config": simulation_exchange.get_config() if hasattr(simulation_exchange, "get_config") else {}
    }


@router.get("/config")
async def get_simulation_config() -> Dict[str, Any]:
    """
    Get current simulation configuration.

    Returns:
        Current configuration settings
    """
    _check_simulation()

    if hasattr(simulation_exchange, "get_config"):
        return simulation_exchange.get_config()

    return {
        "message": "Configuration not available for this exchange type"
    }


@router.post("/config/slippage")
async def set_slippage(update: SlippageUpdate) -> Dict[str, Any]:
    """
    Set slippage percentage.

    Args:
        update: New slippage percentage (0.0-1.0)

    Returns:
        Updated configuration
    """
    _check_simulation()

    if not hasattr(simulation_exchange, "set_slippage"):
        raise HTTPException(status_code=400, detail="This exchange does not support slippage configuration")

    if update.slippage_pct < 0 or update.slippage_pct > 0.10:  # Max 10%
        raise HTTPException(status_code=400, detail="Slippage must be between 0 and 0.10 (10%)")

    simulation_exchange.set_slippage(update.slippage_pct)

    return {
        "status": "updated",
        "slippage_pct": update.slippage_pct
    }


@router.post("/config/failure-rate")
async def set_failure_rate(update: FailureRateUpdate) -> Dict[str, Any]:
    """
    Set order failure rate.

    Args:
        update: New failure rate (0.0-1.0)

    Returns:
        Updated configuration
    """
    _check_simulation()

    if not hasattr(simulation_exchange, "set_failure_rate"):
        raise HTTPException(status_code=400, detail="This exchange does not support failure rate configuration")

    if update.failure_rate < 0 or update.failure_rate > 0.50:  # Max 50%
        raise HTTPException(status_code=400, detail="Failure rate must be between 0 and 0.50 (50%)")

    simulation_exchange.set_failure_rate(update.failure_rate)

    return {
        "status": "updated",
        "failure_rate": update.failure_rate
    }


@router.get("/scenario")
async def get_current_scenario() -> Dict[str, Any]:
    """
    Get current market scenario.

    Returns:
        Current scenario name and description
    """
    _check_simulation()

    if hasattr(simulation_exchange, "config"):
        scenario = simulation_exchange.config.scenario
        return {
            "scenario": scenario.value if hasattr(scenario, "value") else str(scenario),
            "available_scenarios": [
                "trending_up",
                "trending_down",
                "ranging",
                "volatile",
                "crash",
                "rally"
            ]
        }

    return {"scenario": "unknown"}


@router.post("/scenario")
async def set_scenario(update: ScenarioUpdate) -> Dict[str, Any]:
    """
    Change market scenario.

    Args:
        update: New scenario name

    Returns:
        Updated scenario
    """
    _check_simulation()

    if not hasattr(simulation_exchange, "set_scenario"):
        raise HTTPException(status_code=400, detail="This exchange does not support scenario changes")

    # Import MarketScenario
    try:
        from integrations.exchanges.simulation import MarketScenario
        scenario = MarketScenario(update.scenario)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scenario: {update.scenario}. Valid: trending_up, trending_down, ranging, volatile, crash, rally"
        )

    simulation_exchange.set_scenario(scenario)

    return {
        "status": "updated",
        "scenario": update.scenario
    }


@router.get("/stats")
async def get_simulation_stats() -> Dict[str, Any]:
    """
    Get simulation statistics.

    Returns:
        Order counts, slippage totals, failure rates
    """
    _check_simulation()

    if hasattr(simulation_exchange, "stats"):
        return simulation_exchange.stats.to_dict()

    return {"message": "Statistics not available for this exchange type"}


@router.get("/report")
async def get_session_report() -> Dict[str, Any]:
    """
    Get end-of-session report.

    Returns:
        Complete session report with PnL and statistics
    """
    _check_simulation()

    if hasattr(simulation_exchange, "get_session_report"):
        return simulation_exchange.get_session_report()

    return {"message": "Session report not available for this exchange type"}


@router.get("/prices")
async def get_current_prices() -> Dict[str, Any]:
    """
    Get current simulated prices for all assets.

    Returns:
        Current prices for all tracked assets
    """
    _check_simulation()

    if hasattr(simulation_exchange, "_current_prices"):
        return {
            "prices": {k: round(v, 2) for k, v in simulation_exchange._current_prices.items()}
        }

    return {"prices": {}}


@router.post("/prices/{symbol}")
async def set_price(symbol: str, price: float) -> Dict[str, Any]:
    """
    Manually set a simulated price (for testing).

    Args:
        symbol: Asset symbol (e.g., BTC, ETH)
        price: New price

    Returns:
        Updated price
    """
    _check_simulation()

    if price <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")

    if hasattr(simulation_exchange, "_current_prices"):
        simulation_exchange._current_prices[symbol] = price
        return {
            "status": "updated",
            "symbol": symbol,
            "price": price
        }

    raise HTTPException(status_code=400, detail="Price setting not available")
