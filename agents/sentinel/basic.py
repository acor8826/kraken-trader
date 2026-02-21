"""
Sentinel Agent

Risk management and safety guardian.
Validates trading plans, enforces position limits, monitors stop-losses.
Enhanced with volatility-aware stop-loss calculation.
"""

from typing import Dict, List, Optional
import logging
from datetime import datetime, timezone

from core.interfaces import ISentinel, IMemory, IExchange
from core.models import (
    TradingPlan, TradeSignal, Trade, Portfolio, Position,
    TradeAction, TradeStatus
)
from core.config import Settings, get_settings
from core.risk import VolatilityCalculator, VolatilityConfig

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

    def __init__(self, memory: IMemory = None, settings: Settings = None, exchange: IExchange = None):
        self.memory = memory
        self.settings = settings or get_settings()
        self.exchange = exchange
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

        # Initialize volatility-based risk management
        volatility_config = self._load_volatility_config()
        self.volatility_calculator = VolatilityCalculator(volatility_config)
        self.volatility_enabled = self.settings.config.get("volatility_risk", {}).get("enabled", True)

        logger.info(f"Sentinel initialized: max_pos={self.max_position_pct:.0%}, "
                   f"stop_loss={self.stop_loss_pct:.0%}, min_conf={self.min_confidence:.0%}")
        if self._pair_stop_losses:
            logger.info(f"[SENTINEL] Per-pair stop losses configured for {len(self._pair_stop_losses)} pairs")
        if self.volatility_enabled and self.exchange:
            logger.info("[SENTINEL] Volatility-aware risk management enabled")
        else:
            logger.info("[SENTINEL] Using fixed stop-loss percentages (volatility-aware disabled or no exchange)")

    def _load_volatility_config(self) -> VolatilityConfig:
        """Load volatility configuration from settings"""
        vol_config = self.settings.config.get("volatility_risk", {})
        
        return VolatilityConfig(
            atr_period=vol_config.get("atr_period", 14),
            volatility_lookback=vol_config.get("volatility_lookback", 20),
            base_stop_multiplier=vol_config.get("base_stop_multiplier", 2.0),
            base_tp_multiplier=vol_config.get("base_tp_multiplier", 3.0),
            low_volatility_threshold=vol_config.get("low_volatility_threshold", 0.02),
            high_volatility_threshold=vol_config.get("high_volatility_threshold", 0.06),
            low_vol_stop_multiplier=vol_config.get("low_vol_stop_multiplier", 1.5),
            medium_vol_stop_multiplier=vol_config.get("medium_vol_stop_multiplier", 2.0),
            high_vol_stop_multiplier=vol_config.get("high_vol_stop_multiplier", 2.5),
            low_vol_tp_multiplier=vol_config.get("low_vol_tp_multiplier", 2.0),
            medium_vol_tp_multiplier=vol_config.get("medium_vol_tp_multiplier", 3.0),
            high_vol_tp_multiplier=vol_config.get("high_vol_tp_multiplier", 4.0),
            fallback_stop_loss_pct=vol_config.get("fallback_stop_loss_pct", 0.05),
            fallback_take_profit_pct=vol_config.get("fallback_take_profit_pct", 0.10),
            min_candles_required=vol_config.get("min_candles_required", 14)
        )
    
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

        Uses volatility-aware stop losses when enabled and exchange is available,
        otherwise falls back to per-pair or default stop-loss percentages.
        """
        stop_trades = []

        for symbol, position in positions.items():
            if position.amount <= 0:
                continue

            if position.entry_price is None or position.current_price is None:
                continue

            # Determine the appropriate pair format
            pair = f"{symbol}/USDT"  # Most common quote currency
            if hasattr(self.settings, 'trading') and hasattr(self.settings.trading, 'quote_currency'):
                quote = self.settings.trading.quote_currency
                pair = f"{symbol}/{quote}"

            # Get stop loss for this position
            stop_loss_pct = await self._get_dynamic_stop_loss(pair, position)

            # Calculate loss percentage
            loss_pct = (position.entry_price - position.current_price) / position.entry_price

            if loss_pct >= stop_loss_pct:
                logger.warning(f"STOP-LOSS triggered for {symbol}: "
                             f"entry=${position.entry_price:,.2f}, "
                             f"current=${position.current_price:,.2f}, "
                             f"loss={loss_pct:.1%} (threshold: {stop_loss_pct:.1%})")

                # Create sell trade
                trade = Trade(
                    pair=pair,
                    action=TradeAction.SELL,
                    requested_size_base=position.amount,
                    entry_price=position.entry_price,
                    reasoning=f"Stop-loss triggered at {loss_pct:.1%} loss (threshold: {stop_loss_pct:.1%})"
                )
                stop_trades.append(trade)

        return stop_trades

    async def _get_dynamic_stop_loss(self, pair: str, position: Position) -> float:
        """
        Get dynamic stop-loss percentage for a position.
        
        Uses volatility-based calculation if enabled and possible,
        otherwise falls back to configured or default values.
        """
        # Try volatility-based calculation first
        if self.volatility_enabled and self.exchange:
            try:
                # Calculate volatility-aware stop loss based on entry price
                levels = await self.volatility_calculator.calculate_position_levels(
                    pair=pair,
                    entry_price=position.entry_price,
                    exchange=self.exchange
                )
                
                stop_loss_pct = levels['stop_loss_pct']
                
                logger.debug(
                    f"[SENTINEL] Volatility stop-loss for {pair}: {stop_loss_pct:.2%} "
                    f"(ATR: {levels['atr_pct']:.2%}, Rank: {levels['volatility_rank']}, "
                    f"Confidence: {levels['confidence']:.1%})"
                )
                
                return stop_loss_pct
                
            except Exception as e:
                logger.warning(f"[SENTINEL] Failed to calculate volatility stop-loss for {pair}: {e}")
        
        # Fallback to configured per-pair stop loss
        if pair in self._pair_stop_losses:
            return self._pair_stop_losses[pair]
        
        # Final fallback to default stop loss
        return self.stop_loss_pct

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

    async def get_position_risk_levels(self, positions: Dict[str, Position]) -> Dict[str, Dict]:
        """
        Get calculated stop-loss and take-profit levels for all positions.
        
        Returns dictionary with position symbol as key and risk levels as values.
        Used by the portfolio API to show current SL/TP prices.
        """
        risk_levels = {}
        
        for symbol, position in positions.items():
            if position.amount <= 0 or not position.entry_price:
                continue
            
            # Determine pair format
            pair = f"{symbol}/USDT"
            if hasattr(self.settings, 'trading') and hasattr(self.settings.trading, 'quote_currency'):
                quote = self.settings.trading.quote_currency
                pair = f"{symbol}/{quote}"
            
            try:
                # Get dynamic stop-loss
                stop_loss_pct = await self._get_dynamic_stop_loss(pair, position)
                
                # Get volatility-based take-profit if available
                take_profit_pct = await self._get_dynamic_take_profit(pair, position)
                
                # Calculate actual prices
                stop_loss_price = position.entry_price * (1 - stop_loss_pct)
                take_profit_price = position.entry_price * (1 + take_profit_pct)
                
                risk_levels[symbol] = {
                    'stop_loss_pct': stop_loss_pct,
                    'take_profit_pct': take_profit_pct,
                    'stop_loss_price': stop_loss_price,
                    'take_profit_price': take_profit_price,
                    'entry_price': position.entry_price,
                    'current_price': position.current_price,
                    'unrealized_pnl_pct': ((position.current_price - position.entry_price) / position.entry_price) if position.current_price else 0.0
                }
                
                # Add volatility info if available
                if self.volatility_enabled and self.exchange:
                    try:
                        profile = await self.volatility_calculator.get_volatility_profile(pair, self.exchange)
                        risk_levels[symbol].update({
                            'volatility_rank': profile.volatility_rank,
                            'atr_pct': profile.atr_pct,
                            'volatility_confidence': profile.confidence
                        })
                    except Exception:
                        pass
                        
            except Exception as e:
                logger.warning(f"[SENTINEL] Failed to calculate risk levels for {symbol}: {e}")
                # Basic fallback
                risk_levels[symbol] = {
                    'stop_loss_pct': self.stop_loss_pct,
                    'take_profit_pct': self.stop_loss_pct * 2,  # 2:1 ratio
                    'stop_loss_price': position.entry_price * (1 - self.stop_loss_pct) if position.entry_price else 0,
                    'take_profit_price': position.entry_price * (1 + self.stop_loss_pct * 2) if position.entry_price else 0,
                    'entry_price': position.entry_price,
                    'current_price': position.current_price,
                    'unrealized_pnl_pct': ((position.current_price - position.entry_price) / position.entry_price) if position.current_price and position.entry_price else 0.0
                }
        
        return risk_levels

    async def _get_dynamic_take_profit(self, pair: str, position: Position) -> float:
        """
        Get dynamic take-profit percentage for a position.
        
        Uses volatility-based calculation if enabled and possible,
        otherwise falls back to a simple multiple of stop-loss.
        """
        # Try volatility-based calculation first
        if self.volatility_enabled and self.exchange:
            try:
                levels = await self.volatility_calculator.calculate_position_levels(
                    pair=pair,
                    entry_price=position.entry_price,
                    exchange=self.exchange
                )
                
                return levels['take_profit_pct']
                
            except Exception as e:
                logger.debug(f"[SENTINEL] Failed to calculate volatility take-profit for {pair}: {e}")
        
        # Fallback: 2x the stop-loss percentage (2:1 risk-reward ratio)
        stop_loss_pct = await self._get_dynamic_stop_loss(pair, position)
        return stop_loss_pct * 2.0
    
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
    
    def __init__(self, memory: IMemory = None, settings: Settings = None, exchange: IExchange = None):
        super().__init__(memory, settings, exchange)
        
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
