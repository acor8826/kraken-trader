"""
Phase 3 Orchestrator

Full multi-agent orchestrator with:
- All 5 analysts (Technical, Sentiment, On-chain, Macro, Order Book)
- Regime-aware intelligence fusion
- Anomaly detection
- Smart order execution
- Performance tracking and adaptive learning
"""

import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timezone

from core.interfaces import IAnalyst, IExchange, IMemory
from core.models import Portfolio, Position, MarketIntel, Regime, AnalystSignal
from core.models.trading import TradeAction
from core.config import Settings, get_settings
from core.events import EventBus, Event, EventType, get_event_bus
from core.ml import RegimeClassifier, MarketRegime

from agents.analysts.fusion import IntelligenceFusion
from agents.strategist.advanced import AdvancedStrategist
from agents.executor.smart import SmartExecutor
from agents.sentinel.full import FullSentinel
from memory.learning import AnalystPerformanceTracker
from memory.weight_optimizer import WeightOptimizer

logger = logging.getLogger(__name__)


class Phase3Orchestrator:
    """
    Phase 3 Orchestrator - Full multi-agent trading system.

    Features:
    - Concurrent analyst execution
    - Regime detection before fusion
    - Anomaly detection with trading pauses
    - Smart order routing (market/limit/TWAP)
    - Performance tracking for adaptive learning
    - Comprehensive event publishing
    """

    def __init__(
        self,
        exchange: IExchange,
        analysts: List[IAnalyst],
        memory: IMemory,
        settings: Settings = None,
        event_bus: EventBus = None,
        llm=None
    ):
        """
        Initialize Phase 3 orchestrator.

        Args:
            exchange: Exchange interface
            analysts: List of analyst instances
            memory: Memory/storage interface
            settings: Application settings
            event_bus: Event bus for publishing
            llm: LLM provider for strategist
        """
        self.exchange = exchange
        self._analysts_dict = {a.name: a for a in analysts}
        self.analysts = list(analysts)  # Keep as list for route compatibility
        self.memory = memory
        self.settings = settings or get_settings()
        self.event_bus = event_bus or get_event_bus()
        self.llm = llm

        # Initialize Phase 3 components
        self.regime_classifier = RegimeClassifier()
        self.fusion = IntelligenceFusion(analysts=analysts, enable_regime_weights=True)
        self.strategist = AdvancedStrategist(llm=llm, settings=settings)
        self.sentinel = FullSentinel(
            settings=settings,
            exchange=exchange,
            event_bus=event_bus
        )
        self.executor = SmartExecutor(exchange=exchange)

        # Learning components
        self.performance_tracker = AnalystPerformanceTracker(
            evaluation_hours=24,
            storage=memory
        )
        self.weight_optimizer = WeightOptimizer(
            performance_tracker=self.performance_tracker,
            default_weights=self._get_analyst_weights()
        )

        # State
        self._running = False
        self._cycle_count = 0
        self._current_regime: Optional[MarketRegime] = None
        self._latest_intel: Dict[str, MarketIntel] = {}
        self._cycle_metrics: List[Dict] = []

        # Trailing stop state cache — persists across cycles within this instance.
        # Keys are asset symbols (e.g. "BTC"), values are dicts with:
        #   peak_price, trailing_stop_active, trailing_stop_price
        self._exit_state: Dict[str, Dict] = {}

        # Portfolio high-water-mark protection
        self._portfolio_hwm: float = 0.0
        self._hwm_tightened: bool = False

        logger.info(
            f"Phase3Orchestrator initialized with {len(analysts)} analysts: "
            f"{list(self._analysts_dict.keys())}"
        )

    def _get_analyst_weights(self) -> Dict[str, float]:
        """Get analyst weights from settings or defaults."""
        defaults = {
            "technical": 0.30,
            "sentiment": 0.25,
            "onchain": 0.20,
            "macro": 0.15,
            "orderbook": 0.10
        }
        # Override from settings if available
        if hasattr(self.settings, "fusion") and hasattr(self.settings.fusion, "analyst_weights"):
            return {**defaults, **self.settings.fusion.analyst_weights}
        return defaults

    async def run_cycle(self) -> Dict:
        """
        Run one complete Phase 3 trading cycle.

        Flow:
        1. Check system health
        2. Get portfolio state
        3. Check stop-losses
        4. Detect market regime
        5. For each pair: analyze (concurrent) → fuse → strategize → validate → execute
        6. Record performance
        7. Run adaptive learning (if due)
        """
        self._cycle_count += 1
        cycle_start = datetime.now(timezone.utc)

        logger.info("=" * 70)
        logger.info(f"PHASE 3 CYCLE #{self._cycle_count}")

        results = {
            "cycle": self._cycle_count,
            "timestamp": cycle_start.isoformat(),
            "pairs_analyzed": 0,
            "trades_executed": 0,
            "regime": None,
            "anomalies_detected": 0,
            "errors": [],
            "duration_seconds": 0
        }

        try:
            # Publish cycle start
            await self._publish_event(EventType.CYCLE_START, {
                "cycle": self._cycle_count
            })

            # 2. Get current portfolio (moved before health check so stop-losses always run)
            portfolio = await self._get_portfolio_state()

            # 3a. ALWAYS check stop-losses/exits regardless of sentinel pause state
            # This ensures positions are protected even during anomaly-triggered pauses.
            early_stop_trades = await self.sentinel.check_stop_losses(portfolio.positions)
            for symbol, position in portfolio.positions.items():
                tp_hit = self.sentinel._tp_targets_hit.get(symbol, set()) if hasattr(self.sentinel, '_tp_targets_hit') else set()
                self._exit_state[symbol] = {
                    "peak_price": position.peak_price,
                    "trailing_stop_active": position.trailing_stop_active,
                    "trailing_stop_price": position.trailing_stop_price,
                    "tp_targets_hit": tp_hit,
                }
            # Persist exit state to DB after sentinel update
            await self._persist_exit_states()

            if early_stop_trades:
                logger.warning(f"[SAFETY] Executing {len(early_stop_trades)} stop-loss/exit trades (pre-health-gate)")
                await self.executor.execute_stop_loss(early_stop_trades)
                portfolio = await self._get_portfolio_state()
                active_symbols = set(portfolio.positions.keys())
                stale = [s for s in self._exit_state if s not in active_symbols]
                for s in stale:
                    del self._exit_state[s]
                await self._delete_stale_exit_states(stale)

            # Portfolio HWM protection
            if portfolio.total_value > self._portfolio_hwm:
                self._portfolio_hwm = portfolio.total_value
                self._hwm_tightened = False
            if self._portfolio_hwm > 0:
                drawdown = (self._portfolio_hwm - portfolio.total_value) / self._portfolio_hwm
                hwm_cfg = getattr(self.settings, 'portfolio_protection', None)
                hwm_dd = getattr(hwm_cfg, 'hwm_drawdown_pct', 0.03) if hwm_cfg else 0.03
                hwm_crit = getattr(hwm_cfg, 'hwm_critical_drawdown_pct', 0.06) if hwm_cfg else 0.06
                hwm_trail = getattr(hwm_cfg, 'hwm_tighten_trail_pct', 0.005) if hwm_cfg else 0.005

                if drawdown >= hwm_crit:
                    # Critical: force-sell worst position
                    worst_sym, worst_pnl = None, float('inf')
                    for sym, pos in portfolio.positions.items():
                        pnl = pos.unrealized_pnl or 0
                        if pnl < worst_pnl:
                            worst_sym, worst_pnl = sym, pnl
                    if worst_sym and worst_pnl < 0:
                        logger.warning(
                            "[HWM] CRITICAL drawdown %.1f%% from peak $%.0f — "
                            "force-selling worst position %s (PnL: $%.2f)",
                            drawdown * 100, self._portfolio_hwm, worst_sym, worst_pnl,
                        )
                        from core.models.trading import Trade, OrderType
                        pos = portfolio.positions[worst_sym]
                        qc = self.settings.trading.quote_currency
                        hwm_trade = Trade(
                            pair=f"{worst_sym}/{qc}",
                            action=TradeAction.SELL,
                            order_type=OrderType.STOP_LOSS,
                            requested_size_base=pos.amount,
                            entry_price=pos.entry_price,
                            reasoning=f"HWM critical drawdown: {drawdown:.1%} from ${self._portfolio_hwm:,.0f}",
                        )
                        await self.executor.execute_stop_loss([hwm_trade])
                        portfolio = await self._get_portfolio_state()

                elif drawdown >= hwm_dd and not self._hwm_tightened:
                    logger.warning(
                        "[HWM] Drawdown %.1f%% from peak $%.0f — tightening all stops to %.1f%%",
                        drawdown * 100, self._portfolio_hwm, hwm_trail * 100,
                    )
                    for sym, pos in portfolio.positions.items():
                        if not pos.trailing_stop_active:
                            pos.trailing_stop_active = True
                            pos.peak_price = pos.current_price
                        new_trail = round(pos.current_price * (1 - hwm_trail), 2)
                        if pos.trailing_stop_price is None or new_trail > pos.trailing_stop_price:
                            pos.trailing_stop_price = new_trail
                        self._exit_state[sym] = {
                            "peak_price": pos.peak_price,
                            "trailing_stop_active": pos.trailing_stop_active,
                            "trailing_stop_price": pos.trailing_stop_price,
                        }
                    self._hwm_tightened = True

            # Execute any pending force-close trades from circuit breaker
            force_close_trades = self.sentinel.get_pending_force_closes()
            if force_close_trades:
                logger.warning(
                    f"[FORCE-CLOSE] Executing {len(force_close_trades)} "
                    f"circuit-breaker force-close trades")
                await self.executor.execute_stop_loss(force_close_trades)
                portfolio = await self._get_portfolio_state()
                active_symbols = set(portfolio.positions.keys())
                stale = [s for s in self._exit_state if s not in active_symbols]
                for s in stale:
                    del self._exit_state[s]
                await self._delete_stale_exit_states(stale)

            # 1. Check system health (new trades/analysis gated here, exits are already handled above)
            if not await self.sentinel.system_healthy():
                logger.warning("System not healthy - skipping new-trade analysis (exits already checked)")
                results["errors"].append("System paused by sentinel")
                return results
            logger.info(
                f"Portfolio: ${portfolio.total_value:,.2f} | "
                f"Positions: {len(portfolio.positions)} | "
                f"Progress: {portfolio.progress_to_target:.1f}%"
            )

            # Check target
            if portfolio.total_value >= portfolio.target_value:
                logger.info("[TARGET] TARGET REACHED!")
                await self._publish_event(EventType.TARGET_REACHED, {
                    "value": portfolio.total_value,
                    "target": portfolio.target_value
                })
                results["target_reached"] = True
                return results

            # 3. Check stop-losses and exit triggers (trailing stop, TP, etc.)
            stop_trades = await self.sentinel.check_stop_losses(portfolio.positions)

            # Persist trailing stop state changes made by sentinel back to cache
            for symbol, position in portfolio.positions.items():
                tp_hit = self.sentinel._tp_targets_hit.get(symbol, set()) if hasattr(self.sentinel, '_tp_targets_hit') else set()
                self._exit_state[symbol] = {
                    "peak_price": position.peak_price,
                    "trailing_stop_active": position.trailing_stop_active,
                    "trailing_stop_price": position.trailing_stop_price,
                    "tp_targets_hit": tp_hit,
                }

            if stop_trades:
                logger.warning(f"Executing {len(stop_trades)} stop-loss/exit trades")
                await self.executor.execute_stop_loss(stop_trades)
                for trade in stop_trades:
                    # Clear exit state for fully exited positions
                    base = trade.pair.split("/")[0]
                    await self._publish_event(EventType.STOP_LOSS_TRIGGERED, {
                        "pair": trade.pair,
                        "reason": getattr(trade, 'reason', 'stop-loss')
                    })
                portfolio = await self._get_portfolio_state()

                # Clean up exit state for positions that no longer exist
                active_symbols = set(portfolio.positions.keys())
                stale = [s for s in self._exit_state if s not in active_symbols]
                for s in stale:
                    del self._exit_state[s]
                await self._delete_stale_exit_states(stale)
                await self._persist_exit_states()

            # 4. Detect market regime
            regime = await self._detect_regime()
            self._current_regime = regime
            results["regime"] = regime.value if regime else None
            logger.info(f"Market regime: {regime.value if regime else 'UNKNOWN'}")

            # 5. Process each trading pair
            for pair in self.settings.trading.pairs:
                try:
                    trade_result = await self._process_pair(pair, portfolio, regime)
                    results["pairs_analyzed"] += 1

                    if trade_result.get("executed"):
                        results["trades_executed"] += 1
                        portfolio = await self._get_portfolio_state()

                    if trade_result.get("anomaly_detected"):
                        results["anomalies_detected"] += 1

                except Exception as e:
                    logger.error(f"Error processing {pair}: {e}", exc_info=True)
                    results["errors"].append(f"{pair}: {str(e)}")

            # 6. Save portfolio state — use DB-reconstructed value so
            # portfolio_snapshots reflect correct totals after Cloud Run deploys
            # (the sim exchange resets to $1,000 but trade history is preserved).
            await self._save_portfolio_with_db_value(portfolio)

            # 7. Broadcast WebSocket update
            await self._broadcast_portfolio_update(portfolio)

            # 8. Evaluate pending signals for learning
            await self._run_learning_cycle()

            # 9. Run weight optimization if due
            await self._run_optimization()

            # Calculate duration
            results["duration_seconds"] = (
                datetime.now(timezone.utc) - cycle_start
            ).total_seconds()

            # Store metrics
            self._cycle_metrics.append(results)
            if len(self._cycle_metrics) > 100:
                self._cycle_metrics = self._cycle_metrics[-100:]

            # Publish cycle end
            await self._publish_event(EventType.CYCLE_END, {
                "cycle": self._cycle_count,
                "duration": results["duration_seconds"],
                "trades": results["trades_executed"]
            })

            logger.info(
                f"Cycle #{self._cycle_count} complete in {results['duration_seconds']:.1f}s: "
                f"{results['pairs_analyzed']} pairs, {results['trades_executed']} trades"
            )

        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            results["errors"].append(str(e))

        return results

    async def _detect_regime(self) -> MarketRegime:
        """Detect current market regime using BTC as reference."""
        try:
            # Use BTC as market proxy
            qc = self.settings.trading.quote_currency
            btc_pair = f"BTC/{qc}"
            if btc_pair not in self.settings.trading.pairs:
                btc_pair = self.settings.trading.pairs[0]

            candles = await self.exchange.get_ohlcv(btc_pair, interval=60, limit=50)

            if not candles:
                return MarketRegime.UNKNOWN

            classification = self.regime_classifier.predict(candles)
            return classification.regime

        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            return MarketRegime.UNKNOWN

    async def _process_pair(
        self,
        pair: str,
        portfolio: Portfolio,
        regime: MarketRegime
    ) -> Dict:
        """Process a single trading pair through the Phase 3 pipeline."""
        logger.info(f"Processing {pair}...")

        result = {
            "executed": False,
            "action": "HOLD",
            "anomaly_detected": False
        }

        # 1. Get market data
        market_data = await self.exchange.get_market_data(pair)
        current_price = market_data.current_price

        # 2. Run all analysts and fuse via IntelligenceFusion
        intel = await self.fusion.analyze(pair, market_data)
        self._latest_intel[pair] = intel

        if not intel.signals:
            logger.warning(f"No signals for {pair}")
            return result

        # 3. Record signals for learning
        for signal in intel.signals:
            await self.performance_tracker.record_signal(
                analyst=signal.source,
                pair=pair,
                direction=signal.direction,
                confidence=signal.confidence,
                price=current_price,
                regime=regime.value if regime else None
            )

        # Publish signal events
        for signal in intel.signals:
            await self._publish_event(EventType.ANALYST_SIGNAL, {
                "analyst": signal.source,
                "pair": pair,
                "direction": signal.direction,
                "confidence": signal.confidence
            })

        # Publish fusion event
        await self._publish_event(EventType.INTEL_FUSED, {
            "pair": pair,
            "direction": intel.fused_direction,
            "confidence": intel.fused_confidence,
            "regime": intel.regime.value if intel.regime else "unknown"
        })

        # Broadcast intel update to dashboard via WebSocket (fire-and-forget)
        try:
            from api.websocket_manager import connection_manager
            asyncio.create_task(connection_manager.broadcast_event("intel_update", {
                "pair": pair,
                "direction": intel.fused_direction,
                "confidence": intel.fused_confidence,
                "regime": intel.regime.value if intel.regime else "unknown",
            }))
        except Exception:
            pass

        logger.info(
            f"{pair}: direction={intel.fused_direction:+.2f}, "
            f"confidence={intel.fused_confidence:.0%}, "
            f"regime={intel.regime.value}"
        )

        # 5. Get trading plan from advanced strategist
        plan = await self.strategist.create_plan(intel, portfolio)

        # Publish plan event
        await self._publish_event(EventType.PLAN_CREATED, {
            "pair": pair,
            "signals_count": len(plan.signals)
        })

        # 6. Validate through full sentinel (anomaly + correlation + risk)
        validated_plan = await self.sentinel.validate_plan(plan, portfolio)

        # Check for anomaly blocks
        for signal in validated_plan.signals:
            if "anomaly" in signal.reasoning.lower():
                result["anomaly_detected"] = True

        # Publish validation event
        actionable_count = len(validated_plan.actionable_signals)
        total_signals = len(validated_plan.signals) if validated_plan.signals else 0
        rejected_signals = [s for s in (validated_plan.signals or []) if s.action.value == "HOLD" or getattr(s, 'rejected', False)]
        logger.info(
            f"{pair}: plan has {total_signals} signals, {actionable_count} actionable"
            + (f", rejected: {[s.reasoning[:60] for s in rejected_signals]}" if rejected_signals and actionable_count == 0 else "")
        )
        await self._publish_event(EventType.PLAN_VALIDATED, {
            "pair": pair,
            "actionable": actionable_count
        })

        # 7. Execute via smart executor
        if validated_plan.actionable_signals:
            report = await self.executor.execute(validated_plan)

            result["executed"] = len(report.successful_trades) > 0
            result["action"] = (
                validated_plan.signals[0].action.value
                if validated_plan.signals else "HOLD"
            )

            # Record trade results for sentinel + memory
            for trade in report.successful_trades:
                await self.sentinel.record_trade_result({
                    "pair": trade.pair,
                    "pnl": trade.pnl or 0
                })
                # Persist trade to memory for history endpoint
                try:
                    await self.memory.record_trade(trade, intel)
                    # Track entry price for position display
                    if trade.action == TradeAction.BUY and trade.average_price > 0:
                        base = trade.pair.split("/")[0]
                        await self.memory.set_entry_price(
                            base, trade.average_price, trade.filled_size_base
                        )
                    # Feed SELL outcomes to Bayesian updater
                    if trade.action == TradeAction.SELL:
                        try:
                            strategy_name = validated_plan.strategy_name or "unknown"
                            pnl = trade.realized_pnl or trade.pnl or 0
                            success = pnl > 0
                            if hasattr(self.strategist, 'bayesian'):
                                self.strategist.bayesian.update(
                                    strategy_name, trade.pair, success
                                )
                                logger.info(
                                    f"Bayesian update: {strategy_name}/{trade.pair} "
                                    f"{'win' if success else 'loss'} (pnl={pnl:+.2f})"
                                )
                        except Exception as e:
                            logger.debug(f"Bayesian update failed: {e}")
                except Exception as e:
                    logger.warning(f"Failed to record trade to memory: {e}")

            # Publish trade event
            if result["executed"]:
                await self._publish_event(EventType.TRADE_EXECUTED, {
                    "pair": pair,
                    "action": result["action"],
                    "trades": len(report.successful_trades)
                })

                # Broadcast trade to dashboard via WebSocket (fire-and-forget)
                try:
                    from api.websocket_manager import connection_manager
                    for t in report.successful_trades:
                        asyncio.create_task(connection_manager.broadcast_event("trade_executed", {
                            "pair": t.pair,
                            "action": result["action"],
                            "price": getattr(t, "price", 0),
                            "amount": getattr(t, "amount", 0),
                        }))
                except Exception:
                    pass

                # Send trade alerts if alert manager attached
                if hasattr(self, '_alert_manager') and self._alert_manager:
                    try:
                        for trade in report.successful_trades:
                            await self._alert_manager.send_alert(
                                level="INFO",
                                title="Trade Executed",
                                message=f"{result['action']} {pair} @ ${current_price:,.2f}"
                            )
                    except Exception as e:
                        logger.debug(f"Alert send failed: {e}")

                # Record for adaptive risk manager
                if hasattr(self, '_risk_manager') and self._risk_manager:
                    try:
                        for trade in report.successful_trades:
                            self._risk_manager.record_trade(
                                pair=pair,
                                pnl=trade.pnl or 0,
                                pnl_pct=trade.pnl_percent or 0,
                            )
                    except Exception as e:
                        logger.debug(f"Risk manager record failed: {e}")

        return result

    async def _run_analysts_concurrent(
        self,
        pair: str,
        market_data: Dict
    ) -> List[AnalystSignal]:
        """Run all analysts concurrently for efficiency."""
        async def run_analyst(analyst: IAnalyst):
            try:
                return await analyst.analyze(pair, market_data)
            except Exception as e:
                logger.error(f"Analyst {analyst.name} failed: {e}")
                return None

        # Run all analysts in parallel
        tasks = [run_analyst(a) for a in self._analysts_dict.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out failures
        signals = []
        for result in results:
            if isinstance(result, AnalystSignal):
                signals.append(result)
                await self._publish_event(EventType.ANALYST_SIGNAL, {
                    "analyst": result.source,
                    "pair": pair,
                    "direction": result.direction,
                    "confidence": result.confidence
                })

        return signals

    async def _run_learning_cycle(self) -> None:
        """Evaluate pending signals and update accuracy metrics."""
        async def get_current_price(pair: str) -> float:
            try:
                ticker = await self.exchange.get_ticker(pair)
                return ticker.get("price", 0)
            except:
                return 0

        evaluated = await self.performance_tracker.evaluate_pending_signals(
            get_current_price
        )

        if evaluated > 0:
            logger.info(f"Evaluated {evaluated} pending signals")

    async def _run_optimization(self) -> None:
        """Run weight optimization if due."""
        result = await self.weight_optimizer.run_scheduled_optimization()

        if result and result.success:
            # Update fusion weights
            new_weights = result.new_weights
            for analyst, weight in new_weights.items():
                if analyst in self._analysts_dict:
                    self._analysts_dict[analyst].weight = weight

            logger.info(f"Weights optimized: {new_weights}")

            await self._publish_event(EventType.SYSTEM_STOP, {
                "type": "weight_optimization",
                "new_weights": new_weights
            })

    async def _get_portfolio_state(self) -> Portfolio:
        """Fetch and construct current portfolio state.

        Only includes positions for symbols in the configured main trading
        pairs AND that have a recorded entry price in the DB (i.e. we actually
        opened the position).  This prevents demo-account pre-loaded balances
        (BTC, ETH, SOL etc.) from being treated as real positions which would
        cause false "TARGET REACHED" and block all trading.

        Meme-coin positions (managed by the MemeOrchestrator) share the same
        exchange instance but must NOT be touched by Phase3 stop-loss / exit
        logic.
        """
        balance = await self.exchange.get_balance()
        qc = self.settings.trading.quote_currency

        # Symbols the main orchestrator is responsible for
        main_symbols = {p.split("/")[0] for p in self.settings.trading.pairs}

        # Detect and clear stale DB positions (entry price exists but
        # exchange balance is 0).  These block new BUY orders.
        for asset in list(main_symbols):
            if balance.get(asset, 0) <= 0:
                entry_price = await self.memory.get_entry_price(asset)
                if entry_price and entry_price > 0:
                    logger.info(f"Clearing stale entry price for {asset} (exchange balance=0)")
                    await self.memory.clear_entry_price(asset)

        positions = {}
        for asset, amount in balance.items():
            if asset in [qc, "total"] or amount <= 0:
                continue
            # Skip symbols not in main trading pairs (e.g. meme coins)
            if asset not in main_symbols:
                continue

            entry_price = await self.memory.get_entry_price(asset)

            # Skip assets with no DB entry price — these are demo/exchange
            # pre-loaded balances, not positions we opened.
            if not entry_price or entry_price <= 0:
                continue

            try:
                ticker = await self.exchange.get_ticker(f"{asset}/{qc}")
                current_price = ticker.get("price", 0)
            except:
                current_price = 0

            pos = Position(
                symbol=asset,
                amount=amount,
                entry_price=entry_price,
                current_price=current_price
            )

            # Restore trailing stop / exit management state from cache
            if asset in self._exit_state:
                es = self._exit_state[asset]
                pos.peak_price = es.get("peak_price")
                pos.trailing_stop_active = es.get("trailing_stop_active", False)
                pos.trailing_stop_price = es.get("trailing_stop_price")

            positions[asset] = pos

        return Portfolio(
            available_quote=max(0, balance.get(qc, 0)),
            positions=positions,
            initial_value=self.settings.trading.initial_capital,
            target_value=self.settings.trading.target_capital
        )

    async def _broadcast_portfolio_update(self, portfolio: Portfolio) -> None:
        """Broadcast portfolio update via WebSocket."""
        try:
            from api.websocket_manager import portfolio_broadcaster
            await portfolio_broadcaster.broadcast_portfolio_update(
                total_value=portfolio.total_value,
                holdings=portfolio.holdings,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.debug(f"WebSocket broadcast skipped: {e}")

    async def _save_portfolio_with_db_value(self, portfolio: Portfolio) -> None:
        """Save portfolio snapshot using DB-reconstructed total value.

        The sim exchange resets to $1,000 on every Cloud Run deploy, but
        trade history in PostgreSQL is the authoritative source. We query
        total buys/sells across all history and combine with live position
        prices to get the correct total_value for the snapshot.
        """
        try:
            if not hasattr(self.memory, '_connection'):
                await self.memory.save_portfolio(portfolio)
                return

            quote_suffix = f"/{self.settings.trading.quote_currency}"
            async with self.memory._connection() as conn:
                realized_pnl = await conn.fetchval("""
                    SELECT COALESCE(SUM(realized_pnl), 0)
                    FROM trades
                    WHERE status = 'filled' AND action = 'SELL'
                      AND realized_pnl IS NOT NULL
                      AND pair LIKE '%' || $1
                """, quote_suffix)

            realized_pnl = float(realized_pnl or 0)
            initial_capital = self.settings.trading.initial_capital
            # total = initial + realized + unrealized
            unrealized = portfolio.positions_value - sum(
                p.amount * p.entry_price for p in portfolio.positions.values()
                if p.entry_price
            )
            db_total = initial_capital + realized_pnl + unrealized

            # Only override if DB total is meaningfully different (deploy reset)
            if abs(db_total - portfolio.total_value) > 50:
                logger.debug(
                    "Portfolio snapshot corrected: sim=$%.0f → db=$%.0f",
                    portfolio.total_value, db_total,
                )
                portfolio.total_value = db_total
                portfolio.available_quote = max(0, db_total - portfolio.positions_value)

            await self.memory.save_portfolio(portfolio)
        except Exception as e:
            logger.debug("DB-corrected portfolio save failed, saving raw: %s", e)
            await self.memory.save_portfolio(portfolio)

    async def _persist_exit_states(self) -> None:
        """Save current exit state cache to DB and clean up closed positions."""
        if not hasattr(self.memory, 'save_exit_state'):
            return
        try:
            for symbol, state in self._exit_state.items():
                qc = self.settings.trading.quote_currency
                pair = state.get("pair", f"{symbol}/{qc}")
                await self.memory.save_exit_state(symbol, pair, state)
        except Exception as e:
            logger.debug("Exit state persist failed: %s", e)

    async def _delete_stale_exit_states(self, stale_symbols: list) -> None:
        """Remove exit state for positions that no longer exist."""
        if not hasattr(self.memory, 'delete_exit_state'):
            return
        for s in stale_symbols:
            try:
                await self.memory.delete_exit_state(s)
            except Exception as e:
                logger.debug("Exit state delete for %s failed: %s", s, e)

    async def _publish_event(self, event_type: EventType, data: Dict) -> None:
        """Publish event to event bus."""
        if self.event_bus:
            try:
                event = Event(type=event_type, data=data)
                await self.event_bus.publish(event)
            except Exception as e:
                logger.debug(f"Event publish failed: {e}")

    async def start(self) -> None:
        """Start the orchestrator."""
        self._running = True

        # Restore portfolio high-water mark from DB
        try:
            if hasattr(self.memory, '_pool') and self.memory._pool:
                async with self.memory._pool.acquire() as conn:
                    val = await conn.fetchval(
                        "SELECT MAX(total_value) FROM portfolio_snapshots"
                    )
                    if val:
                        self._portfolio_hwm = float(val)
                        logger.info(f"Restored portfolio HWM: ${self._portfolio_hwm:,.2f}")
        except Exception as e:
            logger.debug(f"HWM restore failed (non-critical): {e}")

        # Restore exit state (trailing stops, peak prices, TP hits) from DB
        try:
            if hasattr(self.memory, 'get_exit_states'):
                self._exit_state = await self.memory.get_exit_states()
                if self._exit_state:
                    logger.info(
                        "Restored exit state for %d positions: %s",
                        len(self._exit_state),
                        list(self._exit_state.keys()),
                    )
                    # Restore TP targets hit into sentinel
                    if hasattr(self.sentinel, '_tp_targets_hit'):
                        for sym, es in self._exit_state.items():
                            tp = es.get("tp_targets_hit")
                            if tp:
                                self.sentinel._tp_targets_hit[sym] = set(tp)
        except Exception as e:
            logger.debug(f"Exit state restore failed (non-critical): {e}")

        # Load historical signals for learning
        await self.performance_tracker.load_from_storage()

        # Refresh correlation matrix
        await self.sentinel.refresh_correlations(self.settings.trading.pairs)

        logger.info("Phase3Orchestrator started")

    async def stop(self) -> None:
        """Stop the orchestrator."""
        self._running = False
        logger.info("Phase3Orchestrator stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> Dict:
        """Get orchestrator status."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "current_regime": self._current_regime.value if self._current_regime else None,
            "analysts": list(self._analysts_dict.keys()),
            "weights": self.weight_optimizer.get_weights(),
            "anomaly_summary": self.sentinel.get_anomaly_summary(),
            "correlation_summary": self.sentinel.get_correlation_summary(),
            "learning_status": self.weight_optimizer.get_optimization_status()
        }

    def get_latest_intel(self, pair: Optional[str] = None) -> Dict:
        """Get latest market intelligence."""
        if pair:
            intel = self._latest_intel.get(pair)
            if intel:
                return {
                    "pair": intel.pair,
                    "direction": intel.fused_direction,
                    "confidence": intel.fused_confidence,
                    "regime": intel.regime.value,
                    "signal_count": len(intel.signals)
                }
            return {}
        return {
            pair: {
                "direction": i.fused_direction,
                "confidence": i.fused_confidence,
                "regime": i.regime.value
            }
            for pair, i in self._latest_intel.items()
        }

    def get_cycle_metrics(self, limit: int = 10) -> List[Dict]:
        """Get recent cycle metrics."""
        return self._cycle_metrics[-limit:]
