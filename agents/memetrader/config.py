from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class MemeConfig:
    # Risk limits
    max_meme_allocation_pct: float = 0.25      # 25% of total portfolio
    max_per_coin_pct: float = 0.05             # 5% per coin
    max_simultaneous_positions: int = 3
    min_trade_size_aud: float = 5.0

    # Timing
    cycle_interval_seconds: int = 180           # 3 minutes
    listing_check_every_n_cycles: int = 5       # ~15 min

    # Stop losses
    trailing_stop_activation_pct: float = 0.20  # Activate at +20% gain
    trailing_stop_distance_pct: float = 0.10    # Trail at 10% from peak
    hard_stop_loss_pct: float = 0.15            # Hard stop at -15%

    # Decision thresholds
    entry_cms_threshold: float = 0.65           # CMS >= 0.65 for rule-based BUY
    ambiguous_cms_lower: float = 0.40           # CMS 0.40-0.65 = ask Haiku
    exit_cms_threshold: float = -0.30           # CMS <= -0.30 for rule-based SELL
    min_volume_z_score: float = 1.5             # Min volume Z for entry

    # Signal weights
    twitter_weight: float = 0.55
    volume_weight: float = 0.45

    # Twitter API budget
    daily_api_reads: int = 330
    monthly_api_reads: int = 10000

    # LLM
    haiku_model: str = "claude-haiku-3-5-20241022"

    # Circuit breaker
    consecutive_loss_trigger: int = 2
    circuit_breaker_pause_seconds: int = 3600   # 1 hour
    daily_meme_loss_limit_pct: float = 0.05     # 5% of total portfolio

    # Known meme keywords for listing detection
    meme_keywords: List[str] = field(default_factory=lambda: [
        "DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "WIF", "MEME", "TURBO",
        "NEIRO", "MOG", "POPCAT", "BRETT", "MEW"
    ])

    # Runtime state (populated by ListingDetector)
    known_meme_coins: Dict[str, str] = field(default_factory=dict)
