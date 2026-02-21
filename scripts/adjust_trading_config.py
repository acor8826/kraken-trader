#!/usr/bin/env python3
"""
Adjust Kraken Trader configuration for more frequent trading opportunities
"""

import json
import os

def create_aggressive_config():
    """Create a more aggressive configuration for testing"""
    
    config = {
        "trading": {
            "check_interval_minutes": 15,  # Check every 15 min instead of 60
            "min_hold_time_hours": 0.5,    # 30 min minimum hold instead of 2 hours
            "pairs": ["BTC/AUD", "ETH/AUD", "SOL/AUD"]  # Use AUD pairs for local market
        },
        "volatility": {
            "atr_period": 7,              # Shorter ATR period (7 hours vs 14)
            "min_candles_required": 7,    # Lower requirement to start faster
            "timeframe": "15m",           # Use 15-min candles for more granularity
            "fallback_enabled": True      # Use fallback values immediately
        },
        "risk": {
            "max_position_pct": 0.25,     # Allow 25% positions
            "max_total_exposure_pct": 0.90, # Allow 90% exposure
            "min_confidence": 0.60,       # Lower confidence threshold
            "stop_loss_multiplier": 1.5,  # Tighter stops for quicker exits
            "take_profit_multiplier": 2.0 # Closer targets
        },
        "features": {
            "use_volatility_stops": True,
            "enable_limit_orders": False,
            "aggressive_mode": True
        }
    }
    
    return config

def display_recommendations():
    """Display recommendations for getting the bot trading"""
    
    print("\n" + "="*60)
    print("KRAKEN TRADER CONFIGURATION RECOMMENDATIONS")
    print("="*60)
    
    print("\n1. IMMEDIATE ACTIONS:")
    print("   - Run populate_volatility_data.py to fetch historical data")
    print("   - Consider using AUD pairs instead of USDT for better liquidity")
    print("   - Reduce check_interval_minutes from 60 to 15-30")
    
    print("\n2. VOLATILITY ADJUSTMENTS:")
    print("   - Reduce ATR period from 14 to 7-10 for faster initialization")
    print("   - Use 15-minute candles instead of 1-hour for more data points")
    print("   - Enable fallback profiles for immediate trading")
    
    print("\n3. RISK PARAMETERS:")
    print("   - Increase max_position_pct to 25-30% for more capital usage")
    print("   - Reduce min_confidence from 0.70 to 0.60")
    print("   - Use tighter stop losses (1.5x ATR instead of 2x)")
    
    print("\n4. ENVIRONMENT VARIABLES TO SET:")
    print("   export AGGRESSIVE_MODE=true")
    print("   export CHECK_INTERVAL_MINUTES=15")
    print("   export MIN_HOLD_TIME_HOURS=0.5")
    print("   export USE_FALLBACK_VOLATILITY=true")
    
    print("\n5. DEPLOYMENT COMMAND:")
    print("   gcloud run deploy kraken-trader \\")
    print("     --set-env-vars AGGRESSIVE_MODE=true,CHECK_INTERVAL_MINUTES=15,MIN_HOLD_TIME_HOURS=0.5,USE_FALLBACK_VOLATILITY=true")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    config = create_aggressive_config()
    
    # Save config suggestion
    with open("aggressive_config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    print("Created aggressive_config.json")
    display_recommendations()