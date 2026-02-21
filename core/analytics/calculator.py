"""
Analytics Calculator

Computes trading performance metrics from trade history.
"""

import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict
import logging

from core.models import Trade, TradeStatus

logger = logging.getLogger(__name__)


class AnalyticsCalculator:
    """
    Calculates trading performance analytics.

    Metrics include:
    - P&L (realized and unrealized)
    - Win rate and loss rate
    - Average win/loss size
    - Profit factor (gross profit / gross loss)
    - Sharpe-like ratio
    - Maximum drawdown
    - Best/worst trade
    - Per-pair breakdowns
    - Hourly patterns
    """

    def __init__(self, trades: List[Trade] = None):
        self.trades = trades or []

    def set_trades(self, trades: List[Trade]) -> None:
        """Update trades for analysis"""
        self.trades = trades

    def calculate_summary(self) -> Dict[str, Any]:
        """
        Calculate overall performance summary.

        Returns:
            Dictionary with all performance metrics
        """
        if not self.trades:
            return self._empty_summary()

        completed = [t for t in self.trades if t.status == TradeStatus.FILLED]

        if not completed:
            return self._empty_summary()

        # Calculate P&L
        total_pnl = sum(t.pnl or 0 for t in completed if t.pnl is not None)
        winning_trades = [t for t in completed if (t.pnl or 0) > 0]
        losing_trades = [t for t in completed if (t.pnl or 0) < 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        total_count = len(completed)

        # Win rate
        win_rate = win_count / total_count if total_count > 0 else 0

        # Average win/loss
        gross_profit = sum(t.pnl for t in winning_trades if t.pnl)
        gross_loss = abs(sum(t.pnl for t in losing_trades if t.pnl))

        avg_win = gross_profit / win_count if win_count > 0 else 0
        avg_loss = gross_loss / loss_count if loss_count > 0 else 0

        # Profit factor
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        # Best/worst trade
        best_trade = max(completed, key=lambda t: t.pnl or 0) if completed else None
        worst_trade = min(completed, key=lambda t: t.pnl or 0) if completed else None

        # Sharpe-like ratio (simplified)
        returns = [t.pnl_percent or 0 for t in completed if t.pnl_percent is not None]
        sharpe = self._calculate_sharpe(returns)

        # Maximum drawdown
        max_drawdown, drawdown_duration = self._calculate_drawdown(completed)

        # Average trade duration (if available)
        avg_duration = self._calculate_avg_duration(completed)

        return {
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_count,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate": round(win_rate * 100, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "Infinity",
            "best_trade": self._trade_to_dict(best_trade),
            "worst_trade": self._trade_to_dict(worst_trade),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_drawdown * 100, 1),
            "drawdown_duration_hours": drawdown_duration,
            "avg_trade_duration_minutes": avg_duration,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def calculate_by_pair(self) -> Dict[str, Any]:
        """Calculate performance breakdown by trading pair"""
        if not self.trades:
            return {"pairs": {}}

        completed = [t for t in self.trades if t.status == TradeStatus.FILLED]
        pairs_data = defaultdict(list)

        for trade in completed:
            pairs_data[trade.pair].append(trade)

        result = {}
        for pair, trades in pairs_data.items():
            win_count = len([t for t in trades if (t.pnl or 0) > 0])
            loss_count = len([t for t in trades if (t.pnl or 0) < 0])
            total_pnl = sum(t.pnl or 0 for t in trades)

            result[pair] = {
                "total_trades": len(trades),
                "winning_trades": win_count,
                "losing_trades": loss_count,
                "win_rate": round(win_count / len(trades) * 100, 1) if trades else 0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / len(trades), 2) if trades else 0
            }

        return {"pairs": result}

    def calculate_by_hour(self) -> Dict[str, Any]:
        """Calculate performance breakdown by hour of day"""
        if not self.trades:
            return {"hours": {}}

        completed = [t for t in self.trades if t.status == TradeStatus.FILLED]
        hourly_data = defaultdict(list)

        for trade in completed:
            if trade.timestamp:
                hour = trade.timestamp.hour
                hourly_data[hour].append(trade)

        result = {}
        for hour in range(24):
            trades = hourly_data.get(hour, [])
            if trades:
                win_count = len([t for t in trades if (t.pnl or 0) > 0])
                total_pnl = sum(t.pnl or 0 for t in trades)
                result[str(hour)] = {
                    "total_trades": len(trades),
                    "win_rate": round(win_count / len(trades) * 100, 1),
                    "total_pnl": round(total_pnl, 2)
                }
            else:
                result[str(hour)] = {
                    "total_trades": 0,
                    "win_rate": 0,
                    "total_pnl": 0
                }

        return {"hours": result}

    def calculate_by_regime(self) -> Dict[str, Any]:
        """Calculate performance breakdown by market regime"""
        if not self.trades:
            return {"regimes": {}}

        completed = [t for t in self.trades if t.status == TradeStatus.FILLED]
        regime_data = defaultdict(list)

        for trade in completed:
            regime = getattr(trade, 'regime', None) or 'unknown'
            if hasattr(regime, 'value'):
                regime = regime.value
            regime_data[regime].append(trade)

        result = {}
        for regime, trades in regime_data.items():
            win_count = len([t for t in trades if (t.pnl or 0) > 0])
            total_pnl = sum(t.pnl or 0 for t in trades)

            result[regime] = {
                "total_trades": len(trades),
                "win_rate": round(win_count / len(trades) * 100, 1) if trades else 0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / len(trades), 2) if trades else 0
            }

        return {"regimes": result}

    def export_csv(self) -> str:
        """Export analytics data as CSV string"""
        if not self.trades:
            return "pair,action,price,amount,pnl,pnl_percent,timestamp,status\n"

        lines = ["pair,action,price,amount,pnl,pnl_percent,timestamp,status"]

        for trade in self.trades:
            line = ",".join([
                trade.pair,
                trade.action.value if hasattr(trade.action, 'value') else str(trade.action),
                str(trade.price),
                str(trade.amount),
                str(trade.pnl or 0),
                str(trade.pnl_percent or 0),
                trade.timestamp.isoformat() if trade.timestamp else "",
                trade.status.value if hasattr(trade.status, 'value') else str(trade.status)
            ])
            lines.append(line)

        return "\n".join(lines)

    def _empty_summary(self) -> Dict[str, Any]:
        """Return empty summary with zero values"""
        return {
            "total_pnl": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "gross_profit": 0,
            "gross_loss": 0,
            "profit_factor": 0,
            "best_trade": None,
            "worst_trade": None,
            "sharpe_ratio": 0,
            "max_drawdown": 0,
            "drawdown_duration_hours": 0,
            "avg_trade_duration_minutes": 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def _calculate_sharpe(self, returns: List[float]) -> float:
        """
        Calculate Sharpe-like ratio.

        Simplified: mean return / std deviation of returns
        """
        if len(returns) < 2:
            return 0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance) if variance > 0 else 0

        if std_dev == 0:
            return 0

        return mean_return / std_dev

    def _calculate_drawdown(self, trades: List[Trade]) -> tuple:
        """
        Calculate maximum drawdown and duration.

        Returns:
            (max_drawdown_pct, duration_hours)
        """
        if not trades:
            return 0, 0

        # Sort by timestamp
        sorted_trades = sorted(trades, key=lambda t: t.timestamp if t.timestamp else datetime.min.replace(tzinfo=timezone.utc))

        # Build equity curve
        equity = [0]
        for trade in sorted_trades:
            equity.append(equity[-1] + (trade.pnl or 0))

        if len(equity) < 2:
            return 0, 0

        # Calculate drawdowns
        peak = equity[0]
        max_drawdown = 0
        drawdown_start = None
        max_drawdown_duration = 0

        for i, value in enumerate(equity):
            if value > peak:
                peak = value
                if drawdown_start is not None:
                    duration = i - drawdown_start
                    max_drawdown_duration = max(max_drawdown_duration, duration)
                drawdown_start = None
            else:
                drawdown = (peak - value) / peak if peak > 0 else 0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                    if drawdown_start is None:
                        drawdown_start = i

        # Estimate hours based on typical 1-hour cycle
        return max_drawdown, max_drawdown_duration

    def _calculate_avg_duration(self, trades: List[Trade]) -> float:
        """Calculate average trade duration in minutes"""
        durations = []

        for trade in trades:
            if hasattr(trade, 'duration_seconds') and trade.duration_seconds:
                durations.append(trade.duration_seconds / 60)
            elif hasattr(trade, 'entry_time') and hasattr(trade, 'exit_time'):
                if trade.entry_time and trade.exit_time:
                    delta = trade.exit_time - trade.entry_time
                    durations.append(delta.total_seconds() / 60)

        if not durations:
            return 0

        return round(sum(durations) / len(durations), 1)

    def _trade_to_dict(self, trade: Optional[Trade]) -> Optional[Dict[str, Any]]:
        """Convert trade to dictionary for API response"""
        if not trade:
            return None

        return {
            "pair": trade.pair,
            "action": trade.action.value if hasattr(trade.action, 'value') else str(trade.action),
            "price": trade.price,
            "amount": trade.amount,
            "pnl": trade.pnl,
            "pnl_percent": trade.pnl_percent,
            "timestamp": trade.timestamp.isoformat() if trade.timestamp else None
        }
