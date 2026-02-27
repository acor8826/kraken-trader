# Paper Trading via Binance Testnet - PRD

## Summary
Paper trades were not executing on Binance because the app only recognizes
`BINANCE_API_KEY/SECRET` and forces `SIMULATION_MODE=true` when those are missing.
Users commonly configure testnet credentials as `BINANCE_TESTNET_KEY/SECRET`, so the
app silently falls back to the simulation exchange instead of Binance testnet.

## Goal
Allow paper trading against Binance testnet when `BINANCE_TESTNET=true` and testnet
credentials are provided, without forcing simulation mode.

## Non-Goals
- Enabling live (mainnet) trading without explicit credentials.
- Changing strategy or execution behavior beyond exchange selection.

## Tasks
1. Add testnet credential support in settings loader.  
Status: complete
2. Update startup credential checks to honor testnet keys.  
Status: complete
3. Document required env vars for Binance testnet paper trading.  
Status: complete
4. Validate testnet order flow with a smoke run.  
Status: fail (not executed)

## Acceptance Criteria
1. With `BINANCE_TESTNET=true`, `BINANCE_TESTNET_KEY/SECRET` present, and
   `SIMULATION_MODE=false`, the app uses Binance testnet and submits orders.
   Status: fail (needs verification)
2. With no Binance credentials, the app forces simulation mode and logs a warning.
   Status: fail (needs verification)
3. `.env.example` clearly documents testnet variables and expected usage.
   Status: approved

## Rollout / Validation
- Run `python main.py` with:
  - `EXCHANGE=binance`
  - `BINANCE_TESTNET=true`
  - `BINANCE_TESTNET_KEY=...`
  - `BINANCE_TESTNET_SECRET=...`
  - `SIMULATION_MODE=false`
- Trigger `/trigger` and verify a testnet order is placed.
