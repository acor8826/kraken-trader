"""
Enhanced Multi-Timeframe Analysis with Complete Trade Planning

Calculates:
- Entry points (with specific triggers)
- Exit points (stop-loss and take-profit)
- Estimated hold times based on timeframe
- Risk/reward ratios
- Position sizing recommendations
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
from enum import Enum

from core.interfaces import IExchange
from core.models import MarketData
from .multi_timeframe import (
    MultiTimeframeAnalyzer, MarketRegime, TimeframeAnalysis, 
    MultiTimeframeSignal
)

logger = logging.getLogger(__name__)


@dataclass
class TradePlan:
    """Complete trade plan with all parameters"""
    pair: str
    direction: str  # BUY or SELL
    
    # Entry conditions
    entry_trigger: str  # Description of entry condition
    entry_price: float  # Recommended entry price
    entry_range: Tuple[float, float]  # Min/max acceptable entry range
    
    # Exit points
    stop_loss_price: float
    take_profit_price: float
    
    # Risk metrics
    risk_amount: float  # Dollar risk per trade
    reward_amount: float  # Expected profit
    risk_reward_ratio: float
    
    # Position sizing
    position_size: float  # In base currency
    position_value: float  # In quote currency
    
    # Time parameters
    recommended_timeframe: str
    estimated_hold_time: timedelta
    max_hold_time: timedelta
    entry_expiry: datetime  # When entry signal expires
    
    # Confidence and regime
    confidence: float
    market_regime: MarketRegime
    volatility: float
    
    # Additional metadata
    created_at: datetime
    notes: List[str]


class EnhancedMultiTimeframeAnalyzer(MultiTimeframeAnalyzer):
    """
    Enhanced analyzer that creates complete trade plans with entry/exit points,
    hold times, and position sizing.
    """
    
    # Hold time estimates by timeframe
    HOLD_TIME_MAP = {
        "5m": {"min": timedelta(minutes=5), "typical": timedelta(minutes=20), "max": timedelta(hours=1)},
        "15m": {"min": timedelta(minutes=15), "typical": timedelta(hours=1), "max": timedelta(hours=4)},
        "1h": {"min": timedelta(hours=1), "typical": timedelta(hours=6), "max": timedelta(days=1)},
        "4h": {"min": timedelta(hours=4), "typical": timedelta(days=1), "max": timedelta(days=3)},
        "1d": {"min": timedelta(days=1), "typical": timedelta(days=5), "max": timedelta(weeks=2)},
    }
    
    async def create_trade_plan(
        self,
        pair: str,
        exchange: IExchange,
        capital: float = 1000.0,
        risk_per_trade_pct: float = 0.02,  # Risk 2% per trade
        force_refresh: bool = False
    ) -> Optional[TradePlan]:
        """
        Create a complete trade plan with entry/exit points and timing.
        
        Args:
            pair: Trading pair
            exchange: Exchange interface
            capital: Available capital
            risk_per_trade_pct: Percentage of capital to risk per trade
            force_refresh: Force new analysis
            
        Returns:
            TradePlan if a trade opportunity exists, None otherwise
        """
        # Get base multi-timeframe signal
        signal = await self.analyze(pair, exchange, force_refresh)
        
        if signal.signal == "HOLD" or signal.confidence < 0.6:
            logger.info(f"[TRADE PLAN] No trade for {pair}: Signal={signal.signal}, Confidence={signal.confidence:.2f}")
            return None
        
        # Get current market data
        ticker = await exchange.get_ticker(pair)
        current_price = ticker["price"]
        
        # Calculate entry points based on market regime
        entry_plan = self._calculate_entry_points(
            signal, current_price, ticker
        )
        
        # Calculate position size based on risk
        position_plan = self._calculate_position_size(
            capital=capital,
            risk_pct=risk_per_trade_pct,
            entry_price=entry_plan["entry_price"],
            stop_loss_price=entry_plan["stop_loss_price"]
        )
        
        # Estimate hold times
        hold_times = self._estimate_hold_times(signal.recommended_timeframe)
        
        # Create notes based on analysis
        notes = self._generate_trade_notes(signal, entry_plan)
        
        return TradePlan(
            pair=pair,
            direction=signal.signal,
            
            # Entry
            entry_trigger=entry_plan["trigger"],
            entry_price=entry_plan["entry_price"],
            entry_range=entry_plan["entry_range"],
            
            # Exit
            stop_loss_price=entry_plan["stop_loss_price"],
            take_profit_price=entry_plan["take_profit_price"],
            
            # Risk metrics
            risk_amount=position_plan["risk_amount"],
            reward_amount=position_plan["reward_amount"],
            risk_reward_ratio=position_plan["risk_reward_ratio"],
            
            # Position sizing
            position_size=position_plan["position_size"],
            position_value=position_plan["position_value"],
            
            # Time parameters
            recommended_timeframe=signal.recommended_timeframe,
            estimated_hold_time=hold_times["typical"],
            max_hold_time=hold_times["max"],
            entry_expiry=datetime.now() + hold_times["entry_valid"],
            
            # Metadata
            confidence=signal.confidence,
            market_regime=signal.primary_regime,
            volatility=self._get_avg_volatility(signal),
            created_at=datetime.now(),
            notes=notes
        )
    
    def _calculate_entry_points(
        self,
        signal: MultiTimeframeSignal,
        current_price: float,
        ticker: Dict
    ) -> Dict[str, Any]:
        """Calculate specific entry and exit prices based on market conditions"""
        
        # Base stop-loss and take-profit from signal
        stop_loss_pct = signal.stop_loss_pct
        take_profit_pct = signal.take_profit_pct
        
        if signal.signal == "BUY":
            if signal.primary_regime == MarketRegime.TRENDING_UP:
                # In uptrend: buy on pullbacks
                entry_price = current_price * 0.99  # Enter 1% below current
                entry_range = (current_price * 0.98, current_price * 1.01)
                trigger = f"Buy on pullback to ${entry_price:,.2f} or break above ${current_price * 1.01:,.2f}"
                
            elif signal.primary_regime == MarketRegime.RANGING:
                # In range: buy at support
                entry_price = ticker.get('low_24h', current_price * 0.98)
                entry_range = (entry_price * 0.99, entry_price * 1.02)
                trigger = f"Buy near support at ${entry_price:,.2f}"
                
            elif signal.primary_regime == MarketRegime.BREAKOUT:
                # Breakout: buy the breakout
                entry_price = current_price * 1.01  # Enter 1% above
                entry_range = (current_price, current_price * 1.02)
                trigger = f"Buy breakout above ${current_price:,.2f}"
                
            else:  # VOLATILE or other
                # Wait for stability
                entry_price = current_price
                entry_range = (current_price * 0.99, current_price * 1.01)
                trigger = f"Buy at market ~${current_price:,.2f}"
            
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            take_profit_price = entry_price * (1 + take_profit_pct)
            
        else:  # SELL
            if signal.primary_regime == MarketRegime.TRENDING_DOWN:
                # In downtrend: sell on rallies
                entry_price = current_price * 1.01  # Enter 1% above current
                entry_range = (current_price * 0.99, current_price * 1.02)
                trigger = f"Sell on rally to ${entry_price:,.2f}"
                
            else:
                # Default sell
                entry_price = current_price
                entry_range = (current_price * 0.99, current_price * 1.01)
                trigger = f"Sell at market ~${current_price:,.2f}"
            
            stop_loss_price = entry_price * (1 + stop_loss_pct)  # Stop above for sells
            take_profit_price = entry_price * (1 - take_profit_pct)  # Target below
        
        return {
            "entry_price": entry_price,
            "entry_range": entry_range,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "trigger": trigger
        }
    
    def _calculate_position_size(
        self,
        capital: float,
        risk_pct: float,
        entry_price: float,
        stop_loss_price: float
    ) -> Dict[str, float]:
        """Calculate position size based on risk management"""
        
        # Calculate risk per share
        risk_per_unit = abs(entry_price - stop_loss_price)
        
        # Calculate risk amount
        risk_amount = capital * risk_pct
        
        # Calculate position size
        position_size = risk_amount / risk_per_unit
        position_value = position_size * entry_price
        
        # Ensure position doesn't exceed capital
        if position_value > capital * 0.95:  # Max 95% of capital
            position_value = capital * 0.95
            position_size = position_value / entry_price
            risk_amount = position_size * risk_per_unit
        
        # Calculate reward
        reward_per_unit = abs(entry_price - stop_loss_price) * 2  # Assuming 2:1 default
        reward_amount = position_size * reward_per_unit
        
        # Risk/reward ratio
        risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 0
        
        return {
            "position_size": position_size,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "reward_amount": reward_amount,
            "risk_reward_ratio": risk_reward_ratio
        }
    
    def _estimate_hold_times(self, timeframe: str) -> Dict[str, Any]:
        """Estimate hold times based on timeframe"""
        
        hold_config = self.HOLD_TIME_MAP.get(timeframe, self.HOLD_TIME_MAP["1h"])
        
        # Entry signal valid for about 2-3 candles
        candle_minutes = {
            "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440
        }.get(timeframe, 60)
        
        entry_valid = timedelta(minutes=candle_minutes * 2.5)
        
        return {
            "min": hold_config["min"],
            "typical": hold_config["typical"],
            "max": hold_config["max"],
            "entry_valid": entry_valid
        }
    
    def _get_avg_volatility(self, signal: MultiTimeframeSignal) -> float:
        """Get average volatility from analyses"""
        if not signal.analyses:
            return 0.5
        
        volatilities = [a.volatility for a in signal.analyses.values()]
        return sum(volatilities) / len(volatilities)
    
    def _generate_trade_notes(
        self,
        signal: MultiTimeframeSignal,
        entry_plan: Dict
    ) -> List[str]:
        """Generate helpful notes about the trade"""
        
        notes = []
        
        # Regime-specific notes
        if signal.primary_regime == MarketRegime.TRENDING_UP:
            notes.append("Strong uptrend detected - buy pullbacks, ride the trend")
        elif signal.primary_regime == MarketRegime.TRENDING_DOWN:
            notes.append("Downtrend active - consider reduced position size")
        elif signal.primary_regime == MarketRegime.VOLATILE:
            notes.append("High volatility - wider stops recommended, watch for false breakouts")
        elif signal.primary_regime == MarketRegime.RANGING:
            notes.append("Range-bound market - buy support, sell resistance")
        
        # Timeframe alignment
        buy_count = sum(1 for a in signal.analyses.values() if a.signal == "BUY")
        total_count = len(signal.analyses)
        notes.append(f"Timeframe alignment: {buy_count}/{total_count} bullish")
        
        # Volatility notes
        avg_vol = self._get_avg_volatility(signal)
        if avg_vol > 0.7:
            notes.append("⚠️ High volatility - consider smaller position")
        elif avg_vol < 0.3:
            notes.append("✅ Low volatility - stable conditions")
        
        return notes
    
    async def format_trade_plan(self, plan: TradePlan) -> str:
        """Format trade plan for display"""
        
        return f"""
