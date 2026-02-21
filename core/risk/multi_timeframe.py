"""
Multi-Timeframe Analysis for Dynamic Trading

Analyzes multiple timeframes to adapt trading behavior based on market conditions:
- Short timeframes (5m, 15m) for volatile markets
- Medium timeframes (1h, 4h) for normal conditions  
- Long timeframes (1d, 1w) for trend following
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
from enum import Enum

from core.interfaces import IExchange
from core.models import MarketData

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regimes detected across timeframes"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"
    BREAKOUT = "breakout"


@dataclass
class TimeframeAnalysis:
    """Analysis results for a single timeframe"""
    timeframe: str
    interval_minutes: int
    regime: MarketRegime
    volatility: float  # 0-1 normalized
    trend_strength: float  # -1 to 1 (negative=down, positive=up)
    support: float
    resistance: float
    confidence: float
    signal: str  # BUY, SELL, HOLD


@dataclass
class MultiTimeframeSignal:
    """Combined signal from multiple timeframes"""
    pair: str
    primary_regime: MarketRegime
    signal: str  # BUY, SELL, HOLD
    confidence: float
    stop_loss_pct: float
    take_profit_pct: float
    recommended_timeframe: str
    analyses: Dict[str, TimeframeAnalysis]
    timestamp: datetime


class MultiTimeframeAnalyzer:
    """
    Analyzes multiple timeframes to generate adaptive trading signals.
    
    Automatically adjusts between timeframes based on market conditions:
    - Uses shorter timeframes in volatile/ranging markets
    - Uses longer timeframes in trending markets
    - Provides regime-specific risk parameters
    """
    
    # Timeframe configurations
    TIMEFRAMES = {
        # name: (interval_minutes, candles_needed, weight)
        "5m": (5, 288, 0.1),      # ~24 hours of 5-min data
        "15m": (15, 96, 0.2),     # ~24 hours of 15-min data
        "1h": (60, 168, 0.3),     # ~1 week of hourly data
        "4h": (240, 42, 0.25),    # ~1 week of 4-hour data
        "1d": (1440, 30, 0.15),   # ~1 month of daily data
    }
    
    # Kraken interval mapping
    KRAKEN_INTERVALS = {
        1: 1, 5: 5, 15: 15, 30: 30,
        60: 60, 240: 240, 1440: 1440,
        10080: 10080, 21600: 21600
    }
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, TimeframeAnalysis]] = {}
        self._cache_ttl = timedelta(minutes=5)
    
    async def analyze(
        self,
        pair: str,
        exchange: IExchange,
        force_refresh: bool = False
    ) -> MultiTimeframeSignal:
        """
        Analyze multiple timeframes and generate adaptive signal.
        
        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            exchange: Exchange interface
            force_refresh: Force new analysis
            
        Returns:
            MultiTimeframeSignal with combined analysis
        """
        logger.info(f"[MTF] Starting multi-timeframe analysis for {pair}")
        
        analyses = {}
        
        # Analyze each timeframe
        for tf_name, (interval, candles, weight) in self.TIMEFRAMES.items():
            try:
                analysis = await self._analyze_timeframe(
                    pair, tf_name, interval, candles, exchange
                )
                analyses[tf_name] = analysis
                
                logger.debug(
                    f"[MTF] {pair} {tf_name}: {analysis.regime.value}, "
                    f"Vol={analysis.volatility:.2f}, Signal={analysis.signal}"
                )
                
            except Exception as e:
                logger.warning(f"[MTF] Failed to analyze {tf_name} for {pair}: {e}")
        
        if not analyses:
            logger.error(f"[MTF] No timeframe analysis available for {pair}")
            return self._create_fallback_signal(pair)
        
        # Combine analyses into final signal
        signal = self._combine_analyses(pair, analyses)
        
        logger.info(
            f"[MTF] {pair} Final: {signal.signal} "
            f"(confidence={signal.confidence:.2f}, regime={signal.primary_regime.value}, "
            f"recommended_tf={signal.recommended_timeframe})"
        )
        
        return signal
    
    async def _analyze_timeframe(
        self,
        pair: str,
        timeframe: str,
        interval: int,
        candles_needed: int,
        exchange: IExchange
    ) -> TimeframeAnalysis:
        """Analyze a single timeframe"""
        
        # Get OHLCV data
        ohlcv = await exchange.get_ohlcv(pair, interval, candles_needed)
        
        if len(ohlcv) < 20:  # Minimum data required
            raise ValueError(f"Insufficient data: {len(ohlcv)} candles")
        
        # Extract price data
        closes = [c[4] for c in ohlcv]
        highs = [c[2] for c in ohlcv]
        lows = [c[3] for c in ohlcv]
        volumes = [c[5] for c in ohlcv]
        
        # Calculate indicators
        regime = self._detect_regime(closes, highs, lows, volumes)
        volatility = self._calculate_volatility(closes)
        trend_strength = self._calculate_trend_strength(closes)
        support, resistance = self._find_support_resistance(lows, highs, closes[-1])
        signal = self._generate_signal(
            closes, regime, trend_strength, volatility, support, resistance
        )
        
        # Confidence based on data quality and regime clarity
        confidence = self._calculate_confidence(
            len(ohlcv), candles_needed, volatility, trend_strength
        )
        
        return TimeframeAnalysis(
            timeframe=timeframe,
            interval_minutes=interval,
            regime=regime,
            volatility=volatility,
            trend_strength=trend_strength,
            support=support,
            resistance=resistance,
            confidence=confidence,
            signal=signal
        )
    
    def _detect_regime(
        self, 
        closes: List[float], 
        highs: List[float], 
        lows: List[float],
        volumes: List[float]
    ) -> MarketRegime:
        """Detect current market regime"""
        
        if len(closes) < 20:
            return MarketRegime.QUIET
        
        # Calculate metrics
        recent_closes = closes[-20:]
        ma_short = sum(recent_closes[-5:]) / 5
        ma_long = sum(recent_closes) / 20
        
        # Price range
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])
        price_range = (recent_high - recent_low) / recent_low
        
        # Volatility
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(-19, 0)]
        volatility = np.std(returns)
        
        # Volume trend
        recent_vol = sum(volumes[-5:]) / 5
        older_vol = sum(volumes[-20:-5]) / 15
        volume_surge = recent_vol / older_vol if older_vol > 0 else 1
        
        # Detect regime
        if price_range < 0.02 and volatility < 0.01:
            return MarketRegime.QUIET
        elif price_range > 0.10 or volatility > 0.03:
            return MarketRegime.VOLATILE
        elif ma_short > ma_long * 1.02:
            if closes[-1] > recent_high * 0.98 and volume_surge > 1.5:
                return MarketRegime.BREAKOUT
            return MarketRegime.TRENDING_UP
        elif ma_short < ma_long * 0.98:
            return MarketRegime.TRENDING_DOWN
        else:
            return MarketRegime.RANGING
    
    def _calculate_volatility(self, closes: List[float]) -> float:
        """Calculate normalized volatility (0-1)"""
        if len(closes) < 2:
            return 0.5
        
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        volatility = np.std(returns)
        
        # Normalize to 0-1 range (typical crypto vol 0.01-0.10)
        normalized = min(1.0, volatility / 0.10)
        return normalized
    
    def _calculate_trend_strength(self, closes: List[float]) -> float:
        """Calculate trend strength (-1 to 1)"""
        if len(closes) < 10:
            return 0.0
        
        # Linear regression slope
        x = np.arange(len(closes))
        y = np.array(closes)
        
        # Normalize prices to percentage changes
        y_norm = (y - y[0]) / y[0]
        
        # Calculate slope
        slope = np.polyfit(x, y_norm, 1)[0]
        
        # Normalize to -1 to 1 range
        trend_strength = np.tanh(slope * 100)
        
        return trend_strength
    
    def _find_support_resistance(
        self, 
        lows: List[float], 
        highs: List[float], 
        current_price: float
    ) -> Tuple[float, float]:
        """Find nearest support and resistance levels"""
        
        # Simple approach: use recent lows for support, highs for resistance
        recent_lows = lows[-20:] if len(lows) >= 20 else lows
        recent_highs = highs[-20:] if len(highs) >= 20 else highs
        
        # Support: highest low below current price
        supports = [low for low in recent_lows if low < current_price * 0.99]
        support = max(supports) if supports else min(recent_lows)
        
        # Resistance: lowest high above current price
        resistances = [high for high in recent_highs if high > current_price * 1.01]
        resistance = min(resistances) if resistances else max(recent_highs)
        
        return support, resistance
    
    def _generate_signal(
        self,
        closes: List[float],
        regime: MarketRegime,
        trend_strength: float,
        volatility: float,
        support: float,
        resistance: float
    ) -> str:
        """Generate trading signal based on regime and indicators"""
        
        current_price = closes[-1]
        
        # Regime-specific signal generation
        if regime == MarketRegime.TRENDING_UP:
            # Buy on pullbacks in uptrend
            distance_to_support = (current_price - support) / current_price
            if distance_to_support < 0.02:  # Near support
                return "BUY"
            elif distance_to_support > 0.05:  # Extended
                return "HOLD"
            else:
                return "BUY" if trend_strength > 0.3 else "HOLD"
                
        elif regime == MarketRegime.TRENDING_DOWN:
            # Avoid catching falling knives
            return "SELL" if trend_strength < -0.3 else "HOLD"
            
        elif regime == MarketRegime.RANGING:
            # Buy at support, sell at resistance
            range_position = (current_price - support) / (resistance - support)
            if range_position < 0.3:
                return "BUY"
            elif range_position > 0.7:
                return "SELL"
            else:
                return "HOLD"
                
        elif regime == MarketRegime.VOLATILE:
            # Wait for stability
            return "HOLD"
            
        elif regime == MarketRegime.BREAKOUT:
            # Follow the breakout
            return "BUY" if trend_strength > 0 else "SELL"
            
        else:  # QUIET
            return "HOLD"
    
    def _calculate_confidence(
        self,
        data_points: int,
        required_points: int,
        volatility: float,
        trend_strength: float
    ) -> float:
        """Calculate confidence in the analysis"""
        
        # Data quality component
        data_confidence = min(1.0, data_points / required_points)
        
        # Regime clarity component
        regime_confidence = abs(trend_strength)  # Stronger trends = higher confidence
        
        # Volatility penalty (high vol = lower confidence)
        volatility_penalty = 1.0 - (volatility * 0.5)
        
        # Combine factors
        confidence = (data_confidence * 0.5 + 
                     regime_confidence * 0.3 + 
                     volatility_penalty * 0.2)
        
        return max(0.1, min(1.0, confidence))
    
    def _combine_analyses(
        self,
        pair: str,
        analyses: Dict[str, TimeframeAnalysis]
    ) -> MultiTimeframeSignal:
        """Combine timeframe analyses into final signal"""
        
        # Weight votes by timeframe weights and confidence
        buy_score = 0
        sell_score = 0
        hold_score = 0
        total_weight = 0
        
        regimes = []
        volatilities = []
        
        for tf_name, analysis in analyses.items():
            weight = self.TIMEFRAMES[tf_name][2] * analysis.confidence
            
            if analysis.signal == "BUY":
                buy_score += weight
            elif analysis.signal == "SELL":
                sell_score += weight
            else:
                hold_score += weight
            
            total_weight += weight
            regimes.append(analysis.regime)
            volatilities.append(analysis.volatility)
        
        # Determine primary regime (most common)
        primary_regime = max(set(regimes), key=regimes.count)
        avg_volatility = sum(volatilities) / len(volatilities)
        
        # Determine recommended timeframe based on regime
        if primary_regime in [MarketRegime.VOLATILE, MarketRegime.RANGING]:
            # Use shorter timeframes for volatile/ranging markets
            recommended_tf = "15m" if avg_volatility > 0.7 else "1h"
        elif primary_regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            # Use longer timeframes for trending markets
            recommended_tf = "4h" if avg_volatility < 0.3 else "1h"
        else:
            recommended_tf = "1h"  # Default
        
        # Final signal
        if buy_score > sell_score and buy_score > hold_score:
            signal = "BUY"
            confidence = buy_score / total_weight
        elif sell_score > buy_score and sell_score > hold_score:
            signal = "SELL"
            confidence = sell_score / total_weight
        else:
            signal = "HOLD"
            confidence = hold_score / total_weight
        
        # Risk parameters based on regime and volatility
        if primary_regime == MarketRegime.VOLATILE:
            stop_loss_pct = 0.08 + (avg_volatility * 0.04)  # 8-12%
            take_profit_pct = 0.15 + (avg_volatility * 0.10)  # 15-25%
        elif primary_regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            stop_loss_pct = 0.04 + (avg_volatility * 0.02)  # 4-6%
            take_profit_pct = 0.12 + (avg_volatility * 0.08)  # 12-20%
        else:  # RANGING, QUIET
            stop_loss_pct = 0.03 + (avg_volatility * 0.02)  # 3-5%
            take_profit_pct = 0.06 + (avg_volatility * 0.04)  # 6-10%
        
        return MultiTimeframeSignal(
            pair=pair,
            primary_regime=primary_regime,
            signal=signal,
            confidence=confidence,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            recommended_timeframe=recommended_tf,
            analyses=analyses,
            timestamp=datetime.now()
        )
    
    def _create_fallback_signal(self, pair: str) -> MultiTimeframeSignal:
        """Create fallback signal when analysis fails"""
        return MultiTimeframeSignal(
            pair=pair,
            primary_regime=MarketRegime.QUIET,
            signal="HOLD",
            confidence=0.0,
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
            recommended_timeframe="1h",
            analyses={},
            timestamp=datetime.now()
        )