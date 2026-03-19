# PRD: Dashboard Data Consistency Fix

**Priority:** HIGH
**Date:** 2026-03-19
**Status:** Open

---

## Problem Statement

The dashboard shows conflicting numbers across every page. The header, P&L Breakdown, Daily Profit, and Metrics pages each pull from different data sources with different computation logic, producing wildly inconsistent values for the same underlying portfolio.

**Example from live site (2026-03-19):**

| Metric | Header | P&L Breakdown | Daily Profit | Metrics |
|--------|--------|---------------|--------------|---------|
| Portfolio Value | $2,175.50 | — | $1,001.85 | — |
| Total P&L | $1,175.50 | $20.98 | -$611.80 | — |
| P&L % | 0.0% (bug) | — | -37.91% | — |
| Unrealized P&L | $1,163 (implied) | $0.00 | — | — |
| Win Rate | — | 6071% | — | 1.8% |
| Max Drawdown | — | — | — | +3200% |
| Cumulative P&L | — | — | $1.85 | — |

User trust is zero when every screen contradicts the others.

---

## Root Cause Analysis

### Data Source Map (current state)

```
Header (/portfolio)
  └─ _get_cached_portfolio() → DB trade history + live ticker prices
     └─ total_value = initial_capital + realized_pnl + unrealized_pnl  ✅ CORRECT

P&L Breakdown (/api/pnl/summary)
  └─ /performance endpoint → orchestrator._get_portfolio_state()
     └─ Uses SIM EXCHANGE balance (resets on deploy!)  ❌ WRONG SOURCE

Daily Profit (/api/daily-profit/today)
  └─ Snapshot from daily_portfolio_ledger table
     └─ Captured by old revision before DB-sync fix  ❌ STALE DATA

Metrics (/api/analytics/metrics)
  └─ AnalyticsCalculator → trades table + equity curve
     └─ Equity curve built from individual trade P&L  ⚠️ PARTIAL
```

### Bug-by-Bug Breakdown

#### BUG 1 — P&L Breakdown shows $20.98 instead of ~$1,175 (CRITICAL)
- **File:** `api/app.py` lines ~2235-2274 (`/api/pnl/summary`)
- **Cause:** Endpoint calls `/performance` which uses `orchestrator._get_portfolio_state()`. This queries `exchange.get_balance()` from the sim exchange. After DB sync, the sim exchange knows about positions but computes realized P&L only from trades executed in THIS session. Historical trades from previous deploys are invisible.
- **Fix:** Source realized_pnl and unrealized_pnl from `_get_cached_portfolio()` (DB-reconstructed) instead of the sim exchange.

#### BUG 2 — P&L Breakdown UNREALIZED = $0.00 (CRITICAL)
- **File:** `api/app.py` `/api/pnl/summary`
- **Cause:** The endpoint computes unrealized P&L from `portfolio.positions` where `portfolio` comes from `orchestrator._get_portfolio_state()`. The sim exchange does have positions (seeded from DB), but entry prices in the sim may not match the DB average entry prices. More likely: the endpoint is looking at `portfolio.unrealized_pnl` which isn't populated correctly because the sim exchange computes it from its own `_entry_prices` dict.
- **Fix:** Use DB-reconstructed position data (which correctly has `avg_entry_price` and `current_price`) to compute unrealized P&L.

#### BUG 3 — Win Rate 6071% on P&L page (CRITICAL)
- **File:** `api/app.py` `/performance` endpoint
- **Cause:** Win rate computation: `wins / total * 100`. If total=1 and wins=60.71 (a float from some aggregation), result is 6071%. Or the denominator is trades from current deploy session only (≈1 trade) while numerator includes all DB trades.
- **Fix:** Compute wins/losses from DB `trades` table with `status='filled'` and `action='SELL'` where `realized_pnl > 0` (win) vs `realized_pnl <= 0` (loss).

#### BUG 4 — P&L % badge shows 0.0% (HIGH)
- **File:** `static/js/app.js` header rendering
- **Cause:** The `pnlPercent` or `total_pnl_pct` field from the API is either 0 or the frontend formats it incorrectly. From the API response: `total_pnl_pct: 116.85` — this is a percentage already. The frontend might be dividing by 100 again, or truncating, or displaying from a different field.
- **Fix:** Trace the exact field used by the header P&L badge and ensure it renders `total_pnl_pct` from `/portfolio`.

#### BUG 5 — Max Drawdown +3200% (HIGH)
- **File:** `core/analytics/calculator.py` lines 263-310 (`_calculate_drawdown()`)
- **Cause:** The equity curve starts from `initial_capital` but trades in the DB span multiple deploy cycles with cumulative buying. If the curve goes: $1000 → $1000 → $1000 (buys with phantom balance) → suddenly $22,000 (when positions valued at sim prices), the peak-to-trough calculation breaks. Also, if `peak` is negative, `(peak - value) / peak` inverts.
- **Fix:** Build equity curve from `portfolio_snapshots` table (daily values) instead of individual trades. Or, at minimum, clamp peak to be > 0 before dividing.

#### BUG 6 — Daily Profit CURRENT = $1,001.85 vs Header $2,175.50 (CRITICAL)
- **File:** `api/app.py` lines 2735-2796 (`/api/daily-profit/today`)
- **Cause:** The snapshot was already taken (screenshot shows "LOSS — Snapshot taken"). The snapshot was captured by the OLD revision (before DB-sync fix) when the portfolio value was computed differently. The `end_value` in the ledger was written as $1,001.85 by `_run_daily_profit_snapshot()` at 5:30 PM AEST.
- **Fix:** Two-part:
  1. When snapshot exists, also show the LIVE current value from `/portfolio` for comparison
  2. The `_run_daily_profit_snapshot()` must use `_get_cached_portfolio()` (DB-reconstructed) as the value source, not the orchestrator's portfolio state. **Check if this was already fixed in the previous session** — the summary says it was rewritten but verify the deployed code.

