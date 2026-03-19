# Kraken Trader — Improvements Log

## Improvement Cycle 2026-03-18 19:00 AEST

### Performance Gate
- **Health:** healthy, scheduler running, sentinel not paused
- **Win rate (7d):** 47.06% (target >55%, above underperforming threshold <35%)
- **Profit factor:** 2.3804 ✅ (target >1.5)
- **7d PnL:** +$9.2477 ✅
- **Lifecycle completeness:** 100% (17/17) ✅
- **Status:** NOT UNDERPERFORMING by gate definition
- **Risk note:** Exposure remains extreme (>1000%) with 15 open positions

### Implemented Fixes

- [x] **[2026-03-18]** `[memetrader]` Seed simulation exchange positions during DB reconstruction after deploy restart.
  Addresses: Sell rejections (`"No position"`) for reconstructed meme holdings despite internal position tracking.
  Outcome: `market_sell()` can execute against reconstructed holdings instead of failing due to empty sim exchange position map.
  **Review due: 2026-03-25** (7 days from deployment)
  **Deployed:** 2026-03-18 19:18 AEST — revision `kraken-trader-00238-4rq`
  **Verified:** 2026-03-18 19:18 AEST — `/health` healthy, scheduler active

- [x] **[2026-03-18]** `[sentinel]` Reset `trade_frequency` circuit breaker at midnight UTC alongside daily counters.
  Addresses: Main bot staying blocked up to 24h after hitting daily trade cap despite daily counter reset.
  Outcome: Daily-scoped breaker now clears with the new day, restoring expected daily trading window behavior.
  **Review due: 2026-03-25** (7 days from deployment)
  **Deployed:** 2026-03-18 19:18 AEST — revision `kraken-trader-00238-4rq`
  **Verified:** 2026-03-18 19:18 AEST — deployment healthy and scheduled cycles resumed

- [x] **[2026-03-18]** `[orchestrator]` Correct portfolio snapshot correction to apply DB total to `total_value` and clamp negative available quote.
  Addresses: Portfolio display inconsistency after sim/DB divergence across deploys.
  Outcome: Dashboard totals reflect DB-corrected value consistently.
  **Review due: 2026-03-25** (7 days from deployment)
  **Deployed:** 2026-03-18 19:18 AEST — revision `kraken-trader-00238-4rq`
  **Verified:** 2026-03-18 19:18 AEST — API status healthy after deploy

### Deployment / Verification
- **Commit:** `eac78c9`
- **Build:** Cloud Build `65f5d1a0-4ebe-4c51-b7a3-bce6b10f1698` (SUCCESS)
- **Traffic:** 100% to `kraken-trader-00238-4rq`
- **Smoke test:** `/health` and `/status` passed

## Improvement Cycle 2026-03-17 19:00 AEST

### Observations
- **System:** Healthy, scheduler running, sentinel not paused, cycle #16
- **Active revision:** `kraken-trader-frontend-fix` (deployed 05:22 UTC today)
- **Portfolio:** $1,357.42 (+35.74% unrealized) — but 266% exposure (14 open positions, -$2,256 AUD available)
- **Win rate:** 0% (0 closed trades in 7d) — **UNDERPERFORMING**
- **Profit factor:** 0.0 — **UNDERPERFORMING**
- **Lifecycle completeness:** 0% (0/2) — **UNDERPERFORMING**
- **Profit tracker:** Empty table — no daily rows being written
- **Meme bot:** 34 cycles, DOGE position (trailing stop active), daily PnL +$0.75
- **Fear & Greed Index:** 28 (Fear) — deployment UNBLOCKED
- **Main bot:** Permanently stuck in "System not healthy" — new trades blocked, only pre-gate exits running

### Root Cause Analysis
1. **Consecutive loss circuit breaker deadlock:** 3+ consecutive losses trip the breaker with `reset_on_win=True` but NO time-based fallback. Since the breaker blocks all trading, no winning trade can ever clear it → permanent deadlock.
2. **Meme sell phantom trades:** `market_sell()` returns `{"error": "No position"}` but orchestrator ignores the error key, recording phantom PnL and "closing" positions that never actually sold.

