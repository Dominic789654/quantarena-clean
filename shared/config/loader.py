"""
Shared configuration loader for QuantArena.

This module provides a unified way to load configuration from YAML files
and environment variables, supporting both DeepEar and DeepFund components.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml
from dotenv import load_dotenv


class ConfigLoader:
    """
    Configuration loader that supports YAML files and environment variables.

    Features:
    - Load configuration from YAML files
    - Override values with environment variables
    - Provide default values for missing settings
    - Support for multiple configuration profiles
    """

    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        env_file: Optional[Union[str, Path]] = None,
        profile: Optional[str] = None,
    ):
        """
        Initialize the configuration loader.

        Args:
            config_path: Path to the YAML configuration file.
                        If None, looks for unified_config.yaml in default locations.
            env_file: Path to the .env file. If None, searches for .env in default locations.
            profile: Configuration profile to use (for multiple environments).
        """
        self._config: Dict[str, Any] = {}
        self._env_vars: Dict[str, str] = {}

        # Load environment variables
        self._load_env_vars(env_file)

        # Load configuration
        if config_path is None:
            config_path = self._find_config_file()
        self._load_yaml_config(config_path)

        # Apply profile if specified
        if profile:
            self._apply_profile(profile)

    def _find_config_file(self) -> Path:
        """Find the configuration file in default locations."""
        # Default locations to search
        default_locations = [
            Path.cwd() / "unified_config.yaml",
            Path.cwd() / "config" / "unified_config.yaml",
            Path(__file__).parent / "unified_config.yaml",
            Path.home() / ".config" / "quantarena" / "config.yaml",
        ]

        for location in default_locations:
            if location.exists():
                return location

        # Return the first default location even if it doesn't exist
        # (will raise an error when loading)
        return default_locations[0]

    def _load_env_vars(self, env_file: Optional[Union[str, Path]]) -> None:
        """Load environment variables from .env file and system environment."""
        if env_file is None:
            # Search for .env in default locations
            default_locations = [
                Path.cwd() / ".env",
                Path.cwd() / ".env.local",
                Path(__file__).parent.parent.parent / ".env",
            ]
            for location in default_locations:
                if location.exists():
                    env_file = location
                    break

        if env_file:
            load_dotenv(env_file)

        # Store all environment variables
        self._env_vars = dict(os.environ)

    def _load_yaml_config(self, config_path: Union[str, Path]) -> None:
        """Load configuration from YAML file."""
        config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f) or {}

    def _apply_profile(self, profile: str) -> None:
        """Apply a configuration profile if defined."""
        profiles = self._config.get("profiles", {})
        if profile in profiles:
            profile_config = profiles[profile]
            self._config = self._merge_dicts(self._config, profile_config)

    @staticmethod
    def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigLoader._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key path.

        Supports nested keys using dot notation, e.g., "llm.reasoning_model.provider".

        Args:
            key: Configuration key (supports dot notation for nested keys)
            default: Default value if key is not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_with_env_override(
        self,
        key: str,
        env_key: Optional[str] = None,
        default: Any = None,
    ) -> Any:
        """
        Get a configuration value with environment variable override.

        Args:
            key: Configuration key (supports dot notation)
            env_key: Environment variable key. If None, generates from key.
            default: Default value if not found

        Returns:
            Configuration value from env var or config file
        """
        # Check environment variable first
        if env_key is None:
            # Generate env key from config key (e.g., "llm.reasoning_model.provider" -> "LLM_REASONING_MODEL_PROVIDER")
            env_key = key.replace(".", "_").upper()

        env_value = self._env_vars.get(env_key)
        if env_value is not None:
            # Try to parse as YAML for type conversion
            try:
                return yaml.safe_load(env_value)
            except yaml.YAMLError:
                return env_value

        # Fall back to config file
        return self.get(key, default)

    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration with environment variable overrides."""
        return {
            "reasoning_model": {
                "provider": self.get_with_env_override("llm.reasoning_model.provider", "REASONING_MODEL_PROVIDER"),
                "model_id": self.get_with_env_override("llm.reasoning_model.model_id", "REASONING_MODEL_ID"),
                "host": self.get_with_env_override("llm.reasoning_model.host", "REASONING_MODEL_HOST"),
                "api_key": self.get_env_var(
                    self.get("llm.reasoning_model.api_key_env", "OPENAI_API_KEY")
                ),
            },
            "tool_model": {
                "provider": self.get_with_env_override("llm.tool_model.provider", "TOOL_MODEL_PROVIDER"),
                "model_id": self.get_with_env_override("llm.tool_model.model_id", "TOOL_MODEL_ID"),
                "host": self.get_with_env_override("llm.tool_model.host", "TOOL_MODEL_HOST"),
                "api_key": self.get_env_var(
                    self.get("llm.tool_model.api_key_env", "")
                ),
            },
        }

    def get_data_source_config(self, source: str) -> Dict[str, Any]:
        """Get configuration for a specific data source."""
        config = self.get(f"data_sources.{source}", {})
        if not config:
            return {"enabled": False}

        # Add API key from environment if configured
        api_key_env = config.get("api_key_env")
        if api_key_env:
            config["api_key"] = self.get_env_var(api_key_env)

        return config

    def get_deepear_config(self) -> Dict[str, Any]:
        """Get DeepEar-specific configuration."""
        return {
            "enabled": self.get("deepear.enabled", True),
            "sources": self.get("deepear.sources", {}),
            "news_per_source": self.get("deepear.news_per_source", 10),
            "isq_template": self.get("deepear.isq_template", "default_isq_v1"),
            "sentiment": {
                "mode": self.get("deepear.sentiment.mode", "auto"),
                "bert_model": self.get("deepear.sentiment.bert_model", "uer/roberta-base-finetuned-chinanews-chinese"),
            },
            "search": {
                "embedding_model": self.get("deepear.search.embedding_model", "paraphrase-multilingual-MiniLM-L12-v2"),
                "cache_ttl": self.get("deepear.search.cache_ttl", 3600),
                "jina_api_key": self.get_env_var("JINA_API_KEY"),
            },
            "server": {
                "default_port": self.get("deepear.server.default_port", 8001),
                "instances": self.get("deepear.server.instances", 1),
            },
        }

    def get_deepfund_config(self) -> Dict[str, Any]:
        """Get DeepFund-specific configuration."""
        return {
            "enabled": self.get("deepfund.enabled", True),
            "personality": self.get("deepfund.personality", "balanced"),
            "max_position_ratio": self.get("deepfund.max_position_ratio", 0.33),
            "cashflow": self.get("deepfund.cashflow", 100000),
            "trading_frequency": self.get("deepfund.trading_frequency", "medium"),
            "workflow_analysts": self.get("deepfund.workflow_analysts", []),
            "tickers": self.get("deepfund.tickers", []),
        }

    def get_database_config(self) -> Dict[str, Any]:
        """Get database configuration."""
        return {
            "local": {
                "enabled": self.get("database.local.enabled", True),
                "path": self.get("database.local.path", "data/unified_trading.db"),
            },
            "supabase": {
                "enabled": self.get("database.supabase.enabled", False),
                "url": self.get_env_var(self.get("database.supabase.url_env", "SUPABASE_URL")),
                "key": self.get_env_var(self.get("database.supabase.key_env", "SUPABASE_KEY")),
            },
        }

    def get_env_var(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get an environment variable value."""
        return self._env_vars.get(key, default)

    @property
    def config(self) -> Dict[str, Any]:
        """Get the full configuration dictionary."""
        return self._config.copy()

    @property
    def env_vars(self) -> Dict[str, str]:
        """Get all environment variables."""
        return self._env_vars.copy()

    def __repr__(self) -> str:
        return f"ConfigLoader(config={len(self._config)} keys, env={len(self._env_vars)} vars)"


# Global configuration instance (lazy loaded)
_global_config: Optional[ConfigLoader] = None


def load_config(
    config_path: Optional[Union[str, Path]] = None,
    env_file: Optional[Union[str, Path]] = None,
    profile: Optional[str] = None,
    force_reload: bool = False,
) -> ConfigLoader:
    """
    Load or get the global configuration instance.

    Args:
        config_path: Path to the configuration file
        env_file: Path to the .env file
        profile: Configuration profile to use
        force_reload: Force reload configuration even if already loaded

    Returns:
        ConfigLoader instance
    """
    global _global_config

    if _global_config is None or force_reload:
        _global_config = ConfigLoader(config_path, env_file, profile)

    return _global_config


def get_env_vars() -> Dict[str, str]:
    """
    Get all environment variables from the current configuration.

    Returns:
        Dictionary of environment variables
    """
    config = load_config()
    return config.env_vars


def get_env_var(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get a specific environment variable.

    Args:
        key: Environment variable name
        default: Default value if not found

    Returns:
        Environment variable value or default
    """
    return os.getenv(key, default)


# Convenience functions for common configurations

def get_llm_config() -> Dict[str, Any]:
    """Get LLM configuration."""
    return load_config().get_llm_config()


def get_data_source_config(source: str) -> Dict[str, Any]:
    """Get configuration for a specific data source."""
    return load_config().get_data_source_config(source)


def get_deepear_config() -> Dict[str, Any]:
    """Get DeepEar configuration."""
    return load_config().get_deepear_config()


def get_deepfund_config() -> Dict[str, Any]:
    """Get DeepFund configuration."""
    return load_config().get_deepfund_config()


def get_database_config() -> Dict[str, Any]:
    """Get database configuration."""
    return load_config().get_database_config()
