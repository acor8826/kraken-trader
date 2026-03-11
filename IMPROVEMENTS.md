# Kraken Trader — Improvements Log

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
