-- Phase 1-4 Seed Improver extensions (additive only)
-- No destructive changes. Safe to run on existing schema.

-- Add risk_assessment as a proper column if it doesn't have the right semantics
-- (it already exists from 003, but we ensure it's usable)

-- Add applied tracking to changes
ALTER TABLE seed_improver_changes
    ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'recommended';
    -- Values: recommended | applied | rejected | evaluated

-- Add evaluation fields to runs
ALTER TABLE seed_improver_runs
    ADD COLUMN IF NOT EXISTS recommendations_count INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pattern_updates_count INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS applied_count INT DEFAULT 0;

-- Index for pattern lookups
CREATE INDEX IF NOT EXISTS idx_seed_patterns_key ON seed_improver_patterns(pattern_key);
CREATE INDEX IF NOT EXISTS idx_seed_patterns_seen ON seed_improver_patterns(seen_count DESC);
CREATE INDEX IF NOT EXISTS idx_seed_changes_status ON seed_improver_changes(status);
