"""
Cost-Optimized Strategist

Combines all cost optimization strategies into a single strategist stack:
1. Decision Caching - Reuse decisions if market stable
2. Hybrid Mode - Rules for clear signals, Claude for uncertain
3. Batch Analysis - Multiple pairs in one Claude call

Expected cost reduction: 80-90%
- From ~$12/month to ~$1-2/month for small portfolios
"""

from typing import Dict, List, Optional
import logging
import hashlib
import time

from core.interfaces import IStrategist, ILLM
from core.models import MarketIntel, Portfolio, TradingPlan, TradeSignal, TradeAction
from core.config import Settings, get_settings, CostOptimizationConfig

from .simple import SimpleStrategist, RuleBasedStrategist
from .batch import BatchStrategist, RuleBasedBatchStrategist
from .hybrid import HybridStrategist

logger = logging.getLogger(__name__)


class InMemoryDecisionCache:
    """
    Simple in-memory decision cache with TTL.
    Drop-in replacement for RedisCache decision methods when Redis is unavailable.
    """

    def __init__(self, max_entries: int = 100):
        self._cache: Dict[str, dict] = {}  # key -> {decision, price, expires_at}
        self._max_entries = max_entries

    async def cache_decision(
        self,
        pair: str,
        intel_hash: str,
        decision: Dict,
        price_at_decision: float,
        ttl: int = 1800
    ) -> bool:
        key = f"decision:{pair}:{intel_hash}"
        self._cache[key] = {
            "decision": decision,
            "price": price_at_decision,
            "expires_at": time.time() + ttl
        }
        # Evict oldest if over limit
        if len(self._cache) > self._max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k]["expires_at"])
            del self._cache[oldest_key]
        return True

    async def get_cached_decision(
        self,
        pair: str,
        intel_hash: str,
        current_price: float,
        max_price_deviation: float = 0.02
    ) -> Optional[Dict]:
        key = f"decision:{pair}:{intel_hash}"
        entry = self._cache.get(key)
        if not entry:
            return None
        # Check expiry
        if time.time() > entry["expires_at"]:
            del self._cache[key]
            return None
        # Check price deviation
        cached_price = entry["price"]
        if cached_price > 0 and current_price > 0:
            deviation = abs(current_price - cached_price) / cached_price
            if deviation > max_price_deviation:
                return None
        return entry["decision"]

    def clear(self):
        self._cache.clear()