### Implemented Fixes

- [x] **[2026-03-17]** `agents/sentinel/circuit_breakers.py` Add 4h time-based fallback to consecutive_loss circuit breaker.
  `_trip_breaker("consecutive_loss", ..., reset_on_win=True)` set no `reset_at`, so `check_all()` never auto-reset it. Added `reset_hours=4` as fallback. Breaker now clears after 4 hours OR on a winning trade, whichever comes first.
  Addresses: Main bot permanently stuck in "System not healthy" after 3 consecutive losses.
  Outcome: Trading will auto-resume within 4 hours of breaker trip.
  **Committed:** 2026-03-17 19:00 AEST — `5753706`
  **Tests:** 151/151 passed (excl. 1 pre-existing Binance test)
  **Review due: 2026-03-24**

- [x] **[2026-03-17]** `agents/memetrader/orchestrator.py` Check `market_sell()` error response before recording trade.
  `_execute_signal()` direct sell path called `exchange.market_sell()` but never checked for `{"error": ...}` response. When sim exchange had no balance, it returned error but orchestrator proceeded to record phantom PnL. Now checks `result.get("error")` and returns None if truthy.
  Addresses: Meme positions appearing to close but never actually selling (phantom PnL ~$40).
  Outcome: Failed sells are correctly detected; no phantom trade recording.
  **Committed:** 2026-03-17 19:00 AEST — `5753706`
  **Tests:** 151/151 passed (excl. 1 pre-existing Binance test)
  **Review due: 2026-03-24**

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | monitor | Profit tracker table empty — 5:59 PM snapshot not writing rows | medium | Needs investigation |
| 2 | monitor | 266% exposure / 14 positions — massive overexposure | high | Should self-correct with breaker fix |
| 3 | bugfix | Sim exchange doesn't credit meme buys → direct sells have no balance | medium | Deeper architecture issue |
| 4 | security | API keys as plaintext env vars (use Secret Manager) | high | Needs Alex approval |
| 5 | framework | NEIRO -31%, DOT -13% — candidates for pair rotation | medium | Needs analysis + human approval |

### Next Cycle Actions
1. Verify breaker deadlock resolved — main bot should resume trading within 4h
2. Monitor first completed trade lifecycle (win/loss recording)
3. Investigate empty profit tracker table
4. Review 14-position overexposure as exits start executing
5. Evaluate NEIRO/DOT for pair rotation

---

## Improvement Cycle 2026-03-16 19:00 AEST

### Observations
- **System:** Healthy, `kraken-trader-00225-wlg` at cycle start → promoted `kraken-trader-00242-sog`
- **Portfolio:** $997.10 (-0.29%) — 0 open positions, 0 closed trades (fresh revision)
- **Profit tracker:** ✅ PROFIT today (+$16.80, +1.71%)
- **Meme bot:** 102 cycles, PEPE/DOGE warm, circuit breaker healthy, 0 active positions
- **Fear & Greed Index:** 23 (Extreme Fear, but ≥ 20 → deployment UNBLOCKED for first time since 2026-03-11)
- **Status:** NOT UNDERPERFORMING — profit today, no accumulated losses

### Implemented Fixes

- [x] **[2026-03-16]** `api/app.py` Remove duplicate inline `Stage` import causing `UnboundLocalError` on startup.
  `_create_orchestrator()` had `from core.config.settings import Stage` ~220 lines into the function. Python's scoping rules treated `Stage` as a local variable throughout the function, causing `UnboundLocalError` at line 290 (before the inline import). This would crash every new revision on startup — the running `00225-wlg` was built before this bug was introduced. Fix: remove the redundant inline import; rely on the module-level import.
  Addresses: Startup crash blocking all new deployments.
  Outcome: New revisions now start successfully.
  **Committed:** 2026-03-16 19:00 AEST — `99e8e61`
  **Deployed:** 2026-03-16 19:12 AEST — revision `kraken-trader-00242-sog`
  **Verified:** 2026-03-16 19:12 AEST — `/health` healthy, scheduler running ✅
  **Review due: 2026-03-23**

