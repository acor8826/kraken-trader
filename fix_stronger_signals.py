#!/usr/bin/env python3
"""
Additional fix to make technical analyst generate stronger signals.
The initial fix wasn't aggressive enough - signals are too weak (+0.03).
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

def enhance_technical_signals():
    """Make technical analyst generate much stronger signals"""
    filepath = "agents/analysts/technical/basic.py"
    backup_file(filepath)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Make SMA crossover signals stronger
    content = content.replace(
        'signals.append(("sma", 0.5 + strength * 0.5, 0.3))',
        'signals.append(("sma", 0.7 + strength * 0.3, 0.35))'  # Stronger base signal
    )
    content = content.replace(
        'signals.append(("sma", -0.5 - strength * 0.5, 0.3))',
        'signals.append(("sma", -0.7 - strength * 0.3, 0.35))'
    )
    
    # Make price vs SMA signals stronger
    content = content.replace(
        'signals.append(("price_sma", 0.3 + strength * 0.4, 0.2))',
        'signals.append(("price_sma", 0.5 + strength * 0.5, 0.25))'
    )
    content = content.replace(
        'signals.append(("price_sma", -0.3 - strength * 0.4, 0.2))',
        'signals.append(("price_sma", -0.5 - strength * 0.5, 0.25))'
    )
    
    # Increase momentum scaling from /6 to /3 (double the strength)
    content = content.replace(
        'signals.append(("momentum", momentum / 6, 0.1))',
        'signals.append(("momentum", momentum / 3, 0.15))'  # Double strength, more weight
    )
    
    # Increase analyst weight to 50% (from 40%)
    content = content.replace(
        'self._weight = 0.40  # 40% weight in fusion',
        'self._weight = 0.50  # 50% weight in fusion'
    )
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("[DONE] Enhanced technical signals to be much stronger")

def fix_strategist_prompts():
    """Adjust strategist prompts to be more decisive"""
    filepath = "agents/strategist/simple.py"
    backup_file(filepath)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Update the system prompt to be more aggressive
    old_prompt = '''Decision Rules:
- Analyst direction > +0.2 with confidence > 0.50: RECOMMEND BUY
- Analyst direction < -0.2 with confidence > 0.50: RECOMMEND SELL
- Otherwise: HOLD'''
    
    new_prompt = '''Decision Rules:
- Analyst direction > +0.15 with confidence > 0.45: RECOMMEND BUY
- Analyst direction < -0.15 with confidence > 0.45: RECOMMEND SELL
- Otherwise: HOLD

Trading Philosophy:
- Take decisive action on clear signals
- Don't overthink - the risk layer will protect us
- Size positions aggressively within risk limits
- Momentum is your friend - ride trends'''
    
    content = content.replace(old_prompt, new_prompt)
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("[DONE] Updated strategist to be more decisive")

def main():
    """Apply enhanced fixes"""
    print("Applying enhanced fixes for stronger trading signals...")
    print("=" * 60)
    
    # Change to kraken-trader directory
    os.chdir(r"C:\Users\acor8\OneDrive\Documents\GitHub\kraken-trader")
    
    # Apply fixes
    enhance_technical_signals()
    fix_strategist_prompts()
    
    print("\n" + "=" * 60)
    print("[DONE] Enhanced fixes applied!")
    print("\nChanges made:")
    print("- Technical analyst now generates signals 2x stronger")
    print("- SMA crossover base signal: 0.7 (was 0.5)")
    print("- Price vs SMA base signal: 0.5 (was 0.3)")
    print("- Momentum scaling doubled (÷3 instead of ÷6)")
    print("- Analyst weight increased to 50%")
    print("- Strategist thresholds lowered to ±0.15")
    print("- Strategist confidence threshold: 0.45")

if __name__ == "__main__":
    main()