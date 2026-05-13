"""Canonical investment profile names and legacy aliases."""

from __future__ import annotations

from typing import Optional


PROFILE_ALIASES: dict[str, str] = {
    "conservative": "conservative",
    "balanced": "balanced",
    "aggressive": "aggressive",
    "passive": "passive",
    "fof": "fof",
    "macro_tactical": "macro_tactical",
    "tactical_allocation": "macro_tactical",
    "fundamental_value": "fundamental_value",
    "value": "fundamental_value",
    "behavioral_momentum": "behavioral_momentum",
    "momentum": "behavioral_momentum",
    "equal_weight_index": "equal_weight_index",
    "equal_weight": "equal_weight_index",
    "ewi": "equal_weight_index",
    "smart_beta_passive": "smart_beta_passive",
    "smart_beta": "smart_beta_passive",
}

CANONICAL_PROFILES: tuple[str, ...] = tuple(dict.fromkeys(PROFILE_ALIASES.values()))
VALID_PROFILE_NAMES: tuple[str, ...] = tuple(PROFILE_ALIASES.keys())


def normalize_profile_name(profile: Optional[str], *, default: str = "balanced") -> str:
    """Normalize a profile or legacy personality alias to its canonical name."""
    default_name = PROFILE_ALIASES.get(default.strip().lower(), "balanced")
    name = (profile or default_name).strip().lower()
    return PROFILE_ALIASES.get(name, default_name)


def is_valid_profile_name(profile: Optional[str]) -> bool:
    """Return whether a raw profile name or alias is recognized."""
    if profile is None:
        return False
    return profile.strip().lower() in PROFILE_ALIASES
