"""
Enhanced Orchestrator - Phase 2

Integrates all Phase 2 components:
- IntelligenceFusion for signal combination
- Circuit breakers for risk management
- EnhancedExecutor for limit orders
- PostgresStore for persistence
- EventBus for event-driven communication
"""

from typing import List, Optional, Dict
import logging
from datetime import datetime, timezone

from core.interfaces import IAnalyst, IStrategist, IExecutor, ISentinel, IExchange, IMemory
from core.models import Portfolio, Position, MarketIntel, MarketData, Regime
from core.config import Settings, get_settings
from core.events import EventBus, Event, EventType, get_event_bus
from agents.analysts.fusion import IntelligenceFusion
from agents.sentinel.circuit_breakers import CircuitBreakers

logger = logging.getLogger(__name__)


class EnhancedOrchestrator:
    """
    Phase 2 Orchestrator - Full integration with enhanced components.

    Flow:
    1. Check system health and circuit breakers
    2. Get portfolio state from memory
    3. Check stop-losses
    4. For each pair:
       - Fetch market data
       - Run all analysts (technical + sentiment)
       - Fuse signals with IntelligenceFusion
       - Generate trading plan
       - Validate through sentinel
       - Execute with enhanced executor
    5. Update state and emit events
    """

    def __init__(
        self,
        exchange: IExchange,
        analysts: List[IAnalyst],
        strategist: IStrategist,
        sentinel: ISentinel,
        executor: IExecutor,
        memory: IMemory,
        settings: Settings = None,
        event_bus: EventBus = None,
        circuit_breakers: CircuitBreakers = None
    ):
        self.exchange = exchange
        self.strategist = strategist
        self.sentinel = sentinel
        self.executor = executor
        self.memory = memory
        self.settings = settings or get_settings()
        self.event_bus = event_bus or get_event_bus()

        # Initialize intelligence fusion with analysts
        self.fusion = IntelligenceFusion(analysts)
        self.analysts = analysts

        # Initialize circuit breakers
        self.circuit_breakers = circuit_breakers or CircuitBreakers(
            max_daily_loss_pct=self.settings.risk.max_daily_loss_pct,
            max_daily_trades=self.settings.risk.max_daily_trades
        )

        self._running = False
        self._cycle_count = 0

        logger.info(f"EnhancedOrchestrator initialized with {len(analysts)} analysts")
        logger.info(f"Trading pairs: {self.settings.trading.pairs}")
        logger.info(f"Features: fusion=enabled, circuit_breakers=enabled")

    async def run_cycle(self) -> dict:
        """
        Run one complete trading cycle with full Phase 2 integration.

        Returns:
            Summary of cycle results
        """
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc)

        logger.info("=" * 60)
        logger.info(f"Starting trading cycle #{self._cycle_count}")

        results = {
            "cycle": self._cycle_count,
            "timestamp": cycle_start.isoformat(),
            "pairs_analyzed": 0,
            "trades_executed": 0,
            "errors": [],
            "circuit_breaker_status": self.circuit_breakers.get_status()
        }

        try:
            # Emit cycle start event
            await self.event_bus.emit(
                EventType.CYCLE_START,
                {"cycle": self._cycle_count},
                source="orchestrator"
            )

            # 1. Check system health
            if not await self.sentinel.system_healthy():
                logger.warning("System not healthy - skipping cycle")
                results["errors"].append("System paused")
                return results

            # 2. Check circuit breakers
            can_trade, reason = self.circuit_breakers.check_all(0)  # Will check with portfolio value
            if not can_trade:
                logger.warning(f"Circuit breaker active: {reason}")
                results["errors"].append(reason)
                results["circuit_breaker_tripped"] = True
                return results

            # 3. Get current portfolio state
            portfolio = await self._get_portfolio_state()

            # Update circuit breaker with portfolio value
            self.circuit_breakers.check_daily_loss(portfolio.total_value)

            logger.info(
                f"Portfolio: ${portfolio.total_value:,.2f} | "
                f"Available: ${portfolio.available_quote:,.2f} | "
                f"Progress: {portfolio.progress_to_target:.1f}%"
            )

            # Check if target reached
            if portfolio.total_value >= portfolio.target_value:
                logger.info("TARGET REACHED! Stopping trading.")
                await self.event_bus.emit(
                    EventType.TARGET_REACHED,
                    {"value": portfolio.total_value, "target": portfolio.target_value},
                    source="orchestrator"
                )
                results["target_reached"] = True
                return results

            # 4. Check stop-losses
            stop_trades = await self.sentinel.check_stop_losses(portfolio.positions)
            if stop_trades:
                logger.warning(f"Executing {len(stop_trades)} stop-loss trades")

                for trade in stop_trades:
                    await self.event_bus.emit(
                        EventType.STOP_LOSS_TRIGGERED,
                        {"pair": trade.pair, "entry": trade.entry_price},
                        source="sentinel"
                    )

                stop_report = await self.executor.execute_stop_loss(stop_trades)

                # Record stop-loss results for circuit breakers
                for trade in stop_report.trades:
                    if trade.realized_pnl:
                        self.circuit_breakers.record_trade(trade.realized_pnl)

                # Refresh portfolio after stops
                portfolio = await self._get_portfolio_state()
                results["stop_losses_executed"] = len(stop_trades)

            # 5. Analyze each trading pair
            for pair in self.settings.trading.pairs:
                try:
                    trade_result = await self._process_pair(pair, portfolio)
                    results["pairs_analyzed"] += 1

                    if trade_result.get("executed"):
                        results["trades_executed"] += 1
                        # Update portfolio for next pair
                        portfolio = await self._get_portfolio_state()

                except Exception as e:
                    logger.error(f"Error processing {pair}: {e}")
                    results["errors"].append(f"{pair}: {str(e)}")

            # 6. Save portfolio state
            await self.memory.save_portfolio(portfolio)

            # 7. Emit portfolio update event
            await self.event_bus.emit(
                EventType.PORTFOLIO_UPDATED,
                {
                    "total_value": portfolio.total_value,
                    "available_quote": portfolio.available_quote,
                    "positions": {k: v.amount for k, v in portfolio.positions.items()}
                },
                source="orchestrator"
            )

            # 8. Broadcast via WebSocket
            try:
                from api.websocket_manager import portfolio_broadcaster
                await portfolio_broadcaster.broadcast_portfolio_update(
                    total_value=portfolio.total_value,
                    holdings=portfolio.holdings,
                    timestamp=datetime.now()
                )
            except Exception as e:
                logger.debug(f"WebSocket broadcast skipped: {e}")

            # Emit cycle end event
            await self.event_bus.emit(
                EventType.CYCLE_END,
                {
                    "cycle": self._cycle_count,
                    "trades": results["trades_executed"],
                    "duration_seconds": (datetime.now(timezone.utc) - cycle_start).total_seconds()
                },
                source="orchestrator"
            )

            logger.info(
                f"Cycle #{self._cycle_count} complete: "
                f"{results['pairs_analyzed']} pairs, "
                f"{results['trades_executed']} trades"
            )

        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            results["errors"].append(str(e))

        return results

    async def _get_portfolio_state(self) -> Portfolio:
        """Fetch and construct current portfolio state"""
        balance = await self.exchange.get_balance()

        # Build positions
        positions = {}
        for asset, amount in balance.items():
            if asset in ["AUD", "total"] or amount <= 0:
                continue

            # Get current price
            try:
                ticker = await self.exchange.get_ticker(f"{asset}/AUD")
                current_price = ticker.get("price", 0)
            except:
                current_price = 0

            # Get entry price from memory
            entry_price = await self.memory.get_entry_price(asset)

            positions[asset] = Position(
                symbol=asset,
                amount=amount,
                entry_price=entry_price,
                current_price=current_price
            )

        return Portfolio(
            available_quote=balance.get("AUD", 0),
            positions=positions,
            initial_value=self.settings.trading.initial_capital,
            target_value=self.settings.trading.target_capital
        )

    async def _process_pair(self, pair: str, portfolio: Portfolio) -> dict:
        """
        Process a single trading pair through the full Phase 2 pipeline.

        Returns:
            {"executed": bool, "action": str, "details": dict}
        """
        logger.info(f"Analyzing {pair}...")

        result = {"executed": False, "action": "HOLD", "details": {}}

        # 1. Get market data
        market_data = await self.exchange.get_market_data(pair)

        # 2. Check volatility circuit breaker
        price_change_1h = market_data.indicators.get("momentum", 0) if market_data.indicators else 0
        if abs(price_change_1h) > 0:
            if not self.circuit_breakers.check_volatility(pair, price_change_1h / 100):
                result["action"] = "HOLD"
                result["details"]["reason"] = "Volatility circuit breaker"
                return result

        # 3. Run intelligence fusion (all analysts + fusion)
        intel = await self.fusion.analyze(pair, market_data)

        # Emit intel event
        await self.event_bus.emit(
            EventType.INTEL_FUSED,
            {
                "pair": pair,
                "direction": intel.fused_direction,
                "confidence": intel.fused_confidence,
                "disagreement": intel.disagreement,
                "regime": intel.regime.value if intel.regime else "unknown"
            },
            source="fusion"
        )

        logger.info(
            f"{pair}: direction={intel.fused_direction:+.2f}, "
            f"confidence={intel.fused_confidence:.0%}, "
            f"disagreement={intel.disagreement:.2f}"
        )

        # 4. Get trading plan from strategist
        plan = await self.strategist.create_plan(intel, portfolio)

        await self.event_bus.emit(
            EventType.PLAN_CREATED,
            {"pair": pair, "signals": len(plan.signals)},
            source="strategist"
        )

        # 5. Validate through sentinel
        validated_plan = await self.sentinel.validate_plan(plan, portfolio)

        await self.event_bus.emit(
            EventType.PLAN_VALIDATED,
            {
                "pair": pair,
                "approved": len(validated_plan.actionable_signals),
                "rejected": len(validated_plan.rejected_signals)
            },
            source="sentinel"
        )

        # 6. Execute approved trades
        if validated_plan.actionable_signals:
            report = await self.executor.execute(validated_plan)

            result["executed"] = len(report.successful_trades) > 0
            result["action"] = validated_plan.signals[0].action.value if validated_plan.signals else "HOLD"
            result["details"] = report.to_dict()

            # Record trades for circuit breaker
            for trade in report.successful_trades:
                pnl = trade.realized_pnl if trade.realized_pnl else 0
                self.circuit_breakers.record_trade(pnl)

                # Emit trade event
                await self.event_bus.emit(
                    EventType.TRADE_EXECUTED,
                    {
                        "pair": trade.pair,
                        "action": trade.action.value,
                        "price": trade.average_price,
                        "size_base": trade.filled_size_base,
                        "size_quote": trade.filled_size_quote,
                        "pnl": pnl
                    },
                    source="executor"
                )

            for trade in report.failed_trades:
                await self.event_bus.emit(
                    EventType.TRADE_FAILED,
                    {
                        "pair": trade.pair,
                        "action": trade.action.value,
                        "error": trade.error_message
                    },
                    source="executor"
                )

        else:
            result["action"] = "HOLD"
            if validated_plan.rejected_signals:
                reasons = [s.rejection_reason for s in validated_plan.rejected_signals]
                logger.info(f"{pair}: No action - {reasons}")
                result["details"]["rejection_reasons"] = reasons

        return result

    async def start(self):
        """Start the orchestrator"""
        self._running = True

        await self.event_bus.emit(
            EventType.SYSTEM_START,
            {"version": "phase2"},
            source="orchestrator"
        )

        logger.info("Enhanced Orchestrator started")

    async def stop(self):
        """Stop the orchestrator"""
        self._running = False

        await self.event_bus.emit(
            EventType.SYSTEM_STOP,
            {"cycle_count": self._cycle_count},
            source="orchestrator"
        )

        logger.info("Enhanced Orchestrator stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_stats(self) -> dict:
        """Get orchestrator statistics"""
        return {
            "cycle_count": self._cycle_count,
            "is_running": self._running,
            "circuit_breakers": self.circuit_breakers.get_status(),
            "analysts": [a.name for a in self.analysts],
            "event_subscribers": self.event_bus.subscriber_count()
        }
