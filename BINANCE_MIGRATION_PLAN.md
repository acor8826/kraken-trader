# Kraken-to-Binance Migration Plan

> **Status**: Planning only — no code changes yet
> **Quote Currency**: AUD (staying with AUD; remove any pairs unavailable on Binance)
> **Generated**: 2026-02-17

---

## Table of Contents

1. [Full Inventory of Affected Files](#1-full-inventory-of-affected-files)
2. [Binance API Equivalents](#2-binance-api-equivalents-for-each-kraken-feature)
3. [Seven-Phase Migration Plan](#3-seven-phase-migration-plan)
4. [Critical Differences to Watch For](#4-critical-differences-to-watch-for)
5. [Testing Strategy with Binance Testnet](#5-testing-strategy-with-binance-testnet)

---

## 1. Full Inventory of Affected Files

### 1.1 Tier 1 — Tightly Coupled (Exchange Implementation)

These files contain direct Kraken REST API calls, authentication logic, or Kraken-specific response parsing. They require the most significant rewrites.

| File | Lines | Coupling Description |
|------|-------|---------------------|
| `integrations/exchanges/kraken.py` | 472 | Complete Kraken REST client: base URL `https://api.kraken.com`, HMAC-SHA512 auth, `PAIR_MAP` (BTC/AUD→XBTAUD etc.), `ASSET_MAP` (XXBT→BTC, ZAUD→AUD), all public/private endpoint calls, response parsing |
| `integrations/exchanges/kraken-bassie.py` | 472 | Extended variant with additional pairs (LINK, DOT, AVAX, ADA, ATOM, MATIC, XRP, DOGE, SHIB, PEPE, BONK, FLOKI, WIF) |
| `agents/memetrader/listing_detector.py` | 91 | Hardcoded `https://api.kraken.com/0/public/AssetPairs` URL; parses Kraken `wsname`, `quote`, `base` fields; handles `Z/X` prefixes and `.d` dark pool suffix |

### 1.2 Tier 2 — Response-Format Coupled (Kraken Response Shapes)

These files parse Kraken-specific response fields from the exchange return values. They do not call Kraken directly but assume `txid`, `vol_exec`, `cost` field names.

| File | Lines | Coupling Description |
|------|-------|---------------------|
| `agents/executor/simple.py` | 212 | Parses `result.get("txid")` — handles both list and string formats (~3 locations) |
| `agents/executor/enhanced.py` | 561 | Parses `txid` via `_extract_order_id()`; `_wait_for_fill()` checks `status == "closed"` and reads `vol_exec`, `cost`, `price`, `vol` (lines 385–399) |
| `agents/executor/smart.py` | ~300 | Parses `result.get("txid")` (lines 277, 309) |
| `agents/executor/twap.py` | ~250 | Parses `order.get("txid")` (line 222), handles list-vs-string format |
| `integrations/exchanges/base.py` | 178 | `MockExchange` returns `{"txid": f"MOCK-..."}` — mimics Kraken response shape |
| `integrations/exchanges/simulation.py` | ~500 | `SimulationExchange` returns `{"txid": f"SIM-..."}` — mimics Kraken response shape |

### 1.3 Tier 3 — Config/Naming Coupled (String References)

| File | Lines | Coupling Description |
|------|-------|---------------------|
| `core/config/settings.py` | 433 | `ExchangeConfig.name` defaults to `"kraken"`, `from_env()` reads `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` |
| `core/config/settings-bassie.py` | ~400 | Same pattern as settings.py |
| `main.py` | 90 | Logs "Kraken Trading Agent", checks `KRAKEN_API_KEY` env var |
| `api/app.py` | 926 | FastAPI title `"Kraken Trading Agent"`, imports `KrakenExchange`, instantiates it conditionally |
| `api/app-bassie.py` | ~900 | Same pattern as app.py |
| `api/routes/alerts.py` | 211 | String `"Kraken Trading Agent"` in test alert (line 87) |
| `integrations/exchanges/__init__.py` | 2 | `from integrations.exchanges.kraken import KrakenExchange` |
| `settings.local.json` | 14 | Domain permissions for `api.kraken.com` and `pro.kraken.com` |
| `-bassie.env` | — | `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` env variables |
| `Dockerfile` | 84 | Label `"Kraken Trader Team"` (cosmetic) |

### 1.4 Tier 4 — Config Data Files (Trading Pairs)

All pairs currently use AUD as quote currency. Must verify availability on Binance.

| File | Pairs |
|------|-------|
| `config/stage1.yaml` | BTC/AUD, ETH/AUD, SOL/AUD |
| `config/stage1-bassie.yaml` | + LINK, DOT, AVAX, ADA, ATOM, XRP (9 total) |
| `config/stage2.yaml` | BTC/AUD, ETH/AUD, SOL/AUD |
| `config/stage3.yaml` | + AVAX, DOT (5 total) |
| `config/aggressive.yaml` | High-volatility AUD pairs |
| `config/meme_coins.yaml` | Meme keywords (DOGE, SHIB, PEPE, BONK, FLOKI, WIF, etc.) + comment about "Kraken" |

### 1.5 Tier 5 — Clean (No Changes Required)

These files depend only on the `IExchange` abstract interface and never parse exchange-specific response formats.

- **Orchestrators**: `agents/orchestrator/base.py`, `enhanced.py`, `phase3.py`
- **Strategists**: `agents/strategist/simple.py`, `advanced.py`, `batch.py`, `hybrid.py`, `cost_optimized.py`
- **Analysts**: `agents/analysts/technical/`, `sentiment/`, `orderbook/`, `onchain/`, `macro/`, `fusion.py`
- **Sentinels**: `agents/sentinel/basic.py`, `full.py`, `circuit_breakers.py`, `correlation_monitor.py`, `validation_agent.py`
- **Core models**: `core/models/trading.py`
- **Core interfaces**: `core/interfaces/__init__.py` (defines `IExchange` ABC)
- **Pair manager**: `core/pairs/manager.py`
- **Risk management**: `core/risk/`
- **Memory layer**: `memory/inmemory.py`, `memory/postgres.py`
- **External data**: `integrations/data/` (fear_greed, glassnode, news_api, fred, twitter_client)
- **Meme trader** (other files): `orchestrator.py`, `meme_sentinel.py`, `meme_strategist.py`, `twitter_analyst.py`, `volume_analyst.py`
- **Core utilities**: `core/alerts/`, `core/analytics/`, `core/auth/`, `core/events/`, `core/ml/`, `core/scheduling/`
- **Reflection agent**: `agents/reflection/`
- **Frontend**: `static/`

---

## 2. Binance API Equivalents for Each Kraken Feature

### 2.1 Authentication

| Aspect | Kraken | Binance |
|--------|--------|---------|
| Algorithm | HMAC-SHA512 | HMAC-SHA256 |
| Nonce | `nonce = int(time.time() * 1000)` in POST body | `timestamp = int(time.time() * 1000)` as query param |
| Message construction | `SHA256(nonce + postdata)` then `HMAC-SHA512(urlpath + sha256_digest, base64_decode(secret))` | `HMAC-SHA256(query_string, secret_as_bytes)` — much simpler |
| API key header | `API-Key` | `X-MBX-APIKEY` |
| Signature transport | `API-Sign` header (base64-encoded) | `signature` query parameter (hex-encoded) |
| Secret format | Base64-encoded string | Plain string |
| Replay protection | Nonce (monotonically increasing) | `timestamp` + `recvWindow` (default 5000ms) |

### 2.2 Public Endpoints

| Feature | Kraken Endpoint | Binance Endpoint | Notes |
|---------|----------------|-------------------|-------|
| Ticker | `GET /0/public/Ticker?pair=XBTAUD` | `GET /api/v3/ticker/24hr?symbol=BTCAUD` | Binance returns flat JSON vs Kraken's nested arrays |
| OHLCV | `GET /0/public/OHLC?pair=XBTAUD&interval=60` | `GET /api/v3/klines?symbol=BTCAUD&interval=1h&limit=24` | Binance uses string intervals |
| Order Book | `GET /0/public/Depth?pair=XBTAUD&count=25` | `GET /api/v3/depth?symbol=BTCAUD&limit=100` | Binance limits: 5, 10, 20, 50, 100, 500, 1000, 5000 |
| Asset Pairs | `GET /0/public/AssetPairs` | `GET /api/v3/exchangeInfo` | Binance also returns LOT_SIZE, MIN_NOTIONAL, PRICE_FILTER |

### 2.3 Private Endpoints

| Feature | Kraken Endpoint | Binance Endpoint | Notes |
|---------|----------------|-------------------|-------|
| Balance | `POST /0/private/Balance` | `GET /api/v3/account` | Binance returns `{balances: [{asset, free, locked}]}` |
| Place Order | `POST /0/private/AddOrder` | `POST /api/v3/order` | Binance uses `side=BUY/SELL`, `type=MARKET/LIMIT` |
| Cancel Order | `POST /0/private/CancelOrder` | `DELETE /api/v3/order` | Binance needs `symbol` + `orderId` |
| Open Orders | `POST /0/private/OpenOrders` | `GET /api/v3/openOrders` | Binance can filter by symbol |
| Query Order | `POST /0/private/QueryOrders` | `GET /api/v3/order` | Binance returns `status`, `executedQty`, `cummulativeQuoteQty` |

### 2.4 Order Placement Parameter Mapping

| Parameter | Kraken | Binance |
|-----------|--------|---------|
| Pair/Symbol | `pair=XBTAUD` | `symbol=BTCAUD` |
| Side | `type=buy` / `type=sell` | `side=BUY` / `side=SELL` |
| Order type | `ordertype=market` / `ordertype=limit` | `type=MARKET` / `type=LIMIT` |
| Quantity | `volume=0.001` (always base) | `quantity=0.001` (base) OR `quoteOrderQty=100` (quote, MARKET only) |
| Price | `price=50000` (for limit) | `price=50000` (must comply with PRICE_FILTER tickSize) |
| Time-in-force | Not required | `timeInForce=GTC` **required** for LIMIT orders |

### 2.5 Order Response Mapping

| Field | Kraken | Binance |
|-------|--------|---------|
| Order ID | `result.txid` (list of strings, e.g. `["O6Z2WL-XXXXX"]`) | `result.orderId` (integer, e.g. `12345`) |
| Status | `"open"`, `"closed"`, `"canceled"` | `"NEW"`, `"FILLED"`, `"PARTIALLY_FILLED"`, `"CANCELED"` |
| Executed volume | `vol_exec` | `executedQty` |
| Cost | `cost` | `cummulativeQuoteQty` |
| Average price | `price` (when filled) | Computed from `fills` array or `cummulativeQuoteQty / executedQty` |
| Fill details | Not in basic response | `fills: [{price, qty, commission, commissionAsset}]` |

### 2.6 OHLCV Interval Mapping

| Kraken (minutes) | Binance | Notes |
|-------------------|---------|-------|
| 1 | `1m` | Direct |
| 5 | `5m` | Direct |
| 15 | `15m` | Direct |
| 30 | `30m` | Direct |
| 60 | `1h` | Format change |
| 240 | `4h` | Format change |
| 1440 | `1d` | Format change |
| 10080 | `1w` | Format change |
| 21600 | `1M` | Kraken 15-day vs Binance 1-month (approximate) |

### 2.7 Pair Naming

| Standard | Kraken | Binance |
|----------|--------|---------|
| BTC/AUD | XBTAUD | BTCAUD |
| ETH/AUD | ETHAUD | ETHAUD |
| SOL/AUD | SOLAUD | SOLAUD |
| DOGE/AUD | DOGEAUD | DOGEAUD |

Binance uses standard ticker symbols with no X/Z prefix convention. The `PAIR_MAP` becomes trivial: strip the `/` from standard format (e.g., `BTC/AUD` → `BTCAUD`).

---

## 3. Seven-Phase Migration Plan

### Phase 1: Create BinanceExchange Implementation

**Goal**: Build `integrations/exchanges/binance.py` implementing `IExchange`. Additive only — zero risk to existing code.

**New file**: `integrations/exchanges/binance.py` (~400–500 lines)

**Implementation details**:

1. Class `BinanceExchange(IExchange)` with `BASE_URL = "https://api.binance.com"`.
2. **Authentication** — `_generate_signature(query_string)`:
   - `HMAC-SHA256(query_string, secret.encode('utf-8'))` → hex string
   - Append `&signature=<hex>` to query params
   - Add `X-MBX-APIKEY` header
3. **`_public_request(endpoint, params)`** → `GET /api/v3/{endpoint}?{params}`
4. **`_private_request(endpoint, params, method)`** → adds `timestamp` + `signature`, sends via specified HTTP method
5. **IExchange methods**:
   - `get_balance()` — call `/api/v3/account`, parse `balances` array, filter `free > 0`, normalize asset names
   - `get_ticker(pair)` — call `/api/v3/ticker/24hr`, map flat JSON to `{pair, price, bid, ask, high_24h, low_24h, volume_24h, vwap_24h, trades_24h}`
   - `get_ohlcv(pair, interval, limit)` — call `/api/v3/klines`, map 12-element arrays to `[timestamp, open, high, low, close, volume]`
   - `get_market_data(pair)` — compose ticker + ohlcv into `MarketData`
   - `market_buy(pair, amount_quote)` — use `quoteOrderQty` for quote-denominated market buys
   - `market_sell(pair, amount_base)` — use `quantity`, apply LOT_SIZE rounding
   - `limit_buy(pair, amount_quote, price)` — compute quantity, round via LOT_SIZE, add `timeInForce=GTC`
   - `limit_sell(pair, amount_base, price)` — round via LOT_SIZE, add `timeInForce=GTC`
   - `get_order_book(pair, depth)` — call `/api/v3/depth`, map to `{pair, bids, asks}`
   - `cancel_order(order_id)` — `DELETE /api/v3/order`
   - `get_open_orders()` — `GET /api/v3/openOrders`
6. **Exchange info caching** — `_get_exchange_info(symbol)` fetches and caches LOT_SIZE / MIN_NOTIONAL / PRICE_FILTER per symbol
7. **Rounding helpers** — `_round_quantity(symbol, qty)` and `_round_price(symbol, price)`
8. **Interval map** — `{1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 240: "4h", 1440: "1d", 10080: "1w"}`
9. **Pair conversion** — trivial: `pair.replace("/", "")` (e.g. `BTC/AUD` → `BTCAUD`)

**Key design decision**: Order responses should use a **normalized format** with `order_id` instead of Kraken's `txid`. During transition, include both `order_id` and `txid` keys for backward compatibility:
```python
return {
    "order_id": str(result["orderId"]),
    "txid": [str(result["orderId"])],  # backward compat
    "status": result["status"],
    "filled_base": float(result.get("executedQty", 0)),
    "filled_quote": float(result.get("cummulativeQuoteQty", 0)),
    "price": computed_avg_price,
}
```

---

### Phase 2: Normalize the Order Response Contract

**Goal**: Decouple executor code from Kraken-specific `txid` / `vol_exec` field names.

**Step 2a** — Update all four executors to extract `order_id` instead of `txid`:

| File | Change |
|------|--------|
| `agents/executor/simple.py` | Replace `result.get("txid", [None])[0] if isinstance(...)` with `result.get("order_id")` (3 locations) |
| `agents/executor/enhanced.py` | Update `_extract_order_id()` to read `result.get("order_id")`; update `_wait_for_fill()` to check `status == "FILLED"` OR `status == "closed"` (support both during transition); replace `vol_exec`/`cost` with `filled_base`/`filled_quote` |
| `agents/executor/smart.py` | Replace `result.get("txid")` → `result.get("order_id")` (2 locations) |
| `agents/executor/twap.py` | Replace txid extraction → `result.get("order_id")` (1 location) |

**Step 2b** — Update Mock/Simulation exchanges to return `order_id`:

| File | Change |
|------|--------|
| `integrations/exchanges/base.py` | Add `"order_id": f"MOCK-{...}"` alongside existing `"txid"` in return dicts |
| `integrations/exchanges/simulation.py` | Add `"order_id": f"SIM-{...}"` alongside existing `"txid"` in return dicts |

**Step 2c** — Update `kraken.py` to also return `order_id` alongside `txid`:
```python
# In market_buy, market_sell, limit_buy, limit_sell returns:
txid = result.get("txid", [])
order_id = txid[0] if isinstance(txid, list) and txid else str(txid)
return {"order_id": order_id, "txid": txid, ...}
```

**Files modified**: 7 files, ~60 lines total

---

### Phase 3: Configuration and Environment Variable Migration

**Goal**: Make exchange selection configurable; add Binance credentials support.

**Step 3a** — Update `core/config/settings.py` `ExchangeConfig`:
```python
@dataclass
class ExchangeConfig:
    name: str = "binance"  # Changed default
    api_key: str = ""
    api_secret: str = ""

    @classmethod
    def from_env(cls) -> "ExchangeConfig":
        exchange_name = os.getenv("EXCHANGE", "binance")
        if exchange_name == "kraken":
            return cls(name="kraken",
                       api_key=os.getenv("KRAKEN_API_KEY", ""),
                       api_secret=os.getenv("KRAKEN_API_SECRET", ""))
        else:
            return cls(name="binance",
                       api_key=os.getenv("BINANCE_API_KEY", ""),
                       api_secret=os.getenv("BINANCE_API_SECRET", ""))
```

**Step 3b** — Apply same changes to `core/config/settings-bassie.py`.

**Step 3c** — Update `main.py`:
- Change `"Kraken Trading Agent"` → dynamic based on `EXCHANGE` env var
- Check `BINANCE_API_KEY` instead of `KRAKEN_API_KEY` (or check based on active exchange)

**Step 3d** — Update `api/app.py` and `api/app-bassie.py`:
- Change FastAPI title to `"Crypto Trading Agent"`
- Replace hardcoded `KrakenExchange()` with exchange factory:
  ```python
  if settings.exchange.name == "kraken":
      exchange = KrakenExchange()
  elif settings.exchange.name == "binance":
      exchange = BinanceExchange()
  ```

**Step 3e** — Update `integrations/exchanges/__init__.py`:
```python
from integrations.exchanges.kraken import KrakenExchange
from integrations.exchanges.binance import BinanceExchange
from integrations.exchanges.base import MockExchange
```

**Step 3f** — Update `api/routes/alerts.py`: change `"Kraken Trading Agent"` → `"Trading Agent"`

**Step 3g** — Update `settings.local.json`: add `api.binance.com` and `testnet.binance.vision` to allowed domains

**Step 3h** — Create `.env.example`:
```
EXCHANGE=binance
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
SIMULATION_MODE=true
STAGE=stage2
```

**Step 3i** — Update `Dockerfile` label from "Kraken Trader Team"

**Files modified**: ~10 files, ~80 lines total

---

### Phase 4: Migrate the Listing Detector (Meme Trading)

**Goal**: Replace direct Kraken API calls in `listing_detector.py` with Binance equivalent.

**Current** (Kraken-coupled):
- Calls `https://api.kraken.com/0/public/AssetPairs`
- Parses `pair_info.get("quote")`, `pair_info.get("base")`, `pair_info.get("wsname")`
- Handles `.d` dark pool suffix, `Z/X` asset prefixes

**New** (Binance):
- Call `https://api.binance.com/api/v3/exchangeInfo`
- Iterate `result["symbols"]`
- Filter: `quoteAsset == "AUD"` and `status == "TRADING"`
- Match `baseAsset` against meme keywords
- No dark pool suffix or Z/X prefix handling needed
- Construct pair: `f"{baseAsset}/AUD"`

**Alternative** (preferred long-term): Refactor to accept the `IExchange` instance and call `exchange.get_all_pairs()` through the interface, making it fully exchange-agnostic.

**Files modified**: `agents/memetrader/listing_detector.py` (~40 lines rewritten), `config/meme_coins.yaml` (update comment)

---

### Phase 5: Validate AUD Pair Availability on Binance

**Goal**: Confirm which AUD pairs exist on Binance and adjust configs.

**Action items**:

1. Query `https://api.binance.com/api/v3/exchangeInfo` for the full list of AUD-quoted symbols.
2. Cross-reference against all pairs in config files.
3. For any pair **NOT** available on Binance as `/AUD`:
   - Remove the pair from configs (per user decision to stay with AUD).
4. Update all YAML config files with confirmed available pairs.
5. Update `pair_stop_losses` in `core/config/settings.py` if pairs change.

**Files modified**: 5–7 config files, ~20 lines total

---

### Phase 6: Add Binance-Specific Features

**Goal**: Implement capabilities unique to Binance.

**6a — Exchange Info Caching & Filter Compliance** (critical):

Every Binance order must comply with:
- **LOT_SIZE**: `stepSize` determines quantity precision
- **MIN_NOTIONAL**: minimum order value in quote currency
- **PRICE_FILTER**: `tickSize` determines price precision

```python
async def _ensure_exchange_info(self, symbol: str):
    if symbol not in self._exchange_info_cache:
        data = await self._public_request("exchangeInfo", {"symbol": symbol})
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                self._exchange_info_cache[symbol] = self._parse_filters(s["filters"])

def _round_quantity(self, symbol: str, quantity: float) -> float:
    info = self._exchange_info_cache.get(symbol)
    if info and info.get("stepSize"):
        step = float(info["stepSize"])
        precision = len(str(step).rstrip('0').split('.')[-1])
        return round(quantity - (quantity % step), precision)
    return round(quantity, 8)
```

**6b — Rate Limiting**:

Binance uses weight-based rate limiting (1200 weight/minute). Track cumulative weight in a sliding window:
- GET ticker = 2 weight
- GET klines = 2 weight
- GET depth = 5–50 weight (depends on limit)
- POST order = 1 weight
- GET account = 20 weight

**6c — Testnet Support**:

```python
class BinanceExchange(IExchange):
    def __init__(self, api_key=None, api_secret=None, testnet=False):
        self.BASE_URL = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
```

Controlled via environment variable: `BINANCE_TESTNET=true`.

**6d — Timestamp Synchronization**:

Binance requires `timestamp` within `recvWindow` of server time. On init:
```python
async def _sync_time(self):
    server_time = await self._public_request("time")
    self._time_offset = server_time["serverTime"] - int(time.time() * 1000)
```

**6e — Enhanced Order Status** for `EnhancedExecutor`:

```python
async def query_order(self, order_id: str, symbol: str) -> dict:
    result = await self._private_request("order", {
        "symbol": symbol, "orderId": int(order_id)
    }, method="GET")
    return {
        "order_id": str(result["orderId"]),
        "status": "closed" if result["status"] == "FILLED" else result["status"].lower(),
        "filled_base": float(result.get("executedQty", 0)),
        "filled_quote": float(result.get("cummulativeQuoteQty", 0)),
        "price": float(result.get("price", 0)),
    }
```

**Files modified**: `integrations/exchanges/binance.py` (~100 additional lines)

---

### Phase 7: Cleanup and Deprecation

**Goal**: Clean up remaining Kraken references and establish the exchange factory pattern.

**7a — Exchange Factory** (recommended final state):

```python
# integrations/exchanges/__init__.py
def create_exchange(config: ExchangeConfig) -> IExchange:
    if config.name == "binance":
        from integrations.exchanges.binance import BinanceExchange
        return BinanceExchange(api_key=config.api_key, api_secret=config.api_secret)
    elif config.name == "kraken":
        from integrations.exchanges.kraken import KrakenExchange
        return KrakenExchange(api_key=config.api_key, api_secret=config.api_secret)
    else:
        raise ValueError(f"Unknown exchange: {config.name}")
```

Then `api/app.py` simplifies to:
```python
from integrations.exchanges import create_exchange
exchange = create_exchange(settings.exchange)
```

**7b — Final Cleanup Tasks**:

1. Global search for remaining "kraken"/"Kraken" strings — update to be exchange-agnostic
2. Remove `txid` backward-compat aliases from MockExchange/SimulationExchange once all executors use `order_id`
3. Remove `kraken-bassie.py` if bassie variant is also migrated
4. Update static dashboard files if they contain "Kraken" branding
5. Keep `kraken.py` as a secondary option for at least one release cycle (factory pattern enables instant rollback)

---

## 4. Critical Differences to Watch For

### 4.1 Market Buy Semantics

**Kraken**: `market_buy()` in `kraken.py` pre-computes `volume = amount_quote / ticker["price"]` before calling `AddOrder` with base-currency volume.

**Binance**: Supports `quoteOrderQty` parameter for MARKET buys — specifying how much quote currency to spend. Binance determines the exact quantity. This is simpler and avoids rounding errors. The Binance implementation should use `quoteOrderQty` directly.

### 4.2 LOT_SIZE Compliance (New Requirement)

Kraken silently rounds quantities. **Binance rejects orders** that violate LOT_SIZE with error `-1013 (Filter failure: LOT_SIZE)`. Every `limit_buy`, `limit_sell`, and `market_sell` (with `quantity`) **must** round to the correct step size before submission. The `_round_quantity()` helper must be called before every order.

### 4.3 MIN_NOTIONAL Compliance (New Requirement)

Binance rejects orders below the minimum notional value (e.g., 10 AUD). The current code checks `amount_quote < 10` in enhanced executor — this aligns well but must be verified against Binance's actual MIN_NOTIONAL per symbol.

### 4.4 Order ID Format

**Kraken**: `txid` as a list of strings (e.g., `["O6Z2WL-XXXXX"]`)
**Binance**: `orderId` as integer (e.g., `12345`)

Phase 2 normalizes this to a string `order_id` field across all exchanges.

### 4.5 Order Status Values

**Kraken**: `"closed"` = filled
**Binance**: `"FILLED"` = filled, `"PARTIALLY_FILLED"` = partial

The `_wait_for_fill()` method in `enhanced.py` (line 385) checks `status == "closed"`. Must be updated to handle both conventions during transition.

### 4.6 OHLCV Data Shape

**Kraken**: 8-element arrays `[time, open, high, low, close, vwap, volume, count]`
**Binance**: 12-element arrays `[openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, takerBuyBase, takerBuyQuote, ignore]`

Both must be normalized to `[timestamp, open, high, low, close, volume]` for the `IExchange` contract.

### 4.7 Error Response Format

**Kraken**: `{"error": ["EOrder:Insufficient funds"]}` (list of error strings)
**Binance**: `{"code": -2010, "msg": "Account has insufficient balance..."}` (code + message)

### 4.8 AUD Pair Availability Risk

Binance may have fewer AUD pairs than Kraken, especially for meme coins (SHIB/AUD, PEPE/AUD, BONK/AUD, WIF/AUD may not exist). Pairs not available on Binance should be removed from configs.

### 4.9 Rate Limiting Model

**Kraken**: Simple call-count based rate limits
**Binance**: Weight-based (1200 weight/minute), each endpoint has a different weight. The `BinanceExchange` must track cumulative request weight and back off proactively.

### 4.10 Timestamp Synchronization

Binance rejects requests where `timestamp` is more than `recvWindow` (5000ms) from server time. If the local clock drifts, error `-1021` is returned. Must sync time offset on initialization.

### 4.11 Fee Structure

**Kraken**: Maker/taker fees vary by 30-day volume
**Binance**: Maker/taker fees + BNB discount. Binance order fills include `commission` and `commissionAsset` in the `fills` array — useful for accurate P&L tracking.

---

## 5. Testing Strategy with Binance Testnet

### 5.1 Testnet Setup

- **URL**: `https://testnet.binance.vision`
- Create testnet API keys at the Binance testnet portal
- Testnet has pre-funded accounts with test balances
- Supports the same API endpoints as production
- Pair availability may differ — verify before testing

### 5.2 Test Phases

**Phase A — Unit Tests (No Network)**

| Test | Description |
|------|-------------|
| Signature generation | Test `_generate_signature()` against known test vectors from Binance docs |
| Quantity rounding | Test `_round_quantity()` with various LOT_SIZE configs (stepSize 0.001, 0.00001, 1.0) |
| Price rounding | Test `_round_price()` with various PRICE_FILTER tickSize values |
| Interval mapping | Verify all OHLCV intervals map correctly |
| Pair conversion | Verify `BTC/AUD` → `BTCAUD` for all configured pairs |
| Error parsing | Test error response parsing for common codes (-1013, -2010, -1021) |
| Response normalization | Test `order_id` extraction from Binance response shape |

**Phase B — Integration Tests (Testnet, Public Endpoints)**

| Test | Description |
|------|-------------|
| Exchange info | Fetch `/api/v3/exchangeInfo`, verify filter parsing |
| Ticker | Fetch ticker for multiple AUD pairs, verify normalized output matches `IExchange` contract |
| OHLCV | Fetch klines with various intervals, verify `[timestamp, open, high, low, close, volume]` output |
| Order book | Fetch depth, verify `{pair, bids, asks}` format |
| Contract alignment | Compare output to `MockExchange` to verify contract match |

**Phase C — Integration Tests (Testnet, Authenticated)**

| Test | Description |
|------|-------------|
| Balance | Fetch account balance, verify parsing |
| Market buy | Place MARKET BUY with `quoteOrderQty`, verify response |
| Market sell | Place MARKET SELL with `quantity`, verify response |
| Limit buy | Place LIMIT BUY with `timeInForce=GTC`, verify |
| Query order | Query order status, verify field mapping |
| Cancel order | Cancel limit order, verify cancellation |
| LOT_SIZE enforcement | Attempt order with incorrect precision, confirm pre-submission rounding catches it |

**Phase D — End-to-End Smoke Tests (Testnet)**

| Test | Description |
|------|-------------|
| Full cycle | Run app with `EXCHANGE=binance`, `SIMULATION_MODE=false`, pointing at testnet |
| Trigger trade | Call `POST /trigger` to execute a trading cycle |
| Verify pipeline | Confirm analysis → strategy → sentinel → execution completes |
| Trade history | Check `/history` shows trades |
| Portfolio | Check `/portfolio` reflects changes |
| Meme detector | Verify listing detector works against testnet `exchangeInfo` |
| Limit flow | Test EnhancedExecutor limit order: place → poll → fill/timeout |
| WebSocket | Confirm portfolio WebSocket updates after a trade |

**Phase E — Simulation Mode Verification**

| Test | Description |
|------|-------------|
| MockExchange | Verify `SIMULATION_MODE=true` still works with `order_id` field |
| SimulationExchange | Verify all simulation scenarios function correctly |

**Phase F — Production Readiness (Paper Trading on Real Binance)**

| Test | Description |
|------|-------------|
| Real market data | Run against production Binance with `SIMULATION_MODE=true` |
| Price verification | Compare ticker prices to Binance web interface |
| OHLCV verification | Compare candle data to Binance charts |
| 24-48h soak test | Run paper-trading for 24-48 hours monitoring logs |

### 5.3 Rollback Strategy

The exchange factory pattern enables instant rollback with zero code changes:

```bash
# Rollback to Kraken
export EXCHANGE=kraken
export KRAKEN_API_KEY=your_key
export KRAKEN_API_SECRET=your_secret
# Restart application
```

Both exchange implementations coexist. No code changes needed for rollback.

---

## Summary: Effort by Phase

| Phase | Description | Files Changed | New Files | Est. LOC | Risk |
|-------|-------------|--------------|-----------|----------|------|
| 1 | BinanceExchange implementation | 0 | 1 | ~450 | Low (additive) |
| 2 | Normalize order response contract | 7 | 0 | ~60 | Medium (executors) |
| 3 | Config & env migration | ~10 | 1 | ~80 | Low (strings) |
| 4 | Listing detector rewrite | 2 | 0 | ~40 | Medium (rewrite) |
| 5 | Pair availability validation | 5–7 | 0 | ~20 | High (business) |
| 6 | Binance-specific features | 1 | 0 | ~100 | Medium (rate limits) |
| 7 | Cleanup & factory pattern | 5–10 | 0 | ~30 | Low (cosmetic) |
| **Total** | | **~25 unique** | **~2** | **~780** | |
