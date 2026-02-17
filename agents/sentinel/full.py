"""
Full Sentinel with Anomaly Detection

Stage 3 sentinel that extends EnhancedSentinel with:
- Anomaly detection integration
- Position correlation monitoring
- Adaptive risk adjustment
- Event publishing
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from core.interfaces import ISentinel
from core.models import TradingPlan, Portfolio, TradeAction
from core.config import Settings, get_settings
from core.ml.anomaly_model import AnomalyDetector, AnomalyResult
from agents.sentinel.basic import BasicSentinel
from agents.sentinel.circuit_breakers import CircuitBreakers
from agents.sentinel.correlation_monitor import CorrelationMonitor

logger = logging.getLogger(__name__)


class FullSentinel(ISentinel):
    """
    Full sentinel with anomaly detection and correlation monitoring.

    Features:
    - All BasicSentinel risk rules
    - Circuit breakers
    - Anomaly detection with position size adjustment
    - Position correlation monitoring
    - Event publishing for monitoring
    """

    # Anomaly response thresholds
    ANOMALY_REDUCE_SIZE_THRESHOLD = 0.7  # Reduce position by 50%
    ANOMALY_PAUSE_THRESHOLD = 0.9  # Pause trading

    # Correlation thresholds
    MAX_PORTFOLIO_CORRELATION = 0.8

    def __init__(
        self,
        settings: Settings = None,
        exchange=None,
        event_bus=None
    ):
        """
        Initialize full sentinel.

        Args:
            settings: Application settings
            exchange: Exchange for price data
            event_bus: Event bus for publishing alerts
        """
        self.settings = settings or get_settings()
        self.exchange = exchange
        self.event_bus = event_bus

        # Initialize components
        self.basic_sentinel = BasicSentinel(settings=settings)
        self.circuit_breakers = CircuitBreakers(
            max_daily_loss_pct=self.settings.risk.max_daily_loss_pct,
            max_daily_trades=self.settings.risk.max_daily_trades
        )
        self.anomaly_detector = AnomalyDetector(lookback_periods=30)
        self.correlation_monitor = CorrelationMonitor(
            exchange=exchange,
            threshold=self.MAX_PORTFOLIO_CORRELATION,
            event_bus=event_bus
        )

        # State
        self._is_paused = False
        self._pause_reason = None
        self._pause_until = None
        self._anomaly_history: List[AnomalyResult] = []

        logger.info("FullSentinel initialized with anomaly detection and correlation monitoring")

    async def validate_plan(
        self,
        plan: TradingPlan,
        portfolio: Portfolio
    ) -> TradingPlan:
        """
        Validate and filter trading plan against all risk rules.

        Checks:
        1. Basic risk rules (position size, exposure, etc.)
        2. Circuit breakers
        3. Anomaly detection
        4. Position correlation
        """
        # Check if paused
        if self._is_paused:
            if self._check_pause_expired():
                self._is_paused = False
                self._pause_reason = None
                logger.info("Trading pause expired, resuming")
            else:
                logger.warning(f"Trading paused: {self._pause_reason}")
                return self._block_all_trades(plan)

        # Check circuit breakers
        if not await self.circuit_breakers.is_trading_allowed():
            tripped = self.circuit_breakers.get_tripped_breakers()
            logger.warning(f"Circuit breakers tripped: {tripped}")
            await self._publish_event("CIRCUIT_BREAKER_TRIPPED", {"breakers": tripped})
            return self._block_all_trades(plan)

        # Check anomaly for each signal
        validated_signals = []
        for signal in plan.signals:
            if signal.action == TradeAction.HOLD:
                validated_signals.append(signal)
                continue

            # Check anomaly
            anomaly = await self._check_anomaly(signal.pair)
            if anomaly.is_anomaly:
                await self._handle_anomaly(anomaly, signal)

                if anomaly.score >= self.ANOMALY_PAUSE_THRESHOLD:
                    # Pause trading
                    logger.warning(f"High anomaly score ({anomaly.score:.2f}): pausing trading for 1 hour")
                    self._pause_trading(hours=1, reason=f"Anomaly: {anomaly.anomaly_type}")
                    return self._block_all_trades(plan)

                elif anomaly.score >= self.ANOMALY_REDUCE_SIZE_THRESHOLD:
                    # Reduce position size
                    signal.size_pct = signal.size_pct * 0.5
                    signal.reasoning += f" [Size reduced 50% due to {anomaly.anomaly_type}]"
                    logger.info(f"Reduced position size for {signal.pair} due to anomaly")

            # Check correlation for BUY signals (new positions)
            if signal.action == TradeAction.BUY:
                current_positions = list(portfolio.holdings.keys()) if portfolio.holdings else []
                is_allowed, corr_reason = await self.correlation_monitor.check_new_position(
                    new_pair=signal.pair,
                    current_positions=current_positions
                )
                if not is_allowed:
                    signal.action = TradeAction.HOLD
                    signal.reasoning = f"BLOCKED: {corr_reason}"
                    logger.warning(f"Position blocked by correlation monitor: {signal.pair}")
                    validated_signals.append(signal)
                    continue

            # Apply basic validation
            is_valid = await self.basic_sentinel.validate_signal(signal, portfolio)
            if is_valid:
                validated_signals.append(signal)

        # Update plan with validated signals
        plan.signals = validated_signals
        plan.overall_confidence = sum(s.confidence for s in validated_signals) / len(validated_signals) if validated_signals else 0

        return plan

    async def check_stop_losses(self, positions: Dict) -> List:
        """Check positions for stop-loss triggers"""
        return await self.basic_sentinel.check_stop_losses(positions)

    async def system_healthy(self) -> bool:
        """Check if system is healthy enough to trade"""
        if self._is_paused:
            return False

        if not await self.circuit_breakers.is_trading_allowed():
            return False

        return True

    async def emergency_stop(self) -> None:
        """Trigger emergency stop"""
        self._pause_trading(hours=24, reason="Emergency stop activated")
        await self.circuit_breakers.trigger_emergency_stop()
        await self._publish_event("EMERGENCY_STOP", {"reason": "Manual emergency stop"})
        logger.critical("EMERGENCY STOP ACTIVATED")

    async def _check_anomaly(self, pair: str) -> AnomalyResult:
        """Check for anomalies in current market conditions"""
        try:
            if not self.exchange:
                return AnomalyResult(
                    is_anomaly=False,
                    score=0.0,
                    anomaly_type=None,
                    features={},
                    description="No exchange available",
                    timestamp=datetime.now(timezone.utc)
                )

            # Get current market data
            ticker = await self.exchange.get_ticker(pair)

            current_data = {
                "volume": ticker.get("volume_24h", 0),
                "price": ticker.get("price", 0),
                "spread": ticker.get("ask", 0) - ticker.get("bid", 0),
                "volatility": (ticker.get("high_24h", 0) - ticker.get("low_24h", 0)) / ticker.get("price", 1),
                "price_change": 0  # Would need historical price
            }

            return self.anomaly_detector.detect(current_data, pair)

        except Exception as e:
            logger.error(f"Anomaly check failed for {pair}: {e}")
            return AnomalyResult(
                is_anomaly=False,
                score=0.0,
                anomaly_type=None,
                features={},
                description=f"Error: {e}",
                timestamp=datetime.now(timezone.utc)
            )

    async def _handle_anomaly(self, anomaly: AnomalyResult, signal) -> None:
        """Handle detected anomaly"""
        self._anomaly_history.append(anomaly)

        # Keep only recent history
        if len(self._anomaly_history) > 100:
            self._anomaly_history = self._anomaly_history[-100:]

        # Publish event
        await self._publish_event("ANOMALY_DETECTED", {
            "pair": signal.pair,
            "type": anomaly.anomaly_type,
            "score": anomaly.score,
            "description": anomaly.description,
            "features": anomaly.features
        })

        logger.warning(f"Anomaly detected for {signal.pair}: {anomaly.anomaly_type} (score: {anomaly.score:.2f})")

    def _pause_trading(self, hours: float, reason: str) -> None:
        """Pause trading for specified duration"""
        from datetime import timedelta
        self._is_paused = True
        self._pause_reason = reason
        self._pause_until = datetime.now(timezone.utc) + timedelta(hours=hours)
        logger.warning(f"Trading paused until {self._pause_until}: {reason}")

    def _check_pause_expired(self) -> bool:
        """Check if trading pause has expired"""
        if self._pause_until is None:
            return True
        return datetime.now(timezone.utc) >= self._pause_until

    def _block_all_trades(self, plan: TradingPlan) -> TradingPlan:
        """Block all trades in a plan"""
        for signal in plan.signals:
            if signal.action != TradeAction.HOLD:
                signal.action = TradeAction.HOLD
                signal.reasoning = f"BLOCKED: {self._pause_reason or 'Risk controls'}"
        return plan

    async def _publish_event(self, event_type: str, data: Dict) -> None:
        """Publish event to event bus"""
        if self.event_bus:
            try:
                await self.event_bus.publish(event_type, data)
            except Exception as e:
                logger.error(f"Failed to publish event: {e}")

    def get_anomaly_summary(self) -> Dict:
        """Get summary of recent anomalies"""
        if not self._anomaly_history:
            return {"count": 0, "recent": []}

        recent = self._anomaly_history[-10:]
        by_type = {}
        for a in self._anomaly_history:
            if a.anomaly_type:
                by_type[a.anomaly_type] = by_type.get(a.anomaly_type, 0) + 1

        return {
            "count": len(self._anomaly_history),
            "by_type": by_type,
            "recent": [
                {
                    "type": a.anomaly_type,
                    "score": a.score,
                    "timestamp": a.timestamp.isoformat()
                }
                for a in recent
            ]
        }

    async def record_trade_result(self, trade_result: Dict) -> None:
        """Record trade result for circuit breaker tracking"""
        await self.circuit_breakers.record_trade(
            pnl=trade_result.get("pnl", 0),
            is_win=trade_result.get("pnl", 0) > 0
        )

    def get_correlation_summary(self) -> Dict:
        """Get summary of portfolio correlation status."""
        return self.correlation_monitor.get_matrix_summary()

    async def refresh_correlations(self, pairs: List[str]) -> None:
        """Force refresh of correlation matrix."""
        await self.correlation_monitor.refresh_correlation_matrix(pairs)
