# Seed Improver — Multi-Phase Documentation

## Overview

The Seed Improver runs in 7 phases (0-6) on each invocation, producing concrete improvement recommendations from trade history analysis, autonomously judging them via LLM, and optionally auto-implementing approved changes.

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/internal/seed-improver/run` | POST | Manual/scheduled trigger |
| `/internal/seed-improver/loss` | POST | Event-driven (losing trade) |
| `/internal/seed-improver/status/{run_id}` | GET | Check implementation status for a run |

### Response payload (run/loss)

```json
{
  "status": "completed",
  "run_id": "uuid",
  "trigger_type": "manual",
  "summary": "Phases 0-6 complete. ...",
  "recommendations_count": 3,
  "top_recommendations": ["Tighten stop-loss...", "Review pair DOGE/AUD..."],
  "pattern_updates_count": 2,
  "verdicts_summary": {"approve": 2, "defer": 1},
  "implementations_summary": {"implemented": 1, "failed": 0, "skipped": 1}
}
```

### Status endpoint response

```json
{
  "run_id": "uuid",
  "trigger_type": "manual",
  "status": "completed",
  "summary": "...",
  "started_at": "2026-02-26T...",
  "finished_at": "2026-02-26T...",
  "changes": [
    {
      "change_summary": "...",
      "priority": "critical",
      "verdict": "approve",
      "verdict_reason": "...",
      "verdict_confidence": 0.9,
      "implementation_branch": "seed-improver/auto-abc12345",
      "implementation_commit_sha": "...",
      "implementation_check_result": "implemented"
    }
  ]
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
| 5 | Autonomous judge — LLM (Claude) evaluates each recommendation |
| 6 | Auto-implementation — generates patches, creates branch, tests, commits |

### Phase 5: Autonomous Judge

After Phase 1 generates recommendations, each is sent to Claude for evaluation. The LLM returns:
- **verdict**: `approve`, `reject`, or `defer`
- **reason**: brief explanation
- **confidence**: 0.0–1.0
- **risk_score**: `low`, `medium`, or `high`

High-risk recommendations are auto-deferred unless `SEED_IMPROVER_HIGH_RISK_AUTO=true`.

### Phase 6: Auto-Implementation Pipeline

For approved recommendations:
1. Generate a code patch via Claude
2. Create git branch `seed-improver/auto-{run_id_short}`
3. Apply patch and commit
4. Run `pytest` as validation
5. If tests pass → status=`implemented`, record branch+commit SHA
6. If tests fail → status=`failed`, revert commit, record error

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

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEED_IMPROVER_AUTO_APPLY` | `false` | Enable Phase 3 low-risk auto-apply |
| `SEED_IMPROVER_STRATEGY_AUTO_APPLY` | `false` | Enable Phase 3 strategy auto-apply |
| `ANTHROPIC_API_KEY` | (required for Phase 5/6) | Claude API key for judge + patch generation |
| `SEED_IMPROVER_HIGH_RISK_AUTO` | `false` | Allow high-risk recommendations to be approved (not auto-deferred) |
| `SEED_IMPROVER_AUTO_IMPLEMENT` | `false` | Enable Phase 6 auto-implementation pipeline |

All flags default to disabled. Phase 5 (judge) runs whenever `ANTHROPIC_API_KEY` is set. Phase 6 (implementation) requires both the API key and `SEED_IMPROVER_AUTO_IMPLEMENT=true`.

## Migration

Run all migrations in order:

```bash
python migrations/run_migration.py
```

Or individually:
```bash
psql $DATABASE_URL -f migrations/005_seed_improver_autonomous.sql
```

All migrations are fully additive — no existing columns or tables are dropped.
