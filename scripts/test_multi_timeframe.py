#!/usr/bin/env python3
"""
Test multi-timeframe analysis to see current market conditions
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import get_settings, init_settings
from integrations.exchanges.kraken import KrakenExchange
from core.risk.multi_timeframe import MultiTimeframeAnalyzer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_multi_timeframe():
    """Test multi-timeframe analysis on current markets"""
    
    # Initialize settings
    init_settings()
    settings = get_settings()
    
    # Initialize exchange (can work without API keys for public data)
    exchange = KrakenExchange()
    
    # Initialize multi-timeframe analyzer
    mtf_analyzer = MultiTimeframeAnalyzer()
    
    # Test pairs - using AUD pairs for local market
    test_pairs = ["BTC/AUD", "ETH/AUD", "SOL/AUD"]
    
    logger.info(f"Testing multi-timeframe analysis at {datetime.now()}")
    logger.info("=" * 60)
    
    for pair in test_pairs:
        try:
            logger.info(f"\nAnalyzing {pair}...")
            
            # Get current ticker
            ticker = await exchange.get_ticker(pair)
            logger.info(f"Current price: ${ticker['price']:,.2f} AUD")
            
            # Run multi-timeframe analysis
            signal = await mtf_analyzer.analyze(pair, exchange)
            
            logger.info(f"\nResults for {pair}:")
            logger.info(f"  Primary Regime: {signal.primary_regime.value}")
            logger.info(f"  Signal: {signal.signal}")
            logger.info(f"  Confidence: {signal.confidence:.2%}")
            logger.info(f"  Recommended Timeframe: {signal.recommended_timeframe}")
            logger.info(f"  Stop Loss: {signal.stop_loss_pct:.1%}")
            logger.info(f"  Take Profit: {signal.take_profit_pct:.1%}")
            
            logger.info(f"\n  Timeframe Breakdown:")
            for tf_name, analysis in signal.analyses.items():
                logger.info(
                    f"    {tf_name}: {analysis.signal} "
                    f"(regime={analysis.regime.value}, "
                    f"vol={analysis.volatility:.2f}, "
                    f"trend={analysis.trend_strength:+.2f})"
                )
            
            # Calculate actual price levels
            if signal.signal == "BUY":
                entry_price = ticker['price']
                stop_loss = entry_price * (1 - signal.stop_loss_pct)
                take_profit = entry_price * (1 + signal.take_profit_pct)
                
                logger.info(f"\n  Trade Levels (if buying now):")
                logger.info(f"    Entry: ${entry_price:,.2f}")
                logger.info(f"    Stop Loss: ${stop_loss:,.2f} ({signal.stop_loss_pct:.1%})")
                logger.info(f"    Take Profit: ${take_profit:,.2f} ({signal.take_profit_pct:.1%})")
                
        except Exception as e:
            logger.error(f"Failed to analyze {pair}: {e}")
    
    logger.info("\n" + "=" * 60)
    logger.info("Analysis complete!")

if __name__ == "__main__":
    asyncio.run(test_multi_timeframe())