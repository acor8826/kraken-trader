-- Migration 007: Add regime column to trades table
-- Created: 2026-03-12
-- Purpose: Propagate detected market regime into trade records so analytics
--          can break down performance by regime without joining signals.
--
-- Previously, regime was detected per-cycle but only stored in regime_snapshots
-- and signals.regime. The trades table had no regime field, causing all trades
-- to be classified as "unknown" in the trade history / analytics dashboard.

ALTER TABLE trades ADD COLUMN IF NOT EXISTS regime VARCHAR(50);

-- Index for regime-filtered analytics queries
CREATE INDEX IF NOT EXISTS idx_trades_regime ON trades(regime) WHERE regime IS NOT NULL;

-- Backfill: for existing trades, attempt to join nearest regime_snapshot
-- (best effort — many trades will remain NULL if no snapshot was captured)
UPDATE trades t
SET regime = (
    SELECT rs.regime
    FROM regime_snapshots rs
    WHERE rs.pair = t.pair
      AND rs.created_at <= t.created_at
    ORDER BY rs.created_at DESC
    LIMIT 1
)
WHERE t.regime IS NULL;
