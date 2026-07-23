#!/usr/bin/env python
"""
Smart Beta Simple Test - Minimal Dependencies

This test verifies core Smart Beta components without requiring
the full deepfund/backtest stack to be initialized.
"""

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

def main():
    """Test core Smart Beta components."""
    print("=" * 60)
    print("Smart Beta Simple Test")
    print("=" * 60)

    errors = []

    # Test 1: Configuration
    print("\n1. Testing Smart Beta Configuration...")
    try:
        from smart_beta.config import SmartBetaConfig
        config = SmartBetaConfig(index_code="000300.SH")
        config.validate()
        print(f"   ✓ Config: {config.index_code}, rebalancing={config.rebalance_frequency}")
    except Exception as e:
        errors.append(f"Config: {e}")
        print(f"   ✗ Config failed: {e}")

    # Test 2: Factor Data
    print("\n2. Testing Factor Data...")
    try:
        from smart_beta.factor_engine import FactorData
        fd = FactorData(
            ticker="600519.SH",
            trade_date=datetime.now(),
            dimson_beta=1.05,
            downside_beta=0.85,
            ivol=0.18,
            amihud=0.002,
            is_valid=True
        )
        print(f"   ✓ FactorData created for {fd.ticker}")
    except Exception as e:
        errors.append(f"FactorData: {e}")
        print(f"   ✗ FactorData failed: {e}")

    # Test 3: Macro States
    print("\n3. Testing Macro States...")
    try:
        from smart_beta.macro_analyzer import MacroState
        for state in [MacroState.EXPANSION, MacroState.SLOWDOWN, MacroState.RECESSION, MacroState.RECOVERY]:
            print(f"   ✓ Macro state: {state.value}")
    except Exception as e:
        errors.append(f"MacroState: {e}")
        print(f"   ✗ MacroState failed: {e}")

    # Test 4: Freeze Status
    print("\n4. Testing Freeze Status...")
    try:
        from smart_beta.news_freeze import FreezeStatus, FreezeReason
        status = FreezeStatus.ACTIVE
        reason = FreezeReason.MARKET_DROP
        print(f"   ✓ Freeze status: {status.value}, reason: {reason.value}")
    except Exception as e:
        errors.append(f"Freeze: {e}")
        print(f"   ✗ Freeze failed: {e}")

    # Summary
    print("\n" + "=" * 60)
    if not errors:
        print("✅ All core Smart Beta components are available!")
        return 0
    else:
        print(f"⚠️ {len(errors)} component(s) failed:")
        for err in errors:
            print(f"   - {err}")
        return 1

if __name__ == "__main__":
    exit(main())
