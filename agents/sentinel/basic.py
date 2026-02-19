"""
Sentinel Agent

Risk management and safety guardian.
Validates trading plans, enforces position limits, monitors stop-losses.
"""

from typing import Dict, List, Optional
import logging
from datetime import datetime, timezone

from core.interfaces import ISentinel, IMemory
from core.models import (
    TradingPlan, TradeSignal, Trade, Portfolio, Position,
    TradeAction, TradeStatus
)
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class BasicSentinel(ISentinel):
    """
    Stage 1 Sentinel - Basic risk management.

    Features:
    - Position size limits
    - Stop-loss enforcement (with per-pair support)
    - Total exposure limits
    - Confidence threshold
    """

    def __init__(self, memory: IMemory = None, settings: Settings = None):
        self.memory = memory
        self.settings = settings or get_settings()
        self._paused = False

        # Use effective risk (supports aggressive profile)
        effective_risk = self.settings.get_effective_risk()
        self.max_position_pct = effective_risk.max_position_pct
        self.max_exposure_pct = effective_risk.max_total_exposure_pct
        self.stop_loss_pct = effective_risk.stop_loss_pct
        self.min_confidence = effective_risk.min_confidence

        # Per-pair stop losses (from aggressive config if available)
        self._pair_stop_losses = {}
        if self.settings.aggressive_risk:
            self._pair_stop_losses = self.settings.aggressive_risk.pair_stop_losses.copy()

        logger.info(f"Sentinel initialized: max_pos={self.max_position_pct:.0%}, "
                   f"stop_loss={self.stop_loss_pct:.0%}, min_conf={self.min_confidence:.0%}")
        if self._pair_stop_losses:
            logger.info(f"[SENTINEL] Per-pair stop losses configured for {len(self._pair_stop_losses)} pairs")
    
    async def validate_plan(self, plan: TradingPlan, portfolio: Portfolio) -> TradingPlan:
        """
        Validate trading plan against risk rules.
        Approves or rejects each signal in the plan.
        """
        if self._paused:
            logger.warning("Sentinel is paused - rejecting all trades")
            for signal in plan.signals:
                signal.reject("Trading paused")
            return plan
        
        for signal in plan.signals:
            # Skip HOLD signals
            if signal.action == TradeAction.HOLD:
                signal.approve()
                continue
            
            # Check confidence threshold
            if signal.confidence < self.min_confidence:
                signal.reject(f"Confidence {signal.confidence:.0%} below threshold {self.min_confidence:.0%}")
                continue
            
            # Check position size
            if signal.action == TradeAction.BUY:
                max_size = portfolio.available_quote * self.max_position_pct
                requested_size = portfolio.available_quote * signal.size_pct
                
                if requested_size > max_size:
                    # Reduce to max allowed
                    signal.size_pct = self.max_position_pct
                    logger.warning(f"Reduced position size to {self.max_position_pct:.0%}")
                
                # Check total exposure after this trade
                new_exposure = (portfolio.positions_value + requested_size) / portfolio.total_value
                if new_exposure > self.max_exposure_pct:
                    signal.reject(f"Would exceed max exposure ({new_exposure:.0%} > {self.max_exposure_pct:.0%})")
                    continue
                
                # Check minimum trade size
                trade_value = portfolio.available_quote * signal.size_pct
                if trade_value < 10:  # Minimum trade size
                    signal.reject(f"Trade size too small (${trade_value:.2f})")
                    continue
            
            # Check we have position to sell
            if signal.action == TradeAction.SELL:
                base_asset = signal.pair.split("/")[0]
                position = portfolio.get_position(base_asset)
                
                if not position or position.amount <= 0:
                    signal.reject(f"No {base_asset} position to sell")
                    continue
            
            # All checks passed
            signal.approve()
            logger.info(f"Approved: {signal.action.value} {signal.pair} "
                       f"(size: {signal.size_pct:.0%}, conf: {signal.confidence:.0%})")
        
        return plan
    
    async def check_stop_losses(self, positions: Dict[str, Position]) -> List[Trade]:
        """
        Check all positions for stop-loss triggers.
        Returns list of trades to execute for triggered stops.

        Uses per-pair stop losses if configured (for high-volatility pairs),
        otherwise falls back to the default stop-loss percentage.
        """
        stop_trades = []

        for symbol, position in positions.items():
            if position.amount <= 0:
                continue

            if position.entry_price is None or position.current_price is None:
                continue

            # Get stop loss for this pair (per-pair or default)
            pair = f"{symbol}/{self.settings.trading.quote_currency}"
            stop_loss = self._get_stop_loss_for_pair(pair)

            # Calculate loss percentage
            loss_pct = (position.entry_price - position.current_price) / position.entry_price

            if loss_pct >= stop_loss:
                logger.warning(f"STOP-LOSS triggered for {symbol}: "
                             f"entry=${position.entry_price:,.2f}, "
                             f"current=${position.current_price:,.2f}, "
                             f"loss={loss_pct:.1%} (threshold: {stop_loss:.1%})")

                # Create sell trade
                trade = Trade(
                    pair=pair,
                    action=TradeAction.SELL,
                    requested_size_base=position.amount,
                    entry_price=position.entry_price,
                    reasoning=f"Stop-loss triggered at {loss_pct:.1%} loss (threshold: {stop_loss:.1%})"
                )
                stop_trades.append(trade)

        return stop_trades

    def _get_stop_loss_for_pair(self, pair: str) -> float:
        """
        Get the stop-loss percentage for a specific pair.

        Returns per-pair stop loss if configured (for volatile pairs),
        otherwise returns the default stop-loss percentage.
        """
        if pair in self._pair_stop_losses:
            return self._pair_stop_losses[pair]
        return self.stop_loss_pct

    def set_pair_stop_loss(self, pair: str, stop_loss_pct: float):
        """Set a custom stop-loss for a specific pair."""
        self._pair_stop_losses[pair] = stop_loss_pct
        logger.info(f"[SENTINEL] Set stop-loss for {pair}: {stop_loss_pct:.1%}")

    def get_pair_stop_losses(self) -> Dict[str, float]:
        """Get all per-pair stop losses."""
        return self._pair_stop_losses.copy()
    
    async def system_healthy(self) -> bool:
        """Check if system is healthy enough to trade"""
        if self._paused:
            return False
        return True
    
    async def emergency_stop(self) -> None:
        """Trigger emergency stop - pause all trading"""
        logger.critical("🚨 EMERGENCY STOP TRIGGERED")
        self._paused = True
    
    def pause(self) -> None:
        """Pause trading"""
        logger.warning("Trading paused")
        self._paused = True
    
    def resume(self) -> None:
        """Resume trading"""
        logger.info("Trading resumed")
        self._paused = False
    
    @property
    def is_paused(self) -> bool:
        return self._paused