- [x] **[2026-03-16]** `api/app.py` Guard `None` phase values in `_summarize_dgm_result`.
  `AttributeError: 'NoneType' object has no attribute 'get'` in `_summarize_dgm_result()` when DGM phase dicts have `None` values. Broke the seed improver daily ledger write at 06:45 UTC. Added `if ev is not None:` guards before all `.get()` calls on phase values.
  Addresses: Silent daily seed improver ledger write failures.
  Outcome: DGM cycle results now correctly logged to daily ledger.
  **Committed:** 2026-03-16 19:00 AEST — `0dec7ea`
  **Deployed:** 2026-03-16 19:12 AEST — revision `kraken-trader-00242-sog`
  **Review due: 2026-03-23**

- [x] **[2026-03-16]** `memory/postgres.py` Make `get_entry_price` return `None` on error instead of raising.
  `get_entry_price()` re-raised asyncpg exceptions, causing Phase3 `run_cycle()` to abort when the `entry_prices` table query failed (e.g. missing table, bind_execute error). Changed `raise` to `return None` for graceful degradation; successful queries unchanged.
  Addresses: Orchestrator cycle aborts on transient DB errors in `get_entry_price`.
  Outcome: Trading cycles continue on DB query failures; positions tracked without entry prices until DB stabilises.
  **Committed:** 2026-03-16 19:00 AEST — `0dec7ea`
  **Deployed:** 2026-03-16 19:12 AEST — revision `kraken-trader-00242-sog`
  **Review due: 2026-03-23**

- [x] **[2026-03-16]** `tests/unit/test_sentinel_exits.py` Fix 2 stale test assertions after USDT→AUD pair switch.
  Two tests (`test_stop_loss_trigger_creates_sell_trade`, `test_take_profit_trigger_creates_sell_trade`) asserted `pair.endswith("/USDT")` — broken since the pair migration. Changed to `startswith("BTC/")` / `startswith("ETH/")` to be quote-currency-agnostic. Test suite now **171/171 passing** (excl. 1 pre-existing Binance test).
  Addresses: Stale test failures blocking clean CI baseline.
  Outcome: Clean test suite; future changes can rely on passing baseline.
  **Committed:** 2026-03-16 19:10 AEST — `974d6e1`
  **Deployed:** 2026-03-16 19:15 AEST — revision `kraken-trader-00244-cag` (promoted to 100%)
  **Review due: 2026-03-23**

> **Note:** Revision 00241 failed (startup crash from Stage import bug, caught and fixed by DGM during cycle). Revision 00242 was DGM-only (0% traffic). Final revision serving 100% traffic: **`kraken-trader-00244-cag`** (commit `99e8e61`, includes all 3 fixes above + test fix).

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | bugfix | Binance 400 errors in logs — unused Binance integration present | low | Non-blocking; cleanup next cycle |
| 2 | security | API keys as plaintext env vars (use Secret Manager) | high | Needs Alex approval |
| 3 | framework | Meme entry_cms=0.65 threshold → 0 entries even with positive Twitter signal | low | Evaluate lowering threshold next cycle |

### Next Cycle Actions
1. Monitor `kraken-trader-00244-cag` for first AUD-pair trades (expected within 24-48h)
2. Confirm DGM ledger writes succeeding (no more `AttributeError` in 06:45 UTC log slot)
3. Confirm no `UnboundLocalError` in new revision logs
4. Evaluate meme CMS entry threshold — 0.65 may be too conservative for current Extreme Fear conditions

---

## Improvement Cycle 2026-03-14 19:00 AEST

