-- Darwinian Godel Machine: Population Archive & Fitness Tracking
-- Created: 2026-03-09
-- Purpose: Schema for DGM variant population, fitness evaluation, and
--          evolutionary lineage tracking. Enables the self-improving
--          config evolution loop with full audit trail.
-- No destructive changes. Safe to run on existing schema.

-- ============================================================================
-- DGM Variant Population Archive
-- ============================================================================

-- dgm_variants: Each row is a config variant (candidate or deployed)
CREATE TABLE IF NOT EXISTS dgm_variants (
    id SERIAL PRIMARY KEY,
    parent_id INT REFERENCES dgm_variants(id),
    generation INT NOT NULL DEFAULT 0,
    config_yaml TEXT NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    mutation_description TEXT,
    patches_applied JSONB,
    status VARCHAR(30) NOT NULL DEFAULT 'candidate',
    deployed_at TIMESTAMPTZ,
    evaluation_start TIMESTAMPTZ,
    evaluation_end TIMESTAMPTZ,
    deploy_revision_id VARCHAR(200),
    lineage_depth INT NOT NULL DEFAULT 0,
    branch_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- DGM Fitness Scores
-- ============================================================================

-- dgm_fitness_scores: Computed fitness for each variant over an evaluation window
CREATE TABLE IF NOT EXISTS dgm_fitness_scores (
    id SERIAL PRIMARY KEY,
    variant_id INT NOT NULL REFERENCES dgm_variants(id),
    evaluation_window_start TIMESTAMPTZ NOT NULL,
    evaluation_window_end TIMESTAMPTZ NOT NULL,
    trade_count INT NOT NULL DEFAULT 0,
    total_pnl DECIMAL(20,8),
    total_pnl_after_fees DECIMAL(20,8),
    win_rate DECIMAL(5,4),
    profit_factor DECIMAL(10,4),
    sharpe_estimate DECIMAL(10,4),
    max_drawdown_pct DECIMAL(5,4),
    trades_per_day DECIMAL(8,2),
    fitness_score DECIMAL(10,6) NOT NULL,
    fitness_components JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- DGM Evaluation Log
-- ============================================================================

-- dgm_evaluation_log: Audit trail of variant-vs-parent judgements
CREATE TABLE IF NOT EXISTS dgm_evaluation_log (
    id SERIAL PRIMARY KEY,
    variant_id INT NOT NULL REFERENCES dgm_variants(id),
    parent_variant_id INT REFERENCES dgm_variants(id),
    verdict VARCHAR(20) NOT NULL,
    judge_reasoning TEXT,
    variant_fitness DECIMAL(10,6),
    parent_fitness DECIMAL(10,6),
    fitness_delta DECIMAL(10,6),
    action_taken VARCHAR(30),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Trades Table Extension
-- ============================================================================

-- Link trades to the DGM variant that was active when they executed
ALTER TABLE trades ADD COLUMN IF NOT EXISTS dgm_variant_id INT;

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- dgm_variants indexes
CREATE INDEX IF NOT EXISTS idx_dgm_variants_status ON dgm_variants(status);
CREATE INDEX IF NOT EXISTS idx_dgm_variants_config_hash ON dgm_variants(config_hash);
CREATE INDEX IF NOT EXISTS idx_dgm_variants_parent_id ON dgm_variants(parent_id);
CREATE INDEX IF NOT EXISTS idx_dgm_variants_generation ON dgm_variants(generation);
CREATE INDEX IF NOT EXISTS idx_dgm_variants_created_at ON dgm_variants(created_at DESC);

-- dgm_fitness_scores indexes
CREATE INDEX IF NOT EXISTS idx_dgm_fitness_variant_id ON dgm_fitness_scores(variant_id);
CREATE INDEX IF NOT EXISTS idx_dgm_fitness_computed_at ON dgm_fitness_scores(computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_dgm_fitness_score ON dgm_fitness_scores(fitness_score DESC);

-- dgm_evaluation_log indexes
CREATE INDEX IF NOT EXISTS idx_dgm_eval_variant_id ON dgm_evaluation_log(variant_id);
CREATE INDEX IF NOT EXISTS idx_dgm_eval_verdict ON dgm_evaluation_log(verdict);
CREATE INDEX IF NOT EXISTS idx_dgm_eval_created_at ON dgm_evaluation_log(created_at DESC);

-- trades dgm variant index
CREATE INDEX IF NOT EXISTS idx_trades_dgm_variant ON trades(dgm_variant_id);

-- ============================================================================
-- Triggers
-- ============================================================================

-- Auto-update updated_at on dgm_variants (reuses function from 001)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_dgm_variants_updated_at'
    ) THEN
        CREATE TRIGGER update_dgm_variants_updated_at BEFORE UPDATE ON dgm_variants
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END
$$;
