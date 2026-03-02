#!/usr/bin/env python3
"""
Test the aggressive trading configuration.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment variables before imports
os.environ["RISK_PROFILE"] = "aggressive"
os.environ["SIMULATION_MODE"] = "true"
os.environ["STAGE"] = "stage1"
os.environ["LOG_LEVEL"] = "INFO"

import asyncio
import logging
from datetime import datetime, timezone

from core.config import get_settings
from agents.analysts.technical.basic import TechnicalAnalyst
from agents.strategist.simple import SimpleStrategist
from core.models import MarketData, Portfolio, Position
# from integrations.llm.anthropic import AnthropicLLM

# Mock OHLCV data with a clear uptrend
MOCK_OHLCV = [
    [int((datetime.now(timezone.utc).timestamp() - 3600 * i) * 1000), 
     67000 - i * 100,  # Open
     67100 - i * 100,  # High  
     66900 - i * 100,  # Low
     67050 - i * 100,  # Close (uptrend)
     1000 + i * 10]    # Volume (increasing)
    for i in range(24, 0, -1)  # 24 hours of data
]

async def test_configuration():
    """Test the aggressive configuration"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Testing Aggressive Trading Configuration")
    print("=" * 60)
    
    # Load settings
    settings = get_settings()
    risk_config = settings.get_effective_risk()
    
    print(f"\nRisk Profile: {settings.risk_profile}")
    print(f"Min Confidence: {risk_config.min_confidence} (should be 0.50)")
    print(f"Max Position %: {risk_config.max_position_pct} (should be 0.35)")
    print(f"Max Daily Trades: {risk_config.max_daily_trades} (should be 30)")
    
    # Test technical analyst
    analyst = TechnicalAnalyst()
    market_data = MarketData(
        pair="BTC/AUD",
        current_price=67050,
        high_24h=67100,
        low_24h=66000,
        volume_24h=24000,
        ohlcv=MOCK_OHLCV,
        timestamp=datetime.now(timezone.utc)
    )
    
    signal = await analyst.analyze("BTC/AUD", market_data)
    
    print(f"\nTechnical Analysis Signal:")
    print(f"  Direction: {signal.direction:+.2f}")
    print(f"  Confidence: {signal.confidence:.2f}")
    print(f"  Reasoning: {signal.reasoning}")
    
    # Test strategist with mock LLM
    class MockLLM:
        async def complete(self, messages, **kwargs):
            # Simulate a bullish response
            return {
                "action": "BUY",
                "confidence": 0.65,
                "size_pct": 0.25,
                "strategy": "TREND_FOLLOW",
                "reasoning": "Strong uptrend with increasing volume",
                "key_factors": ["Upward momentum", "Volume confirmation"],
                "risks": ["Potential resistance at 68000"]
            }
    
    # Create portfolio
    portfolio = Portfolio(
        initial_value=1000.0,
        available_quote=1000.0,
        positions={},
        quote_currency="AUD"
    )
    
    # Test strategist
    llm = MockLLM()
    strategist = SimpleStrategist(llm, settings)
    
    # Create mock intel (would normally come from fusion)
    from core.models import MarketIntel
    intel = MarketIntel(
        pair="BTC/AUD", 
        signals=[signal],
        fused_direction=signal.direction,
        fused_confidence=signal.confidence,
        timestamp=datetime.now(timezone.utc)
    )
    
    plan = await strategist.create_plan(intel, portfolio)
    
    print(f"\nTrading Plan:")
    print(f"  Trades: {len(plan.trades)}")
    if plan.trades:
        trade = plan.trades[0]
        print(f"  Action: {trade.action}")
        print(f"  Confidence: {trade.confidence:.2f}")
        print(f"  Size %: {trade.size_pct:.2f}")
        print(f"  Reasoning: {trade.reasoning}")
        
        # Check if trade would pass risk check
        would_trade = trade.confidence >= risk_config.min_confidence
        print(f"\n  Would Execute: {'YES' if would_trade else 'NO'}")
        print(f"  Trade confidence ({trade.confidence:.2f}) {'≥' if would_trade else '<'} min required ({risk_config.min_confidence:.2f})")

async def main():
    """Run all tests"""
    await test_configuration()

if __name__ == "__main__":
    asyncio.run(main())