### Observations
- **System:** Healthy, revision `kraken-trader-00222-ped`, deployed ~13:50 AEST today
- **Pairs:** BTC/AUD, ETH/AUD, SOL/AUD, DOGE/AUD, WIF/AUD (AUD pairs confirmed ✅)
- **Simulation mode:** True ✅
- **Portfolio:** $995.38 (-0.46%) — legacy positions open (AVAX/DOT/MEME/BONK/NEIRO)
- **Profit tracker:** First row today — STAGNANT ($0 PnL, 0 trades in first 5 hours)
- **Win rate:** N/A (0 closed trades under new revision)
- **Meme bot:** 44 cycles, 0 active positions, circuit breaker healthy, Twitter budget OK
- **Fear & Greed Index:** 16 (Extreme Fear) — deployment blocked
- **Critical bug found:** `/performance` endpoint returning 500 — `get_performance_summary()` missing from `PostgresStore`

### Implemented Fixes

- [x] **[2026-03-14]** `memory/postgres.py` Add `get_performance_summary()` to `PostgresStore`.
  `AttributeError: 'PostgresStore' object has no attribute 'get_performance_summary'` caused `/performance` to 500 on every request. Also silently broke the 6 PM daily profit review — `profit_context` injected into seed improver was always empty. Implemented SQL-based summary: win_rate (7d/30d), profit_factor, net_pnl, trade counts, lifecycle_completeness_pct, and `underperforming` boolean. Graceful fallback (never raises) returns zero-value dict on DB error.
  Addresses: `/performance` 500 (since first deployment), silent failure in seed improver daily profit review.
  **Committed:** 2026-03-14 19:00 AEST — main `d973db4`
  **Deploy blocked:** F&G=16 (Extreme Fear), safety rail blocks deploy
  **Tests:** 171 passed / 1 pre-existing Binance failure (unchanged)
  **Review due: 2026-03-21**

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | deploy | `get_performance_summary()` fix committed, awaiting F&G ≥ 20 | low | F&G=16, safety rail |
| 2 | bugfix | `/api/analytics` 404 — analytics endpoint not wired in app.py | low | Time budget; next cycle |
| 3 | monitor | AVAX/DOT legacy positions (null entry_price) still open after pair switch | medium | Needs manual review by Alex |
| 4 | security | API keys as plaintext env vars (use Secret Manager) | high | Infrastructure change, needs Alex |

### Next Cycle Actions
1. **Deploy `d973db4` when F&G ≥ 20** — fixes /performance and daily profit review chain
2. **Investigate /api/analytics 404** — wire analytics endpoint for MACD+BB accuracy
3. **Monitor first trades** — AUD pairs expected to generate signals within 24-48h
4. **Review legacy open positions** — AVAX/DOT may need manual close (null entry_price)

---

## Improvement Cycle 2026-03-13 19:00 AEST

### Observations
- **Fear & Greed Index:** 15 (Extreme Fear) — deployment blocked for 3rd consecutive day
- **System:** gcloud auth expired — live endpoints unreachable; git history used for state assessment
- **Pending deploy:** Branch `improvement/2026-03-11` now carries 7 critical fixes (6 prior + 1 new)
- **Status:** UNDERPERFORMING (win rate ~4%, profit factor <1.0, PnL negative)
- **Root cause identified this cycle:** `MemeOrchestrator._execute_signal` for SELL delegates to `SimpleExecutor`, which calls `balance.get(base_asset, 0)`. Simulation/testnet meme coin balances are not credited after mock buys → all sell orders return "No fills" → positions held indefinitely

### Implemented Fixes

- [x] **[2026-03-13]** `agents/memetrader/orchestrator.py` Fix meme sell "No fills" by bypassing executor balance lookup for tracked positions.
  When `signal.action == SELL` and a tracked position exists, the orchestrator now calls `exchange.market_sell(pair, tracked_amount)` directly instead of routing through `SimpleExecutor`. This ensures sell orders use the known position amount rather than the exchange balance (which is 0 in simulation for meme coins). Partial sells (size_pct < 1.0) correctly sell `tracked_amount × size_pct`. Falls back to executor when no position is tracked.
  Addresses: Meme trader sell failures (PEPE/FLOKI/BONK held indefinitely, deferred item from 2026-03-11 19:00).
  Outcome: Meme sell orders will complete successfully in simulation.
  **Committed:** 2026-03-13 19:00 AEST — branch `improvement/2026-03-11` (e76b1b9)
  **Deploy blocked:** F&G=15 (Extreme Fear)
  **Review due: 2026-03-20**

