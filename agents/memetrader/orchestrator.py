"""
Meme Orchestrator

Main 3-minute trading cycle coordinator for meme coins.
Ties together listing detection, twitter sentiment, volume momentum,
strategist decision-making, sentinel risk management, and trade execution.
"""

import logging
from collections import deque
from typing import Dict, List, Optional
from datetime import datetime, timezone

from agents.memetrader.config import MemeConfig
from agents.memetrader.models import MemeTier, MemePosition, MemeBudgetState, CoinSentiment, MomentumSnapshot
from agents.memetrader.listing_detector import ListingDetector
from agents.memetrader.twitter_analyst import TwitterSentimentAnalyst
from agents.memetrader.volume_analyst import VolumeMomentumAnalyst
from agents.memetrader.meme_strategist import MemeStrategist
from agents.memetrader.meme_sentinel import MemeSentinel
from core.interfaces import IExchange, IExecutor
from core.models import MarketIntel, Portfolio, AnalystSignal, TradeAction, Regime

logger = logging.getLogger(__name__)


class MemeOrchestrator:
    """
    3-minute meme coin trading cycle coordinator.

    Orchestrates the full pipeline: listing detection -> data fetch ->
    twitter + volume analysis -> signal fusion -> strategy -> risk check -> execution.

    Coins are tiered (HOT/WARM/COLD) to control polling frequency.
    Active positions are always forced to HOT tier.
    """

    def __init__(
        self,
        exchange: IExchange,
        executor: IExecutor,
        twitter_analyst: TwitterSentimentAnalyst,
        volume_analyst: VolumeMomentumAnalyst,
        strategist: MemeStrategist,
        sentinel: MemeSentinel,
        listing_detector: ListingDetector,
        config: MemeConfig = None,
    ):
        self.exchange = exchange
        self.executor = executor
        self.twitter_analyst = twitter_analyst
        self.volume_analyst = volume_analyst
        self.strategist = strategist
        self.sentinel = sentinel
        self.listing_detector = listing_detector
        self.config = config or MemeConfig()

        # Internal state
        self._cycle_count: int = 0
        self._coin_tiers: Dict[str, MemeTier] = {}
        self._positions: Dict[str, MemePosition] = {}
        self._last_errors: List[str] = []

        # Evidence trail: per-coin analysis snapshots
        self._analysis_history: deque = deque(maxlen=200)
        self._latest_cycle_analyses: List[Dict] = []

    async def run_cycle(self) -> Dict:
        """
        Execute the full meme trading cycle.

        Returns a results dict with cycle_count, timestamp, coins_analyzed,
        trades_executed, twitter_budget, and any errors encountered.
        """
        self._last_errors = []
        self._latest_cycle_analyses = []
        trades_executed: List[Dict] = []
        coins_analyzed: List[str] = []
        now = datetime.now(timezone.utc)

        # 1. System health check
        if not await self.sentinel.system_healthy():
            status = self.sentinel.get_status()
            logger.info("[MEME] Cycle skipped - sentinel reports unhealthy: %s", status)
            return {
                "cycle_count": self._cycle_count,
                "timestamp": now.isoformat(),
                "skipped": True,
                "reason": "sentinel_unhealthy",
                "sentinel_status": status,
                "coins_analyzed": [],
                "trades_executed": [],
                "twitter_budget": self.twitter_analyst.budget.to_dict(),
                "errors": [],
            }

        # 2. Increment cycle count
        self._cycle_count += 1
        logger.info("[MEME] === Cycle %d starting ===", self._cycle_count)

        # 3. Periodic listing detection (also run if no pairs known yet)
        if self._cycle_count % self.config.listing_check_every_n_cycles == 0 or not self.listing_detector.active_pairs:
            try:
                await self.listing_detector.detect_meme_pairs()
                logger.info("[MEME] Listing detection complete: %d pairs", len(self.listing_detector.active_pairs))
            except Exception as e:
                err = f"Listing detection failed: {e}"
                logger.warning("[MEME] %s", err)
                self._last_errors.append(err)

        # 4. Get active symbols
        all_symbols = self.listing_detector.active_symbols
        active_pairs = self.listing_detector.active_pairs

        if not all_symbols:
            logger.info("[MEME] No active meme pairs found, skipping cycle")
            return {
                "cycle_count": self._cycle_count,
                "timestamp": now.isoformat(),
                "skipped": True,
                "reason": "no_active_pairs",
                "coins_analyzed": [],
                "trades_executed": [],
                "twitter_budget": self.twitter_analyst.budget.to_dict(),
                "errors": self._last_errors,
            }

        # Assign default tiers for new coins — start WARM so they get
        # polled within the first few cycles instead of waiting 10 cycles
        for symbol in all_symbols:
            if symbol not in self._coin_tiers:
                self._coin_tiers[symbol] = MemeTier.WARM

        # 5. Filter symbols by tier for this cycle
        polled_symbols: List[str] = []
        for symbol in all_symbols:
            # Coins with active positions are forced HOT
            if symbol in self._positions:
                self._coin_tiers[symbol] = MemeTier.HOT

            tier = self._coin_tiers.get(symbol, MemeTier.COLD)

            if tier == MemeTier.HOT:
                polled_symbols.append(symbol)
            elif tier == MemeTier.WARM and self._cycle_count % 3 == 0:
                polled_symbols.append(symbol)
            elif tier == MemeTier.COLD and self._cycle_count % 10 == 0:
                polled_symbols.append(symbol)

        if not polled_symbols:
            logger.debug("[MEME] No symbols polled this cycle (tier filtering)")
            return {
                "cycle_count": self._cycle_count,
                "timestamp": now.isoformat(),
                "skipped": False,
                "reason": "no_symbols_polled",
                "coins_analyzed": [],
                "trades_executed": [],
                "twitter_budget": self.twitter_analyst.budget.to_dict(),
                "errors": self._last_errors,
            }

        logger.info("[MEME] Polling %d symbols: %s", len(polled_symbols), polled_symbols)

        # 6. Batch twitter fetch for all polled symbols
        try:
            await self.twitter_analyst.fetch_and_classify_batch(polled_symbols)
        except Exception as e:
            err = f"Twitter batch fetch failed: {e}"
            logger.warning("[MEME] %s", err)
            self._last_errors.append(err)

        # 7. Get portfolio for strategist
        portfolio = await self._build_portfolio()

        # Current prices collected for trailing stop updates
        current_prices: Dict[str, float] = {}

        # 8. Per-coin analysis and trading
        for symbol in polled_symbols:
            try:
                pair = active_pairs.get(symbol)
                if not pair:
                    logger.debug("[MEME] No pair mapping for %s, skipping", symbol)
                    continue

                coins_analyzed.append(symbol)

                # 8a. Fetch market data
                market_data = await self._fetch_market_data(pair)
                ticker = market_data.get("ticker", {})

                # Track current price
                last_price = float(ticker.get("last", 0) or ticker.get("price", 0) or 0)
                if last_price > 0:
                    current_prices[symbol] = last_price

                # Update position price tracking
                if symbol in self._positions and last_price > 0:
                    self._positions[symbol].update_price(last_price)

                # 8b. Run analysts (sequential - they use cached batch data)
                twitter_signal = await self.twitter_analyst.analyze(pair, market_data)
                volume_signal = await self.volume_analyst.analyze(pair, market_data)

                # 8c. Fuse signals
                tw_weight = self.config.twitter_weight
                vol_weight = self.config.volume_weight

                fused_direction = (
                    twitter_signal.direction * tw_weight +
                    volume_signal.direction * vol_weight
                )
                fused_confidence = (
                    twitter_signal.confidence * tw_weight +
                    volume_signal.confidence * vol_weight
                )

                intel = MarketIntel(
                    pair=pair,
                    signals=[twitter_signal, volume_signal],
                    fused_direction=fused_direction,
                    fused_confidence=fused_confidence,
                    regime=Regime.VOLATILE,
                )

                logger.debug(
                    "[MEME] %s fused: dir=%.3f conf=%.3f (tw=%.2f/%.2f vol=%.2f/%.2f)",
                    symbol, fused_direction, fused_confidence,
                    twitter_signal.direction, twitter_signal.confidence,
                    volume_signal.direction, volume_signal.confidence,
                )

                # 8d. Strategy decision
                plan = await self.strategist.create_plan(intel, portfolio)

                # Capture pre-sentinel size for evidence trail
                original_size = plan.signals[0].size_pct if plan.signals else 0

                # 8e. Risk validation
                plan = await self.sentinel.validate_plan(plan, portfolio)

                # 8f. Build analysis snapshot (evidence trail)
                snapshot = self._build_analysis_snapshot(
                    symbol, pair, twitter_signal, volume_signal,
                    intel, plan, original_size, now,
                )

                # 8g. Execute approved actionable trades
                for signal in plan.actionable_signals:
                    try:
                        trade_result = await self._execute_signal(signal, symbol, pair, portfolio, last_price)
                        if trade_result:
                            trades_executed.append(trade_result)
                            snapshot["execution"] = {
                                "executed": True,
                                "fill_price": trade_result.get("price", 0),
                                "fill_amount": trade_result.get("amount", 0),
                                "fill_value": trade_result.get("value", 0),
                            }
                    except Exception as e:
                        err = f"Execution error for {symbol}: {e}"
                        logger.error("[MEME] %s", err)
                        self._last_errors.append(err)

                self._latest_cycle_analyses.append(snapshot)
                self._analysis_history.append(snapshot)

            except Exception as e:
                err = f"Error processing {symbol}: {e}"
                logger.error("[MEME] %s", err)
                self._last_errors.append(err)

        # 9. Update sentinel portfolio context
        try:
            await self._update_sentinel_context()
        except Exception as e:
            err = f"Failed to update sentinel context: {e}"
            logger.warning("[MEME] %s", err)
            self._last_errors.append(err)

        # 10. Update trailing stops
        try:
            self.strategist.update_trailing_stops(current_prices)
        except Exception as e:
            err = f"Failed to update trailing stops: {e}"
            logger.warning("[MEME] %s", err)
            self._last_errors.append(err)

        # Build results
        result = {
            "cycle_count": self._cycle_count,
            "timestamp": now.isoformat(),
            "skipped": False,
            "coins_analyzed": coins_analyzed,
            "trades_executed": trades_executed,
            "twitter_budget": self.twitter_analyst.budget.to_dict(),
            "errors": self._last_errors,
        }

        logger.info(
            "[MEME] === Cycle %d complete: %d analyzed, %d trades, %d errors ===",
            self._cycle_count, len(coins_analyzed), len(trades_executed), len(self._last_errors),
        )

        return result

    def _build_analysis_snapshot(
        self, symbol: str, pair: str, twitter_signal, volume_signal,
        intel: MarketIntel, plan, original_size: float, now: datetime,
    ) -> Dict:
        """Build a per-coin analysis snapshot capturing all evidence."""
        signal = plan.signals[0] if plan.signals else None
        reasoning = plan.reasoning or ""

        # Detect decision method
        if reasoning.startswith("Haiku:"):
            method = "haiku"
        elif "(no LLM)" in reasoning:
            method = "rule_fallback"
        else:
            method = "rule"

        # Detect thresholds mode
        twitter_available = twitter_signal.confidence > 0.01
        if twitter_available:
            thresholds = {
                "entry_cms": self.config.entry_cms_threshold,
                "ambiguous_lower": self.config.ambiguous_cms_lower,
                "min_vol_z": self.config.min_volume_z_score,
                "mode": "twitter_and_volume",
            }
        else:
            thresholds = {
                "entry_cms": 0.25,
                "ambiguous_lower": 0.15,
                "min_vol_z": 1.0,
                "mode": "volume_only",
            }

        # Sentinel result
        final_size = signal.size_pct if signal else 0
        size_modified = abs(final_size - original_size) > 0.0001

        return {
            "symbol": symbol,
            "pair": pair,
            "cycle": self._cycle_count,
            "timestamp": now.isoformat(),
            "tier": self._coin_tiers.get(symbol, MemeTier.COLD).value,
            "twitter": {
                "searched": True,
                "mention_count": twitter_signal.metadata.get("mention_count", 0),
                "sentiment_score": twitter_signal.metadata.get("sentiment_score", 0),
                "bullish_ratio": twitter_signal.metadata.get("bullish_ratio", 0),
                "influencer_mentions": twitter_signal.metadata.get("influencer_mentions", 0),
                "engagement_rate": twitter_signal.metadata.get("engagement_rate", 0),
                "mention_velocity": twitter_signal.metadata.get("mention_velocity", 0),
                "signal_direction": round(twitter_signal.direction, 4),
                "signal_confidence": round(twitter_signal.confidence, 4),
            },
            "volume": {
                "volume_z_score": volume_signal.metadata.get("volume_z_score", 0),
                "price_momentum_5m": volume_signal.metadata.get("price_momentum_5m", 0),
                "price_momentum_15m": volume_signal.metadata.get("price_momentum_15m", 0),
                "buy_sell_ratio": volume_signal.metadata.get("buy_sell_ratio", 0),
                "spread_pct": volume_signal.metadata.get("spread_pct", 0),
                "signal_direction": round(volume_signal.direction, 4),
                "signal_confidence": round(volume_signal.confidence, 4),
            },
            "fusion": {
                "cms": round(intel.fused_direction, 4),
                "fused_confidence": round(intel.fused_confidence, 4),
                "twitter_weight": self.config.twitter_weight,
                "volume_weight": self.config.volume_weight,
            },
            "decision": {
                "action": signal.action.value if signal else "HOLD",
                "method": method,
                "confidence": round(signal.confidence, 4) if signal else 0,
                "size_pct": round(final_size, 6) if signal else 0,
                "reasoning": reasoning,
                "thresholds_used": thresholds,
            },
            "sentinel": {
                "approved": signal.status.value == "approved" if signal else False,
                "rejection_reason": signal.rejection_reason if signal else None,
                "size_modified": size_modified,
                "original_size_pct": round(original_size, 6) if size_modified else None,
            },
            "execution": {
                "executed": False,
                "fill_price": None,
                "fill_amount": None,
                "fill_value": None,
            },
        }

    async def _execute_signal(
        self,
        signal,
        symbol: str,
        pair: str,
        portfolio: Portfolio,
        last_price: float,
    ) -> Optional[Dict]:
        """Execute a single approved trade signal and manage position state."""
        from core.models import TradingPlan, Trade, TradeStatus

        # For SELL orders, if we have a tracked position with a known amount,
        # bypass the executor's balance lookup (which returns 0 for simulation
        # meme coins) and call the exchange directly with the exact tracked amount.
        if signal.action == TradeAction.SELL:
            tracked = self._positions.get(symbol)
            if tracked and tracked.amount > 0:
                sell_amount = tracked.amount * signal.size_pct if signal.size_pct < 1.0 else tracked.amount
                if sell_amount > 0:
                    try:
                        result = await self.exchange.market_sell(pair, sell_amount)
                        # Check if the exchange rejected the sell (e.g. sim has no balance)
                        if result.get("error"):
                            logger.warning(
                                "[MEME] Direct sell rejected for %s: %s",
                                symbol, result["error"],
                            )
                            return None
                        avg_price = (
                            result.get("price")
                            or result.get("average")
                            or last_price
                        )
                        if not avg_price or avg_price <= 0:
                            avg_price = last_price
                        trade_obj = Trade(
                            pair=pair,
                            action=signal.action,
                            status=TradeStatus.FILLED,
                            filled_size_base=sell_amount,
                            average_price=avg_price,
                            filled_size_quote=sell_amount * avg_price,
                            signal_confidence=signal.confidence,
                            reasoning=signal.reasoning,
                        )
                        # Build a minimal mock report so the rest of the code path
                        # (position cleanup, PnL recording) proceeds as normal.
                        class _MockReport:
                            successful_trades = [trade_obj]
                        report = _MockReport()
                        logger.debug(
                            "[MEME] Direct sell %s: %.6f @ $%.6f (bypassed executor balance lookup)",
                            symbol, sell_amount, avg_price,
                        )
                    except Exception as e:
                        logger.error("[MEME] Direct sell failed for %s: %s", symbol, e)
                        return None
                else:
                    logger.warning("[MEME] Tracked position for %s has zero sell amount, skipping", symbol)
                    return None
            else:
                # No tracked position: fall through to executor (may still fail if balance=0)
                logger.warning("[MEME] No tracked position for %s sell, falling back to executor", symbol)
                exec_plan = TradingPlan(
                    signals=[signal],
                    strategy_name="meme_momentum",
                    regime="volatile",
                    overall_confidence=signal.confidence,
                    reasoning=signal.reasoning,
                )
                report = await self.executor.execute(exec_plan)
                if not report.successful_trades:
                    logger.info("[MEME] No fills for %s %s (no tracked position)", signal.action.value, symbol)
                    return None
        else:
            # BUY and HOLD: use executor as normal
            exec_plan = TradingPlan(
                signals=[signal],
                strategy_name="meme_momentum",
                regime="volatile",
                overall_confidence=signal.confidence,
                reasoning=signal.reasoning,
            )

            report = await self.executor.execute(exec_plan)

            if not report.successful_trades:
                logger.info("[MEME] No fills for %s %s", signal.action.value, symbol)
                return None

        trade = report.successful_trades[0]

        if signal.action == TradeAction.BUY:
            # Create position tracking
            position = MemePosition(
                symbol=symbol,
                pair=pair,
                entry_price=trade.average_price,
                amount=trade.filled_size_base,
            )
            self._positions[symbol] = position
            self.strategist.update_position(symbol, position)
            self._coin_tiers[symbol] = MemeTier.HOT

            logger.info(
                "[MEME] BUY %s: %.6f @ $%.6f ($%.2f)",
                symbol, trade.filled_size_base, trade.average_price, trade.filled_size_quote,
            )

            return {
                "action": "BUY",
                "symbol": symbol,
                "pair": pair,
                "amount": trade.filled_size_base,
                "price": trade.average_price,
                "value": trade.filled_size_quote,
            }

        elif signal.action == TradeAction.SELL:
            # Calculate PnL
            position = self._positions.get(symbol)
            pnl = 0.0
            if position:
                pnl = (trade.average_price - position.entry_price) * trade.filled_size_base

            # Record with sentinel
            self.sentinel.record_meme_trade_result(pnl)

            # Check if this is a partial sell (remaining position > min trade size)
            remaining_amount = 0.0
            if position:
                remaining_amount = position.amount - trade.filled_size_base

            if remaining_amount > 0 and remaining_amount * trade.average_price >= self.config.min_trade_size_quote:
                # Partial sell: update position amount, keep tracking
                position.amount = remaining_amount
                self.strategist.update_position(symbol, position)
                logger.info(
                    "[MEME] PARTIAL SELL %s: %.6f @ $%.6f (PnL: $%.2f, remaining: %.6f)",
                    symbol, trade.filled_size_base, trade.average_price, pnl, remaining_amount,
                )
            else:
                # Full exit: clean up position
                self.strategist.update_position(symbol, None)
                # Clear TP targets tracking
                if hasattr(self.strategist, '_tp_targets_hit'):
                    self.strategist._tp_targets_hit.pop(symbol, None)
                self._positions.pop(symbol, None)
                self._coin_tiers[symbol] = MemeTier.WARM
                logger.info(
                    "[MEME] SELL %s: %.6f @ $%.6f (PnL: $%.2f)",
                    symbol, trade.filled_size_base, trade.average_price, pnl,
                )

            return {
                "action": "SELL",
                "symbol": symbol,
                "pair": pair,
                "amount": trade.filled_size_base,
                "price": trade.average_price,
                "value": trade.filled_size_quote,
                "pnl": pnl,
            }

        return None

    async def _fetch_market_data(self, pair: str) -> Dict:
        """Fetch all market data needed for analysts."""
        market_data: Dict = {}

        try:
            market_data["ticker"] = await self.exchange.get_ticker(pair)
        except Exception as e:
            logger.warning("[MEME] Failed to get ticker for %s: %s", pair, e)
            market_data["ticker"] = {}

        try:
            market_data["ohlcv_5m"] = await self.exchange.get_ohlcv(pair, 5, 48)
        except Exception as e:
            logger.warning("[MEME] Failed to get 5m OHLCV for %s: %s", pair, e)
            market_data["ohlcv_5m"] = []

        try:
            market_data["ohlcv_15m"] = await self.exchange.get_ohlcv(pair, 15, 24)
        except Exception as e:
            logger.warning("[MEME] Failed to get 15m OHLCV for %s: %s", pair, e)
            market_data["ohlcv_15m"] = []

        try:
            market_data["order_book"] = await self.exchange.get_order_book(pair, 25)
        except AttributeError:
            # Exchange may not support order book
            market_data["order_book"] = {}
        except Exception as e:
            logger.debug("[MEME] Order book unavailable for %s: %s", pair, e)
            market_data["order_book"] = {}

        return market_data

    async def _build_portfolio(self) -> Portfolio:
        """Build a Portfolio object from exchange balance."""
        try:
            balance = await self.exchange.get_balance()
            qc = getattr(self.exchange, '_quote', 'AUD')
            available = float(balance.get(qc, 0))
            portfolio = Portfolio(
                available_quote=available,
                quote_currency=qc,
            )
            return portfolio
        except Exception as e:
            logger.warning("[MEME] Failed to get balance: %s", e)
            return Portfolio(available_quote=0.0, quote_currency="AUD")

    async def _update_sentinel_context(self) -> None:
        """Update sentinel with current portfolio context."""
        try:
            balance = await self.exchange.get_balance()
            qc = getattr(self.exchange, '_quote', 'AUD')
            total_quote = float(balance.get(qc, 0))
        except Exception:
            total_quote = 0.0

        # Compute meme exposure from tracked positions
        meme_exposure = 0.0
        for symbol, position in self._positions.items():
            if hasattr(position, '_current_price') and position._current_price:
                meme_exposure += position._current_price * position.amount
            else:
                # Fallback to entry price
                meme_exposure += position.entry_price * position.amount

        total_portfolio_value = total_quote + meme_exposure

        self.sentinel.update_portfolio_context(
            total_portfolio_value=total_portfolio_value,
            meme_exposure=meme_exposure,
            active_positions=len(self._positions),
        )

        logger.debug(
            "[MEME] Sentinel context updated: total=$%.2f, meme_exposure=$%.2f, positions=%d",
            total_portfolio_value, meme_exposure, len(self._positions),
        )

    def get_status(self) -> Dict:
        """Get complete orchestrator status."""
        return {
            "enabled": True,
            "cycle_count": self._cycle_count,
            "positions": {
                symbol: pos.to_dict() for symbol, pos in self._positions.items()
            },
            "coin_tiers": {
                symbol: tier.value for symbol, tier in self._coin_tiers.items()
            },
            "active_pairs_count": len(self.listing_detector.active_pairs),
            "sentinel_status": self.sentinel.get_status(),
            "twitter_budget": self.twitter_analyst.budget.to_dict(),
            "strategist_stats": self.strategist.get_stats(),
            "last_errors": self._last_errors,
            "latest_analyses": list(self._latest_cycle_analyses),
        }

    def get_analysis_history(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """Get recent analysis snapshots, optionally filtered by symbol."""
        history = list(self._analysis_history)
        if symbol:
            history = [a for a in history if a["symbol"] == symbol]
        return list(reversed(history))[:limit]

    async def get_portfolio_context(self) -> Dict:
        """
        Helper to fetch exchange balance, compute meme exposure,
        and update sentinel context. Returns context dict.
        """
        await self._update_sentinel_context()

        meme_exposure = 0.0
        for symbol, position in self._positions.items():
            if hasattr(position, '_current_price') and position._current_price:
                meme_exposure += position._current_price * position.amount
            else:
                meme_exposure += position.entry_price * position.amount

        return {
            "meme_exposure": meme_exposure,
            "active_positions": len(self._positions),
            "positions": {
                symbol: pos.to_dict() for symbol, pos in self._positions.items()
            },
        }
