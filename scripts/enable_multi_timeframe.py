#!/usr/bin/env python3
"""
Enable multi-timeframe trading in Kraken Trader

This script shows how to integrate the multi-timeframe analyzer
with the existing bot infrastructure.
"""

import os

def create_deployment_script():
    """Create a deployment script with multi-timeframe enabled"""
    
    script = """#!/bin/bash
# Deploy Kraken Trader with Multi-Timeframe Analysis

echo "Deploying Kraken Trader with Multi-Timeframe Analysis..."

# Build and deploy
gcloud builds submit --tag australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader:latest .

gcloud run deploy kraken-trader \
  --image australia-southeast1-docker.pkg.dev/cryptotrading-485110/cloud-run-source-deploy/kraken-trader:latest \
  --platform managed \
  --region australia-southeast1 \
  --set-env-vars "MULTI_TIMEFRAME_ENABLED=true,CHECK_INTERVAL_MINUTES=15,MIN_HOLD_TIME_HOURS=0.5,USE_FALLBACK_VOLATILITY=true,PRIMARY_TIMEFRAMES=15m,1h,4h" \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 1 \
  --allow-unauthenticated

echo "Deployment complete!"
"""
    
    with open("deploy_multi_timeframe.sh", "w") as f:
        f.write(script)
    
    print("Created deploy_multi_timeframe.sh")

def show_integration_example():
    """Show how to integrate multi-timeframe into existing code"""
    
    print("\n" + "="*60)
    print("MULTI-TIMEFRAME INTEGRATION EXAMPLE")
    print("="*60)
    
    print("\n1. Add to your technical analyst (agents/analysts/technical/basic.py):\n")
    
    print("""
from core.risk.multi_timeframe import MultiTimeframeAnalyzer

class TechnicalAnalyst(IAnalyst):
    def __init__(self):
        super().__init__()
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.multi_timeframe_enabled = os.getenv("MULTI_TIMEFRAME_ENABLED", "false").lower() == "true"
    
    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        # Existing analysis...
        
        # Add multi-timeframe if enabled
        if self.multi_timeframe_enabled:
            mtf_signal = await self.mtf_analyzer.analyze(pair, self.exchange)
            
            # Incorporate MTF signal into analysis
            if mtf_signal.signal == "BUY" and mtf_signal.confidence > 0.7:
                signal_strength = min(1.0, signal_strength + 0.2)
                action = SignalAction.BUY
                
                # Use MTF risk parameters
                metadata["stop_loss_pct"] = mtf_signal.stop_loss_pct
                metadata["take_profit_pct"] = mtf_signal.take_profit_pct
                metadata["regime"] = mtf_signal.primary_regime.value
                metadata["recommended_timeframe"] = mtf_signal.recommended_timeframe
""")
    
    print("\n2. Environment variables to set:\n")
    print("   MULTI_TIMEFRAME_ENABLED=true")
    print("   PRIMARY_TIMEFRAMES=15m,1h,4h  # Timeframes to analyze")
    print("   ADAPTIVE_TIMEFRAME=true  # Auto-switch based on market regime")
    
    print("\n3. Benefits of multi-timeframe approach:")
    print("   - Adapts to market conditions automatically")
    print("   - Uses short timeframes (5m, 15m) in volatile/ranging markets")
    print("   - Uses longer timeframes (4h, 1d) in trending markets")
    print("   - Provides regime-specific risk parameters")
    print("   - Combines signals from multiple timeframes for confirmation")

def show_timeframe_strategy():
    """Show how different timeframes work"""
    
    print("\n" + "="*60)
    print("TIMEFRAME STRATEGY GUIDE")
    print("="*60)
    
    strategies = {
        "5-minute": {
            "best_for": "Scalping, volatile markets, quick trades",
            "hold_time": "5-30 minutes",
            "stop_loss": "1-2%",
            "take_profit": "2-4%",
            "signals_per_day": "10-50"
        },
        "15-minute": {
            "best_for": "Day trading, ranging markets",
            "hold_time": "30 min - 2 hours",
            "stop_loss": "2-4%",
            "take_profit": "4-8%",
            "signals_per_day": "5-20"
        },
        "1-hour": {
            "best_for": "Swing trading, balanced approach",
            "hold_time": "2-24 hours",
            "stop_loss": "3-6%",
            "take_profit": "6-12%",
            "signals_per_day": "2-10"
        },
        "4-hour": {
            "best_for": "Position trading, trending markets",
            "hold_time": "1-5 days",
            "stop_loss": "5-10%",
            "take_profit": "10-20%",
            "signals_per_day": "0.5-3"
        },
        "Daily": {
            "best_for": "Long-term trends, low maintenance",
            "hold_time": "1-4 weeks",
            "stop_loss": "8-15%",
            "take_profit": "15-30%",
            "signals_per_day": "0.1-0.5"
        }
    }
    
    for timeframe, details in strategies.items():
        print(f"\n{timeframe} Timeframe:")
        for key, value in details.items():
            print(f"  {key.replace('_', ' ').title()}: {value}")
    
    print("\n" + "="*60)
    print("CURRENT ISSUE: Bot stuck on 1-hour timeframe with 2-hour minimum hold")
    print("SOLUTION: Enable multi-timeframe to dynamically switch between timeframes")
    print("="*60)

if __name__ == "__main__":
    create_deployment_script()
    show_integration_example()
    show_timeframe_strategy()