- [x] **[2026-03-13]** `tests/unit/test_meme_sell_fix.py` Added 4 unit tests covering: direct sell with tracked position, partial sell size_pct calculation, fallback to executor when no position tracked, BUY path unchanged.
  **Result:** 4/4 new tests pass; 83 total non-Binance tests pass.

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | ops | Refresh gcloud auth (manual action required) | n/a | Needs operator CLI access |
| 2 | deploy | 7 critical fixes on branch `improvement/2026-03-11` awaiting F&G ≥ 20 | critical | F&G=15, safety rail blocks |
| 3 | framework | Win rate 4% — evaluate grid/DCA/mean-reversion for ranging Extreme Fear market | medium | Requires backtesting and human approval |
| 4 | security | API keys as plaintext env vars (use Secret Manager) | high | Infrastructure change, needs human review |
| 5 | escalation | F&G <20 for 3+ consecutive days — 7 bug fixes accumulating deploy delay | critical | Alex should consider manual override — fixes are safety-critical, not strategy changes |

### Next Cycle Actions
1. **ESCALATE to Alex:** F&G ≤ 15 for 3 days; 7 critical bug fixes undeployed. Risk of NOT deploying (phantom PnL, unprotected BTC position) may exceed deploy risk
2. **Deploy when F&G ≥ 20** — all 7 fixes on branch `improvement/2026-03-11` are tested and ready
3. **Refresh gcloud auth** before next deploy attempt
4. **Post-deploy:** verify meme sells execute, BTC trailing stop active, sentinel cycling, PnL tracking

---

## Improvement Cycle 2026-03-12 19:00 AEST

### Observations
- **Fear & Greed Index:** 18 (Extreme Fear) — deployment still blocked
- **System:** Cloud Run auth expired — live endpoints unreachable; git history used for state assessment
- **Pending deploy:** Branch `improvement/2026-03-11` carries 4 critical fixes (sentinel pause-expiry, trailing stop persistence, sentinel pre-gate stop-loss, FastAPI CVE)
- **Status:** UNDERPERFORMING (win rate ~4%, profit factor <1.0, realized PnL negative)
- **Root causes identified this cycle:** (1) `set_entry_price` TypeError silently swallowed → entry prices never saved → core pair PnL shows 0; (2) trades table missing `regime` column → all trades classified "unknown" in analytics

### Implemented Fixes

