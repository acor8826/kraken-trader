-- Phase 5/6 Seed Improver autonomous judge + auto-implementation (additive only)
-- No destructive changes. Safe to run on existing schema.

-- Verdict fields (Phase 5: Autonomous Judge)
ALTER TABLE seed_improver_changes
    ADD COLUMN IF NOT EXISTS verdict VARCHAR(20) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS verdict_reason TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS verdict_confidence FLOAT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS verdict_risk_score VARCHAR(20) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS judged_by_model VARCHAR(100) DEFAULT NULL;

-- Implementation fields (Phase 6: Auto-Implementation Pipeline)
ALTER TABLE seed_improver_changes
    ADD COLUMN IF NOT EXISTS implementation_branch VARCHAR(200) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS implementation_commit_sha VARCHAR(64) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS implementation_check_result VARCHAR(30) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS implementation_error TEXT DEFAULT NULL;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_seed_changes_verdict ON seed_improver_changes(verdict);
CREATE INDEX IF NOT EXISTS idx_seed_changes_status_verdict ON seed_improver_changes(status, verdict);
