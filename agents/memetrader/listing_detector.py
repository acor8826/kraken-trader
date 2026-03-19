import logging
import os
from typing import Dict, List
import httpx

from agents.memetrader.config import MemeConfig

logger = logging.getLogger(__name__)

BINANCE_EXCHANGE_INFO_URL = "https://api.binance.us/api/v3/exchangeInfo"
KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"

# Kraken asset name normalization (X/Z prefix convention)
_ASSET_NORMALIZE = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "XDOGE": "DOGE",
    "XXDG": "DOGE",
}


def _normalize_asset(raw: str) -> str:
    """Strip Kraken X/Z prefixes to get standard ticker symbol."""
    upper = raw.upper()
    if upper in _ASSET_NORMALIZE:
        return _ASSET_NORMALIZE[upper]
    if len(upper) >= 4 and upper[0] in ("X", "Z"):
        return upper[1:]
    return upper


class ListingDetector:
    """Auto-discovers meme coin pairs on Binance (USDT) or Kraken (AUD)."""

    def __init__(self, config: MemeConfig = None):
        self.config = config or MemeConfig()
        self._last_known_pairs: Dict[str, str] = {}
        self._keywords_upper = [k.upper() for k in self.config.meme_keywords]
        self._exchange = os.getenv("EXCHANGE", "kraken").lower()
        self._quote = "USDT" if self._exchange == "binance" else "AUD"

    @property
    def active_pairs(self) -> Dict[str, str]:
        """symbol -> pair mapping of detected meme coins."""
        return dict(self._last_known_pairs)

    @property
    def active_symbols(self) -> List[str]:
        """List of active meme coin symbols."""
        return list(self._last_known_pairs.keys())

    async def detect_meme_pairs(self) -> Dict[str, str]:
        """Detect meme coin pairs on the configured exchange."""
        if self._exchange == "binance":
            return await self._detect_binance()
        return await self._detect_kraken()

    async def _detect_binance(self) -> Dict[str, str]:
        """Fetch Binance exchangeInfo and filter for meme coin USDT pairs."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(BINANCE_EXCHANGE_INFO_URL)
                resp.raise_for_status()
                data = resp.json()

            found: Dict[str, str] = {}

            for symbol_info in data.get("symbols", []):
                if symbol_info.get("status") != "TRADING":
                    continue
                quote = symbol_info.get("quoteAsset", "")
                if quote != "USDT":
                    continue
                base = symbol_info.get("baseAsset", "").upper()

                for keyword in self._keywords_upper:
                    if keyword in base or base.startswith(keyword):
                        standard_pair = f"{base}/USDT"
                        found[base] = standard_pair
                        break

            new_coins = set(found.keys()) - set(self._last_known_pairs.keys())
            removed_coins = set(self._last_known_pairs.keys()) - set(found.keys())
            if new_coins:
                logger.info(f"[LISTING] New meme coins detected: {new_coins}")
            if removed_coins:
                logger.info(f"[LISTING] Meme coins removed: {removed_coins}")

            self._last_known_pairs = found
            logger.info(f"[LISTING] Active meme pairs: {len(found)} - {list(found.values())}")
            return dict(found)

        except Exception as e:
            logger.warning(f"[LISTING] Binance detection failed: {e}")
            if self._last_known_pairs:
                return dict(self._last_known_pairs)
            # Fallback: use well-known meme coins for simulation mode
            return self._sim_fallback_pairs()

    def _sim_fallback_pairs(self) -> Dict[str, str]:
        """Return hardcoded meme coin pairs for simulation when API is unavailable."""
        sim_memes = ["SHIB", "PEPE", "BONK", "FLOKI", "WIF", "MEME",
                     "TURBO", "NEIRO", "MOG", "POPCAT", "BRETT", "MEW", "DOGE"]
        found = {}
        for symbol in sim_memes:
            for keyword in self._keywords_upper:
                if keyword in symbol or symbol.startswith(keyword):
                    found[symbol] = f"{symbol}/{self._quote}"
                    break
        if found:
            self._last_known_pairs = found
            logger.info(f"[LISTING] Using sim fallback: {len(found)} pairs")
        return found

    async def _detect_kraken(self) -> Dict[str, str]:
        """Fetch Kraken AssetPairs and filter for meme coin AUD pairs."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(KRAKEN_ASSET_PAIRS_URL)
                resp.raise_for_status()
                data = resp.json()

            errors = data.get("error", [])
            if errors:
                logger.warning(f"[LISTING] Kraken API errors: {errors}")
                if self._last_known_pairs:
                    return dict(self._last_known_pairs)

            pairs_data = data.get("result", {})
            found: Dict[str, str] = {}

            for pair_name, pair_info in pairs_data.items():
                if pair_name.endswith(".d"):
                    continue

                quote_raw = pair_info.get("quote", "")
                base_raw = pair_info.get("base", "")

                quote_norm = _normalize_asset(quote_raw)
                if quote_norm != "AUD":
                    continue

                base_norm = _normalize_asset(base_raw)

                for keyword in self._keywords_upper:
                    if keyword in base_norm or base_norm.startswith(keyword):
                        standard_pair = f"{base_norm}/AUD"
                        found[base_norm] = standard_pair
                        break

            new_coins = set(found.keys()) - set(self._last_known_pairs.keys())
            removed_coins = set(self._last_known_pairs.keys()) - set(found.keys())
            if new_coins:
                logger.info(f"[LISTING] New meme coins detected: {new_coins}")
            if removed_coins:
                logger.info(f"[LISTING] Meme coins removed: {removed_coins}")

            self._last_known_pairs = found
            logger.info(f"[LISTING] Active meme pairs: {len(found)} - {list(found.values())}")
            return dict(found)

        except Exception as e:
            logger.warning(f"[LISTING] Kraken detection failed: {e}")
            if self._last_known_pairs:
                return dict(self._last_known_pairs)
            return {}
