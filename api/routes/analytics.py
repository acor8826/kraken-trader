"""
Analytics API Routes

Endpoints for trading performance analytics.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from typing import Dict, Any

from core.analytics.calculator import AnalyticsCalculator

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Will be set by app.py during initialization
memory = None
calculator = None


def set_memory(mem) -> None:
    """Set the memory store for analytics"""
    global memory, calculator
    memory = mem
    calculator = AnalyticsCalculator()


async def _get_trades():
    """Get trades from memory"""
    if memory is None:
        return []
    try:
        return await memory.get_trade_history(limit=1000)
    except Exception:
        return []


@router.get("/summary")
async def get_analytics_summary() -> Dict[str, Any]:
    """
    Get overall trading performance summary.

    Returns:
        Performance metrics including P&L, win rate, profit factor, etc.
    """
    if calculator is None:
        raise HTTPException(status_code=503, detail="Analytics not initialized")

    trades = await _get_trades()
    calculator.set_trades(trades)

    return calculator.calculate_summary()


@router.get("/by-pair")
async def get_analytics_by_pair() -> Dict[str, Any]:
    """
    Get performance breakdown by trading pair.

    Returns:
        Per-pair metrics including win rate, P&L, trade count
    """
    if calculator is None:
        raise HTTPException(status_code=503, detail="Analytics not initialized")

    trades = await _get_trades()
    calculator.set_trades(trades)

    return calculator.calculate_by_pair()


@router.get("/by-hour")
async def get_analytics_by_hour() -> Dict[str, Any]:
    """
    Get performance breakdown by hour of day.

    Returns:
        Hourly metrics showing best/worst trading hours
    """
    if calculator is None:
        raise HTTPException(status_code=503, detail="Analytics not initialized")

    trades = await _get_trades()
    calculator.set_trades(trades)

    return calculator.calculate_by_hour()


@router.get("/by-regime")
async def get_analytics_by_regime() -> Dict[str, Any]:
    """
    Get performance breakdown by market regime.

    Returns:
        Per-regime metrics (trending, ranging, volatile)
    """
    if calculator is None:
        raise HTTPException(status_code=503, detail="Analytics not initialized")

    trades = await _get_trades()
    calculator.set_trades(trades)

    return calculator.calculate_by_regime()


@router.get("/export")
async def export_analytics() -> PlainTextResponse:
    """
    Export trade history as CSV.

    Returns:
        CSV file content with all trades
    """
    if calculator is None:
        raise HTTPException(status_code=503, detail="Analytics not initialized")

    trades = await _get_trades()
    calculator.set_trades(trades)

    csv_content = calculator.export_csv()

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=trades.csv"
        }
    )


@router.get("/metrics")
async def get_key_metrics() -> Dict[str, Any]:
    """
    Get key metrics for dashboard display.

    Returns:
        Simplified metrics for dashboard cards
    """
    if calculator is None:
        return {
            "win_rate": 0,
            "profit_factor": 0,
            "sharpe_ratio": 0,
            "max_drawdown": 0,
            "total_trades": 0,
            "total_pnl": 0
        }

    trades = await _get_trades()
    calculator.set_trades(trades)

    summary = calculator.calculate_summary()

    return {
        "win_rate": summary.get("win_rate", 0),
        "profit_factor": summary.get("profit_factor", 0),
        "sharpe_ratio": summary.get("sharpe_ratio", 0),
        "max_drawdown": summary.get("max_drawdown", 0),
        "total_trades": summary.get("total_trades", 0),
        "total_pnl": summary.get("total_pnl", 0),
        "avg_win": summary.get("avg_win", 0),
        "avg_loss": summary.get("avg_loss", 0)
    }
