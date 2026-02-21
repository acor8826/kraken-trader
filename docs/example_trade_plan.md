# Example Trade Plan Output

Here's what the enhanced system produces when it finds a trade opportunity:

## Real Example: BTC/AUD Trade Plan

```
📊 Trade Plan for BTC/AUD
Direction: BUY
Confidence: 82%
Market Regime: trending_up

Entry:
Buy on pullback to $95,121.87 or break above $97,043.53
Entry Range: $94,219.65 - $96,073.09

Exit Points:
Stop Loss: $91,367.00 (-3.9%)
Take Profit: $104,634.06 (+10.0%)

Position Sizing:
Position Value: $950.00
Position Size: 0.00999 BTC
Risk Amount: $20.00
Reward Target: $60.00
Risk/Reward: 1:3.0

Timing:
Timeframe: 1h
Est. Hold Time: 6:00:00
Max Hold Time: 1 day, 0:00:00
Entry Valid Until: 2026-02-21 13:40

Notes:
• Strong uptrend detected - buy pullbacks, ride the trend
• Timeframe alignment: 4/5 bullish
• ✅ Low volatility - stable conditions
```

## What Each Component Means

### Entry Section
- **Entry Trigger**: "Buy on pullback to $95,121" - Wait for price to drop to this level
- **Entry Range**: $94,219 - $96,073 - Acceptable price range for entry
- The bot will place a limit order at the optimal entry price

### Exit Points
- **Stop Loss**: $91,367 - Exit if price drops here (limits loss to $20)
- **Take Profit**: $104,634 - Exit when price reaches here (captures $60 profit)
- Percentages shown are from entry price, not current price

### Position Sizing (Based on 2% Risk)
- **Position Value**: $950 - How much AUD to spend
- **Position Size**: 0.00999 BTC - Actual amount of Bitcoin to buy
- **Risk Amount**: $20 - Maximum loss if stop hit (2% of $1,000)
- **Risk/Reward**: 1:3 - Risking $1 to make $3

### Timing
- **Est. Hold Time**: 6 hours - Typical for 1-hour timeframe trades
- **Max Hold Time**: 1 day - Force exit after this to free capital
- **Entry Valid Until**: Time when signal expires if not filled

## How the Bot Uses This

1. **Entry**: Places limit buy order at $95,121
2. **Risk Management**: Sets stop-loss order at $91,367
3. **Profit Taking**: Sets take-profit order at $104,634
4. **Time Management**: Cancels unfilled orders after expiry
5. **Position Tracking**: Monitors hold time, exits if exceeds maximum

## Market Regime Strategies

### Trending Up (Current Example)
- Entry: Buy on 1-2% pullbacks
- Stops: Wider (3-5%) to avoid noise
- Targets: Extended (8-15%) to ride trend

### Ranging
- Entry: Buy near support levels
- Stops: Tight (2-3%) below support
- Targets: Modest (5-8%) at resistance

### Volatile
- Entry: Wait for stability or use wider ranges
- Stops: Very wide (6-10%)
- Targets: Aggressive (15-25%)

### Breakout
- Entry: Buy above resistance with momentum
- Stops: Just below breakout level
- Targets: Measured moves based on pattern

## Benefits Over Simple Signals

**Old System**: "BUY BTC"
- No entry price
- Fixed 5% stop loss
- Fixed 10% take profit
- No time limits
- No position sizing

**New System**: Complete actionable plan
- Exact entry price and strategy
- Dynamic stops based on volatility
- Regime-appropriate targets
- Time-based management
- Risk-based position sizing

This is what allows the bot to actually execute trades with confidence!