"""Shared configuration module."""
from shared.config.loader import ConfigLoader, load_config
from shared.config.profile_registry import (
    CANONICAL_PROFILES,
    PROFILE_ALIASES,
    VALID_PROFILE_NAMES,
    is_valid_profile_name,
    normalize_profile_name,
)
from shared.config.provider_routing import (
    default_us_data_provider,
    normalize_cn_data_provider,
    normalize_us_data_provider,
    preferred_us_data_provider,
)
from shared.config.validator import EnvValidator, validate_env

__all__ = [
    "CANONICAL_PROFILES",
    "ConfigLoader",
    "EnvValidator",
    "PROFILE_ALIASES",
    "VALID_PROFILE_NAMES",
    "default_us_data_provider",
    "is_valid_profile_name",
    "load_config",
    "normalize_cn_data_provider",
    "normalize_profile_name",
    "normalize_us_data_provider",
    "preferred_us_data_provider",
    "validate_env",
]
