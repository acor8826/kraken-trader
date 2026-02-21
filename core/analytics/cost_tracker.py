"""
Cost Tracker Module

Tracks API costs, calculates profitability, and manages cost budgets.
Integrates with ClaudeLLM for token usage tracking.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


@dataclass
class CostConfig:
    """Configuration for cost tracking and budgets."""
    max_daily_cost_usd: float = 1.0           # Daily API budget
    min_profit_ratio: float = 2.0             # Expected profit must be 2x API cost
    skip_llm_under_portfolio: float = 500     # Use rules only if portfolio < this
    skip_llm_under_position: float = 30       # Use rules if position size < this
    warn_at_budget_pct: float = 0.8           # Warn when 80% of budget used


@dataclass
class CostSummary:
    """Summary of costs and profitability."""
    # API costs
    total_api_cost_usd: float = 0.0
    today_api_cost_usd: float = 0.0
    this_month_api_cost_usd: float = 0.0

    # Trading P&L
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0

    # Net profit
    net_profit_usd: float = 0.0  # Trading P&L - API costs

    # Efficiency metrics
    cost_per_trade: float = 0.0
    cost_per_profitable_trade: float = 0.0
    roi_on_api_spend: float = 0.0  # (profit / api_cost) * 100

    # Budget status
    budget_remaining_usd: float = 0.0
    budget_used_pct: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "api_costs": {
                "total_usd": round(self.total_api_cost_usd, 4),
                "today_usd": round(self.today_api_cost_usd, 4),
                "this_month_usd": round(self.this_month_api_cost_usd, 4)
            },
            "trading_pnl": {
                "realized_usd": round(self.total_realized_pnl, 2),
                "unrealized_usd": round(self.total_unrealized_pnl, 2),
                "total_usd": round(self.total_realized_pnl + self.total_unrealized_pnl, 2)
            },
            "net_profit_usd": round(self.net_profit_usd, 2),
            "efficiency": {
                "cost_per_trade": round(self.cost_per_trade, 4),
                "cost_per_profitable_trade": round(self.cost_per_profitable_trade, 4),
                "roi_on_api_spend_pct": round(self.roi_on_api_spend, 2)
            },
            "budget": {
                "remaining_usd": round(self.budget_remaining_usd, 4),
                "used_pct": round(self.budget_used_pct, 2)
            }
        }


class CostTracker:
    """
    Tracks API costs and calculates net profitability.

    Integrates with:
    - ClaudeLLM for token usage stats
    - Memory for trade P&L data
    - Orchestrator for cost-aware decisions
    """

    def __init__(self, config: CostConfig = None):
        self.config = config or CostConfig()
        self._trade_count = 0
        self._profitable_trade_count = 0

    def get_api_usage_from_llm(self) -> Dict:
        """Get API usage stats from ClaudeLLM class."""
        try:
            from integrations.llm.claude import ClaudeLLM
            return ClaudeLLM.get_usage_stats()
        except Exception as e:
            logger.warning(f"Could not get LLM usage stats: {e}")
            return {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
                "calls_today": 0,
                "cost_today_usd": 0.0
            }

    def record_trade(self, pnl: float) -> None:
        """Record a trade for efficiency calculations."""
        self._trade_count += 1
        if pnl > 0:
            self._profitable_trade_count += 1

    def should_use_llm(
        self,
        portfolio_value: float,
        position_size: float,
        expected_profit_pct: float = 0.02
    ) -> bool:
        """
        Determine if LLM analysis is cost-effective.

        Returns True if:
        - Portfolio is large enough
        - Position size justifies API cost
        - Expected profit exceeds API cost threshold
        """
        # Check portfolio threshold
        if portfolio_value < self.config.skip_llm_under_portfolio:
            logger.debug(f"[COST] Skipping LLM: portfolio ${portfolio_value:.2f} < threshold")
            return False

        # Check position size threshold
        if position_size < self.config.skip_llm_under_position:
            logger.debug(f"[COST] Skipping LLM: position ${position_size:.2f} < threshold")
            return False

        # Check expected profit vs API cost
        expected_profit = position_size * expected_profit_pct
        estimated_api_cost = 0.005  # ~$0.005 per Sonnet call with typical prompt

        if expected_profit < estimated_api_cost * self.config.min_profit_ratio:
            logger.debug(f"[COST] Skipping LLM: expected profit ${expected_profit:.4f} "
                        f"< {self.config.min_profit_ratio}x API cost ${estimated_api_cost:.4f}")
            return False

        return True

    def is_budget_exceeded(self) -> bool:
        """Check if daily API budget is exceeded."""
        usage = self.get_api_usage_from_llm()
        return usage.get("cost_today_usd", 0) >= self.config.max_daily_cost_usd

    def get_budget_status(self) -> Dict:
        """Get current budget status."""
        usage = self.get_api_usage_from_llm()
        cost_today = usage.get("cost_today_usd", 0)

        return {
            "daily_budget_usd": self.config.max_daily_cost_usd,
            "used_today_usd": cost_today,
            "remaining_usd": max(0, self.config.max_daily_cost_usd - cost_today),
            "used_pct": (cost_today / self.config.max_daily_cost_usd * 100) if self.config.max_daily_cost_usd > 0 else 0,
            "exceeded": cost_today >= self.config.max_daily_cost_usd,
            "warning": cost_today >= self.config.max_daily_cost_usd * self.config.warn_at_budget_pct
        }

    def calculate_summary(
        self,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0
    ) -> CostSummary:
        """
        Calculate comprehensive cost and profitability summary.

        Args:
            realized_pnl: Total realized P&L from closed trades
            unrealized_pnl: Unrealized P&L from open positions

        Returns:
            CostSummary with all metrics
        """
        usage = self.get_api_usage_from_llm()

        total_api_cost = usage.get("total_cost_usd", 0)
        today_api_cost = usage.get("cost_today_usd", 0)

        # Calculate net profit
        total_pnl = realized_pnl + unrealized_pnl
        net_profit = total_pnl - total_api_cost

        # Efficiency metrics
        cost_per_trade = total_api_cost / self._trade_count if self._trade_count > 0 else 0
        cost_per_profitable = total_api_cost / self._profitable_trade_count if self._profitable_trade_count > 0 else 0
        roi = (total_pnl / total_api_cost * 100) if total_api_cost > 0 else 0

        # Budget
        budget_remaining = max(0, self.config.max_daily_cost_usd - today_api_cost)
        budget_used_pct = (today_api_cost / self.config.max_daily_cost_usd * 100) if self.config.max_daily_cost_usd > 0 else 0

        return CostSummary(
            total_api_cost_usd=total_api_cost,
            today_api_cost_usd=today_api_cost,
            this_month_api_cost_usd=total_api_cost,  # TODO: Add monthly tracking
            total_realized_pnl=realized_pnl,
            total_unrealized_pnl=unrealized_pnl,
            net_profit_usd=net_profit,
            cost_per_trade=cost_per_trade,
            cost_per_profitable_trade=cost_per_profitable,
            roi_on_api_spend=roi,
            budget_remaining_usd=budget_remaining,
            budget_used_pct=budget_used_pct
        )

    def get_break_even_analysis(
        self,
        realized_pnl: float = 0.0
    ) -> Dict:
        """
        Analyze if trading is profitable after API costs.

        Returns break-even analysis with recommendations.
        """
        usage = self.get_api_usage_from_llm()
        total_api_cost = usage.get("total_cost_usd", 0)

        break_even = realized_pnl >= total_api_cost
        profit_margin = ((realized_pnl - total_api_cost) / total_api_cost * 100) if total_api_cost > 0 else 0

        # Recommendations based on profitability
        recommendations = []
        if not break_even:
            recommendations.append("Consider using more rule-based decisions to reduce API costs")
            recommendations.append("Increase minimum position size to improve profit/cost ratio")
        if profit_margin < 50 and profit_margin > 0:
            recommendations.append("Profit margin is thin - consider batching more API calls")

        return {
            "api_costs_total_usd": round(total_api_cost, 4),
            "realized_pnl_usd": round(realized_pnl, 2),
            "net_after_costs_usd": round(realized_pnl - total_api_cost, 2),
            "break_even_achieved": break_even,
            "profit_margin_pct": round(profit_margin, 2),
            "recommendations": recommendations
        }
