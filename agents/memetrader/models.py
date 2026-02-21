from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from enum import Enum
from typing import Dict, Optional, List

class MemeTier(Enum):
    HOT = "hot"      # Active position or recent spike - poll every cycle
    WARM = "warm"    # Moderate recent activity - poll every 3rd cycle
    COLD = "cold"    # No recent activity - poll every 10th cycle

@dataclass
class CoinSentiment:
    symbol: str
    mention_count: int = 0
    sentiment_score: float = 0.0        # -1.0 to +1.0
    bullish_ratio: float = 0.0          # 0.0 to 1.0
    influencer_mentions: int = 0        # Authors with >= 10K followers
    engagement_rate: float = 0.0        # avg(likes+retweets) normalized
    mention_velocity: float = 0.0       # mentions per minute

@dataclass
class MomentumSnapshot:
    symbol: str
    volume_z_score: float = 0.0
    price_momentum_5m: float = 0.0      # % change over 5 min
    price_momentum_15m: float = 0.0     # % change over 15 min
    buy_sell_ratio: float = 1.0         # bid_vol / ask_vol
    spread_pct: float = 0.0            # spread as % of price
    trades_acceleration: float = 0.0    # trade frequency change

@dataclass
class MemePosition:
    symbol: str
    pair: str
    entry_price: float
    amount: float
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    peak_price: float = 0.0
    trailing_active: bool = False
    trailing_stop_price: float = 0.0

    def __post_init__(self):
        if self.peak_price == 0.0:
            self.peak_price = self.entry_price

    @property
    def unrealized_pnl_pct(self) -> float:
        """Unrealized PnL as percentage of entry price. Needs current_price set externally or via update."""
        if self.entry_price > 0 and hasattr(self, '_current_price') and self._current_price:
            return ((self._current_price - self.entry_price) / self.entry_price) * 100
        return 0.0

    @property
    def from_peak_pct(self) -> float:
        """Drop from peak as negative percentage."""
        if self.peak_price > 0 and hasattr(self, '_current_price') and self._current_price:
            return ((self._current_price - self.peak_price) / self.peak_price) * 100
        return 0.0

    def update_price(self, current_price: float):
        """Update current price and peak tracking."""
        self._current_price = current_price
        if current_price > self.peak_price:
            self.peak_price = current_price

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "pair": self.pair,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "peak_price": self.peak_price,
            "trailing_active": self.trailing_active,
            "trailing_stop_price": self.trailing_stop_price,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "from_peak_pct": self.from_peak_pct,
        }

@dataclass
class MemeBudgetState:
    daily_reads_limit: int = 330
    monthly_reads_limit: int = 10000
    reads_used_today: int = 0
    reads_used_month: int = 0
    _current_day: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    _current_month: int = field(default_factory=lambda: datetime.now(timezone.utc).month)

    @property
    def daily_reads_remaining(self) -> int:
        self._check_reset()
        return max(0, self.daily_reads_limit - self.reads_used_today)

    @property
    def monthly_reads_remaining(self) -> int:
        self._check_reset()
        return max(0, self.monthly_reads_limit - self.reads_used_month)

    @property
    def budget_exhausted(self) -> bool:
        self._check_reset()
        return self.daily_reads_remaining <= 0 or self.monthly_reads_remaining <= 0

    def record_read(self, count: int = 1):
        self._check_reset()
        self.reads_used_today += count
        self.reads_used_month += count

    def _check_reset(self):
        now = datetime.now(timezone.utc)
        today = now.date()
        if today != self._current_day:
            self.reads_used_today = 0
            self._current_day = today
        if now.month != self._current_month:
            self.reads_used_month = 0
            self._current_month = now.month

    def to_dict(self) -> Dict:
        return {
            "daily_reads_remaining": self.daily_reads_remaining,
            "monthly_reads_remaining": self.monthly_reads_remaining,
            "reads_used_today": self.reads_used_today,
            "reads_used_month": self.reads_used_month,
            "budget_exhausted": self.budget_exhausted,
        }