class EnhancedSentinel(BasicSentinel):
    """
    Stage 2 Sentinel - Enhanced risk management.
    
    Additional features:
    - Circuit breakers (pause on extreme volatility)
    - Daily loss limits
    - Trade frequency limits
    """
    
    def __init__(self, memory: IMemory = None, settings: Settings = None):
        super().__init__(memory, settings)
        
        # Circuit breaker state
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._last_reset = datetime.now(timezone.utc).date()
        
        # Limits
        self.max_daily_loss_pct = self.settings.risk.max_daily_loss_pct
        self.max_daily_trades = self.settings.risk.max_daily_trades
    
    async def validate_plan(self, plan: TradingPlan, portfolio: Portfolio) -> TradingPlan:
        """Enhanced validation with circuit breakers"""
        # Reset daily counters if new day
        today = datetime.now(timezone.utc).date()
        if today != self._last_reset:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._last_reset = today
        
        # Check daily loss circuit breaker
        if self._daily_pnl < -self.max_daily_loss_pct:
            logger.warning(f"Daily loss circuit breaker active: {self._daily_pnl:.1%}")
            for signal in plan.signals:
                signal.reject("Daily loss limit reached")
            return plan
        
        # Check daily trade limit
        if self._daily_trades >= self.max_daily_trades:
            logger.warning(f"Daily trade limit reached: {self._daily_trades}")
            for signal in plan.signals:
                if signal.action != TradeAction.HOLD:
                    signal.reject("Daily trade limit reached")
            return plan
        
        # Run basic validation
        return await super().validate_plan(plan, portfolio)
    
    def record_trade_result(self, pnl_pct: float) -> None:
        """Record trade result for circuit breaker tracking"""
        self._daily_pnl += pnl_pct
        self._daily_trades += 1
        
        logger.info(f"Daily stats: trades={self._daily_trades}, pnl={self._daily_pnl:+.1%}")