class CostOptimizedStrategist(IStrategist):
    """
    Top-level cost-optimized strategist that combines:

    1. **Decision Caching** (if Redis available)
       - Caches decisions with price at decision time
       - Reuses if price hasn't moved > threshold
       - Saves ~20-50% during stable markets

    2. **Hybrid Mode** (rules vs Claude)
       - Uses rules for clear signals (free)
       - Uses Claude for uncertain signals (paid)
       - Saves ~30-70% depending on market

    3. **Batch Analysis**
       - Combines multiple pairs into one Claude call
       - Reduces 3 calls to 1 per cycle
       - Saves ~66%

    Stack: Cache -> Hybrid -> Batch -> Claude
    """

    def __init__(
        self,
        llm: Optional[ILLM] = None,
        cache=None,  # RedisCache instance
        settings: Optional[Settings] = None
    ):
        """
        Initialize cost-optimized strategist.

        Args:
            llm: LLM instance for Claude calls (None = rules only)
            cache: Optional RedisCache for decision caching
            settings: Settings object
        """
        self.settings = settings or get_settings()
        self.config = self.settings.cost_optimization
        self.llm = llm
        # Use provided cache, or fall back to in-memory cache if caching is enabled
        if cache:
            self.cache = cache
        elif self.config.enable_decision_cache:
            self.cache = InMemoryDecisionCache()
            logger.info("[COST_OPT] Using in-memory decision cache (no Redis)")
        else:
            self.cache = None

        # Statistics
        self._total_calls = 0
        self._cache_hits = 0
        self._rule_decisions = 0
        self._claude_decisions = 0
        self._batch_calls = 0

        # Build strategist stack
        self._build_stack()

        logger.info(
            f"[COST_OPT] Initialized with: "
            f"batch={self.config.enable_batch_analysis}, "
            f"hybrid={self.config.enable_hybrid_mode}, "
            f"cache={self.config.enable_decision_cache and cache is not None}"
        )

    def _build_stack(self):
        """Build the strategist stack based on configuration."""
        # Base strategists
        self.rule_strategist = RuleBasedStrategist(self.settings)
        self.rule_batch_strategist = RuleBasedBatchStrategist(self.settings)

        if self.llm:
            # LLM-based strategists
            self.llm_strategist = SimpleStrategist(self.llm, self.settings)
            self.batch_strategist = BatchStrategist(self.llm, self.settings)

            # Hybrid wrapper (if enabled)
            if self.config.enable_hybrid_mode:
                self.hybrid_strategist = HybridStrategist(
                    llm_strategist=self.batch_strategist if self.config.enable_batch_analysis else self.llm_strategist,
                    rule_strategist=self.rule_strategist,
                    thresholds=self.config.hybrid,
                    settings=self.settings
                )
            else:
                self.hybrid_strategist = None
        else:
            # No LLM - use rules only
            self.llm_strategist = None
            self.batch_strategist = None
            self.hybrid_strategist = None
            logger.info("[COST_OPT] No LLM provided, using rules only (zero API cost)")

    async def create_plan(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Create trading plan with cost optimization for single pair.

        Flow:
        1. Check decision cache (if enabled)
        2. If cache miss, use hybrid/batch/rules
        3. Cache the decision (if enabled)
        """
        self._total_calls += 1
        return await self._process_single(intel, portfolio, risk_params)

    async def create_batch_plan(
        self,
        intel_list: List[MarketIntel],
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """
        Create trading plan for multiple pairs with maximum cost optimization.

        This is the most efficient entry point - batches all pairs together.
        """
        if not intel_list:
            return TradingPlan(
                signals=[],
                strategy_name="cost_optimized",
                overall_confidence=0.0,
                reasoning="No pairs to analyze"
            )

        self._total_calls += 1
        return await self._process_batch(intel_list, portfolio, risk_params)

    async def _process_single(
        self,
        intel: MarketIntel,
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """Process a single pair with caching and hybrid logic."""

        # Step 1: Check cache
        if self.config.enable_decision_cache and self.cache:
            cached = await self._get_cached_decision(intel)
            if cached:
                self._cache_hits += 1
                return cached

        # Step 2: Make decision
        if not self.llm:
            # No LLM - use rules
            self._rule_decisions += 1
            plan = await self.rule_strategist.create_plan(intel, portfolio, risk_params)
        elif self.hybrid_strategist:
            # Use hybrid (decides rules vs Claude)
            plan = await self.hybrid_strategist.create_plan(intel, portfolio, risk_params)
            # Track stats from hybrid
            if "[RULE-BASED]" in plan.reasoning:
                self._rule_decisions += 1
            else:
                self._claude_decisions += 1
        else:
            # Use LLM directly
            self._claude_decisions += 1
            plan = await self.llm_strategist.create_plan(intel, portfolio, risk_params)

        # Step 3: Cache decision
        if self.config.enable_decision_cache and self.cache:
            await self._cache_decision(intel, plan)

        return plan

    async def _process_batch(
        self,
        intel_list: List[MarketIntel],
        portfolio: Portfolio,
        risk_params: Dict = None
    ) -> TradingPlan:
        """Process multiple pairs with batching and hybrid logic."""

        # Separate cached and uncached
        cached_signals = []
        uncached_intel = []

        if self.config.enable_decision_cache and self.cache:
            for intel in intel_list:
                cached = await self._get_cached_decision(intel)
                if cached:
                    self._cache_hits += 1
                    cached_signals.extend(cached.signals)
                else:
                    uncached_intel.append(intel)
        else:
            uncached_intel = intel_list

        # Process uncached
        new_signals = []
        if uncached_intel:
            if not self.llm:
                # Rules only
                self._rule_decisions += len(uncached_intel)
                plan = await self.rule_batch_strategist.create_batch_plan(
                    uncached_intel, portfolio, risk_params
                )
                new_signals = plan.signals
            elif self.config.enable_hybrid_mode and self.hybrid_strategist:
                # Hybrid batch
                plan = await self.hybrid_strategist.create_batch_plan(
                    uncached_intel, portfolio, risk_params
                )
                new_signals = plan.signals
                # Stats tracked by hybrid
            elif self.config.enable_batch_analysis and self.batch_strategist:
                # Batch LLM call
                self._batch_calls += 1
                self._claude_decisions += 1  # One call for all
                plan = await self.batch_strategist.create_batch_plan(
                    uncached_intel, portfolio, risk_params
                )
                new_signals = plan.signals
            else:
                # Individual LLM calls (fallback)
                for intel in uncached_intel:
                    self._claude_decisions += 1
                    p = await self.llm_strategist.create_plan(intel, portfolio, risk_params)
                    new_signals.extend(p.signals)

            # Cache new decisions
            if self.config.enable_decision_cache and self.cache:
                for i, intel in enumerate(uncached_intel):
                    if i < len(new_signals):
                        signal_plan = TradingPlan(
                            signals=[new_signals[i]],
                            strategy_name="cached"
                        )
                        await self._cache_decision(intel, signal_plan)

        # Combine all signals
        all_signals = cached_signals + new_signals

        # Calculate overall confidence
        active = [s for s in all_signals if s.action != TradeAction.HOLD]
        overall_conf = sum(s.confidence for s in active) / len(active) if active else 0.0

        return TradingPlan(
            signals=all_signals,
            strategy_name="cost_optimized_batch",
            regime="mixed",
            overall_confidence=overall_conf,
            reasoning=f"Processed {len(intel_list)} pairs (cache: {len(cached_signals)}, new: {len(new_signals)})"
        )

    async def _get_cached_decision(self, intel: MarketIntel) -> Optional[TradingPlan]:
        """Check cache for existing decision."""
        if not self.cache:
            return None

        intel_hash = self._hash_intel(intel)
        current_price = self._get_price_from_intel(intel)

        cached = await self.cache.get_cached_decision(
            pair=intel.pair,
            intel_hash=intel_hash,
            current_price=current_price,
            max_price_deviation=self.config.cache_price_deviation
        )

        if cached:
            # Convert cached dict back to TradingPlan
            try:
                signal = TradeSignal(
                    pair=intel.pair,
                    action=TradeAction[cached.get("action", "HOLD")],
                    confidence=cached.get("confidence", 0),
                    size_pct=cached.get("size_pct", 0),
                    reasoning=f"[CACHED] {cached.get('reasoning', '')}"
                )
                return TradingPlan(
                    signals=[signal],
                    strategy_name="cached",
                    overall_confidence=signal.confidence,
                    reasoning="Decision from cache"
                )
            except Exception as e:
                logger.warning(f"[COST_OPT] Failed to restore cached decision: {e}")
                return None

        return None

    async def _cache_decision(self, intel: MarketIntel, plan: TradingPlan):
        """Cache a decision for future reuse."""
        if not self.cache or not plan.signals:
            return

        intel_hash = self._hash_intel(intel)
        current_price = self._get_price_from_intel(intel)
        signal = plan.signals[0]

        decision = {
            "action": signal.action.value,
            "confidence": signal.confidence,
            "size_pct": signal.size_pct,
            "reasoning": signal.reasoning
        }

        await self.cache.cache_decision(
            pair=intel.pair,
            intel_hash=intel_hash,
            decision=decision,
            price_at_decision=current_price,
            ttl=self.config.cache_ttl_seconds
        )

    def _hash_intel(self, intel: MarketIntel) -> str:
        """Create hash of market intel for cache key."""
        # Hash key factors that would change the decision
        key_data = f"{intel.fused_direction:.2f}:{intel.fused_confidence:.2f}:{intel.regime.value}"
        return hashlib.md5(key_data.encode()).hexdigest()[:12]

    def _get_price_from_intel(self, intel: MarketIntel) -> float:
        """Extract current price from intel."""
        # Try to get price from signal metadata
        if intel.signals:
            for signal in intel.signals:
                if hasattr(signal, 'metadata') and signal.metadata:
                    price = signal.metadata.get('price', 0)
                    if price > 0:
                        return price
        return 0.0

    def get_stats(self) -> dict:
        """Get cost optimization statistics."""
        total_saved = self._cache_hits + self._rule_decisions
        cost_per_call = 0.002  # Estimated

        stats = {
            "total_calls": self._total_calls,
            "cache_hits": self._cache_hits,
            "rule_decisions": self._rule_decisions,
            "claude_decisions": self._claude_decisions,
            "batch_calls": self._batch_calls,
            "savings_pct": f"{total_saved / self._total_calls * 100:.1f}%" if self._total_calls > 0 else "0%",
            "estimated_savings": f"${total_saved * cost_per_call:.2f}",
            "config": {
                "batch_enabled": self.config.enable_batch_analysis,
                "hybrid_enabled": self.config.enable_hybrid_mode,
                "cache_enabled": self.config.enable_decision_cache
            }
        }

        # Add hybrid stats if available
        if self.hybrid_strategist:
            stats["hybrid"] = self.hybrid_strategist.get_stats()

        return stats

    def reset_stats(self):
        """Reset statistics."""
        self._total_calls = 0
        self._cache_hits = 0
        self._rule_decisions = 0
        self._claude_decisions = 0
        self._batch_calls = 0
        if self.hybrid_strategist:
            self.hybrid_strategist.reset_stats()


def create_cost_optimized_strategist(
    llm: Optional[ILLM] = None,
    cache=None,
    settings: Optional[Settings] = None
) -> IStrategist:
    """
    Factory function to create appropriate strategist based on settings.

    Returns:
        CostOptimizedStrategist if cost optimization is enabled,
        otherwise returns standard strategist.
    """
    settings = settings or get_settings()
    config = settings.cost_optimization

    # Check if any optimization is enabled
    any_optimization = (
        config.enable_batch_analysis or
        config.enable_hybrid_mode or
        config.enable_decision_cache
    )

    if any_optimization:
        return CostOptimizedStrategist(llm=llm, cache=cache, settings=settings)
    elif llm:
        return SimpleStrategist(llm, settings)
    else:
        return RuleBasedStrategist(settings)
