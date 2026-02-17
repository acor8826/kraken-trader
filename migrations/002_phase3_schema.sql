-- Phase 3 Database Schema Extensions
-- Created: 2026-01-12
-- Purpose: Add regime detection, anomaly tracking, adaptive weights, and execution quality tables

-- ============================================================================
-- Phase 3 Core Tables
-- ============================================================================

-- Regime snapshots: Historical market regime classifications
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pair VARCHAR(20) NOT NULL,
    regime VARCHAR(50) NOT NULL,  -- TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
    confidence DECIMAL(5, 4) NOT NULL,  -- 0.0 to 1.0
    features JSONB,  -- ADX, ATR, Bollinger width, momentum values
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Anomaly events: Detected market anomalies
CREATE TABLE IF NOT EXISTS anomaly_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    anomaly_type VARCHAR(100) NOT NULL,  -- volume_spike, price_deviation, spread_widening, etc
    score DECIMAL(5, 4) NOT NULL,  -- 0.0 to 1.0, >0.8 is anomaly
    pair VARCHAR(20) NOT NULL,
    description TEXT,
    features JSONB,  -- Raw feature values that triggered detection
    action_taken VARCHAR(100),  -- reduced_size, paused_trading, etc
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analyst weights: Adaptive weights per analyst per regime
CREATE TABLE IF NOT EXISTS analyst_weights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analyst_name VARCHAR(50) NOT NULL,
    regime VARCHAR(50),  -- NULL for default weights
    weight DECIMAL(5, 4) NOT NULL,  -- 0.0 to 1.0
    accuracy_30d DECIMAL(5, 4),  -- Rolling 30-day accuracy
    sample_count INT DEFAULT 0,  -- Number of signals used for calculation
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(analyst_name, regime)
);

-- Execution quality: Track execution performance
CREATE TABLE IF NOT EXISTS execution_quality (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID REFERENCES trades(id) ON DELETE CASCADE,
    strategy VARCHAR(50) NOT NULL,  -- market, limit, twap, split
    expected_price DECIMAL(20, 8),
    executed_price DECIMAL(20, 8),
    slippage_pct DECIMAL(10, 6),  -- (executed - expected) / expected * 100
    execution_time_ms INT,  -- Time from order to fill
    order_count INT DEFAULT 1,  -- Number of child orders (for TWAP/split)
    fill_rate DECIMAL(5, 4),  -- Percentage of limit orders filled without market fallback
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- Alter Existing Tables
-- ============================================================================

-- Add regime and anomaly_score columns to signals table
ALTER TABLE signals ADD COLUMN IF NOT EXISTS regime VARCHAR(50);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS anomaly_score DECIMAL(5, 4);

-- Add strategy column to trades for tracking execution strategy used
ALTER TABLE trades ADD COLUMN IF NOT EXISTS execution_strategy VARCHAR(50);

-- ============================================================================
-- Phase 3 Indexes
-- ============================================================================

-- Regime snapshots indexes
CREATE INDEX IF NOT EXISTS idx_regime_created_at ON regime_snapshots(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_regime_pair ON regime_snapshots(pair);
CREATE INDEX IF NOT EXISTS idx_regime_type ON regime_snapshots(regime);

-- Anomaly events indexes
CREATE INDEX IF NOT EXISTS idx_anomaly_created_at ON anomaly_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_pair ON anomaly_events(pair);
CREATE INDEX IF NOT EXISTS idx_anomaly_type ON anomaly_events(anomaly_type);
CREATE INDEX IF NOT EXISTS idx_anomaly_score ON anomaly_events(score) WHERE score > 0.7;

-- Analyst weights indexes
CREATE INDEX IF NOT EXISTS idx_weights_analyst ON analyst_weights(analyst_name);
CREATE INDEX IF NOT EXISTS idx_weights_regime ON analyst_weights(regime);

-- Execution quality indexes
CREATE INDEX IF NOT EXISTS idx_exec_quality_trade ON execution_quality(trade_id);
CREATE INDEX IF NOT EXISTS idx_exec_quality_strategy ON execution_quality(strategy);
CREATE INDEX IF NOT EXISTS idx_exec_quality_created ON execution_quality(created_at DESC);

-- Signals with regime index
CREATE INDEX IF NOT EXISTS idx_signals_regime ON signals(regime) WHERE regime IS NOT NULL;

-- ============================================================================
-- Triggers
-- ============================================================================

-- Auto-update updated_at for analyst_weights
CREATE TRIGGER update_analyst_weights_updated_at BEFORE UPDATE ON analyst_weights
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Initial Data: Default Analyst Weights
-- ============================================================================

-- Insert default weights for all analysts (NULL regime = default)
INSERT INTO analyst_weights (analyst_name, regime, weight) VALUES
    ('technical', NULL, 0.30),
    ('sentiment', NULL, 0.25),
    ('onchain', NULL, 0.20),
    ('macro', NULL, 0.15),
    ('orderbook', NULL, 0.10)
ON CONFLICT (analyst_name, regime) DO NOTHING;

-- Insert regime-specific weight adjustments
-- TRENDING regime: Technical gets higher weight
INSERT INTO analyst_weights (analyst_name, regime, weight) VALUES
    ('technical', 'TRENDING_UP', 0.40),
    ('technical', 'TRENDING_DOWN', 0.40),
    ('sentiment', 'TRENDING_UP', 0.25),
    ('sentiment', 'TRENDING_DOWN', 0.25),
    ('onchain', 'TRENDING_UP', 0.15),
    ('onchain', 'TRENDING_DOWN', 0.15),
    ('macro', 'TRENDING_UP', 0.10),
    ('macro', 'TRENDING_DOWN', 0.10),
    ('orderbook', 'TRENDING_UP', 0.10),
    ('orderbook', 'TRENDING_DOWN', 0.10)
ON CONFLICT (analyst_name, regime) DO NOTHING;

-- RANGING regime: Orderbook gets higher weight for timing
INSERT INTO analyst_weights (analyst_name, regime, weight) VALUES
    ('technical', 'RANGING', 0.25),
    ('sentiment', 'RANGING', 0.25),
    ('onchain', 'RANGING', 0.20),
    ('macro', 'RANGING', 0.10),
    ('orderbook', 'RANGING', 0.20)
ON CONFLICT (analyst_name, regime) DO NOTHING;

-- VOLATILE regime: On-chain gets higher weight
INSERT INTO analyst_weights (analyst_name, regime, weight) VALUES
    ('technical', 'VOLATILE', 0.25),
    ('sentiment', 'VOLATILE', 0.20),
    ('onchain', 'VOLATILE', 0.25),
    ('macro', 'VOLATILE', 0.15),
    ('orderbook', 'VOLATILE', 0.15)
ON CONFLICT (analyst_name, regime) DO NOTHING;

-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Uncomment to verify Phase 3 tables after migration:
-- SELECT table_name FROM information_schema.tables
--     WHERE table_schema = 'public'
--     AND table_name IN ('regime_snapshots', 'anomaly_events', 'analyst_weights', 'execution_quality');
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'signals' AND column_name IN ('regime', 'anomaly_score');
