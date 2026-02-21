#!/usr/bin/env python3
"""
Populate volatility data for Kraken Trader to jump-start ATR calculations
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import get_settings, init_settings
from core.exchanges.kraken import KrakenExchange
from core.risk.volatility import VolatilityCalculator
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def populate_volatility_data():
    """Fetch historical data and calculate volatility profiles for all trading pairs"""
    
    # Initialize settings
    init_settings()
    settings = get_settings()
    
    # Initialize exchange
    exchange = KrakenExchange(
        api_key=os.getenv("KRAKEN_API_KEY"),
        api_secret=os.getenv("KRAKEN_API_SECRET")
    )
    
    # Initialize volatility calculator
    volatility_calc = VolatilityCalculator()
    
    logger.info(f"Populating volatility data for pairs: {settings.trading.pairs}")
    
    for pair in settings.trading.pairs:
        try:
            logger.info(f"Calculating volatility profile for {pair}...")
            
            # Force refresh to get fresh data
            profile = await volatility_calc.get_volatility_profile(
                pair=pair,
                exchange=exchange,
                force_refresh=True
            )
            
            logger.info(
                f"{pair} profile: ATR={profile.atr_pct:.2%}, "
                f"Rank={profile.volatility_rank}, "
                f"SL={profile.suggested_stop_loss_pct:.2%}, "
                f"TP={profile.suggested_take_profit_pct:.2%}, "
                f"Confidence={profile.confidence:.2f}"
            )
            
        except Exception as e:
            logger.error(f"Failed to populate data for {pair}: {e}")
    
    logger.info("Volatility data population complete!")
    
    # Show cached profiles
    cached = volatility_calc.get_cached_profiles()
    logger.info(f"Cached profiles: {list(cached.keys())}")

if __name__ == "__main__":
    asyncio.run(populate_volatility_data())