#### BUG 7 — Cumulative P&L = $1.85 vs Header P&L $1,175.50 (HIGH)
- **File:** `static/js/pages/daily-profit.js`
- **Cause:** Cumulative P&L sums `daily_pnl` from all ledger entries. Each daily entry was computed with different logic over time (some from sim exchange, some from DB). The sum of small inaccurate daily deltas produces a tiny cumulative that bears no relation to actual P&L.
- **Fix:** Either recalculate all historical ledger entries (the `/api/daily-profit/recalculate` endpoint exists for this), or compute cumulative as `current_portfolio_value - initial_capital` instead of summing daily deltas.

#### BUG 8 — Metrics page mostly "--" (MEDIUM)
- **File:** `static/js/pages/metrics.js`, `api/routes/analytics.py`
- **Cause:** Analytics calculator requires sufficient trade data. Many metrics return `None` when data is sparse. The frontend displays "--" for null values.
- **Fix:** Return 0 with an "insufficient data" flag instead of null. Or show "N/A (need X more trades)" in the UI.

#### BUG 9 — Win Rate 1.8% on Metrics page (HIGH)
- **File:** `core/analytics/calculator.py`
- **Cause:** Uses `completed_trades` from DB which includes ALL trades (BUY and SELL). A BUY trade doesn't have P&L, so it counts as a "loss" (pnl=0 or null). With 56 buys and 1 profitable sell, win rate = 1/57 = 1.8%.
- **Fix:** Filter to SELL trades only when computing win rate (only sells have realized P&L).

---

## Implementation Plan

### Phase 1 — Single Source of Truth (CRITICAL)

**Goal:** All pages use `_get_cached_portfolio()` (DB-reconstructed) as the authoritative portfolio data source.

| Endpoint | Current Source | New Source | File |
|----------|---------------|-----------|------|
| `/portfolio` | `_get_cached_portfolio()` | No change (already correct) | `api/app.py` |
| `/performance` | `orchestrator._get_portfolio_state()` | `_get_cached_portfolio()` | `api/app.py` |
| `/api/pnl/summary` | `/performance` → sim exchange | `_get_cached_portfolio()` + DB trades | `api/app.py` |
| `/api/daily-profit/today` | Snapshot + fallback | Snapshot + LIVE override from `_get_cached_portfolio()` | `api/app.py` |

### Phase 2 — Fix Analytics Calculator (HIGH)

| Fix | File | Lines |
|-----|------|-------|
| Filter win/loss to SELL trades only | `core/analytics/calculator.py` | ~55-70 |
| Clamp drawdown peak > 0 | `core/analytics/calculator.py` | ~298 |
| Build equity curve from portfolio_snapshots | `core/analytics/calculator.py` | ~263-310 |
| Return 0 instead of None for sparse metrics | `core/analytics/calculator.py` | throughout |

### Phase 3 — Fix Frontend Display (HIGH)

| Fix | File |
|-----|------|
| P&L % badge renders correct field | `static/js/app.js` |
| Daily Profit shows live value when snapshot exists | `static/js/pages/daily-profit.js` |
| Cumulative P&L = portfolio_value - initial_capital | `static/js/pages/daily-profit.js` |

### Phase 4 — Backfill Historical Ledger (MEDIUM)

1. Call `POST /api/daily-profit/recalculate` to recompute all historical daily entries using the DB-reconstructed portfolio values
2. This fixes the cumulative P&L and daily P&L history

---

## Acceptance Criteria

1. Header P&L ($X) matches P&L Breakdown NET PROFIT ($X) within $1
2. Header PORTFOLIO ($X) matches Daily Profit CURRENT ($X) within $1
3. UNREALIZED P&L on P&L Breakdown = HOLDINGS + MEME from header
4. Win Rate is consistent across Metrics and P&L pages (same formula, same trades)
5. Max Drawdown is negative (represents a loss, not a gain)
6. P&L % badge shows correct percentage (not 0.0%)
7. All metrics on Metrics page show computed values (not "--") or explicit "N/A"
8. Cumulative P&L on Daily Profit page = current portfolio value - initial capital

---

## Files to Modify

| File | Changes |
|------|---------|
| `api/app.py` | Rewrite `/performance`, `/api/pnl/summary` to use `_get_cached_portfolio()` |
| `core/analytics/calculator.py` | Fix win rate (SELL only), drawdown (clamp peak), equity curve (use snapshots) |
| `static/js/app.js` | Fix P&L % badge field mapping |
| `static/js/pages/daily-profit.js` | Show live value alongside snapshot, fix cumulative |
| `static/js/pages/metrics.js` | Handle null metrics gracefully |

---

## Verification

1. Open dashboard header — note PORTFOLIO and P&L values
2. Navigate to P&L Breakdown — NET PROFIT and UNREALIZED should match header
3. Navigate to Daily Profit — CURRENT should match header PORTFOLIO
4. Navigate to Metrics — Win Rate should match P&L Breakdown, Max Drawdown should be negative
5. All values should remain consistent after a page refresh
6. After a Cloud Run deploy, all values should remain consistent (DB is source of truth)
