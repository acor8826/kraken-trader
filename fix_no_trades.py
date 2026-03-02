#!/usr/bin/env python3
"""
Fix for Kraken Trader bot not executing trades.

This script:
1. Enables aggressive risk profile for more trading opportunities
2. Adjusts technical analyst to generate stronger signals
3. Lowers strategist thresholds to allow more trades
"""

import os
import shutil
from datetime import datetime

def backup_file(filepath):
    """Create a backup of the file before modifying"""
    backup_path = f"{filepath}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(filepath, backup_path)
    print(f"Backed up {filepath} to {backup_path}")
    return backup_path

def fix_technical_analyst():
    """Make technical analyst generate stronger signals"""
    filepath = "agents/analysts/technical/basic.py"
    backup_file(filepath)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Lower momentum thresholds from 3% to 1.5%
    content = content.replace(
        "if momentum > 3:",
        "if momentum > 1.5:"
    )
    content = content.replace(
        "elif momentum < -3:",
        "elif momentum < -1.5:"
    )
    
    # Increase signal strength for momentum
    content = content.replace(
        'signals.append(("momentum", 0.5, 0.15))',
        'signals.append(("momentum", 0.7, 0.20))'  # Stronger signal, higher weight
    )
    content = content.replace(
        'signals.append(("momentum", -0.5, 0.15))',
        'signals.append(("momentum", -0.7, 0.20))'
    )
    
    # Lower RSI thresholds slightly (from 30/70 to 35/65)
    content = content.replace(
        "if rsi < 30:",
        "if rsi < 35:"
    )
    content = content.replace(
        "elif rsi > 70:",
        "elif rsi > 65:"
    )
    
    # Increase confidence calculation
    old_confidence = "confidence = min(0.9, avg_magnitude * 0.5 + agreement * 0.5 + 0.2)"
    new_confidence = "confidence = min(0.95, avg_magnitude * 0.6 + agreement * 0.4 + 0.25)"
    content = content.replace(old_confidence, new_confidence)
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("[DONE] Fixed technical analyst to generate stronger signals")

def fix_strategist_thresholds():
    """Lower strategist decision thresholds"""
    filepath = "agents/strategist/simple.py"
    backup_file(filepath)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Lower direction thresholds from ±0.3 to ±0.2
    content = content.replace(
        "Analyst direction > +0.3 with confidence > 0.55",
        "Analyst direction > +0.2 with confidence > 0.50"
    )
    content = content.replace(
        "Analyst direction < -0.3 with confidence > 0.55",
        "Analyst direction < -0.2 with confidence > 0.50"
    )
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("[DONE] Lowered strategist decision thresholds")

def enable_aggressive_risk():
    """Create docker-compose override to enable aggressive risk profile"""
    override_content = """version: '3.8'

services:
  kraken_trader:
    environment:
      - RISK_PROFILE=aggressive
      - LOG_LEVEL=INFO
      # Override check interval for faster trading cycles
      - CHECK_INTERVAL_MINUTES=30  # Check every 30 minutes instead of 60
"""
    
    with open("docker-compose.override.yml", 'w') as f:
        f.write(override_content)
    
    print("[DONE] Created docker-compose.override.yml with aggressive risk profile")

def create_env_aggressive():
    """Create .env.aggressive file for local testing"""
    env_content = """# Aggressive trading configuration for testing
RISK_PROFILE=aggressive
CHECK_INTERVAL_MINUTES=30
LOG_LEVEL=INFO
SIMULATION_MODE=true

# Stage 1 for simpler logic
STAGE=stage1

# Add your API keys here when ready for real trading
# KRAKEN_API_KEY=your_key_here
# KRAKEN_API_SECRET=your_secret_here
# ANTHROPIC_API_KEY=your_key_here
"""
    
    with open(".env.aggressive", 'w') as f:
        f.write(env_content)
    
    print("[DONE] Created .env.aggressive for local testing")

def main():
    """Apply all fixes"""
    print("Fixing Kraken Trader bot to enable trading...")
    print("=" * 60)
    
    # Change to kraken-trader directory
    os.chdir(r"C:\Users\acor8\OneDrive\Documents\GitHub\kraken-trader")
    
    # Apply fixes
    fix_technical_analyst()
    fix_strategist_thresholds()
    enable_aggressive_risk()
    create_env_aggressive()
    
    print("\n" + "=" * 60)
    print("[DONE] All fixes applied successfully!")
    print("\nNext steps:")
    print("1. Test locally: python main.py (uses .env.aggressive)")
    print("2. Deploy to production: gcloud builds submit --config cloudbuild.yaml")
    print("3. Monitor the bot for trading activity")
    print("\nThe bot will now:")
    print("- Use aggressive risk profile (lower min confidence)")
    print("- Generate stronger signals from technical analysis")
    print("- Have lower thresholds for trade decisions")
    print("- Check markets every 30 minutes instead of 60")

if __name__ == "__main__":
    main()