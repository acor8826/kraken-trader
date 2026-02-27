-- Phase 0 Seed Improver observability + memory schema (additive only)

ALTER TABLE trades
    ADD COLUMN IF NOT EXISTS fees_quote DECIMAL(20, 8),
    ADD COLUMN IF NOT EXISTS realized_pnl_after_fees DECIMAL(20, 8),
    ADD COLUMN IF NOT EXISTS decision_timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS filled_timestamp TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS latency_decision_to_submit_ms DECIMAL(12, 3),
    ADD COLUMN IF NOT EXISTS latency_submit_to_fill_ms DECIMAL(12, 3),
    ADD COLUMN IF NOT EXISTS latency_decision_to_fill_ms DECIMAL(12, 3);

CREATE INDEX IF NOT EXISTS idx_trades_realized_pnl_after_fees ON trades(realized_pnl_after_fees);

CREATE TABLE IF NOT EXISTS seed_improver_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type VARCHAR(30) NOT NULL, -- scheduled | losing_trade | manual
    status VARCHAR(30) NOT NULL DEFAULT 'started', -- started | completed | failed
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    context JSONB,
    summary TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS seed_improver_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES seed_improver_runs(id) ON DELETE CASCADE,
    priority VARCHAR(30), -- critical | observability | strategy | quality
    hypothesis TEXT,
    change_summary TEXT NOT NULL,
    expected_impact JSONB,
    risk_assessment TEXT,
    compatibility_check TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS seed_improver_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_key VARCHAR(120) NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    resolution TEXT,
    tags TEXT[],
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    seen_count INT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_seed_runs_trigger ON seed_improver_runs(trigger_type, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_seed_changes_run ON seed_improver_changes(run_id, created_at DESC);
