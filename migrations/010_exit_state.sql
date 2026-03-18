-- Exit state persistence: trailing stops, peak prices, TP targets hit
-- Survives Cloud Run deploys so positions stay protected

CREATE TABLE IF NOT EXISTS exit_state (
    symbol       TEXT PRIMARY KEY,
    pair         TEXT NOT NULL,
    peak_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    trailing_stop_active BOOLEAN NOT NULL DEFAULT FALSE,
    trailing_stop_price  DOUBLE PRECISION,
    tp_targets_hit       JSONB DEFAULT '[]',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exit_state_updated
    ON exit_state(updated_at DESC);
