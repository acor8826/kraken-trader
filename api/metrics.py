"""
Prometheus Metrics

Exposes trading metrics for Prometheus scraping.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    REGISTRY
)
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Create a custom registry for our metrics
# This allows us to avoid conflicts with default metrics
TRADING_REGISTRY = REGISTRY

# ============================================================================
# Counters - Track cumulative values
# ============================================================================

# Trade counters
trades_total = Counter(
    "trading_trades_total",
    "Total number of trades executed",
    ["pair", "action", "status"],
    registry=TRADING_REGISTRY
)

signals_total = Counter(
    "trading_signals_total",
    "Total number of signals generated",
    ["analyst", "direction"],
    registry=TRADING_REGISTRY
)

cycles_total = Counter(
    "trading_cycles_total",
    "Total number of trading cycles run",
    ["status"],
    registry=TRADING_REGISTRY
)

errors_total = Counter(
    "trading_errors_total",
    "Total number of errors",
    ["component", "error_type"],
    registry=TRADING_REGISTRY
)

# ============================================================================
# Gauges - Track current values
# ============================================================================

# Portfolio gauges
portfolio_value = Gauge(
    "trading_portfolio_value",
    "Current portfolio value in quote currency",
    registry=TRADING_REGISTRY
)

portfolio_pnl = Gauge(
    "trading_portfolio_pnl",
    "Total unrealized P&L",
    registry=TRADING_REGISTRY
)

portfolio_pnl_percent = Gauge(
    "trading_portfolio_pnl_percent",
    "P&L as percentage of initial capital",
    registry=TRADING_REGISTRY
)

target_progress = Gauge(
    "trading_target_progress",
    "Progress toward target (0-100%)",
    registry=TRADING_REGISTRY
)

positions_count = Gauge(
    "trading_positions_count",
    "Number of open positions",
    registry=TRADING_REGISTRY
)

# Risk gauges
anomaly_score = Gauge(
    "trading_anomaly_score",
    "Current anomaly score (0-1)",
    ["pair"],
    registry=TRADING_REGISTRY
)

portfolio_correlation = Gauge(
    "trading_portfolio_correlation",
    "Average portfolio correlation",
    registry=TRADING_REGISTRY
)

circuit_breaker_status = Gauge(
    "trading_circuit_breaker_status",
    "Circuit breaker status (0=OK, 1=tripped)",
    ["breaker_type"],
    registry=TRADING_REGISTRY
)

# Market regime
regime_current = Gauge(
    "trading_regime_current",
    "Current market regime (encoded)",
    ["regime"],
    registry=TRADING_REGISTRY
)

# Analyst weights
analyst_weight = Gauge(
    "trading_analyst_weight",
    "Current analyst weight",
    ["analyst"],
    registry=TRADING_REGISTRY
)

analyst_accuracy = Gauge(
    "trading_analyst_accuracy",
    "Analyst accuracy over last period",
    ["analyst"],
    registry=TRADING_REGISTRY
)

# ============================================================================
# Histograms - Track distributions
# ============================================================================

cycle_duration_seconds = Histogram(
    "trading_cycle_duration_seconds",
    "Trading cycle duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300],
    registry=TRADING_REGISTRY
)

trade_size = Histogram(
    "trading_trade_size",
    "Trade size as percentage of portfolio",
    buckets=[0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.50],
    registry=TRADING_REGISTRY
)

execution_slippage = Histogram(
    "trading_execution_slippage",
    "Execution slippage percentage",
    buckets=[0.001, 0.005, 0.01, 0.02, 0.05, 0.10],
    registry=TRADING_REGISTRY
)

# ============================================================================
# Info - Static metadata
# ============================================================================

system_info = Info(
    "trading_system",
    "Trading system information",
    registry=TRADING_REGISTRY
)


class MetricsCollector:
    """
    Collects and updates Prometheus metrics from trading components.
    """

    def __init__(self):
        self._initialized = False

    def initialize(
        self,
        stage: str,
        pairs: list,
        initial_capital: float,
        target_capital: float
    ) -> None:
        """Initialize system info metrics."""
        system_info.info({
            "stage": stage,
            "pairs": ",".join(pairs),
            "initial_capital": str(initial_capital),
            "target_capital": str(target_capital)
        })
        self._initialized = True
        logger.info("Prometheus metrics initialized")

    def record_trade(
        self,
        pair: str,
        action: str,
        status: str,
        size_pct: float = 0.0
    ) -> None:
        """Record a trade execution."""
        trades_total.labels(pair=pair, action=action, status=status).inc()
        if size_pct > 0:
            trade_size.observe(size_pct)

    def record_signal(
        self,
        analyst: str,
        direction: str
    ) -> None:
        """Record an analyst signal."""
        signals_total.labels(analyst=analyst, direction=direction).inc()

    def record_cycle(
        self,
        status: str,
        duration_seconds: float
    ) -> None:
        """Record a trading cycle completion."""
        cycles_total.labels(status=status).inc()
        cycle_duration_seconds.observe(duration_seconds)

    def record_error(
        self,
        component: str,
        error_type: str
    ) -> None:
        """Record an error."""
        errors_total.labels(component=component, error_type=error_type).inc()

    def record_slippage(self, slippage_pct: float) -> None:
        """Record execution slippage."""
        execution_slippage.observe(abs(slippage_pct))

    def update_portfolio(
        self,
        value: float,
        pnl: float,
        pnl_pct: float,
        progress: float,
        position_count: int
    ) -> None:
        """Update portfolio metrics."""
        portfolio_value.set(value)
        portfolio_pnl.set(pnl)
        portfolio_pnl_percent.set(pnl_pct)
        target_progress.set(progress)
        positions_count.set(position_count)

    def update_anomaly_score(self, pair: str, score: float) -> None:
        """Update anomaly score for a pair."""
        anomaly_score.labels(pair=pair).set(score)

    def update_correlation(self, avg_correlation: float) -> None:
        """Update portfolio correlation."""
        portfolio_correlation.set(avg_correlation)

    def update_circuit_breaker(self, breaker_type: str, is_tripped: bool) -> None:
        """Update circuit breaker status."""
        circuit_breaker_status.labels(breaker_type=breaker_type).set(1 if is_tripped else 0)

    def update_regime(self, regime: str) -> None:
        """Update current market regime."""
        # Clear all regime labels first
        for r in ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE", "UNKNOWN"]:
            regime_current.labels(regime=r).set(0)
        # Set current regime
        regime_current.labels(regime=regime).set(1)

    def update_analyst_weights(self, weights: Dict[str, float]) -> None:
        """Update analyst weights."""
        for analyst, weight in weights.items():
            analyst_weight.labels(analyst=analyst).set(weight)

    def update_analyst_accuracy(self, accuracies: Dict[str, float]) -> None:
        """Update analyst accuracy metrics."""
        for analyst, accuracy in accuracies.items():
            analyst_accuracy.labels(analyst=analyst).set(accuracy)


# Global metrics collector instance
metrics_collector = MetricsCollector()


def get_metrics_response() -> Response:
    """Generate Prometheus metrics response."""
    return Response(
        content=generate_latest(TRADING_REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )
