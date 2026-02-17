"""
Meme Strategist

Hybrid rules + Haiku decision engine for meme coin trading.
Rules handle ~80% of decisions (clear entries, all exits/stops).
Haiku handles ~20% (ambiguous signals).
"""

import logging
from typing import Dict, List, Optional

from core.interfaces import IStrategist, ILLM
from core.models import MarketIntel, Portfolio, TradingPlan, TradeSignal, TradeAction, OrderType
from agents.memetrader.models import MemePosition
from agents.memetrader.config import MemeConfig

logger = logging.getLogger(__name__)

MEME_SYSTEM_PROMPT = """Meme coin trader. Fast momentum trades. ENTER=momentum+sentiment aligned, EXIT=momentum fading/bearish, HOLD=unclear.
Respond JSON only: {"action":"ENTER|EXIT|HOLD","confidence":0.0-1.0,"size_pct":0.0-0.05,"reasoning":"brief"}"""


class MemeStrategist(IStrategist):
    """
    Hybrid rules + Haiku strategist for meme coins.
    Manages trailing stops per position.
    """

    def __init__(self, llm: Optional[ILLM] = None, config: MemeConfig = None):
        self.llm = llm
        self.config = config or MemeConfig()
        self._positions: Dict[str, MemePosition] = {}
        self._stats = {"rule_decisions": 0, "haiku_decisions": 0, "errors": 0}

    def update_position(self, symbol: str, position: Optional[MemePosition]):
        """Track or remove a meme position."""
        if position is None:
            self._positions.pop(symbol, None)
        else:
            self._positions[symbol] = position

    def update_trailing_stops(self, current_prices: Dict[str, float]):
        """Update peak prices and activate trailing stops."""
        for symbol, pos in self._positions.items():
            price = current_prices.get(symbol)
            if price is None:
                continue

            pos.update_price(price)

            # Activate trailing stop at +20% gain
            if not pos.trailing_active:
                gain_pct = ((price - pos.entry_price) / pos.entry_price) if pos.entry_price > 0 else 0
                if gain_pct >= self.config.trailing_stop_activation_pct:
                    pos.trailing_active = True
                    pos.trailing_stop_price = price * (1.0 - self.config.trailing_stop_distance_pct)
                    logger.info(f"[MEME_STRAT] Trailing stop activated for {symbol} at ${pos.trailing_stop_price:.6f}")

            # Ratchet trailing stop up (never decrease)
            if pos.trailing_active:
                new_stop = price * (1.0 - self.config.trailing_stop_distance_pct)
                if new_stop > pos.trailing_stop_price:
                    pos.trailing_stop_price = new_stop

    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None,
    ) -> TradingPlan:
        """Create trading plan for a meme coin."""
        pair = intel.pair
        symbol = pair.split("/")[0]
        position = self._positions.get(symbol)

        # Extract key metrics from intel metadata
        cms = intel.fused_direction  # Combined Meme Score
        confidence = intel.fused_confidence
        vol_z = self._get_volume_z(intel)

        # --- RULE-BASED EXITS (always check first) ---

        # Trailing stop hit
        if position and position.trailing_active:
            position_price = getattr(position, '_current_price', None)
            if position_price and position_price <= position.trailing_stop_price:
                self._stats["rule_decisions"] += 1
                return self._make_plan(pair, TradeAction.SELL, 0.95, 1.0,
                    f"Trailing stop hit: price ${position_price:.6f} <= stop ${position.trailing_stop_price:.6f}")

        # Hard stop loss
        if position:
            pnl_pct = position.unrealized_pnl_pct
            if pnl_pct <= -self.config.hard_stop_loss_pct * 100:
                self._stats["rule_decisions"] += 1
                return self._make_plan(pair, TradeAction.SELL, 0.99, 1.0,
                    f"Hard stop: {pnl_pct:.1f}% loss")

        # Strong bearish exit
        if position and cms <= self.config.exit_cms_threshold and vol_z < -0.5:
            self._stats["rule_decisions"] += 1
            return self._make_plan(pair, TradeAction.SELL, 0.85, 1.0,
                f"Bearish exit: CMS={cms:+.2f}, vol_z={vol_z:+.1f}")

        # --- RULE-BASED ENTRY ---
        if not position and cms >= self.config.entry_cms_threshold and vol_z >= self.config.min_volume_z_score:
            self._stats["rule_decisions"] += 1
            size = min(self.config.max_per_coin_pct, cms * 0.08)
            return self._make_plan(pair, TradeAction.BUY, min(0.9, cms), size,
                f"Strong entry: CMS={cms:+.2f}, vol_z={vol_z:+.1f}")

        # --- AMBIGUOUS -> HAIKU ---
        if self.config.ambiguous_cms_lower <= cms < self.config.entry_cms_threshold:
            return await self._ask_haiku(pair, intel, portfolio, position, cms, vol_z)

        # --- HOLD ---
        self._stats["rule_decisions"] += 1
        return self._make_plan(pair, TradeAction.HOLD, 0.0, 0.0,
            f"Hold zone: CMS={cms:+.2f}")

    async def _ask_haiku(
        self, pair: str, intel: MarketIntel, portfolio: Portfolio,
        position: Optional[MemePosition], cms: float, vol_z: float
    ) -> TradingPlan:
        """Ask Haiku for ambiguous signals."""
        if not self.llm:
            self._stats["rule_decisions"] += 1
            return self._make_plan(pair, TradeAction.HOLD, 0.0, 0.0, "No LLM available")

        symbol = pair.split("/")[0]

        # Build compact prompt
        twitter_meta = {}
        volume_meta = {}
        for sig in intel.signals:
            if sig.source == "twitter_sentiment":
                twitter_meta = sig.metadata
            elif sig.source == "volume_momentum":
                volume_meta = sig.metadata

        pos_str = "NONE"
        if position:
            pos_str = f"LONG entry=${position.entry_price:.6f} pnl={position.unrealized_pnl_pct:.1f}%"

        prompt = (
            f"{symbol}/AUD | CMS={cms:+.2f}\n"
            f"Twitter: mentions={twitter_meta.get('mention_count', 0)}, "
            f"sentiment={twitter_meta.get('sentiment_score', 0):+.2f}, "
            f"velocity={twitter_meta.get('mention_velocity', 0):.1f}/min, "
            f"influencers={twitter_meta.get('influencer_mentions', 0)}\n"
            f"Volume: z={vol_z:+.1f}, "
            f"mom5m={volume_meta.get('price_momentum_5m', 0):+.1f}%, "
            f"B/S={volume_meta.get('buy_sell_ratio', 1.0):.2f}\n"
            f"Position: {pos_str}\n"
            f"Budget: ${portfolio.available_quote:.0f}"
        )

        try:
            response = await self.llm.complete_json(
                prompt=f"{MEME_SYSTEM_PROMPT}\n\n{prompt}",
                max_tokens=200,
            )
            self._stats["haiku_decisions"] += 1

            action_str = response.get("action", "HOLD").upper()
            if action_str == "ENTER":
                action = TradeAction.BUY
            elif action_str == "EXIT":
                action = TradeAction.SELL
            else:
                action = TradeAction.HOLD

            haiku_conf = float(response.get("confidence", 0.5))
            haiku_size = float(response.get("size_pct", 0.0))
            haiku_reasoning = response.get("reasoning", "Haiku decision")

            return self._make_plan(pair, action, haiku_conf, haiku_size,
                f"Haiku: {haiku_reasoning}")

        except Exception as e:
            logger.warning(f"[MEME_STRAT] Haiku error for {pair}: {e}")
            self._stats["errors"] += 1
            return self._make_plan(pair, TradeAction.HOLD, 0.0, 0.0,
                f"Haiku error: {e}")

    def _get_volume_z(self, intel: MarketIntel) -> float:
        """Extract volume Z-score from intel signals."""
        for sig in intel.signals:
            if sig.source == "volume_momentum":
                return sig.metadata.get("volume_z_score", 0.0)
        return 0.0

    def _make_plan(
        self, pair: str, action: TradeAction, confidence: float,
        size_pct: float, reasoning: str
    ) -> TradingPlan:
        """Create a TradingPlan with a single signal."""
        signal = TradeSignal(
            pair=pair,
            action=action,
            confidence=confidence,
            size_pct=size_pct,
            reasoning=reasoning,
            order_type=OrderType.MARKET,
            stop_loss_pct=self.config.hard_stop_loss_pct,
        )

        return TradingPlan(
            signals=[signal],
            strategy_name="meme_momentum",
            regime="volatile",
            overall_confidence=confidence,
            reasoning=reasoning,
        )

    def get_stats(self) -> Dict:
        return dict(self._stats)
