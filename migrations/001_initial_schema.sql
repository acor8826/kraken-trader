-- Phase 2 Initial Database Schema
-- Created: 2026-01-11
-- Purpose: Persistent storage for trading agent state, trades, signals, and events

-- ============================================================================
-- Core Trading Tables
-- ============================================================================

-- Trades table: All trade executions
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pair VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL,  -- BUY, SELL
    order_type VARCHAR(20) NOT NULL,  -- market, limit
    requested_size_quote DECIMAL(20, 8),
    requested_size_base DECIMAL(20, 8),
    filled_size_base DECIMAL(20, 8),
    filled_size_quote DECIMAL(20, 8),
    average_price DECIMAL(20, 8),
    status VARCHAR(20) NOT NULL,  -- pending, filled, partially_filled, cancelled, failed
    exchange_order_id VARCHAR(100),
    signal_confidence DECIMAL(5, 4),
    reasoning TEXT,
    entry_price DECIMAL(20, 8),
    exit_price DECIMAL(20, 8),
    realized_pnl DECIMAL(20, 8),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Portfolio snapshots: Historical portfolio state
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    available_quote DECIMAL(20, 8) NOT NULL,
    total_value DECIMAL(20, 8) NOT NULL,
    positions JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analyst signals: Raw signals from each analyst
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID REFERENCES trades(id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,  -- technical, sentiment, onchain, macro
    pair VARCHAR(20) NOT NULL,
    direction DECIMAL(5, 4) NOT NULL,  -- -1.0 to +1.0
    confidence DECIMAL(5, 4) NOT NULL,  -- 0.0 to 1.0
    reasoning TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Events table: System events for monitoring and debugging
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    source VARCHAR(50),
    data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analyst performance tracking
CREATE TABLE IF NOT EXISTS analyst_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analyst_name VARCHAR(50) NOT NULL,
    regime VARCHAR(50),  -- trending, ranging, volatile, calm
    total_signals INT DEFAULT 0,
    correct_signals INT DEFAULT 0,
    accuracy DECIMAL(5, 4),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(analyst_name, regime)
);

-- Entry prices for position tracking
CREATE TABLE IF NOT EXISTS entry_prices (
    symbol VARCHAR(20) PRIMARY KEY,
    price DECIMAL(20, 8) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Trades indexes
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_pair ON trades(pair);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_action ON trades(action);

-- Signals indexes
CREATE INDEX IF NOT EXISTS idx_signals_trade_id ON signals(trade_id);
CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at DESC);

-- Events indexes
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

-- Portfolio snapshots index
CREATE INDEX IF NOT EXISTS idx_portfolio_created_at ON portfolio_snapshots(created_at DESC);

-- ============================================================================
-- Functions and Triggers
-- ============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_trades_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_analyst_performance_updated_at BEFORE UPDATE ON analyst_performance
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_entry_prices_updated_at BEFORE UPDATE ON entry_prices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Initial Data
-- ============================================================================

-- Insert initial portfolio snapshot if none exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM portfolio_snapshots) THEN
        INSERT INTO portfolio_snapshots (available_quote, total_value, positions)
        VALUES (1000.00, 1000.00, '{}'::jsonb);
    END IF;
END
$$;

-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Uncomment to verify schema after migration:
-- SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;
-- SELECT * FROM pg_indexes WHERE schemaname = 'public';
