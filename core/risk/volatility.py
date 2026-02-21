"""
Volatility-Based Risk Calculator

Calculates dynamic stop-loss and take-profit levels based on:
- Average True Range (ATR) for volatility measurement
- Historical price volatility
- Asset-specific volatility profiles
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import statistics
import math

from core.interfaces import IExchange
from core.models import MarketData

logger = logging.getLogger(__name__)


@dataclass
class VolatilityProfile:
    """Asset volatility profile with calculated metrics"""
    asset: str
    atr_14: float  # 14-period ATR
    atr_pct: float  # ATR as percentage of current price
    volatility_rank: str  # "LOW", "MEDIUM", "HIGH"
    suggested_stop_loss_pct: float
    suggested_take_profit_pct: float
    confidence: float  # 0-1, how confident we are in this data
    last_updated: datetime


@dataclass
class VolatilityConfig:
    """Configuration for volatility-based risk calculations"""
    atr_period: int = 14  # ATR calculation period
    volatility_lookback: int = 20  # How many periods to look back for volatility
    base_stop_multiplier: float = 2.0  # ATR multiplier for base stop-loss
    base_tp_multiplier: float = 3.0  # ATR multiplier for base take-profit
    
    # Volatility thresholds (ATR % of price)
    low_volatility_threshold: float = 0.02  # 2%
    high_volatility_threshold: float = 0.06  # 6%
    
    # Risk adjustments per volatility tier
    low_vol_stop_multiplier: float = 1.5  # Tighter stops for stable assets
    medium_vol_stop_multiplier: float = 2.0  # Normal stops
    high_vol_stop_multiplier: float = 2.5  # Wider stops for volatile assets
    
    low_vol_tp_multiplier: float = 2.0
    medium_vol_tp_multiplier: float = 3.0
    high_vol_tp_multiplier: float = 4.0
    
    # Fallback values when volatility data unavailable
    fallback_stop_loss_pct: float = 0.05  # 5%
    fallback_take_profit_pct: float = 0.10  # 10%
    
    # Minimum data requirements
    min_candles_required: int = 14


class VolatilityCalculator:
    """
    Calculates volatility-based stop-loss and take-profit levels.
    
    Uses ATR (Average True Range) as the primary volatility measure,
    with fallbacks to historical volatility and fixed percentages.
    """
    
    def __init__(self, config: VolatilityConfig = None):
        self.config = config or VolatilityConfig()
        self._cache: Dict[str, VolatilityProfile] = {}
        self._cache_ttl = timedelta(minutes=30)  # Cache profiles for 30 minutes
    
    async def get_volatility_profile(
        self, 
        pair: str, 
        exchange: IExchange,
        force_refresh: bool = False
    ) -> VolatilityProfile:
        """
        Get or calculate volatility profile for a trading pair.
        
        Args:
            pair: Trading pair (e.g., "BTC/USDT")
            exchange: Exchange interface for market data
            force_refresh: Force recalculation even if cached
            
        Returns:
            VolatilityProfile with calculated risk levels
        """
        # Check cache first
        if not force_refresh and pair in self._cache:
            profile = self._cache[pair]
            if datetime.now() - profile.last_updated < self._cache_ttl:
                logger.debug(f"[VOLATILITY] Using cached profile for {pair}")
                return profile
        
        logger.info(f"[VOLATILITY] Calculating profile for {pair}")
        
        try:
            # Get market data with sufficient history for ATR calculation
            market_data = await exchange.get_market_data(pair)
            
            # Get additional OHLCV data for volatility calculation
            ohlcv_data = await exchange.get_ohlcv(
                pair=pair,
                interval=60,  # 1-hour candles
                limit=max(self.config.atr_period * 2, 48)  # At least 48 hours of data
            )
            
            profile = await self._calculate_profile(pair, market_data, ohlcv_data)
            
            # Cache the result
            self._cache[pair] = profile
            
            logger.info(
                f"[VOLATILITY] {pair}: ATR={profile.atr_pct:.2%}, "
                f"Rank={profile.volatility_rank}, "
                f"SL={profile.suggested_stop_loss_pct:.2%}, "
                f"TP={profile.suggested_take_profit_pct:.2%}"
            )
            
            return profile
            
        except Exception as e:
            logger.warning(f"[VOLATILITY] Failed to calculate profile for {pair}: {e}")
            return self._create_fallback_profile(pair)
    
    async def _calculate_profile(
        self,
        pair: str,
        market_data: MarketData,
        ohlcv_data: List[List]
    ) -> VolatilityProfile:
        """Calculate volatility profile from market data"""
        
        if len(ohlcv_data) < self.config.min_candles_required:
            logger.warning(
                f"[VOLATILITY] Insufficient data for {pair}: "
                f"{len(ohlcv_data)} candles < {self.config.min_candles_required} required"
            )
            return self._create_fallback_profile(pair)
        
        # Calculate ATR
        atr_values = self._calculate_atr(ohlcv_data, self.config.atr_period)
        if not atr_values:
            return self._create_fallback_profile(pair)
        
        current_atr = atr_values[-1]
        current_price = market_data.current_price
        atr_pct = current_atr / current_price if current_price > 0 else 0
        
        # Determine volatility rank
        volatility_rank = self._classify_volatility(atr_pct)
        
        # Calculate suggested stop-loss and take-profit
        stop_loss_pct, take_profit_pct = self._calculate_risk_levels(
            atr_pct, volatility_rank, current_price, current_atr
        )
        
        # Calculate confidence based on data quality
        confidence = self._calculate_confidence(ohlcv_data, atr_values)
        
        return VolatilityProfile(
            asset=pair.split('/')[0],  # Extract base asset
            atr_14=current_atr,
            atr_pct=atr_pct,
            volatility_rank=volatility_rank,
            suggested_stop_loss_pct=stop_loss_pct,
            suggested_take_profit_pct=take_profit_pct,
            confidence=confidence,
            last_updated=datetime.now()
        )
    
    def _calculate_atr(self, ohlcv_data: List[List], period: int) -> List[float]:
        """
        Calculate Average True Range (ATR) from OHLCV data.
        
        True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        ATR = Simple moving average of True Range over the period
        """
        if len(ohlcv_data) < period + 1:
            return []
        
        true_ranges = []
        
        for i in range(1, len(ohlcv_data)):
            current = ohlcv_data[i]
            previous = ohlcv_data[i - 1]
            
            # [timestamp, open, high, low, close, volume]
            high = current[2]
            low = current[3]
            prev_close = previous[4]
            
            # Calculate True Range
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            
            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)
        
        # Calculate ATR using simple moving average
        atr_values = []
        for i in range(period - 1, len(true_ranges)):
            atr = sum(true_ranges[i - period + 1:i + 1]) / period
            atr_values.append(atr)
        
        return atr_values
    
    def _classify_volatility(self, atr_pct: float) -> str:
        """Classify volatility as LOW, MEDIUM, or HIGH"""
        if atr_pct <= self.config.low_volatility_threshold:
            return "LOW"
        elif atr_pct >= self.config.high_volatility_threshold:
            return "HIGH"
        else:
            return "MEDIUM"
    
    def _calculate_risk_levels(
        self,
        atr_pct: float,
        volatility_rank: str,
        current_price: float,
        atr_value: float
    ) -> Tuple[float, float]:
        """Calculate stop-loss and take-profit percentages based on volatility"""
        
        # Get multipliers based on volatility rank
        if volatility_rank == "LOW":
            stop_multiplier = self.config.low_vol_stop_multiplier
            tp_multiplier = self.config.low_vol_tp_multiplier
        elif volatility_rank == "HIGH":
            stop_multiplier = self.config.high_vol_stop_multiplier
            tp_multiplier = self.config.high_vol_tp_multiplier
        else:  # MEDIUM
            stop_multiplier = self.config.medium_vol_stop_multiplier
            tp_multiplier = self.config.medium_vol_tp_multiplier
        
        # Calculate stop-loss and take-profit as percentage of current price
        stop_loss_pct = (atr_value * stop_multiplier) / current_price
        take_profit_pct = (atr_value * tp_multiplier) / current_price
        
        # Apply reasonable bounds
        stop_loss_pct = max(0.01, min(0.15, stop_loss_pct))  # 1% to 15%
        take_profit_pct = max(0.02, min(0.30, take_profit_pct))  # 2% to 30%
        
        return stop_loss_pct, take_profit_pct
    
    def _calculate_confidence(self, ohlcv_data: List[List], atr_values: List[float]) -> float:
        """
        Calculate confidence in the volatility measurements.
        
        Higher confidence for:
        - More data points
        - Stable ATR readings
        - Recent data
        """
        data_points = len(ohlcv_data)
        atr_points = len(atr_values)
        
        # Base confidence from data quantity
        data_confidence = min(1.0, data_points / (self.config.atr_period * 3))
        
        # ATR stability confidence
        if atr_points >= 5:
            atr_stability = 1.0 - (statistics.stdev(atr_values[-5:]) / statistics.mean(atr_values[-5:]))
            atr_stability = max(0.0, min(1.0, atr_stability))
        else:
            atr_stability = 0.5
        
        # Combine confidences
        overall_confidence = (data_confidence * 0.6) + (atr_stability * 0.4)
        
        return max(0.1, min(1.0, overall_confidence))
    
    def _create_fallback_profile(self, pair: str) -> VolatilityProfile:
        """Create fallback profile when calculation fails"""
        asset = pair.split('/')[0]
        
        # Asset-specific fallbacks based on known characteristics
        if asset in ['BTC', 'ETH']:
            # Major assets - lower volatility
            stop_loss = 0.04  # 4%
            take_profit = 0.08  # 8%
            rank = "LOW"
        elif asset in ['SOL', 'AVAX', 'MATIC']:
            # Alt coins - higher volatility
            stop_loss = 0.08  # 8%
            take_profit = 0.15  # 15%
            rank = "HIGH"
        else:
            # Default medium volatility
            stop_loss = self.config.fallback_stop_loss_pct
            take_profit = self.config.fallback_take_profit_pct
            rank = "MEDIUM"
        
        logger.info(f"[VOLATILITY] Using fallback profile for {pair}: SL={stop_loss:.1%}, TP={take_profit:.1%}")
        
        return VolatilityProfile(
            asset=asset,
            atr_14=0.0,
            atr_pct=0.0,
            volatility_rank=rank,
            suggested_stop_loss_pct=stop_loss,
            suggested_take_profit_pct=take_profit,
            confidence=0.3,  # Low confidence for fallback
            last_updated=datetime.now()
        )
    
    async def calculate_position_levels(
        self,
        pair: str,
        entry_price: float,
        exchange: IExchange,
        strategy_multipliers: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        Calculate actual stop-loss and take-profit prices for a position.
        
        Args:
            pair: Trading pair
            entry_price: Entry price for the position
            exchange: Exchange interface
            strategy_multipliers: Optional strategy-specific multipliers
            
        Returns:
            Dictionary with 'stop_loss_price' and 'take_profit_price'
        """
        profile = await self.get_volatility_profile(pair, exchange)
        
        # Apply strategy multipliers if provided
        stop_loss_pct = profile.suggested_stop_loss_pct
        take_profit_pct = profile.suggested_take_profit_pct
        
        if strategy_multipliers:
            stop_multiplier = strategy_multipliers.get('stop_loss_multiplier', 1.0)
            tp_multiplier = strategy_multipliers.get('take_profit_multiplier', 1.0)
            
            stop_loss_pct *= stop_multiplier
            take_profit_pct *= tp_multiplier
        
        # Calculate actual prices
        stop_loss_price = entry_price * (1 - stop_loss_pct)
        take_profit_price = entry_price * (1 + take_profit_pct)
        
        return {
            'stop_loss_price': stop_loss_price,
            'take_profit_price': take_profit_price,
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct,
            'volatility_rank': profile.volatility_rank,
            'atr_pct': profile.atr_pct,
            'confidence': profile.confidence
        }
    
    def get_cached_profiles(self) -> Dict[str, VolatilityProfile]:
        """Get all cached volatility profiles"""
        return self._cache.copy()
    
    def clear_cache(self) -> None:
        """Clear the volatility profile cache"""
        self._cache.clear()
        logger.info("[VOLATILITY] Profile cache cleared")