"""
Tests for Threshold Configuration System
=========================================

Tests the centralized threshold configuration loading and validation.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
import yaml
import sys
import os

# Add the deepfund/src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'deepfund', 'src'))

# Import threshold_config (depends only on yaml + loguru, both core deps)
from util.threshold_config import (
    ThresholdConfig,
    get_threshold_config,
    reset_threshold_config
)


class TestThresholdConfig:
    """Tests for ThresholdConfig class."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_threshold_config()

    def test_default_config_loading(self):
        """Test that config loads from default path."""
        config = ThresholdConfig()
        thresholds = config.get_thresholds("technical")

        # Check structure
        assert "trend" in thresholds
        assert "rsi" in thresholds
        assert "volatility" in thresholds

    def test_get_technical_thresholds(self):
        """Test technical analyst thresholds."""
        config = ThresholdConfig()
        tech = config.get_thresholds("technical")

        # Trend thresholds
        assert tech["trend"]["short"] == 8
        assert tech["trend"]["medium"] == 21
        assert tech["trend"]["long"] == 55

        # RSI thresholds
        assert tech["rsi"]["period"] == 14
        assert tech["rsi"]["bullish"] == 30
        assert tech["rsi"]["bearish"] == 70

        # Mean reversion thresholds
        assert tech["mean_reversion"]["bollinger_window"] == 20
        assert tech["mean_reversion"]["rolling_window"] == 50
        assert tech["mean_reversion"]["z_score_extreme"] == 2.0

    def test_get_policy_thresholds(self):
        """Test policy analyst thresholds."""
        config = ThresholdConfig()
        policy = config.get_thresholds("policy")

        assert policy["news_count"] == 10

    def test_get_company_news_thresholds(self):
        """Test company news analyst thresholds."""
        config = ThresholdConfig()
        cn = config.get_thresholds("company_news")

        assert cn["news_count"] == 10

    def test_get_insider_thresholds(self):
        """Test insider analyst thresholds."""
        config = ThresholdConfig()
        insider = config.get_thresholds("insider")

        assert insider["num_trades"] == 10

    def test_get_unknown_analyst_returns_default(self):
        """Test that unknown analyst returns default thresholds."""
        config = ThresholdConfig()
        unknown = config.get_thresholds("unknown_analyst")

        # Should return default thresholds
        assert "news_count" in unknown
        assert unknown["news_count"] == 10

    def test_get_all_thresholds(self):
        """Test getting all thresholds."""
        config = ThresholdConfig()
        all_thresholds = config.get_all_thresholds()

        assert "technical" in all_thresholds
        assert "policy" in all_thresholds
        assert "company_news" in all_thresholds
        assert "insider" in all_thresholds
        assert "default" in all_thresholds

    def test_validate_config(self):
        """Test configuration validation."""
        config = ThresholdConfig()
        assert config.validate() is True

    def test_invalid_rsi_thresholds(self):
        """Test validation catches invalid RSI thresholds."""
        config = ThresholdConfig()

        # Manually set invalid RSI
        config._config["technical"]["rsi"]["bullish"] = 75  # Higher than bearish
        config._config["technical"]["rsi"]["bearish"] = 70

        assert config.validate() is False

    def test_rsi_out_of_range(self):
        """Test validation catches RSI out of range."""
        config = ThresholdConfig()

        # Set RSI out of valid range
        config._config["technical"]["rsi"]["bullish"] = -10

        assert config.validate() is False

    def test_custom_config_path(self):
        """Test loading from custom config path."""
        # Create a mock config
        mock_config = {
            "technical": {"trend": {"short": 5, "medium": 10, "long": 20}},
            "default": {"news_count": 5}
        }

        with patch("builtins.open", mock_open(read_data=yaml.dump(mock_config))):
            with patch.object(Path, "exists", return_value=True):
                config = ThresholdConfig(config_path="/custom/path.yaml")
                tech = config.get_thresholds("technical")

                assert tech["trend"]["short"] == 5
                assert tech["trend"]["medium"] == 10

    def test_missing_config_uses_defaults(self):
        """Test that missing config file uses defaults."""
        with patch.object(Path, "exists", return_value=False):
            config = ThresholdConfig(config_path="/nonexistent/path.yaml")

            # Should still have default values
            tech = config.get_thresholds("technical")
            assert tech["trend"]["short"] == 8

    def test_singleton_instance(self):
        """Test that get_threshold_config returns singleton."""
        config1 = get_threshold_config()
        config2 = get_threshold_config()

        assert config1 is config2

    def test_reload(self):
        """Test config reload functionality."""
        config = ThresholdConfig()

        # Get initial thresholds
        initial_tech = config.get_thresholds("technical")

        # Reload
        config.reload()

        # Should still have same structure
        reloaded_tech = config.get_thresholds("technical")
        assert reloaded_tech == initial_tech

    def test_get_config_path(self):
        """Test getting config path."""
        config = ThresholdConfig()
        path = config.get_config_path()

        assert isinstance(path, Path)
        assert "analyst_thresholds.yaml" in str(path)


class TestThresholdConfigEdgeCases:
    """Edge case tests for threshold config."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_threshold_config()

    def test_empty_analyst_key(self):
        """Test empty analyst key returns default."""
        config = ThresholdConfig()
        result = config.get_thresholds("")

        # Should return default
        assert "news_count" in result

    def test_none_config_after_load(self):
        """Test handling of None config."""
        config = ThresholdConfig()
        config._config = None

        result = config.get_thresholds("technical")
        assert result == {}

    def test_yaml_parse_error(self):
        """Test handling of YAML parse error."""
        with patch("builtins.open", mock_open(read_data="invalid: yaml: ::")):
            with patch.object(Path, "exists", return_value=True):
                config = ThresholdConfig(config_path="/bad/path.yaml")

                # Should fall back to defaults
                tech = config.get_thresholds("technical")
                assert tech["trend"]["short"] == 8


class TestThresholdConfigValues:
    """Test that all expected threshold values are present."""

    def test_technical_all_values(self):
        """Test all technical threshold values."""
        config = ThresholdConfig()
        tech = config.get_thresholds("technical")

        # Trend
        assert tech["trend"]["short"] == 8
        assert tech["trend"]["medium"] == 21
        assert tech["trend"]["long"] == 55

        # Mean reversion
        assert tech["mean_reversion"]["bollinger_window"] == 20
        assert tech["mean_reversion"]["rolling_window"] == 50
        assert tech["mean_reversion"]["z_score_extreme"] == 2.0
        assert tech["mean_reversion"]["bb_position_threshold"] == 0.2

        # RSI
        assert tech["rsi"]["period"] == 14
        assert tech["rsi"]["bullish"] == 30
        assert tech["rsi"]["bearish"] == 70

        # Volatility
        assert tech["volatility"]["bullish"] == 0.8
        assert tech["volatility"]["bearish"] == 1.2

        # Volume
        assert tech["volume"]["trend"] == 20
        assert tech["volume"]["correlation"] == 20
        assert tech["volume"]["unusual_volume"] == 2.0

        # Support/Resistance
        assert tech["support_resistance"]["pivot_window"] == 5
        assert tech["support_resistance"]["lookback_period"] == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
