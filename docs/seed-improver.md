# Seed Improver — Multi-Phase Documentation

## Overview

The Seed Improver runs in 5 phases (0-4) on each invocation, producing concrete improvement recommendations from trade history analysis.

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/internal/seed-improver/run` | POST | Manual/scheduled trigger |
| `/internal/seed-improver/loss` | POST | Event-driven (losing trade) |

### Response payload

```json
{
  "status": "completed",
  "run_id": "uuid",
  "trigger_type": "manual",
  "summary": "Phases 0-4 complete. trades_sampled=50, gaps=0, recommendations=3, ...",
  "recommendations_count": 3,
  "top_recommendations": ["Tighten stop-loss...", "Review pair DOGE/AUD..."],
  "pattern_updates_count": 2
}
```

## Phases

| Phase | What it does |
|-------|-------------|
| 0 | Observability audit — checks data completeness |
| 1 | Analysis + ranked recommendation generation |
| 2 | Pattern learning — upserts recurring failure patterns |
| 3 | Controlled actioning — feature-flagged auto-apply |
| 4 | Evaluation loop — compares prior run outcomes |

## Querying Recommendations

```sql
-- All recommendations for a run
SELECT priority, hypothesis, change_summary, risk_assessment, expected_impact
FROM seed_improver_changes
WHERE run_id = '<run-uuid>'
ORDER BY created_at;

-- Critical recommendations across all runs
SELECT c.*, r.trigger_type, r.started_at
FROM seed_improver_changes c
JOIN seed_improver_runs r ON r.id = c.run_id
WHERE c.priority = 'critical'
ORDER BY c.created_at DESC
LIMIT 20;

-- Applied changes
SELECT * FROM seed_improver_changes
WHERE compatibility_check LIKE '%[APPLIED]%'
ORDER BY created_at DESC;
```

## Querying Patterns

```sql
-- Most frequent patterns
SELECT pattern_key, title, seen_count, last_seen_at
FROM seed_improver_patterns
ORDER BY seen_count DESC;

-- Patterns by tag
SELECT * FROM seed_improver_patterns
WHERE 'strategy' = ANY(tags)
ORDER BY seen_count DESC;
```

## Enabling Safe Auto-Apply

Auto-apply is **disabled by default**. It only applies low-risk, non-strategy changes (e.g., telemetry fixes).

```bash
# Enable low-risk auto-apply
export SEED_IMPROVER_AUTO_APPLY=true

# Enable strategy auto-apply (use with caution)
export SEED_IMPROVER_STRATEGY_AUTO_APPLY=true
```

Setting these as environment variables on Cloud Run or in `.env` will activate the feature-flagged paths.

## Migration

Run `migrations/004_seed_improver_phases.sql` to add the new columns and indexes:

```bash
psql $DATABASE_URL -f migrations/004_seed_improver_phases.sql
```

This is fully additive — no existing columns or tables are dropped.
