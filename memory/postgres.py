"""
PostgreSQL-backed persistent storage for Phase 2.

Implements IMemory interface with full database persistence for:
- Portfolio snapshots
- Trade history
- Entry prices
- Analyst signals
- System events
"""

import logging
import json
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import asyncpg

from core.interfaces import IMemory
from core.models.portfolio import Portfolio, Position
from core.models.trading import Trade, TradeAction, TradeStatus, OrderType
from core.models.signals import MarketIntel

logger = logging.getLogger(__name__)


class PostgresStore(IMemory):
    """PostgreSQL-backed persistent storage"""

    def __init__(self, database_url: str):
        """
        Initialize PostgreSQL store.

        Args:
            database_url: PostgreSQL connection string
                          (e.g., postgresql://user:pass@host:port/db)
        """
        self.database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None
        logger.info("PostgresStore initialized")

    async def connect(self):
        """Initialize connection pool"""
        try:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            logger.info("PostgreSQL connection pool created")

            # Verify connection
            async with self._pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"Connected to PostgreSQL: {version}")

        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self):
        """Close connection pool"""
        if self._pool:
            await self._pool.close()
            logger.info("PostgreSQL connection pool closed")

    @asynccontextmanager
    async def _connection(self):
        """Get connection from pool"""
        if not self._pool:
            raise RuntimeError("PostgresStore not connected. Call connect() first.")

        async with self._pool.acquire() as conn:
            yield conn

    # =========================================================================
    # IMemory Interface Implementation
    # =========================================================================

    async def get_portfolio(self) -> Portfolio:
        """Get latest portfolio snapshot"""
        try:
            async with self._connection() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM portfolio_snapshots
                    ORDER BY created_at DESC LIMIT 1
                """)

                if not row:
                    logger.warning("No portfolio snapshot found, returning default")
                    return Portfolio()

                # Parse positions from JSONB
                positions_data = json.loads(row["positions"]) if isinstance(row["positions"], str) else row["positions"]
                positions = {}

                for symbol, pos_data in positions_data.items():
                    positions[symbol] = Position(
                        symbol=symbol,
                        amount=float(pos_data.get("amount", 0)),
                        entry_price=float(pos_data.get("entry_price", 0)),
                        current_price=float(pos_data.get("current_price", 0))
                    )

                portfolio = Portfolio(
                    available_quote=float(row["available_quote"]),
                    positions=positions,
                    timestamp=row["created_at"]
                )

                logger.debug(f"Retrieved portfolio: {portfolio.total_value:.2f} AUD")
                return portfolio

        except Exception as e:
            logger.error(f"Failed to get portfolio: {e}")
            raise

    async def save_portfolio(self, portfolio: Portfolio) -> None:
        """Save portfolio snapshot"""
        try:
            # Serialize positions to JSON
            positions_json = {}
            for symbol, position in portfolio.positions.items():
                positions_json[symbol] = {
                    "amount": position.amount,
                    "entry_price": position.entry_price,
                    "current_price": position.current_price,
                    "peak_price": position.peak_price,
                    "trailing_stop_active": position.trailing_stop_active,
                    "trailing_stop_price": position.trailing_stop_price,
                }

            async with self._connection() as conn:
                await conn.execute("""
                    INSERT INTO portfolio_snapshots
                    (available_quote, total_value, positions, created_at)
                    VALUES ($1, $2, $3, $4)
                """,
                    portfolio.available_quote,
                    portfolio.total_value,
                    json.dumps(positions_json),
                    portfolio.timestamp or datetime.now(timezone.utc)
                )

            logger.debug(f"Saved portfolio snapshot: {portfolio.total_value:.2f} AUD")

        except Exception as e:
            logger.error(f"Failed to save portfolio: {e}")
            raise

    async def record_trade(
        self,
        trade: Trade,
        intel: Optional[MarketIntel] = None
    ) -> None:
        """Record executed trade with associated signals"""
        try:
            async with self._connection() as conn:
                async with conn.transaction():
                    # Insert trade
                    # Read DGM variant ID from environment if set
                    dgm_variant_raw = os.environ.get('DGM_VARIANT_ID')
                    dgm_variant_id = int(dgm_variant_raw) if dgm_variant_raw else None

                    # Extract regime from intel (MarketIntel.regime is a Regime enum)
                    regime_value: Optional[str] = None
                    if intel and hasattr(intel, 'regime') and intel.regime is not None:
                        regime_value = intel.regime.value if hasattr(intel.regime, 'value') else str(intel.regime)

                    trade_id = await conn.fetchval("""
                        INSERT INTO trades (
                            pair, action, order_type,
                            requested_size_quote, requested_size_base,
                            filled_size_base, filled_size_quote,
                            average_price, status, exchange_order_id,
                            signal_confidence, reasoning,
                            entry_price, exit_price, realized_pnl,
                            fees_quote, realized_pnl_after_fees,
                            decision_timestamp, submitted_timestamp, filled_timestamp,
                            latency_decision_to_submit_ms, latency_submit_to_fill_ms, latency_decision_to_fill_ms,
                            dgm_variant_id,
                            created_at, updated_at,
                            regime
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, $15, $16, $17, $18,
                            $19, $20, $21, $22, $23, $24, $25, $26,
                            $27
                        ) RETURNING id
                    """,
                        trade.pair,
                        trade.action.value,
                        trade.order_type.value,
                        trade.requested_size_quote,
                        trade.requested_size_base,
                        trade.filled_size_base,
                        trade.filled_size_quote,
                        trade.average_price,
                        trade.status.value,
                        trade.exchange_order_id,
                        trade.signal_confidence,
                        trade.reasoning,
                        trade.entry_price,
                        trade.exit_price,
                        trade.realized_pnl,
                        trade.fees_quote,
                        trade.realized_pnl_after_fees,
                        trade.decision_timestamp,
                        trade.submitted_timestamp,
                        trade.filled_timestamp,
                        trade.latency_decision_to_submit_ms,
                        trade.latency_submit_to_fill_ms,
                        trade.latency_decision_to_fill_ms,
                        dgm_variant_id,
                        trade.timestamp or datetime.now(timezone.utc),
                        datetime.now(timezone.utc),
                        regime_value
                    )

                    # Insert associated signals if provided
                    if intel and hasattr(intel, 'signals'):
                        for signal in intel.signals:
                            await conn.execute("""
                                INSERT INTO signals (
                                    trade_id, source, pair,
                                    direction, confidence, reasoning, metadata,
                                    created_at
                                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """,
                                trade_id,
                                signal.source,
                                signal.pair,
                                signal.direction,
                                signal.confidence,
                                signal.reasoning,
                                json.dumps(signal.metadata) if hasattr(signal, 'metadata') and signal.metadata else None,
                                datetime.now(timezone.utc)
                            )

            logger.info(f"Recorded trade: {trade.action.value} {trade.pair} ({trade.status.value})")

        except Exception as e:
            logger.error(f"Failed to record trade: {e}")
            raise

    async def get_trade_history(self, limit: int = 100) -> List[Trade]:
        """Get recent trades"""
        try:
            async with self._connection() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM trades
                    ORDER BY created_at DESC
                    LIMIT $1
                """, limit)

                trades = []
                for row in rows:
                    trade = Trade(
                        pair=row["pair"],
                        action=TradeAction(row["action"]),
                        order_type=OrderType(row["order_type"]),
                        requested_size_quote=float(row["requested_size_quote"]) if row["requested_size_quote"] else None,
                        requested_size_base=float(row["requested_size_base"]) if row["requested_size_base"] else None,
                        filled_size_base=float(row["filled_size_base"]) if row["filled_size_base"] else None,
                        filled_size_quote=float(row["filled_size_quote"]) if row["filled_size_quote"] else None,
                        average_price=float(row["average_price"]) if row["average_price"] else None,
                        status=TradeStatus(row["status"]),
                        exchange_order_id=row["exchange_order_id"],
                        signal_confidence=float(row["signal_confidence"]) if row["signal_confidence"] else None,
                        reasoning=row["reasoning"],
                        entry_price=float(row["entry_price"]) if row["entry_price"] else None,
                        exit_price=float(row["exit_price"]) if row["exit_price"] else None,
                        realized_pnl=float(row["realized_pnl"]) if row["realized_pnl"] else None,
                        fees_quote=float(row["fees_quote"]) if "fees_quote" in row and row["fees_quote"] is not None else None,
                        realized_pnl_after_fees=float(row["realized_pnl_after_fees"]) if "realized_pnl_after_fees" in row and row["realized_pnl_after_fees"] is not None else None,
                        decision_timestamp=row["decision_timestamp"] if "decision_timestamp" in row else None,
                        submitted_timestamp=row["submitted_timestamp"] if "submitted_timestamp" in row else None,
                        filled_timestamp=row["filled_timestamp"] if "filled_timestamp" in row else None,
                        latency_decision_to_submit_ms=float(row["latency_decision_to_submit_ms"]) if "latency_decision_to_submit_ms" in row and row["latency_decision_to_submit_ms"] is not None else None,
                        latency_submit_to_fill_ms=float(row["latency_submit_to_fill_ms"]) if "latency_submit_to_fill_ms" in row and row["latency_submit_to_fill_ms"] is not None else None,
                        latency_decision_to_fill_ms=float(row["latency_decision_to_fill_ms"]) if "latency_decision_to_fill_ms" in row and row["latency_decision_to_fill_ms"] is not None else None,
                        timestamp=row["created_at"]
                    )
                    trades.append(trade)

                logger.debug(f"Retrieved {len(trades)} trades from history")
                return trades

        except Exception as e:
            logger.error(f"Failed to get trade history: {e}")
            raise

    async def get_entry_price(self, symbol: str) -> Optional[float]:
        """Get entry price for position"""
        try:
            async with self._connection() as conn:
                row = await conn.fetchrow("""
                    SELECT price FROM entry_prices
                    WHERE symbol = $1
                """, symbol)

                if row:
                    return float(row["price"])
                return None

        except Exception as e:
            logger.error(f"Failed to get entry price for {symbol}: {e}")
            raise

    async def set_entry_price(self, symbol: str, price: float, size: Optional[float] = None) -> None:
        """Set entry price for position.

        Args:
            symbol: Asset symbol (e.g. "BTC")
            price: Entry price per unit in quote currency
            size: Optional position size in base currency (accepted for interface compatibility, unused)
        """
        try:
            async with self._connection() as conn:
                await conn.execute("""
                    INSERT INTO entry_prices (symbol, price, updated_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (symbol) DO UPDATE
                    SET price = $2, updated_at = $3
                """, symbol, price, datetime.now(timezone.utc))

            logger.debug(f"Set entry price for {symbol}: {price:.2f}")

        except Exception as e:
            logger.error(f"Failed to set entry price for {symbol}: {e}")
            raise

    # =========================================================================
    # Additional Phase 2 Methods (Not in IMemory interface)
    # =========================================================================

    async def record_event(
        self,
        event_type: str,
        source: str,
        data: Dict
    ) -> None:
        """Record system event"""
        try:
            async with self._connection() as conn:
                await conn.execute("""
                    INSERT INTO events (event_type, source, data, created_at)
                    VALUES ($1, $2, $3, $4)
                """, event_type, source, json.dumps(data), datetime.now(timezone.utc))

            logger.debug(f"Recorded event: {event_type} from {source}")

        except Exception as e:
            logger.error(f"Failed to record event: {e}")
            # Don't raise - event logging should not break main flow

    async def get_daily_pnl(self) -> float:
        """Calculate P&L for current day"""
        try:
            async with self._connection() as conn:
                result = await conn.fetchval("""
                    SELECT COALESCE(SUM(realized_pnl), 0) as daily_pnl
                    FROM trades
                    WHERE DATE(created_at) = CURRENT_DATE
                    AND realized_pnl IS NOT NULL
                """)

                return float(result) if result else 0.0

        except Exception as e:
            logger.error(f"Failed to get daily P&L: {e}")
            return 0.0

    async def get_trade_count_today(self) -> int:
        """Get number of trades executed today"""
        try:
            async with self._connection() as conn:
                count = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM trades
                    WHERE DATE(created_at) = CURRENT_DATE
                """)

                return int(count) if count else 0

        except Exception as e:
            logger.error(f"Failed to get trade count: {e}")
            return 0

    async def update_analyst_performance(
        self,
        analyst_name: str,
        regime: str,
        correct: bool
    ) -> None:
        """Update analyst accuracy tracking"""
        try:
            async with self._connection() as conn:
                await conn.execute("""
                    INSERT INTO analyst_performance
                    (analyst_name, regime, total_signals, correct_signals, accuracy, updated_at)
                    VALUES ($1, $2, 1, $3::int, $3::decimal, $4)
                    ON CONFLICT (analyst_name, regime) DO UPDATE
                    SET total_signals = analyst_performance.total_signals + 1,
                        correct_signals = analyst_performance.correct_signals + $3::int,
                        accuracy = (analyst_performance.correct_signals + $3::int)::decimal /
                                  (analyst_performance.total_signals + 1),
                        updated_at = $4
                """, analyst_name, regime, correct, datetime.now(timezone.utc))

            logger.debug(f"Updated performance for {analyst_name} in {regime} regime")

        except Exception as e:
            logger.error(f"Failed to update analyst performance: {e}")
            # Don't raise - performance tracking should not break main flow

    # =========================================================================
    # Daily Portfolio Ledger
    # =========================================================================

    async def save_daily_ledger_entry(self, entry: Dict) -> None:
        """Save or update a daily portfolio ledger entry."""
        try:
            async with self._connection() as conn:
                await conn.execute("""
                    INSERT INTO daily_portfolio_ledger (
                        date, start_value, end_value, daily_pnl, daily_pnl_pct,
                        realized_pnl, unrealized_pnl, total_trades, wins, losses,
                        win_rate, main_pnl, meme_pnl, fees_total, status,
                        improvement_action, improvement_result
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17
                    )
                    ON CONFLICT (date) DO UPDATE SET
                        end_value = $3, daily_pnl = $4, daily_pnl_pct = $5,
                        realized_pnl = $6, unrealized_pnl = $7,
                        total_trades = $8, wins = $9, losses = $10,
                        win_rate = $11, main_pnl = $12, meme_pnl = $13,
                        fees_total = $14, status = $15,
                        improvement_action = COALESCE($16, daily_portfolio_ledger.improvement_action),
                        improvement_result = COALESCE($17, daily_portfolio_ledger.improvement_result)
                """,
                    entry["date"],
                    entry.get("start_value", 0),
                    entry.get("end_value", 0),
                    entry.get("daily_pnl", 0),
                    entry.get("daily_pnl_pct", 0),
                    entry.get("realized_pnl", 0),
                    entry.get("unrealized_pnl", 0),
                    entry.get("total_trades", 0),
                    entry.get("wins", 0),
                    entry.get("losses", 0),
                    entry.get("win_rate", 0),
                    entry.get("main_pnl", 0),
                    entry.get("meme_pnl", 0),
                    entry.get("fees_total", 0),
                    entry.get("status", "NO_DATA"),
                    entry.get("improvement_action"),
                    entry.get("improvement_result"),
                )
            logger.info("Saved daily ledger entry for %s: %s", entry["date"], entry.get("status"))
        except Exception as e:
            logger.error("Failed to save daily ledger entry: %s", e)
            raise

    async def get_daily_ledger(self, days: int = 30) -> List[Dict]:
        """Get recent daily portfolio ledger entries."""
        try:
            async with self._connection() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM daily_portfolio_ledger
                    ORDER BY date DESC
                    LIMIT $1
                """, days)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get daily ledger: %s", e)
            return []

    async def get_daily_ledger_entry(self, date) -> Optional[Dict]:
        """Get a specific daily ledger entry by date."""
        try:
            async with self._connection() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM daily_portfolio_ledger WHERE date = $1
                """, date)
                return dict(row) if row else None
        except Exception as e:
            logger.error("Failed to get daily ledger entry for %s: %s", date, e)
            return None

    async def get_previous_day_end_value(self, today) -> Optional[float]:
        """Get the end_value from the most recent ledger entry before today."""
        try:
            async with self._connection() as conn:
                val = await conn.fetchval("""
                    SELECT end_value FROM daily_portfolio_ledger
                    WHERE date < $1
                    ORDER BY date DESC LIMIT 1
                """, today)
                return float(val) if val is not None else None
        except Exception as e:
            logger.error("Failed to get previous day end value: %s", e)
            return None

    async def update_daily_ledger_improvement(self, date, action: str, result: str) -> None:
        """Update the improvement action/result for a daily ledger entry."""
        try:
            async with self._connection() as conn:
                await conn.execute("""
                    UPDATE daily_portfolio_ledger
                    SET improvement_action = $2, improvement_result = $3
                    WHERE date = $1
                """, date, action, result)
            logger.info("Updated improvement info for %s", date)
        except Exception as e:
            logger.error("Failed to update improvement for %s: %s", date, e)

    async def get_daily_profit_streak(self) -> Dict:
        """Get current profit/loss streak and summary stats."""
        try:
            async with self._connection() as conn:
                rows = await conn.fetch("""
                    SELECT date, daily_pnl, status FROM daily_portfolio_ledger
                    ORDER BY date DESC LIMIT 14
                """)
                if not rows:
                    return {"streak_type": "none", "streak_days": 0, "total_days": 0,
                            "profit_days": 0, "loss_days": 0, "stagnant_days": 0}

                streak_type = rows[0]["status"]
                streak_days = 0
                for r in rows:
                    if r["status"] == streak_type:
                        streak_days += 1
                    else:
                        break

                profit_days = sum(1 for r in rows if r["status"] == "PROFIT")
                loss_days = sum(1 for r in rows if r["status"] == "LOSS")
                stagnant_days = sum(1 for r in rows if r["status"] == "STAGNANT")

                return {
                    "streak_type": streak_type,
                    "streak_days": streak_days,
                    "total_days": len(rows),
                    "profit_days": profit_days,
                    "loss_days": loss_days,
                    "stagnant_days": stagnant_days,
                }
        except Exception as e:
            logger.error("Failed to get daily profit streak: %s", e)
            return {"streak_type": "none", "streak_days": 0, "total_days": 0,
                    "profit_days": 0, "loss_days": 0, "stagnant_days": 0}

    async def get_daily_fees_today(self) -> float:
        """Get total fees paid today."""
        try:
            async with self._connection() as conn:
                val = await conn.fetchval("""
                    SELECT COALESCE(SUM(fees_quote), 0)
                    FROM trades
                    WHERE DATE(created_at) = CURRENT_DATE
                    AND fees_quote IS NOT NULL
                """)
                return float(val) if val else 0.0
        except Exception as e:
            logger.error("Failed to get daily fees: %s", e)
            return 0.0

    async def get_performance_summary(self) -> dict:
        """Return a performance summary dict used by /performance endpoint and daily profit review."""
        try:
            async with self._connection() as conn:
                # 7-day window
                row_7d = await conn.fetchrow("""
                    SELECT
                        COUNT(*) FILTER (WHERE action = 'SELL' AND realized_pnl IS NOT NULL) AS closed_trades,
                        COUNT(*) FILTER (WHERE action = 'SELL' AND realized_pnl > 0) AS wins,
                        COUNT(*) FILTER (WHERE action = 'SELL' AND realized_pnl < 0) AS losses,
                        COALESCE(SUM(realized_pnl) FILTER (WHERE action = 'SELL' AND realized_pnl > 0), 0) AS gross_wins,
                        COALESCE(ABS(SUM(realized_pnl) FILTER (WHERE action = 'SELL' AND realized_pnl < 0)), 0) AS gross_losses,
                        COALESCE(SUM(realized_pnl) FILTER (WHERE action = 'SELL' AND realized_pnl IS NOT NULL), 0) AS net_pnl,
                        COUNT(*) AS total_actions
                    FROM trades
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                """)
                # 30-day window
                row_30d = await conn.fetchrow("""
                    SELECT
                        COUNT(*) FILTER (WHERE action = 'SELL' AND realized_pnl IS NOT NULL) AS closed_trades,
                        COUNT(*) FILTER (WHERE action = 'SELL' AND realized_pnl > 0) AS wins,
                        COALESCE(SUM(realized_pnl) FILTER (WHERE action = 'SELL' AND realized_pnl IS NOT NULL), 0) AS net_pnl
                    FROM trades
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                """)
                # lifecycle completeness (all time)
                lc_row = await conn.fetchrow("""
                    SELECT
                        COUNT(*) AS total_sell,
                        COUNT(*) FILTER (
                            WHERE entry_price IS NOT NULL AND exit_price IS NOT NULL AND realized_pnl IS NOT NULL
                        ) AS complete_lifecycle
                    FROM trades WHERE action = 'SELL'
                """)

            closed_7d = int(row_7d["closed_trades"] or 0)
            wins_7d = int(row_7d["wins"] or 0)
            losses_7d = int(row_7d["losses"] or 0)
            gross_wins_7d = float(row_7d["gross_wins"] or 0)
            gross_losses_7d = float(row_7d["gross_losses"] or 0)
            net_pnl_7d = float(row_7d["net_pnl"] or 0)
            total_actions_7d = int(row_7d["total_actions"] or 0)

            win_rate_7d = (wins_7d / closed_7d * 100) if closed_7d > 0 else 0.0
            profit_factor_7d = (gross_wins_7d / gross_losses_7d) if gross_losses_7d > 0 else (float("inf") if gross_wins_7d > 0 else 0.0)

            closed_30d = int(row_30d["closed_trades"] or 0)
            wins_30d = int(row_30d["wins"] or 0)
            net_pnl_30d = float(row_30d["net_pnl"] or 0)
            win_rate_30d = (wins_30d / closed_30d * 100) if closed_30d > 0 else 0.0

            total_sell = int(lc_row["total_sell"] or 0)
            complete_lc = int(lc_row["complete_lifecycle"] or 0)
            lifecycle_pct = (complete_lc / total_sell * 100) if total_sell > 0 else 0.0

            return {
                "win_rate": round(win_rate_7d, 2),
                "win_rate_7d": round(win_rate_7d, 2),
                "win_rate_30d": round(win_rate_30d, 2),
                "profit_factor": round(profit_factor_7d, 4),
                "total_pnl": round(net_pnl_7d, 6),
                "total_pnl_7d": round(net_pnl_7d, 6),
                "total_pnl_30d": round(net_pnl_30d, 6),
                "total_trades": total_actions_7d,
                "closed_trades_7d": closed_7d,
                "wins_7d": wins_7d,
                "losses_7d": losses_7d,
                "gross_wins_7d": round(gross_wins_7d, 6),
                "gross_losses_7d": round(gross_losses_7d, 6),
                "lifecycle_completeness_pct": round(lifecycle_pct, 2),
                "lifecycle_complete": complete_lc,
                "lifecycle_total": total_sell,
                "underperforming": (
                    win_rate_7d < 35 or profit_factor_7d < 1.0 or net_pnl_7d < 0
                ) if closed_7d > 0 else False,
            }
        except Exception as e:
            logger.error(f"Failed to get performance summary: {e}")
            return {
                "win_rate": 0.0, "win_rate_7d": 0.0, "win_rate_30d": 0.0,
                "profit_factor": 0.0, "total_pnl": 0.0, "total_trades": 0,
                "closed_trades_7d": 0, "wins_7d": 0, "losses_7d": 0,
                "lifecycle_completeness_pct": 0.0, "underperforming": False,
                "error": str(e),
            }