📊 **Trade Plan for {plan.pair}**
Direction: **{plan.direction}**
Confidence: **{plan.confidence:.1%}**
Market Regime: **{plan.market_regime.value}**

**Entry:**
{plan.entry_trigger}
Entry Range: ${plan.entry_range[0]:,.2f} - ${plan.entry_range[1]:,.2f}

**Exit Points:**
Stop Loss: ${plan.stop_loss_price:,.2f} (-{((plan.entry_price - plan.stop_loss_price) / plan.entry_price * 100):.1f}%)
Take Profit: ${plan.take_profit_price:,.2f} (+{((plan.take_profit_price - plan.entry_price) / plan.entry_price * 100):.1f}%)

**Position Sizing:**
Position Value: ${plan.position_value:,.2f}
Position Size: {plan.position_size:.8f} {plan.pair.split('/')[0]}
Risk Amount: ${plan.risk_amount:,.2f}
Reward Target: ${plan.reward_amount:,.2f}
Risk/Reward: 1:{plan.risk_reward_ratio:.1f}

**Timing:**
Timeframe: {plan.recommended_timeframe}
Est. Hold Time: {plan.estimated_hold_time}
Max Hold Time: {plan.max_hold_time}
Entry Valid Until: {plan.entry_expiry.strftime('%Y-%m-%d %H:%M')}

**Notes:**
{chr(10).join(f'• {note}' for note in plan.notes)}
"""