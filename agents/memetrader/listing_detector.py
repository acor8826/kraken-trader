import logging
from typing import Dict, List
import httpx

from agents.memetrader.config import MemeConfig

logger = logging.getLogger(__name__)

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
    # Strip leading X (non-fiat) or Z (fiat) prefix if 4+ chars
    if len(upper) >= 4 and upper[0] in ("X", "Z"):
        return upper[1:]
    return upper


class ListingDetector:
    """Auto-discovers meme coin AUD pairs on Kraken."""

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
                # Skip dark pool pairs (end with .d)
                if pair_name.endswith(".d"):
                    continue

                # Use wsname for clean pair representation, fallback to raw fields
                wsname = pair_info.get("wsname", "")
                quote_raw = pair_info.get("quote", "")
                base_raw = pair_info.get("base", "")

                # Normalize quote to check for AUD
                quote_norm = _normalize_asset(quote_raw)
                if quote_norm != "AUD":
                    continue

                # Normalize base asset
                base_norm = _normalize_asset(base_raw)

                # Check if base matches any meme keyword
                for keyword in self._keywords_upper:
                    if keyword in base_norm or base_norm.startswith(keyword):
                        standard_pair = f"{base_norm}/AUD"
                        found[base_norm] = standard_pair
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
