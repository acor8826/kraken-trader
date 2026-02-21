"""
Kraken Exchange Integration

Full implementation of the IExchange interface for Kraken.
"""

import os
import time
import hmac
import base64
import hashlib
import urllib.parse
from typing import Dict, List, Optional
import httpx
import logging
from datetime import datetime, timezone

from core.interfaces import IExchange
from core.models import MarketData

logger = logging.getLogger(__name__)


class KrakenExchange(IExchange):
    """
    Kraken exchange implementation.
    Supports both REST API for trading and market data.
    """
    
    BASE_URL = "https://api.kraken.com"
    
    # Pair mapping: standard -> Kraken format
    PAIR_MAP = {
        # Major caps
        "BTC/AUD": "XBTAUD",
        "ETH/AUD": "ETHAUD",
        # Mid-tier volatility
        "SOL/AUD": "SOLAUD",
        "LINK/AUD": "LINKAUD",
        "DOT/AUD": "DOTAUD",
        "AVAX/AUD": "AVAXAUD",
        "ADA/AUD": "ADAAUD",
        "ATOM/AUD": "ATOMAUD",
        "MATIC/AUD": "MATICAUD",
        "XRP/AUD": "XRPAUD",
    }
    
    # Asset mapping: Kraken -> standard
    ASSET_MAP = {
        "XXBT": "BTC",
        "XBT": "BTC",
        "XETH": "ETH",
        "ETH": "ETH",
        "SOL": "SOL",
        "LINK": "LINK",
        "DOT": "DOT",
        "AVAX": "AVAX",
        "ADA": "ADA",
        "ATOM": "ATOM",
        "MATIC": "MATIC",
        "XRP": "XRP",
        "XXRP": "XRP",
        "ZAUD": "AUD",
        "AUD": "AUD",
    }
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or os.getenv("KRAKEN_API_KEY", "")
        self.api_secret = api_secret or os.getenv("KRAKEN_API_SECRET", "")
        
        if not self.api_key or not self.api_secret:
            logger.warning("Kraken API credentials not configured")
    
    @property
    def name(self) -> str:
        return "kraken"
    
    def _get_kraken_pair(self, pair: str) -> str:
        """Convert standard pair to Kraken format"""
        return self.PAIR_MAP.get(pair, pair.replace("/", ""))
    
    def _normalize_asset(self, asset: str) -> str:
        """Convert Kraken asset code to standard format"""
        return self.ASSET_MAP.get(asset, asset)
    
    def _generate_signature(self, urlpath: str, data: Dict) -> str:
        """Generate API signature for authenticated requests"""
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data['nonce']) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        
        mac = hmac.new(
            base64.b64decode(self.api_secret),
            message,
            hashlib.sha512
        )
        return base64.b64encode(mac.digest()).decode()
    
    async def _public_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make public API request"""
        url = f"{self.BASE_URL}/0/public/{endpoint}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("error"):
                raise Exception(f"Kraken API error: {data['error']}")
            
            return data.get("result", {})
    
    async def _private_request(self, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Make authenticated API request"""
        if not self.api_key or not self.api_secret:
            raise Exception("Kraken API credentials not configured")
        
        urlpath = f"/0/private/{endpoint}"
        url = f"{self.BASE_URL}{urlpath}"
        
        data = data or {}
        data["nonce"] = str(int(time.time() * 1000))
        
        headers = {
            "API-Key": self.api_key,
            "API-Sign": self._generate_signature(urlpath, data)
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=data, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if result.get("error"):
                raise Exception(f"Kraken API error: {result['error']}")
            
            return result.get("result", {})
    
    async def get_balance(self) -> Dict[str, float]:
        """Get account balance"""
        result = await self._private_request("Balance")
        
        balance = {}
        total = 0.0
        
        for asset, amount in result.items():
            normalized = self._normalize_asset(asset)
            amount = float(amount)
            
            if amount > 0:
                balance[normalized] = amount
                
                if normalized == "AUD":
                    total += amount
                else:
                    # Get current price for non-AUD assets
                    try:
                        ticker = await self.get_ticker(f"{normalized}/AUD")
                        total += amount * ticker.get("price", 0)
                    except:
                        pass
        
        balance["total"] = total
        return balance
    
    async def get_ticker(self, pair: str) -> Dict:
        """Get current ticker data"""
        kraken_pair = self._get_kraken_pair(pair)
        result = await self._public_request("Ticker", {"pair": kraken_pair})
        
        if not result:
            raise Exception(f"No ticker data for {pair}")
        
        # Get first result (handles different naming)
        ticker_data = list(result.values())[0]
        
        return {
            "pair": pair,
            "price": float(ticker_data["c"][0]),  # Last trade price
            "bid": float(ticker_data["b"][0]),
            "ask": float(ticker_data["a"][0]),
            "high_24h": float(ticker_data["h"][1]),
            "low_24h": float(ticker_data["l"][1]),
            "volume_24h": float(ticker_data["v"][1]),
            "vwap_24h": float(ticker_data["p"][1]),
            "trades_24h": int(ticker_data["t"][1])
        }
    
    async def get_ohlcv(self, pair: str, interval: int = 60, limit: int = 24) -> List:
        """
        Get OHLCV candles.
        
        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            interval: Candle interval in minutes (1, 5, 15, 30, 60, 240, 1440, 10080, 21600)
            limit: Number of candles to return
        
        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        kraken_pair = self._get_kraken_pair(pair)
        result = await self._public_request("OHLC", {
            "pair": kraken_pair,
            "interval": interval
        })
        
        candles = []
        for key, value in result.items():
            if key != "last":
                # Kraken returns: [time, open, high, low, close, vwap, volume, count]
                for candle in value[-limit:]:
                    candles.append([
                        int(candle[0]),      # timestamp
                        float(candle[1]),    # open
                        float(candle[2]),    # high
                        float(candle[3]),    # low
                        float(candle[4]),    # close
                        float(candle[6])     # volume
                    ])
                break
        
        return candles
    
    async def get_market_data(self, pair: str) -> MarketData:
        """Get comprehensive market data for analysis"""
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
            ohlcv=ohlcv
        )
    
    async def market_buy(self, pair: str, amount_quote: float) -> Dict:
        """
        Execute market buy order.
        
        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            amount_quote: Amount in quote currency (e.g., AUD) to spend
        """
        kraken_pair = self._get_kraken_pair(pair)
        
        # Get current price to calculate volume
        ticker = await self.get_ticker(pair)
        volume = amount_quote / ticker["price"]
        
        result = await self._private_request("AddOrder", {
            "pair": kraken_pair,
            "type": "buy",
            "ordertype": "market",
            "volume": str(round(volume, 8))
        })
        
        logger.info(f"Market buy: {pair} | Volume: {volume:.8f} | ~${amount_quote:.2f} AUD")
        return result
    
    async def market_sell(self, pair: str, amount_base: float) -> Dict:
        """
        Execute market sell order.
        
        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            amount_base: Amount in base currency (e.g., BTC) to sell
        """
        kraken_pair = self._get_kraken_pair(pair)
        
        result = await self._private_request("AddOrder", {
            "pair": kraken_pair,
            "type": "sell",
            "ordertype": "market",
            "volume": str(round(amount_base, 8))
        })
        
        logger.info(f"Market sell: {pair} | Volume: {amount_base:.8f}")
        return result
    
    async def limit_buy(self, pair: str, amount_quote: float, price: float) -> Dict:
        """Place limit buy order"""
        kraken_pair = self._get_kraken_pair(pair)
        volume = amount_quote / price
        
        result = await self._private_request("AddOrder", {
            "pair": kraken_pair,
            "type": "buy",
            "ordertype": "limit",
            "price": str(price),
            "volume": str(round(volume, 8))
        })
        
        logger.info(f"Limit buy: {pair} | {volume:.8f} @ ${price:,.2f}")
        return result
    
    async def limit_sell(self, pair: str, amount_base: float, price: float) -> Dict:
        """Place limit sell order"""
        kraken_pair = self._get_kraken_pair(pair)
        
        result = await self._private_request("AddOrder", {
            "pair": kraken_pair,
            "type": "sell",
            "ordertype": "limit",
            "price": str(price),
            "volume": str(round(amount_base, 8))
        })
        
        logger.info(f"Limit sell: {pair} | {amount_base:.8f} @ ${price:,.2f}")
        return result
    
    async def cancel_order(self, order_id: str) -> Dict:
        """Cancel an open order"""
        return await self._private_request("CancelOrder", {"txid": order_id})
    
    async def get_open_orders(self) -> Dict:
        """Get all open orders"""
        return await self._private_request("OpenOrders")

    async def get_order_book(self, pair: str, depth: int = 25) -> Dict:
        """
        Get order book depth.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            depth: Number of levels to fetch (1-500, default 25)

        Returns:
            {
                "bids": [[price, volume, timestamp], ...],
                "asks": [[price, volume, timestamp], ...],
                "pair": pair
            }
        """
        kraken_pair = self._get_kraken_pair(pair)
        result = await self._public_request("Depth", {
            "pair": kraken_pair,
            "count": min(depth, 500)
        })

        if not result:
            raise Exception(f"No order book data for {pair}")

        # Get first result
        book_data = list(result.values())[0]

        return {
            "pair": pair,
            "bids": [
                [float(level[0]), float(level[1]), int(level[2])]
                for level in book_data.get("bids", [])
            ],
            "asks": [
                [float(level[0]), float(level[1]), int(level[2])]
                for level in book_data.get("asks", [])
            ]
        }

    async def get_all_pairs(self, quote_currency: str = "AUD") -> List[Dict]:
        """
        Fetch all tradable pairs for a quote currency.

        This enables dynamic pair discovery instead of static pair lists.

        Args:
            quote_currency: Quote currency to filter by (default: "AUD")

        Returns:
            List of pairs with metadata:
            - pair: Standard format (e.g., "BTC/AUD")
            - kraken_pair: Kraken format (e.g., "XBTAUD")
            - base_asset: Base currency (e.g., "BTC")
            - min_order: Minimum order size
            - tick_size: Price precision
            - status: Trading status
        """
        result = await self._public_request("AssetPairs")

        pairs = []
        quote_suffix = quote_currency.upper()

        for kraken_pair, info in result.items():
            # Get quote asset
            quote = info.get("quote", "")

            # Check if this pair has our desired quote currency
            is_aud_pair = (
                quote.endswith(quote_suffix) or
                quote == f"Z{quote_suffix}" or
                quote == quote_suffix
            )

            if not is_aud_pair:
                continue

            # Skip if not tradable
            if info.get("status") not in ["online", None]:
                continue

            # Extract base asset
            base = info.get("base", "")
            base_normalized = self._normalize_asset(base)

            # Skip wrapped/staked versions (e.g., XXBT.M)
            if "." in kraken_pair:
                continue

            # Create standard pair name
            pair_standard = f"{base_normalized}/{quote_currency}"

            # Update PAIR_MAP dynamically
            if pair_standard not in self.PAIR_MAP:
                self.PAIR_MAP[pair_standard] = kraken_pair

            pairs.append({
                "pair": pair_standard,
                "kraken_pair": kraken_pair,
                "base_asset": base_normalized,
                "quote_asset": quote_currency,
                "min_order": float(info.get("ordermin", 0)),
                "lot_decimals": info.get("lot_decimals", 8),
                "pair_decimals": info.get("pair_decimals", 8),
                "status": info.get("status", "online"),
                "wsname": info.get("wsname", "")
            })

        logger.info(f"[PAIRS] Discovered {len(pairs)} {quote_currency} pairs from Kraken")
        return pairs

    async def get_tradable_pairs(
        self,
        quote_currency: str = "AUD",
        min_volume_24h: float = 1000
    ) -> List[Dict]:
        """
        Get tradable pairs filtered by volume.

        Args:
            quote_currency: Quote currency (default: "AUD")
            min_volume_24h: Minimum 24h volume in quote currency

        Returns:
            List of pairs with volume data, sorted by volume descending
        """
        all_pairs = await self.get_all_pairs(quote_currency)

        tradable = []
        for pair_info in all_pairs:
            try:
                ticker = await self.get_ticker(pair_info["pair"])

                # Calculate volume in quote currency
                volume_quote = ticker["volume_24h"] * ticker["price"]

                if volume_quote >= min_volume_24h:
                    pair_info["volume_24h"] = volume_quote
                    pair_info["price"] = ticker["price"]
                    pair_info["spread_pct"] = (ticker["ask"] - ticker["bid"]) / ticker["price"] * 100
                    tradable.append(pair_info)
            except Exception as e:
                logger.debug(f"Could not get ticker for {pair_info['pair']}: {e}")
                continue

        # Sort by volume descending
        tradable.sort(key=lambda x: x.get("volume_24h", 0), reverse=True)

        logger.info(f"[PAIRS] {len(tradable)} pairs with volume > ${min_volume_24h:.0f}")
        return tradable