- [x] **[2026-03-12]** `core/interfaces/__init__.py`, `memory/postgres.py` Fix `set_entry_price` to accept optional `size` parameter.
  `phase3._process_pair` calls `set_entry_price(symbol, price, size)` but interface/implementation only accepted `(symbol, price)`. TypeError was silently caught, meaning entry prices were never persisted for BUY trades. `entry_price=None` for all core pair positions → realized PnL showed 0 for all 40 trades.
  Addresses: Core pair PnL not tracking (deferred item #2 from 2026-03-11 19:00).
  Outcome: Entry prices now saved on each BUY → PnL calculation will work post-deploy.
  **Committed:** 2026-03-12 19:00 AEST — branch `improvement/2026-03-11` (7b794de)
  **Deploy blocked:** F&G=18 (Extreme Fear)
  **Review due: 2026-03-19**

- [x] **[2026-03-12]** `migrations/007_trades_regime.sql`, `memory/postgres.py` Add `regime` column to trades table and propagate `intel.regime.value` into trade INSERT.
  `record_trade()` never stored regime; trades table had no `regime` column. All trades showed "unknown" in analytics, making regime-based performance analysis impossible.
  Addresses: All trades classified as "unknown" regime (deferred item #3 from 2026-03-11 and 2026-03-11 19:00).
  Outcome: Future trades store correct regime; historical trades backfilled from nearest regime_snapshot.
  **Committed:** 2026-03-12 19:00 AEST — branch `improvement/2026-03-11` (7b794de)
  **Deploy blocked:** F&G=18 (Extreme Fear)
  **Review due: 2026-03-19**

- [x] **[2026-03-12]** `tests/unit/test_memory_interface.py` Added 6 new unit tests covering `set_entry_price` 2-arg and 3-arg compatibility + `record_trade` regime propagation with and without intel.
  **Result:** 6/6 new tests pass; 167 total pass (1 pre-existing unrelated Binance test failure).

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | framework | Win rate 4% — evaluate grid/DCA/mean-reversion for ranging Extreme Fear market | medium | Requires backtesting and human approval |
| 2 | security | API keys as plaintext env vars (use Secret Manager) | high | Infrastructure change, needs human review |
| 3 | deploy | 4 critical fixes on branch `improvement/2026-03-11` awaiting F&G ≥ 20 | critical | F&G=18, safety rail blocks deploy |

### Next Cycle Actions
1. **Deploy when F&G ≥ 20** — all 6 fixes on branch `improvement/2026-03-11` are ready
2. **Refresh gcloud auth** before next deploy attempt
3. **Post-deploy:** verify BTC trailing stop active, core pair PnL tracking, regime in analytics
4. **If F&G <20 for 3+ more days:** escalate to Alex — critical fixes accumulating deploy delay risk

---

## Improvement Cycle 2026-03-11 09:25 AEST

### Observations
- **System:** Healthy, cycle #230, revision `kraken-trader-00200-gfj`
- **Portfolio:** $1,006.12 (+0.61% from $1,000 initial)
- **Positions:** BTC (+30.4% unrealized, $80.62), AVAX (+7.6%, $4.75)
- **Win rate:** 4.08% (2 wins / 49 trades) — **critically below 55% target**
- **Profit factor:** 0.21 — **critically below 1.5 target**
- **Realized PnL:** -$3.74 (all losses from meme trades: TURBO -$3.91, NEIRO -$0.71, SHIB +$0.87)
- **Core pairs (BTC/ETH/SOL/AVAX/DOT):** 40 trades recorded, 0 wins, 0 losses — PnL not tracking
- **All 49 trades in "unknown" regime** — regime-aware weights have no effect on analytics
- **Trailing stop INACTIVE on BTC at +30.4%** despite 3% activation threshold — state lost every cycle
- **Meme trader:** Twitter analyst budget exhausted, running without sentiment signals
- **Seed improver:** Stable, 0 recommendations in last 4 runs
- **Errors:** None in last 24h
- **Fear & Greed Index:** 13 (Extreme Fear) — deployment blocked per safety rails

### Root Cause Analysis
**Critical Bug — Trailing stop state not persisting across cycles:**
`Phase3Orchestrator._get_portfolio_state()` constructs fresh `Position` objects every cycle from exchange balance, only loading `entry_price` from memory. All trailing stop fields (`peak_price`, `trailing_stop_active`, `trailing_stop_price`) reset to defaults (`None`/`False`) each cycle. The sentinel activates trailing stops, but the activation is immediately forgotten next cycle.

Additionally, the trailing stop had no "ratchet" mechanism — `peak_price` was set once at activation but never updated as price rose further, meaning the trailing stop would never tighten.

### Implemented Fixes

- [x] **[2026-03-11]** `orchestrator/phase3.py` Added `_exit_state` cache dict to persist trailing stop state (peak_price, trailing_stop_active, trailing_stop_price) across trading cycles. State is saved after sentinel processes positions and restored when positions are reconstructed.
  Addresses: Trailing stop not persisting. Outcome: BTC +30.4% gain now gets trailing stop protection.
  **Committed:** 2026-03-11 09:33 AEST — branch `improvement/2026-03-11` (72a9603)
  **Deploy blocked:** F&G=13 (Extreme Fear), awaiting F&G 20-80 window
  **Review due: 2026-03-18**

- [x] **[2026-03-11]** `sentinel/basic.py` Added trailing stop ratchet mechanism — when price rises above peak_price while trailing stop is active, peak_price and trailing_stop_price are updated upward. Prevents stale trailing stop from lagging behind price.
  Addresses: Trailing stop never tightening after activation. Outcome: Trailing stop follows price up, locks in more profit.
  **Committed:** 2026-03-11 09:33 AEST — same commit
  **Deploy blocked:** F&G=13 (Extreme Fear)

- [x] **[2026-03-11]** `memory/postgres.py` Portfolio save now includes trailing stop fields (peak_price, trailing_stop_active, trailing_stop_price) in position JSON.
  Addresses: Exit state lost on service restart. Outcome: State persists across restarts via database.

- [x] **[2026-03-11]** `tests/unit/test_sentinel_exits.py` Added `test_trailing_stop_ratchets_peak_upward` test verifying the ratchet mechanism.
  Outcome: 16/16 sentinel exit tests pass.

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | framework | Win rate 4% suggests fundamental strategy issues — evaluate grid/DCA/mean-reversion for ranging markets | medium | Requires backtesting and human approval |
| 2 | bugfix | Core pair PnL not tracking (40 trades show 0 wins/0 losses) — analytics misleading | low | Needs investigation of trade recording flow |
| 3 | bugfix | All trades classified as "unknown" regime in analytics | low | Regime saved on MarketIntel but not propagated to trade record |
| 4 | optimize | Meme trader Twitter analyst budget exhausted — reduce polling or increase daily_api_reads | low | Non-critical, meme allocation small |
| 5 | security | API keys exposed as plaintext env vars in Cloud Run (visible via `gcloud run services describe`) | high | Use Secret Manager for all keys, not just DATABASE_URL |
| 6 | security | FastAPI CVE-2024-24762 — ReDoS via python-multipart. Bump to >=0.109.1 | medium | Should be done in next maintenance window |
| 7 | optimize | Remove `aioredis` dependency (deprecated, merged into `redis>=5.0`) | low | Routine maintenance |

### Dependency Audit Summary
- **🔴 FastAPI:** CVE-2024-24762 (ReDoS) — current floor `>=0.109.0` is vulnerable, needs `>=0.109.1`
- **🟡 aioredis:** Deprecated, frozen at 2.0.1 — functionality merged into `redis.asyncio`
- **🟢 All other deps:** No active vulnerabilities, updates available for features/performance

### Market Context (2026-03-11)
- **BTC:** ~$68-71k, volatile ranging after 50% correction from Oct 2025 peak ($126k+)
- **Regime:** Ranging with volatility — sharp daily swings (3-6%) within weekly range
- **Sentiment:** Extreme Fear (F&G=13), bearish short-term
- **Outlook:** Analysts project potential recovery to $74-76k by end of March; Rainbow Chart shows "BUY" zone
- **ETF flows:** Strong inflows continuing despite correction — structural demand floor
- **Implication for strategy:** Current trending-up/down strategy may underperform in this ranging environment. Mean reversion or grid strategies could be more effective. Accumulation/DCA during Extreme Fear aligns with the system's existing ACCUMULATE strategy.

### Next Cycle Actions
1. **Deploy when F&G returns to 20-80 range** — trailing stop fix is critical
2. Investigate core pair PnL tracking (why 40 trades show 0 wins/0 losses)
3. Investigate regime not being stored in trade records
4. ~~Bump FastAPI to >=0.109.1 (security fix)~~ ✅ Done 2026-03-11 19:00
5. Consider pair rotation analysis (all 5 pairs are correlated crypto)

---

## Improvement Cycle 2026-03-11 19:00 AEST

### Observations
- **System:** Sentinel PAUSED — main orchestrator skipping all cycles ("System not healthy")
- **Portfolio:** $994.73 (-0.53% from $1,000 initial) — deteriorated from +0.61% last cycle
- **Positions:** BTC (+4.7%), ETH (-9.5%), SOL (-2.0%), AVAX (-12.7%), DOT (-12.5%) — all stop-losses null
- **Win rate:** 4% (1W/1L/23 unknown) | **Profit factor:** 0.60 | **Sharpe:** -0.18
- **Seed improver:** 0 recommendations in last 2 runs
- **Errors:** None in Cloud Run logs (last 24h), but sentinel permanently paused
- **Fear & Greed Index:** 15 (Extreme Fear) — deployment blocked per safety rails
- **Meme trader:** Running but all sell orders failing ("No fills" for PEPE/FLOKI/BONK)

### Root Cause Analysis
**Critical Bug — Sentinel pause never expires in system_healthy():**
`FullSentinel.system_healthy()` checks `_is_paused` but never calls `_check_pause_expired()`. An anomaly-triggered timed pause (1 hour) became permanent because the only expiry check is in `validate_plan()`, which is never reached when `system_healthy()` returns False early. The Phase3 orchestrator returns immediately, skipping all stop-loss checks, trade analysis, and exit management.

**Design flaw — Stop-losses gated behind health check:**
`check_stop_losses()` ran AFTER the `system_healthy()` gate, meaning any pause also disabled all exit protection. Stop-losses should run unconditionally as a safety mechanism.

### Implemented Fixes

- [x] **[2026-03-11]** `agents/sentinel/full.py` Fix `system_healthy()` to call `_check_pause_expired()` before returning False, so timed pauses auto-clear when their timer elapses.
  Addresses: Sentinel permanently paused after anomaly detection. Outcome: Main orchestrator will resume cycling.
  **Committed:** 2026-03-11 19:11 AEST — branch `improvement/2026-03-11` (a31898d)
  **Deploy blocked:** F&G=15 (Extreme Fear), awaiting F&G 20-80 window
  **Review due: 2026-03-18**

- [x] **[2026-03-11]** `agents/orchestrator/phase3.py` Move stop-loss/exit checks before the `system_healthy()` gate, so positions are always protected even when sentinel is paused for new trades.
  Addresses: Design flaw where pause disables exit protection. Outcome: Stop-losses fire unconditionally.
  **Committed:** 2026-03-11 19:11 AEST — same commit (a31898d)
  **Deploy blocked:** F&G=15 (Extreme Fear)

- [x] **[2026-03-11]** `requirements.txt` Bump FastAPI floor to >=0.109.1 (CVE-2024-24762 ReDoS via python-multipart).
  Addresses: Security vulnerability. Outcome: ReDoS vector closed on next build.

- [x] **[2026-03-11]** `requirements.txt` Remove deprecated `aioredis>=2.0.1` (functionality merged into `redis>=5.0.1`).
  Addresses: Dead dependency. Outcome: Cleaner dependency tree.

- [x] **[2026-03-11]** `tests/unit/test_sentinel_exits.py` Added 2 tests: `test_full_sentinel_system_healthy_respects_pause_expiry` and `test_full_sentinel_system_healthy_blocks_during_active_pause`.
  Outcome: 18/18 sentinel tests pass.

### Deferred / Logged for Human Review

| # | Type | Description | Risk | Reason Deferred |
|---|------|-------------|------|-----------------|
| 1 | bugfix | Meme trader sell failures — "No fills" for PEPE/FLOKI/BONK (held 9+ hrs past max) | low | Likely testnet balance mismatch; needs investigation |
| 2 | bugfix | 23/25 trades show unknown outcome (trade recording gaps) | low | Needs investigation of recording flow |
| 3 | bugfix | All trades classified as "unknown" regime | low | Regime not propagated to trade record |
| 4 | framework | Win rate 4% — evaluate grid/DCA/mean-reversion strategies | medium | Requires backtesting and human approval |
| 5 | security | API keys as plaintext env vars (use Secret Manager) | high | Infrastructure change, needs human review |

### Next Cycle Actions
1. **Deploy when F&G returns to 20-80 range** — sentinel fix + trailing stop fix are both critical
2. Investigate meme trader sell failures (testnet balance vs tracked positions mismatch)
3. Investigate trade recording gaps (23/25 unknown outcome)
4. Consider manual sentinel resume via API to unblock the current deployment
5. Evaluate pair rotation — AVAX and DOT consistently underperforming
