-- Migration 011: Backfill realized_pnl for SELL trades that have NULL values.
-- Computes realized_pnl from average buy price for the same pair.
-- This fixes dashboard wins/losses/P&L that depend on realized_pnl being populated.

UPDATE trades AS t
SET
    realized_pnl = (t.average_price - buy_avg.avg_buy_price) * t.filled_size_base,
    realized_pnl_after_fees = (t.average_price - buy_avg.avg_buy_price) * t.filled_size_base - COALESCE(t.fees_quote, 0),
    entry_price = buy_avg.avg_buy_price,
    exit_price = t.average_price
FROM (
    SELECT pair,
           CASE WHEN SUM(filled_size_base) > 0
                THEN SUM(filled_size_quote) / SUM(filled_size_base)
                ELSE 0 END AS avg_buy_price
    FROM trades
    WHERE action = 'BUY' AND status = 'filled' AND filled_size_base > 0
    GROUP BY pair
) AS buy_avg
WHERE t.action = 'SELL'
  AND t.status = 'filled'
  AND t.realized_pnl IS NULL
  AND t.pair = buy_avg.pair
  AND buy_avg.avg_buy_price > 0;
