#!/usr/bin/env python3
"""
Test threshold configuration without external dependencies.
"""

import sys
import os
from unittest.mock import Mock

# Add the deepfund/src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'deepfund', 'src'))

# Mock dependencies before importing
sys.modules['loguru'] = Mock()
sys.modules['loguru'].logger = Mock()
sys.modules['supabase'] = Mock()
sys.modules['database'] = Mock()
sys.modules['database.supabase_helper'] = Mock()
sys.modules['database.sqlite_helper'] = Mock()

# Direct import from threshold_config module
import importlib.util
spec = importlib.util.spec_from_file_location(
    "threshold_config",
    os.path.join(os.path.dirname(__file__), '..', 'deepfund', 'src', 'util', 'threshold_config.py')
)
threshold_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(threshold_config)

ThresholdConfig = threshold_config.ThresholdConfig
get_threshold_config = threshold_config.get_threshold_config
reset_threshold_config = threshold_config.reset_threshold_config

print("=" * 60)
print("Testing Threshold Configuration")
print("=" * 60)

# Test 1: Basic loading
config = ThresholdConfig()
tech = config.get_thresholds("technical")
assert tech["trend"]["short"] == 8, "Trend short should be 8"
assert tech["trend"]["medium"] == 21, "Trend medium should be 21"
assert tech["trend"]["long"] == 55, "Trend long should be 55"
assert tech["rsi"]["period"] == 14, "RSI period should be 14"
assert tech["rsi"]["bullish"] == 30, "RSI bullish should be 30"
assert tech["rsi"]["bearish"] == 70, "RSI bearish should be 70"
print("✅ Technical thresholds correct")

# Test 2: Policy thresholds
policy = config.get_thresholds("policy")
assert policy["news_count"] == 10, "Policy news_count should be 10"
print("✅ Policy thresholds correct")

# Test 3: Company news thresholds
cn = config.get_thresholds("company_news")
assert cn["news_count"] == 10, "Company news news_count should be 10"
print("✅ Company news thresholds correct")

# Test 4: Insider thresholds
insider = config.get_thresholds("insider")
assert insider["num_trades"] == 10, "Insider num_trades should be 10"
print("✅ Insider thresholds correct")

# Test 5: Unknown analyst returns default
unknown = config.get_thresholds("unknown")
assert "news_count" in unknown, "Unknown analyst should return default"
print("✅ Unknown analyst returns default")

# Test 6: Validation
assert config.validate() is True, "Config should be valid"
print("✅ Config validation passes")

# Test 7: Singleton
reset_threshold_config()
config1 = get_threshold_config()
config2 = get_threshold_config()
assert config1 is config2, "Should return same instance"
print("✅ Singleton works correctly")

print("\n" + "=" * 60)
print("All threshold config tests passed!")
print("=" * 60)
