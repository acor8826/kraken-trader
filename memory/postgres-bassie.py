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
                    "current_price": position.current_price
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
                    trade_id = await conn.fetchval("""
                        INSERT INTO trades (
                            pair, action, order_type,
                            requested_size_quote, requested_size_base,
                            filled_size_base, filled_size_quote,
                            average_price, status, exchange_order_id,
                            signal_confidence, reasoning,
                            entry_price, exit_price, realized_pnl,
                            created_at, updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, $15, $16, $17
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
                        trade.timestamp or datetime.now(timezone.utc),
                        datetime.now(timezone.utc)
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

    async def set_entry_price(self, symbol: str, price: float) -> None:
        """Set entry price for position"""
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

    async def get_performance_summary(self) -> Dict:
        """Get trading performance summary"""
        try:
            async with self._connection() as conn:
                # Get trade statistics
                stats = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_trades,
                        COUNT(CASE WHEN realized_pnl > 0 THEN 1 END) as winning_trades,
                        COUNT(CASE WHEN realized_pnl < 0 THEN 1 END) as losing_trades,
                        COALESCE(SUM(realized_pnl), 0) as total_pnl
                    FROM trades
                """)

                if not stats or stats["total_trades"] == 0:
                    return {
                        "total_trades": 0,
                        "winning_trades": 0,
                        "losing_trades": 0,
                        "total_pnl": 0.0,
                        "win_rate": 0.0
                    }

                total = int(stats["total_trades"])
                winning = int(stats["winning_trades"])

                return {
                    "total_trades": total,
                    "winning_trades": winning,
                    "losing_trades": int(stats["losing_trades"]),
                    "total_pnl": float(stats["total_pnl"]),
                    "win_rate": winning / total if total > 0 else 0.0
                }

        except Exception as e:
            logger.error(f"Failed to get performance summary: {e}")
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0
            }
