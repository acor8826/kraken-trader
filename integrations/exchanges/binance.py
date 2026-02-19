"""
Binance Exchange Integration

Full implementation of the IExchange interface for Binance.
Supports production and testnet environments, HMAC-SHA256 authentication,
exchange info caching, LOT_SIZE/PRICE_FILTER rounding, rate limiting,
and server time synchronisation.
"""

import asyncio
import os
import time
import hmac
import hashlib
import math
import logging
from collections import deque
from typing import Dict, List, Optional, Any

import httpx

from core.interfaces import IExchange
from core.models import MarketData

logger = logging.getLogger(__name__)


class BinanceExchange(IExchange):
    """Binance exchange implementation with full REST API support."""

    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    INTERVAL_MAP: Dict[int, str] = {
        1: "1m", 5: "5m", 15: "15m", 30: "30m",
        60: "1h", 240: "4h", 1440: "1d", 10080: "1w",
    }

    # Approximate request weights for rate-limit tracking
    _WEIGHTS: Dict[str, int] = {
        "ticker": 2, "klines": 2, "depth_20": 5, "depth_50": 10,
        "depth_100": 10, "depth_500": 50, "order": 1, "account": 20,
        "openOrders": 6, "exchangeInfo": 20, "time": 1, "allOrders": 20,
    }
    RATE_LIMIT_PER_MINUTE = 1200

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        testnet: Optional[bool] = None,
    ):
        self.api_key: str = api_key or os.getenv("BINANCE_API_KEY", "")
        self.api_secret: str = api_secret or os.getenv("BINANCE_API_SECRET", "")

        if testnet is None:
            testnet = os.getenv("BINANCE_TESTNET", "").lower() in ("1", "true", "yes")
        self._testnet: bool = testnet
        self.base_url: str = self.TESTNET_URL if self._testnet else self.BASE_URL

        if not self.api_key or not self.api_secret:
            logger.warning("Binance API credentials not configured")

        self._exchange_info_cache: Dict[str, Dict[str, Any]] = {}
        self._time_offset_ms: int = 0
        self._time_synced: bool = False
        self._request_log: deque = deque()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a shared httpx.AsyncClient, creating it on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    @property
    def name(self) -> str:
        return "binance"

    # --------------------------------------------------------- pair helpers

    @staticmethod
    def _to_binance_symbol(pair: str) -> str:
        """``BTC/AUD`` -> ``BTCAUD``"""
        return pair.replace("/", "")

    @staticmethod
    def _to_standard_pair(symbol: str, quote: str = "USDT") -> str:
        if symbol.endswith(quote):
            return f"{symbol[:-len(quote)]}/{quote}"
        return symbol

    def _map_interval(self, interval_minutes: int) -> str:
        mapped = self.INTERVAL_MAP.get(interval_minutes)
        if mapped is None:
            raise ValueError(
                f"Unsupported interval {interval_minutes}m. "
                f"Supported: {list(self.INTERVAL_MAP.keys())}"
            )
        return mapped

    # ----------------------------------------------------------- time sync

    async def _sync_time(self) -> None:
        """Compute offset between local clock and Binance server time."""
        try:
            local_before = int(time.time() * 1000)
            data = await self._public_request("/api/v3/time", weight_key="time")
            local_after = int(time.time() * 1000)
            server_time = int(data["serverTime"])
            self._time_offset_ms = server_time - (local_before + local_after) // 2
            logger.debug("Binance time offset: %d ms", self._time_offset_ms)
        except Exception as exc:
            logger.warning("Failed to sync Binance server time: %s", exc)
            self._time_offset_ms = 0
        self._time_synced = True

    def _server_timestamp_ms(self) -> int:
        return int(time.time() * 1000) + self._time_offset_ms

    # ------------------------------------------------------- rate limiting

    async def _record_weight(self, weight: int) -> None:
        now = time.time()
        cutoff = now - 60
        while self._request_log and self._request_log[0][0] < cutoff:
            self._request_log.popleft()
        total = sum(w for _, w in self._request_log)

        # Block if adding this request would exceed the limit
        if total + weight > self.RATE_LIMIT_PER_MINUTE:
            oldest_ts = self._request_log[0][0] if self._request_log else now
            wait = 60 - (now - oldest_ts) + 0.5
            logger.warning(
                "Binance rate limit reached (%d + %d > %d). Waiting %.1f s",
                total, weight, self.RATE_LIMIT_PER_MINUTE, wait,
            )
            await asyncio.sleep(wait)
            # Prune again after sleeping
            now = time.time()
            cutoff = now - 60
            while self._request_log and self._request_log[0][0] < cutoff:
                self._request_log.popleft()

        self._request_log.append((now, weight))
        total = sum(w for _, w in self._request_log)
        if total > self.RATE_LIMIT_PER_MINUTE * 0.8:
            logger.warning(
                "Binance rate limit approaching: %d / %d in trailing 60 s",
                total, self.RATE_LIMIT_PER_MINUTE,
            )

    # -------------------------------------------------------- authentication

    def _sign(self, query_string: str) -> str:
        """HMAC-SHA256 signature of *query_string*."""
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    # --------------------------------------------------------- HTTP helpers

    async def _public_request(
        self, path: str, params: Optional[Dict[str, Any]] = None,
        weight_key: str = "ticker",
    ) -> Any:
        """Unauthenticated GET request with retry."""
        url = f"{self.base_url}{path}"
        await self._record_weight(self._WEIGHTS.get(weight_key, 1))

        client = await self._get_client()
        last_exc = None
        for attempt in range(3):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "code" in data and data["code"] != 200:
                    raise Exception(f"Binance API error {data['code']}: {data.get('msg', '')}")
                return data
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("Binance request %s failed (attempt %d): %s. Retrying in %ds",
                               path, attempt + 1, exc, wait)
                await asyncio.sleep(wait)
        raise last_exc

    async def _signed_request(
        self, method: str, path: str,
        params: Optional[Dict[str, Any]] = None,
        weight_key: str = "order",
    ) -> Any:
        """Authenticated request (GET / POST / DELETE).

        Adds ``timestamp`` + ``signature`` query params and sends the
        API key via the ``X-MBX-APIKEY`` header.
        """
        if not self.api_key or not self.api_secret:
            raise Exception("Binance API credentials not configured")
        if not self._time_synced:
            await self._sync_time()

        params = dict(params or {})
        params["timestamp"] = self._server_timestamp_ms()
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        qs += f"&signature={self._sign(qs)}"

        url = f"{self.base_url}{path}?{qs}"
        headers = {"X-MBX-APIKEY": self.api_key}
        await self._record_weight(self._WEIGHTS.get(weight_key, 1))

        client = await self._get_client()
        last_exc = None
        for attempt in range(3):
            try:
                if method == "GET":
                    resp = await client.get(url, headers=headers)
                elif method == "POST":
                    resp = await client.post(url, headers=headers)
                elif method == "DELETE":
                    resp = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "code" in data and data["code"] != 200:
                    raise Exception(f"Binance API error {data['code']}: {data.get('msg', '')}")
                return data
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning("Binance signed request %s failed (attempt %d): %s. Retrying in %ds",
                               path, attempt + 1, exc, wait)
                await asyncio.sleep(wait)
                # Re-sign on retry (timestamp may be stale)
                params["timestamp"] = self._server_timestamp_ms()
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                qs += f"&signature={self._sign(qs)}"
                url = f"{self.base_url}{path}?{qs}"
        raise last_exc

    # ------------------------------------------- exchange info & rounding

    async def _ensure_exchange_info(self, symbol: str) -> Dict[str, Any]:
        """Fetch and cache LOT_SIZE, MIN_NOTIONAL, PRICE_FILTER for *symbol*."""
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]

        data = await self._public_request(
            "/api/v3/exchangeInfo", params={"symbol": symbol},
            weight_key="exchangeInfo",
        )
        filters: Dict[str, Any] = {}
        for sym_info in data.get("symbols", []):
            if sym_info["symbol"] != symbol:
                continue
            for f in sym_info.get("filters", []):
                ft = f["filterType"]
                if ft == "LOT_SIZE":
                    filters["lot_step"] = float(f["stepSize"])
                    filters["lot_min"] = float(f["minQty"])
                    filters["lot_max"] = float(f["maxQty"])
                elif ft == "PRICE_FILTER":
                    filters["price_tick"] = float(f["tickSize"])
                    filters["price_min"] = float(f["minPrice"])
                    filters["price_max"] = float(f["maxPrice"])
                elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                    filters["min_notional"] = float(f.get("minNotional", 0))
            break

        self._exchange_info_cache[symbol] = filters
        return filters

    @staticmethod
    def _round_step(value: float, step: float) -> float:
        """Round *value* down to the nearest multiple of *step*."""
        if step <= 0:
            return value
        precision = max(0, int(round(-math.log10(step))))
        return round(math.floor(value / step) * step, precision)

    async def _round_quantity(self, symbol: str, qty: float) -> float:
        info = await self._ensure_exchange_info(symbol)
        return self._round_step(qty, info.get("lot_step", 1e-8))

    async def _round_price(self, symbol: str, price: float) -> float:
        info = await self._ensure_exchange_info(symbol)
        return self._round_step(price, info.get("price_tick", 0.01))

    # --------------------------------------------- normalised order response

    @staticmethod
    def _normalise_order(result: Dict, pair: str, side: str) -> Dict:
        """Reshape Binance order response to project-standard format
        (backward-compatible with Kraken-shaped code)."""
        executed_qty = float(result.get("executedQty", 0))
        cum_quote = float(result.get("cummulativeQuoteQty", 0))
        avg_price = (cum_quote / executed_qty) if executed_qty > 0 else 0.0
        return {
            "order_id": str(result["orderId"]),
            "txid": [str(result["orderId"])],
            "status": result.get("status", ""),
            "price": avg_price,
            "filled_base": executed_qty,
            "filled_quote": cum_quote,
            "pair": pair,
            "side": side,
            "volume": float(result.get("origQty", executed_qty)),
            "cost": cum_quote,
        }

    # ========================================================= IExchange API

    # ----------------------------------------------------------- get_balance

    async def get_balance(self) -> Dict[str, float]:
        """Non-zero balances keyed by asset, plus ``total`` in USDT.

        Only values assets that have a USDT trading pair among
        commonly traded assets to avoid exhausting the rate limit
        on testnet accounts that hold hundreds of small assets.
        """
        result = await self._signed_request("GET", "/api/v3/account", weight_key="account")

        # Significant-balance threshold to skip dust amounts
        _DUST_THRESHOLD = 1e-6

        balance: Dict[str, float] = {}
        total_usdt = 0.0
        assets_to_value: List[tuple] = []

        for entry in result.get("balances", []):
            amount = float(entry["free"]) + float(entry["locked"])
            if amount <= _DUST_THRESHOLD:
                continue
            asset = entry["asset"]
            balance[asset] = amount
            if asset == "USDT":
                total_usdt += amount
            else:
                assets_to_value.append((asset, amount))

        # Only price the top assets by balance size to avoid rate limit abuse
        # (Binance testnet gives 50+ non-zero assets)
        assets_to_value.sort(key=lambda x: x[1], reverse=True)
        for asset, amount in assets_to_value[:10]:
            try:
                ticker = await self.get_ticker(f"{asset}/USDT")
                total_usdt += amount * ticker.get("price", 0)
            except Exception:
                pass  # no USDT pair for this asset

        balance["total"] = total_usdt
        return balance

    # ----------------------------------------------------------- get_ticker

    async def get_ticker(self, pair: str) -> Dict:
        """24-hour ticker data for *pair*."""
        symbol = self._to_binance_symbol(pair)
        data = await self._public_request(
            "/api/v3/ticker/24hr", params={"symbol": symbol}, weight_key="ticker",
        )
        return {
            "pair": pair,
            "price": float(data["lastPrice"]),
            "bid": float(data["bidPrice"]),
            "ask": float(data["askPrice"]),
            "high_24h": float(data["highPrice"]),
            "low_24h": float(data["lowPrice"]),
            "volume_24h": float(data["volume"]),
            "vwap_24h": float(data["weightedAvgPrice"]),
            "trades_24h": int(data["count"]),
        }

    # ------------------------------------------------------------ get_ohlcv

    async def get_ohlcv(self, pair: str, interval: int = 60, limit: int = 24) -> List:
        """OHLCV candles as ``[timestamp, open, high, low, close, volume]``."""
        symbol = self._to_binance_symbol(pair)
        data = await self._public_request(
            "/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": self._map_interval(interval),
                "limit": min(limit, 1000),
            },
            weight_key="klines",
        )
        # Binance returns 12-element arrays per kline
        return [
            [int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
            for k in data
        ]

    # -------------------------------------------------------- get_market_data

    async def get_market_data(self, pair: str) -> MarketData:
        """Compose ticker + OHLCV into a MarketData object."""
        ticker = await self.get_ticker(pair)
        ohlcv = await self.get_ohlcv(pair, interval=60, limit=24)
        return MarketData(
            pair=pair,
            current_price=ticker["price"],
            high_24h=ticker["high_24h"],
            low_24h=ticker["low_24h"],
            volume_24h=ticker["volume_24h"],
            vwap_24h=ticker.get("vwap_24h"),
            trades_24h=ticker.get("trades_24h"),
            ohlcv=ohlcv,
        )

    # ------------------------------------------------------------- market_buy

    async def market_buy(self, pair: str, amount_quote: float) -> Dict:
        """Market buy spending *amount_quote* of the quote currency.
        Uses Binance-native ``quoteOrderQty``."""
        symbol = self._to_binance_symbol(pair)
        result = await self._signed_request("POST", "/api/v3/order", params={
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": f"{amount_quote:.8f}",
        }, weight_key="order")
        logger.info("Market BUY %s | quoteQty=%.4f | orderId=%s | status=%s",
                     pair, amount_quote, result.get("orderId"), result.get("status"))
        return self._normalise_order(result, pair, "buy")

    # ------------------------------------------------------------ market_sell

    async def market_sell(self, pair: str, amount_base: float) -> Dict:
        """Market sell *amount_base* of the base currency (LOT_SIZE rounded)."""
        symbol = self._to_binance_symbol(pair)
        quantity = await self._round_quantity(symbol, amount_base)
        result = await self._signed_request("POST", "/api/v3/order", params={
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": f"{quantity:.8f}",
        }, weight_key="order")
        logger.info("Market SELL %s | qty=%.8f | orderId=%s | status=%s",
                     pair, quantity, result.get("orderId"), result.get("status"))
        return self._normalise_order(result, pair, "sell")

    # -------------------------------------------------------------- limit_buy

    async def limit_buy(self, pair: str, amount_quote: float, price: float) -> Dict:
        """GTC limit buy.  Quantity = amount_quote / price, LOT_SIZE rounded."""
        symbol = self._to_binance_symbol(pair)
        quantity = await self._round_quantity(symbol, amount_quote / price)
        rounded_price = await self._round_price(symbol, price)
        result = await self._signed_request("POST", "/api/v3/order", params={
            "symbol": symbol, "side": "BUY", "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{quantity:.8f}", "price": f"{rounded_price:.8f}",
        }, weight_key="order")
        logger.info("Limit BUY %s | qty=%.8f @ %.8f | orderId=%s",
                     pair, quantity, rounded_price, result.get("orderId"))
        return self._normalise_order(result, pair, "buy")

    # ------------------------------------------------------------- limit_sell

    async def limit_sell(self, pair: str, amount_base: float, price: float) -> Dict:
        """GTC limit sell.  Quantity LOT_SIZE rounded."""
        symbol = self._to_binance_symbol(pair)
        quantity = await self._round_quantity(symbol, amount_base)
        rounded_price = await self._round_price(symbol, price)
        result = await self._signed_request("POST", "/api/v3/order", params={
            "symbol": symbol, "side": "SELL", "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": f"{quantity:.8f}", "price": f"{rounded_price:.8f}",
        }, weight_key="order")
        logger.info("Limit SELL %s | qty=%.8f @ %.8f | orderId=%s",
                     pair, quantity, rounded_price, result.get("orderId"))
        return self._normalise_order(result, pair, "sell")

    # ---------------------------------------------------------- cancel_order

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict:
        """Cancel an open order.  *symbol* is required by Binance."""
        if symbol is None:
            raise ValueError("Binance requires the symbol/pair to cancel an order")
        result = await self._signed_request("DELETE", "/api/v3/order", params={
            "symbol": self._to_binance_symbol(symbol), "orderId": order_id,
        }, weight_key="order")
        logger.info("Cancelled order %s on %s", order_id, symbol)
        return result

    # -------------------------------------------------------- get_open_orders

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """All open orders, optionally filtered by *symbol*."""
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = self._to_binance_symbol(symbol)
        return await self._signed_request(
            "GET", "/api/v3/openOrders", params=params, weight_key="openOrders",
        )  # type: ignore[return-value]

    # -------------------------------------------------------- get_order_book

    async def get_order_book(self, pair: str, depth: int = 25) -> Dict:
        """Order book: ``{pair, bids: [[price, qty], ...], asks: [...]}``."""
        symbol = self._to_binance_symbol(pair)
        clamped = min(depth, 5000)
        wk = ("depth_20" if clamped <= 20 else "depth_50" if clamped <= 50
              else "depth_100" if clamped <= 100 else "depth_500")
        data = await self._public_request(
            "/api/v3/depth", params={"symbol": symbol, "limit": clamped},
            weight_key=wk,
        )
        return {
            "pair": pair,
            "bids": [[float(l[0]), float(l[1])] for l in data.get("bids", [])],
            "asks": [[float(l[0]), float(l[1])] for l in data.get("asks", [])],
        }

    # ---------------------------------------------------------- query_order

    async def query_order(self, order_id: str, symbol: str) -> Dict:
        """Poll status of a specific order."""
        result = await self._signed_request("GET", "/api/v3/order", params={
            "symbol": self._to_binance_symbol(symbol), "orderId": order_id,
        }, weight_key="order")
        executed_qty = float(result.get("executedQty", 0))
        cum_quote = float(result.get("cummulativeQuoteQty", 0))
        return {
            "order_id": str(result["orderId"]),
            "symbol": result["symbol"],
            "status": result["status"],
            "side": result["side"],
            "type": result["type"],
            "price": (cum_quote / executed_qty) if executed_qty > 0 else 0.0,
            "orig_qty": float(result.get("origQty", 0)),
            "executed_qty": executed_qty,
            "cum_quote_qty": cum_quote,
            "time": result.get("time"),
            "update_time": result.get("updateTime"),
        }

    # --------------------------------------------------------- get_all_pairs

    async def get_all_pairs(self, quote_currency: str = "USDT") -> List[str]:
        """Every active trading pair for *quote_currency*."""
        data = await self._public_request("/api/v3/exchangeInfo", weight_key="exchangeInfo")
        return sorted(
            f"{s['baseAsset']}/{quote_currency}"
            for s in data.get("symbols", [])
            if s.get("quoteAsset") == quote_currency and s.get("status") == "TRADING"
        )

    # ----------------------------------------------------- get_tradable_pairs

    async def get_tradable_pairs(
        self, quote_currency: str = "USDT", min_volume_24h: float = 0.0,
    ) -> List[str]:
        """Pairs filtered by minimum 24 h quote volume."""
        all_pairs = await self.get_all_pairs(quote_currency)
        if min_volume_24h <= 0:
            return all_pairs

        tickers = await self._public_request("/api/v3/ticker/24hr", weight_key="ticker")
        vol_map: Dict[str, float] = {t["symbol"]: float(t["quoteVolume"]) for t in tickers}
        return sorted(
            p for p in all_pairs
            if vol_map.get(self._to_binance_symbol(p), 0) >= min_volume_24h
        )
