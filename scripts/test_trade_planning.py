#!/usr/bin/env python3
"""
Test the enhanced multi-timeframe analyzer with complete trade planning
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
from core.risk.multi_timeframe_enhanced import EnhancedMultiTimeframeAnalyzer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_trade_planning():
    """Test complete trade planning with entry/exit/timing"""
    
    # Initialize
    init_settings()
    exchange = KrakenExchange()
    analyzer = EnhancedMultiTimeframeAnalyzer()
    
    # Test parameters
    capital = 1000.0  # $1000 AUD capital
    risk_per_trade = 0.02  # Risk 2% per trade
    test_pairs = ["BTC/AUD", "ETH/AUD", "SOL/AUD"]
    
    logger.info(f"Testing Trade Planning at {datetime.now()}")
    logger.info(f"Capital: ${capital:,.2f} | Risk per trade: {risk_per_trade:.1%}")
    logger.info("=" * 60)
    
    for pair in test_pairs:
        try:
            logger.info(f"\n🔍 Analyzing {pair}...")
            
            # Get current price
            ticker = await exchange.get_ticker(pair)
            logger.info(f"Current price: ${ticker['price']:,.2f}")
            logger.info(f"24h Range: ${ticker['low_24h']:,.2f} - ${ticker['high_24h']:,.2f}")
            
            # Create trade plan
            plan = await analyzer.create_trade_plan(
                pair=pair,
                exchange=exchange,
                capital=capital,
                risk_per_trade_pct=risk_per_trade
            )
            
            if plan:
                # Format and display the plan
                formatted = await analyzer.format_trade_plan(plan)
                print(formatted)
                
                # Additional calculations
                logger.info("\n📈 Additional Analysis:")
                
                # Distance to entry
                distance_to_entry = (plan.entry_price - ticker['price']) / ticker['price'] * 100
                logger.info(f"Distance to entry: {distance_to_entry:+.2f}%")
                
                # Break-even including fees (0.16% Kraken fee)
                fee_pct = 0.0016
                breakeven = plan.entry_price * (1 + fee_pct * 2)  # Entry + exit fees
                logger.info(f"Break-even (inc. fees): ${breakeven:,.2f}")
                
                # Multiple timeframe confirmation
                timeframes = ["5m", "15m", "1h", "4h", "1d"]
                logger.info("\nTimeframe Analysis:")
                for tf in timeframes:
                    hold_time = analyzer.HOLD_TIME_MAP[tf]["typical"]
                    logger.info(f"  {tf}: Typical hold {hold_time}")
                
            else:
                logger.info(f"❌ No trade opportunity for {pair} at current levels")
                
        except Exception as e:
            logger.error(f"Failed to analyze {pair}: {e}")
            import traceback
            traceback.print_exc()
    
    logger.info("\n" + "=" * 60)
    logger.info("Trade planning analysis complete!")
    
    # Summary
    logger.info("\n📋 SUMMARY:")
    logger.info("The enhanced analyzer now calculates:")
    logger.info("✅ Entry points with specific price levels and triggers")
    logger.info("✅ Stop-loss and take-profit prices (not just percentages)")
    logger.info("✅ Estimated hold times based on timeframe")
    logger.info("✅ Position sizing based on risk management")
    logger.info("✅ Risk/reward ratios")
    logger.info("✅ Entry expiration times")
    logger.info("✅ Market regime-specific entry strategies")

if __name__ == "__main__":
    asyncio.run(test_trade_planning())