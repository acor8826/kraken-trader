"""
Meme Orchestrator

Main 3-minute trading cycle coordinator for meme coins.
Ties together listing detection, twitter sentiment, volume momentum,
strategist decision-making, sentinel risk management, and trade execution.
"""

import logging
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

    async def run_cycle(self) -> Dict:
        """
        Execute the full meme trading cycle.

        Returns a results dict with cycle_count, timestamp, coins_analyzed,
        trades_executed, twitter_budget, and any errors encountered.
        """
        self._last_errors = []
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

        # 3. Periodic listing detection
        if self._cycle_count % self.config.listing_check_every_n_cycles == 0:
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

        # Assign default tiers for new coins
        for symbol in all_symbols:
            if symbol not in self._coin_tiers:
                self._coin_tiers[symbol] = MemeTier.COLD

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
                last_price = float(ticker.get("last", 0) or 0)
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

                # 8e. Risk validation
                plan = await self.sentinel.validate_plan(plan, portfolio)

                # 8f. Execute approved actionable trades
                for signal in plan.actionable_signals:
                    try:
                        trade_result = await self._execute_signal(signal, symbol, pair, portfolio, last_price)
                        if trade_result:
                            trades_executed.append(trade_result)
                    except Exception as e:
                        err = f"Execution error for {symbol}: {e}"
                        logger.error("[MEME] %s", err)
                        self._last_errors.append(err)

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

    async def _execute_signal(
        self,
        signal,
        symbol: str,
        pair: str,
        portfolio: Portfolio,
        last_price: float,
    ) -> Optional[Dict]:
        """Execute a single approved trade signal and manage position state."""
        from core.models import TradingPlan

        # Wrap signal in a plan for the executor
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

            # Clean up position
            self.strategist.update_position(symbol, None)
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
            available_aud = float(balance.get("AUD", balance.get("ZAUD", 0)))
            portfolio = Portfolio(
                available_quote=available_aud,
                quote_currency="AUD",
            )
            return portfolio
        except Exception as e:
            logger.warning("[MEME] Failed to get balance: %s", e)
            return Portfolio(available_quote=0.0, quote_currency="AUD")

    async def _update_sentinel_context(self) -> None:
        """Update sentinel with current portfolio context."""
        try:
            balance = await self.exchange.get_balance()
            total_aud = float(balance.get("AUD", balance.get("ZAUD", 0)))
        except Exception:
            total_aud = 0.0

        # Compute meme exposure from tracked positions
        meme_exposure = 0.0
        for symbol, position in self._positions.items():
            if hasattr(position, '_current_price') and position._current_price:
                meme_exposure += position._current_price * position.amount
            else:
                # Fallback to entry price
                meme_exposure += position.entry_price * position.amount

        total_portfolio_value = total_aud + meme_exposure

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
        }

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
