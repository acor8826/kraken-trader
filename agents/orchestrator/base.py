"""
Orchestrator Agent

The central coordinator that runs the trading cycle.
Manages workflow between all agents.
"""

from typing import List, Optional
import logging
from datetime import datetime, timezone

from core.interfaces import IAnalyst, IStrategist, IExecutor, ISentinel, IExchange, IMemory
from core.models import Portfolio, Position, MarketIntel
from core.config import Settings, get_settings
from core.events import EventBus, Event, EventType, get_event_bus

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Stage 1 Orchestrator - Simple sequential workflow.
    
    Flow:
    1. Get portfolio state
    2. Check stop-losses
    3. For each pair: analyze → strategize → validate → execute
    4. Update state
    """
    
    def __init__(
        self,
        exchange: IExchange,
        analysts: List[IAnalyst],
        strategist: IStrategist,
        sentinel: ISentinel,
        executor: IExecutor,
        memory: IMemory,
        settings: Settings = None
    ):
        self.exchange = exchange
        self.analysts = analysts
        self.strategist = strategist
        self.sentinel = sentinel
        self.executor = executor
        self.memory = memory
        self.settings = settings or get_settings()
        
        self._running = False
        self._cycle_count = 0
        self._latest_fusion = None  # Store latest fusion for dashboard
        self._alert_manager = None  # Set by app.py
        self._risk_manager = None  # Adaptive risk manager (set by app.py)
        self._last_milestone_pct = 0  # Track portfolio milestones

        logger.info(f"Orchestrator initialized with {len(analysts)} analysts")
        logger.info(f"Trading pairs: {self.settings.trading.pairs}")
    
    async def run_cycle(self) -> dict:
        """
        Run one complete trading cycle.
        
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
            "errors": []
        }
        
        try:
            # 1. Check system health
            if not await self.sentinel.system_healthy():
                logger.warning("System not healthy - skipping cycle")
                results["errors"].append("System paused")
                return results
            
            # 2. Get current portfolio state
            portfolio = await self._get_portfolio_state()
            logger.info(f"Portfolio: ${portfolio.total_value:,.2f} | "
                       f"Available: ${portfolio.available_quote:,.2f} | "
                       f"Progress: {portfolio.progress_to_target:.1f}%")

            # Update risk manager with portfolio value for drawdown tracking
            await self._update_risk_manager_portfolio(portfolio)
            
            # Check if target reached
            if portfolio.total_value >= portfolio.target_value:
                logger.info("🎯 TARGET REACHED! Stopping trading.")
                results["target_reached"] = True
                await self._send_milestone_alert(portfolio, 100.0)
                return results

            # Check portfolio milestones (every 10%)
            await self._check_milestones(portfolio)
            
            # 3. Check stop-losses
            stop_trades = await self.sentinel.check_stop_losses(portfolio.positions)
            if stop_trades:
                logger.warning(f"Executing {len(stop_trades)} stop-loss trades")
                # Alert for each stop-loss
                for trade in stop_trades:
                    await self._send_stop_loss_alert(trade)
                await self.executor.execute_stop_loss(stop_trades)
                # Refresh portfolio after stops
                portfolio = await self._get_portfolio_state()
            
            # 4. Analyze trading pairs (batch or sequential)
            if self._supports_batch_mode():
                # Batch mode: analyze all pairs in single Claude call
                trade_results = await self._process_pairs_batch(
                    self.settings.trading.pairs, portfolio
                )
                for pair, trade_result in trade_results.items():
                    results["pairs_analyzed"] += 1
                    if trade_result.get("executed"):
                        results["trades_executed"] += 1
                        portfolio = await self._get_portfolio_state()
            else:
                # Sequential mode: process each pair individually
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
            
            # 5. Save portfolio state
            await self.memory.save_portfolio(portfolio)

            # 6. Broadcast portfolio update via WebSocket
            try:
                from api.websocket_manager import portfolio_broadcaster
                await portfolio_broadcaster.broadcast_portfolio_update(
                    total_value=portfolio.total_value,
                    holdings=portfolio.holdings,
                    timestamp=datetime.now()
                )
            except Exception as e:
                logger.debug(f"WebSocket broadcast skipped: {e}")

            logger.info(f"Cycle #{self._cycle_count} complete: "
                       f"{results['pairs_analyzed']} pairs, "
                       f"{results['trades_executed']} trades")
            
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            results["errors"].append(str(e))
        
        return results
    
    async def _get_portfolio_state(self) -> Portfolio:
        """Fetch and construct current portfolio state.

        Only builds positions for base assets of configured trading pairs
        to avoid excessive API calls on accounts with many assets.
        """
        quote = self.settings.trading.quote_currency  # e.g. "USDT"
        balance = await self.exchange.get_balance()

        # Only track assets from configured pairs (e.g. BTC, ETH, SOL)
        tracked_assets = {
            pair.split("/")[0] for pair in self.settings.trading.pairs
        }

        positions = {}
        for asset in tracked_assets:
            amount = balance.get(asset, 0)
            if amount <= 0:
                continue

            try:
                ticker = await self.exchange.get_ticker(f"{asset}/{quote}")
                current_price = ticker.get("price", 0)
            except:
                current_price = 0

            entry_price = await self.memory.get_entry_price(asset)

            positions[asset] = Position(
                symbol=asset,
                amount=amount,
                entry_price=entry_price,
                current_price=current_price
            )

        return Portfolio(
            available_quote=balance.get(quote, 0),
            positions=positions,
            initial_value=self.settings.trading.initial_capital,
            target_value=self.settings.trading.target_capital
        )
    
    def _supports_batch_mode(self) -> bool:
        """Check if strategist supports batch analysis."""
        return hasattr(self.strategist, 'create_batch_plan')

    async def _process_pairs_batch(
        self, pairs: List[str], portfolio: Portfolio
    ) -> dict:
        """
        Process all pairs in batch mode for cost optimization.

        This reduces N Claude API calls to 1 by analyzing all pairs together.
        """
        logger.info(f"[BATCH] Analyzing {len(pairs)} pairs in batch mode")

        # 1. Gather market data and run analysts for all pairs
        intel_list = []
        for pair in pairs:
            try:
                logger.info(f"Analyzing {pair}...")
                market_data = await self.exchange.get_market_data(pair)

                # Run analysts
                signals = []
                for analyst in self.analysts:
                    try:
                        signal = await analyst.analyze(pair, market_data)
                        signals.append(signal)
                    except Exception as e:
                        logger.error(f"Analyst {analyst.name} failed: {e}")

                if not signals:
                    continue

                # Create market intel
                from core.models import MarketIntel, Regime

                if len(signals) == 1:
                    intel = MarketIntel(
                        pair=pair,
                        signals=signals,
                        fused_direction=signals[0].direction,
                        fused_confidence=signals[0].confidence,
                        regime=Regime.UNKNOWN
                    )
                else:
                    direction = sum(s.direction for s in signals) / len(signals)
                    confidence = sum(s.confidence for s in signals) / len(signals)
                    intel = MarketIntel(
                        pair=pair,
                        signals=signals,
                        fused_direction=direction,
                        fused_confidence=confidence,
                        regime=Regime.UNKNOWN
                    )

                intel_list.append(intel)
                logger.info(f"{pair}: direction={intel.fused_direction:+.2f}, "
                           f"confidence={intel.fused_confidence:.0%}")

            except Exception as e:
                logger.error(f"Error gathering intel for {pair}: {e}")

        if not intel_list:
            return {}

        # 2. Get batch trading plan (single Claude call)
        plan = await self.strategist.create_batch_plan(intel_list, portfolio)

        # Store latest fusion for dashboard
        if intel_list:
            self._latest_fusion = intel_list[-1]

        # 3. Validate through sentinel
        validated_plan = await self.sentinel.validate_plan(plan, portfolio)

        # 4. Execute approved trades
        results = {}
        for pair in pairs:
            results[pair] = {"executed": False, "action": "HOLD", "details": {}}

        if validated_plan.actionable_signals:
            report = await self.executor.execute(validated_plan)

            for trade in report.successful_trades:
                results[trade.pair] = {
                    "executed": True,
                    "action": trade.action.value,
                    "details": {"trade_id": str(trade.id)}
                }
                # Send trade alert
                await self._send_trade_alert(trade)
                # Record trade for adaptive risk
                await self._record_trade_for_risk(trade)
        else:
            if validated_plan.rejected_signals:
                for signal in validated_plan.rejected_signals:
                    logger.info(f"{signal.pair}: Rejected - {signal.rejection_reason}")

        logger.info(f"[BATCH] Complete: {len(intel_list)} pairs analyzed")
        return results

    async def _process_pair(self, pair: str, portfolio: Portfolio) -> dict:
        """
        Process a single trading pair through the full pipeline.
        
        Returns:
            {"executed": bool, "action": str, "details": dict}
        """
        logger.info(f"Analyzing {pair}...")
        
        result = {"executed": False, "action": "HOLD", "details": {}}
        
        # 1. Get market data
        market_data = await self.exchange.get_market_data(pair)
        
        # 2. Run analysts
        signals = []
        for analyst in self.analysts:
            try:
                signal = await analyst.analyze(pair, market_data)
                signals.append(signal)
            except Exception as e:
                logger.error(f"Analyst {analyst.name} failed: {e}")
        
        if not signals:
            logger.warning(f"No signals for {pair}")
            return result
        
        # 3. Fuse intelligence (for Stage 1, just use first signal)
        from core.models import MarketIntel, Regime
        
        if len(signals) == 1:
            intel = MarketIntel(
                pair=pair,
                signals=signals,
                fused_direction=signals[0].direction,
                fused_confidence=signals[0].confidence,
                regime=Regime.UNKNOWN
            )
        else:
            # Simple average fusion
            direction = sum(s.direction for s in signals) / len(signals)
            confidence = sum(s.confidence for s in signals) / len(signals)
            intel = MarketIntel(
                pair=pair,
                signals=signals,
                fused_direction=direction,
                fused_confidence=confidence,
                regime=Regime.UNKNOWN
            )
        
        logger.info(f"{pair}: direction={intel.fused_direction:+.2f}, "
                   f"confidence={intel.fused_confidence:.0%}")

        # Store latest fusion for dashboard API
        self._latest_fusion = intel

        # 4. Get trading plan from strategist
        plan = await self.strategist.create_plan(intel, portfolio)
        
        # 5. Validate through sentinel
        validated_plan = await self.sentinel.validate_plan(plan, portfolio)
        
        # 6. Execute approved trades
        if validated_plan.actionable_signals:
            report = await self.executor.execute(validated_plan)

            result["executed"] = len(report.successful_trades) > 0
            result["action"] = validated_plan.signals[0].action.value if validated_plan.signals else "HOLD"
            result["details"] = report.to_dict()

            # Send trade alerts and record for adaptive risk
            for trade in report.successful_trades:
                await self._send_trade_alert(trade)
                await self._record_trade_for_risk(trade)
        else:
            result["action"] = "HOLD"
            if validated_plan.rejected_signals:
                reasons = [s.rejection_reason for s in validated_plan.rejected_signals]
                logger.info(f"{pair}: No action - {reasons}")
        
        return result
    
    async def start(self):
        """Start the orchestrator (for async context)"""
        self._running = True
        logger.info("Orchestrator started")
    
    async def stop(self):
        """Stop the orchestrator"""
        self._running = False
        logger.info("Orchestrator stopped")
    
    @property
    def is_running(self) -> bool:
        return self._running

    # =========================================================================
    # Alert Helper Methods
    # =========================================================================

    async def _send_trade_alert(self, trade) -> None:
        """Send alert for executed trade"""
        if not self._alert_manager:
            return

        try:
            await self._alert_manager.trade_executed(
                pair=trade.pair,
                action=trade.action.value,
                price=trade.price,
                amount=trade.amount,
                pnl=getattr(trade, 'pnl', None)
            )
        except Exception as e:
            logger.debug(f"Trade alert failed: {e}")

    async def _send_stop_loss_alert(self, trade) -> None:
        """Send alert for stop-loss triggered"""
        if not self._alert_manager:
            return

        try:
            entry_price = getattr(trade, 'entry_price', trade.price)
            exit_price = trade.price
            loss_pct = (entry_price - exit_price) / entry_price if entry_price > 0 else 0

            await self._alert_manager.stop_loss_triggered(
                pair=trade.pair,
                entry_price=entry_price,
                exit_price=exit_price,
                loss_pct=abs(loss_pct)
            )
        except Exception as e:
            logger.debug(f"Stop-loss alert failed: {e}")

    async def _check_milestones(self, portfolio: Portfolio) -> None:
        """Check and alert on portfolio milestones (every 10%)"""
        if not self._alert_manager:
            return

        try:
            progress = portfolio.progress_to_target
            milestone = int(progress // 10) * 10

            if milestone > self._last_milestone_pct and milestone > 0:
                await self._send_milestone_alert(portfolio, milestone)
                self._last_milestone_pct = milestone
        except Exception as e:
            logger.debug(f"Milestone check failed: {e}")

    async def _send_milestone_alert(self, portfolio: Portfolio, milestone: float) -> None:
        """Send alert for portfolio milestone"""
        if not self._alert_manager:
            return

        try:
            await self._alert_manager.portfolio_milestone(
                current_value=portfolio.total_value,
                target_value=portfolio.target_value,
                progress_pct=milestone / 100.0
            )
        except Exception as e:
            logger.debug(f"Milestone alert failed: {e}")

    async def _record_trade_for_risk(self, trade) -> None:
        """Record trade result for adaptive risk management"""
        if not self._risk_manager:
            return

        try:
            pnl = trade.realized_pnl or 0
            # Calculate pnl_percent if not available
            if trade.realized_pnl_percent:
                pnl_percent = trade.realized_pnl_percent
            elif trade.average_price and trade.entry_price and trade.entry_price > 0:
                pnl_percent = ((trade.average_price - trade.entry_price) / trade.entry_price) * 100
            else:
                pnl_percent = 0

            self._risk_manager.record_trade(
                pair=trade.pair,
                pnl=pnl,
                pnl_percent=pnl_percent
            )
        except Exception as e:
            logger.debug(f"Failed to record trade for risk manager: {e}")

    async def _update_risk_manager_portfolio(self, portfolio: Portfolio) -> None:
        """Update risk manager with portfolio value for drawdown tracking"""
        if not self._risk_manager:
            return

        try:
            self._risk_manager.update_portfolio_value(portfolio.total_value)
        except Exception as e:
            logger.debug(f"Failed to update risk manager portfolio: {e}")
