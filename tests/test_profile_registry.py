"""Tests for the shared investment profile registry."""

import pytest

from shared.config.profile_registry import (
    CANONICAL_PROFILES,
    PROFILE_ALIASES,
    VALID_PROFILE_NAMES,
    is_valid_profile_name,
    normalize_profile_name,
)


@pytest.mark.parametrize(
    ("raw_name", "canonical"),
    [
        ("conservative", "conservative"),
        ("balanced", "balanced"),
        ("aggressive", "aggressive"),
        ("passive", "passive"),
        ("fof", "fof"),
        ("macro_tactical", "macro_tactical"),
        ("tactical_allocation", "macro_tactical"),
        ("fundamental_value", "fundamental_value"),
        ("value", "fundamental_value"),
        ("behavioral_momentum", "behavioral_momentum"),
        ("momentum", "behavioral_momentum"),
        ("equal_weight_index", "equal_weight_index"),
        ("equal_weight", "equal_weight_index"),
        ("ewi", "equal_weight_index"),
        ("smart_beta_passive", "smart_beta_passive"),
        ("smart_beta", "smart_beta_passive"),
    ],
)
def test_profile_aliases_normalize_to_canonical_names(raw_name: str, canonical: str):
    assert normalize_profile_name(raw_name) == canonical
    assert PROFILE_ALIASES[raw_name] == canonical
    assert raw_name in VALID_PROFILE_NAMES
    assert canonical in CANONICAL_PROFILES
    assert is_valid_profile_name(raw_name)


def test_profile_normalization_is_case_and_whitespace_tolerant():
    assert normalize_profile_name(" Momentum ") == "behavioral_momentum"
    assert normalize_profile_name(" EWI ") == "equal_weight_index"


def test_unknown_profile_falls_back_to_default():
    assert normalize_profile_name("unknown") == "balanced"
    assert normalize_profile_name("unknown", default="macro_tactical") == "macro_tactical"
    assert not is_valid_profile_name("unknown")
