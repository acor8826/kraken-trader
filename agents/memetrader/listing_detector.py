import logging
from typing import Dict, List, Optional
import httpx

from agents.memetrader.config import MemeConfig

logger = logging.getLogger(__name__)

BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

class ListingDetector:
    """Auto-discovers meme coin USDT pairs on Binance."""

    def __init__(self, config: MemeConfig = None):
        self.config = config or MemeConfig()
        self._last_known_pairs: Dict[str, str] = {}
        self._keywords_upper = [k.upper() for k in self.config.meme_keywords]

    @property
    def active_pairs(self) -> Dict[str, str]:
        """symbol -> pair mapping of detected meme coins."""
        return dict(self._last_known_pairs)

    @property
    def active_symbols(self) -> List[str]:
        """List of active meme coin symbols."""
        return list(self._last_known_pairs.keys())

    async def detect_meme_pairs(self) -> Dict[str, str]:
        """Fetch Binance exchangeInfo and filter for meme coin USDT pairs."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(BINANCE_EXCHANGE_INFO_URL)
                resp.raise_for_status()
                data = resp.json()

            if "code" in data:
                logger.warning(f"[LISTING] Binance API error: {data.get('msg', 'Unknown')}")
                if self._last_known_pairs:
                    return dict(self._last_known_pairs)

            symbols = data.get("symbols", [])
            found: Dict[str, str] = {}

            for symbol_info in symbols:
                quote = symbol_info.get("quoteAsset", "")
                base = symbol_info.get("baseAsset", "")
                status = symbol_info.get("status", "")

                # Only USDT pairs that are actively trading
                if quote != "USDT" or status != "TRADING":
                    continue

                # Check if base matches any meme keyword
                base_upper = base.upper()
                for keyword in self._keywords_upper:
                    if keyword in base_upper or base_upper.startswith(keyword):
                        standard_pair = f"{base_upper}/USDT"
                        found[base_upper] = standard_pair
                        break

            # Log changes
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
            logger.warning(f"[LISTING] Failed to detect pairs: {e}")
            if self._last_known_pairs:
                logger.info("[LISTING] Using last known pairs as fallback")
                return dict(self._last_known_pairs)
            return {}
