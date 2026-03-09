import json
import logging
import math
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)


class FitnessEvaluator:
    """Compute immutable fitness scores from raw trade data.

    Fitness = total PnL after fees. Simple, ungameable, aligned with
    the only thing that matters: did this config make money?
    """

    def __init__(self, db_pool):
        self.pool = db_pool

    async def evaluate(self, variant_id, window_start, window_end, min_trades=3):
        """Compute fitness from trades WHERE dgm_variant_id = variant_id within window.

        Returns fitness record dict if enough trades, None otherwise.
        """
        # Query trades for this variant within the evaluation window
        trades = await self.pool.fetch(
            """SELECT realized_pnl, realized_pnl_after_fees, fees_quote, created_at
               FROM trades
               WHERE dgm_variant_id = $1
               AND created_at >= $2 AND created_at <= $3
               AND status = 'filled'
               ORDER BY created_at ASC""",
            variant_id, window_start, window_end
        )

        trade_count = len(trades)
        if trade_count < min_trades:
            logger.info(f"Variant {variant_id}: only {trade_count}/{min_trades} trades, skipping evaluation")
            return None

        # Extract PnL values
        pnls = [float(t['realized_pnl'] or 0) for t in trades]
        pnls_after_fees = [float(t['realized_pnl_after_fees'] or t['realized_pnl'] or 0) for t in trades]

        # Compute metrics
        total_pnl = sum(pnls)
        total_pnl_after_fees = sum(pnls_after_fees)

        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / trade_count if trade_count > 0 else 0.0

        gains = sum(p for p in pnls if p > 0)
        losses = abs(sum(p for p in pnls if p < 0))
        profit_factor = min(gains / losses, 10.0) if losses > 0 else 10.0

        # Sharpe estimate (annualized)
        mean_pnl = total_pnl / trade_count
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / trade_count if trade_count > 1 else 0
        std_pnl = math.sqrt(variance)
        sharpe = (mean_pnl / std_pnl) * math.sqrt(365) if std_pnl > 0 else 0.0

        # Max drawdown from cumulative PnL
        cumulative = []
        running = 0
        for p in pnls:
            running += p
            cumulative.append(running)

        peak = cumulative[0]
        max_dd = 0.0
        for val in cumulative:
            if val > peak:
                peak = val
            dd = (peak - val) / abs(peak) if peak != 0 else 0
            if dd > max_dd:
                max_dd = dd
        max_drawdown_pct = min(max_dd, 1.0)

        # Trades per day
        window_days = max((window_end - window_start).total_seconds() / 86400, 1)
        trades_per_day = trade_count / window_days

        # Fitness = total PnL after fees
        # This is the only metric that matters. All other metrics are recorded
        # for observability but do not influence selection.
        fitness_score = total_pnl_after_fees

        fitness_components = {
            'total_pnl': round(total_pnl, 8),
            'total_pnl_after_fees': round(total_pnl_after_fees, 8),
            'sharpe_raw': round(sharpe, 6),
            'profit_factor_raw': round(profit_factor, 6),
            'win_rate': round(win_rate, 6),
            'max_drawdown_pct': round(max_drawdown_pct, 6),
            'trades_per_day': round(trades_per_day, 4),
        }

        # Insert into dgm_fitness_scores
        row = await self.pool.fetchrow(
            """INSERT INTO dgm_fitness_scores
               (variant_id, evaluation_window_start, evaluation_window_end,
                trade_count, total_pnl, total_pnl_after_fees, win_rate,
                profit_factor, sharpe_estimate, max_drawdown_pct, trades_per_day,
                fitness_score, fitness_components)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
               RETURNING *""",
            variant_id, window_start, window_end,
            trade_count,
            Decimal(str(round(total_pnl, 8))),
            Decimal(str(round(total_pnl_after_fees, 8))),
            Decimal(str(round(win_rate, 4))),
            Decimal(str(round(profit_factor, 4))),
            Decimal(str(round(sharpe, 4))),
            Decimal(str(round(max_drawdown_pct, 4))),
            Decimal(str(round(trades_per_day, 2))),
            Decimal(str(round(fitness_score, 6))),
            json.dumps(fitness_components)
        )

        logger.info(f"Variant {variant_id} fitness={fitness_score:.6f} "
                     f"(trades={trade_count}, pnl={total_pnl:.4f}, wr={win_rate:.2%})")

        return dict(row) if row else None

    async def get_fitness(self, variant_id):
        """Get latest fitness score for a variant."""
        row = await self.pool.fetchrow(
            """SELECT * FROM dgm_fitness_scores
               WHERE variant_id = $1
               ORDER BY computed_at DESC LIMIT 1""",
            variant_id
        )
        return dict(row) if row else None

    async def get_fitness_history(self, variant_id):
        """All fitness scores for a variant, newest first."""
        rows = await self.pool.fetch(
            """SELECT * FROM dgm_fitness_scores
               WHERE variant_id = $1
               ORDER BY computed_at DESC""",
            variant_id
        )
        return [dict(r) for r in rows]
