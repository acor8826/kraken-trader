-- Autoresearch experiments table
CREATE TABLE IF NOT EXISTS autoresearch_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    objective TEXT NOT NULL,
    target_file VARCHAR(255) NOT NULL,
    commit_hash VARCHAR(40),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    -- PENDING, COMMITTED, VALIDATED, KEPT, REVERTED, FAILED
    code_diff TEXT,
    metrics_before JSONB,
    metrics_after JSONB,
    llm_reasoning TEXT,
    evaluation_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autoresearch_date ON autoresearch_experiments(date);
CREATE INDEX IF NOT EXISTS idx_autoresearch_status ON autoresearch_experiments(status);
