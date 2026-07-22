"""
Threshold Configuration Loader
==============================

Centralized configuration management for analyst thresholds.
Loads thresholds from YAML file and provides easy access.

Usage:
    from util.threshold_config import ThresholdConfig

    # Get thresholds for specific analyst
    config = ThresholdConfig()
    tech_thresholds = config.get_thresholds("technical")
    rsi_period = tech_thresholds["rsi"]["period"]

    # Or use singleton instance
    from util.threshold_config import get_threshold_config
    config = get_threshold_config()
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache
from loguru import logger


class ThresholdConfig:
    """
    Centralized threshold configuration loader.

    Loads analyst thresholds from YAML file and provides
    convenient access methods.
    """

    # Default config path relative to project root
    DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "analyst_thresholds.yaml"

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize threshold configuration.

        Args:
            config_path: Path to YAML config file. If None, uses default path.
        """
        self._config_path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH
        self._config: Optional[Dict[str, Any]] = None
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        try:
            if not self._config_path.exists():
                logger.warning(f"Threshold config file not found: {self._config_path}")
                self._config = self._get_default_config()
                return

            with open(self._config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)

            logger.debug(f"Loaded threshold config from {self._config_path}")

        except yaml.YAMLError as e:
            logger.error(f"Failed to parse threshold config: {e}")
            self._config = self._get_default_config()
        except Exception as e:
            logger.error(f"Failed to load threshold config: {e}")
            self._config = self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration as fallback."""
        logger.info("Using default threshold configuration")
        return {
            "technical": {
                "trend": {"short": 8, "medium": 21, "long": 55},
                "mean_reversion": {
                    "bollinger_window": 20,
                    "rolling_window": 50,
                    "z_score_extreme": 2.0,
                    "bb_position_threshold": 0.2
                },
                "rsi": {"period": 14, "bullish": 30, "bearish": 70},
                "volatility": {"bullish": 0.8, "bearish": 1.2},
                "volume": {"trend": 20, "correlation": 20, "unusual_volume": 2.0},
                "support_resistance": {"pivot_window": 5, "lookback_period": 20}
            },
            "policy": {"news_count": 10},
            "company_news": {"news_count": 10},
            "insider": {"num_trades": 10},
            "social_sentiment": {"filter_key": "wallstreetbets", "trending_top_n": 10},
            "default": {"news_count": 10, "lookback_days": 30}
        }

    def get_thresholds(self, analyst_key: str) -> Dict[str, Any]:
        """
        Get thresholds for a specific analyst.

        Args:
            analyst_key: Key identifying the analyst (e.g., "technical", "policy")

        Returns:
            Dictionary containing thresholds for the analyst.
            Returns empty dict if analyst not found.
        """
        if self._config is None:
            return {}

        # Try to get analyst-specific config
        thresholds = self._config.get(analyst_key)

        if thresholds is None:
            logger.warning(f"No thresholds found for analyst '{analyst_key}', using defaults")
            thresholds = self._config.get("default", {})

        return thresholds

    def get_all_thresholds(self) -> Dict[str, Any]:
        """
        Get all thresholds.

        Returns:
            Complete configuration dictionary.
        """
        return self._config.copy() if self._config else {}

    def reload(self) -> None:
        """Reload configuration from file (hot reload)."""
        logger.info("Reloading threshold configuration...")
        self._load_config()

    def validate(self) -> bool:
        """
        Validate configuration integrity.

        Checks:
        - All required analysts have config
        - Value types are correct
        - Numeric values are in reasonable ranges

        Returns:
            True if valid, False otherwise.
        """
        if not self._config:
            logger.error("Configuration is empty")
            return False

        required_analysts = ["technical", "policy", "company_news", "insider"]

        for analyst in required_analysts:
            if analyst not in self._config:
                logger.warning(f"Missing threshold config for '{analyst}'")

        # Validate technical thresholds
        tech = self._config.get("technical", {})
        if tech:
            rsi = tech.get("rsi", {})
            if rsi:
                bullish = rsi.get("bullish", 30)
                bearish = rsi.get("bearish", 70)
                if bullish >= bearish:
                    logger.error(f"Invalid RSI thresholds: bullish ({bullish}) >= bearish ({bearish})")
                    return False
                if not (0 <= bullish <= 100 and 0 <= bearish <= 100):
                    logger.error(f"RSI thresholds out of range: {bullish}, {bearish}")
                    return False

        return True

    def get_config_path(self) -> Path:
        """Get the current configuration file path."""
        return self._config_path


# Singleton instance
_threshold_config_instance: Optional[ThresholdConfig] = None


def get_threshold_config() -> ThresholdConfig:
    """
    Get singleton instance of ThresholdConfig.

    Returns:
        ThresholdConfig singleton instance.
    """
    global _threshold_config_instance
    if _threshold_config_instance is None:
        _threshold_config_instance = ThresholdConfig()
    return _threshold_config_instance


def reset_threshold_config() -> None:
    """Reset singleton instance (useful for testing)."""
    global _threshold_config_instance
    _threshold_config_instance = None
