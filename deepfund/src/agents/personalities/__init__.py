"""
Investment personality definitions for DeepFund.

Each personality defines a distinct investment style with different risk tolerances,
position sizing strategies, and trading frequencies.
"""

from typing import TypedDict

from shared.config.profile_registry import PROFILE_ALIASES


class Personality(TypedDict):
    """Definition of an investment personality."""
    risk_tolerance: str  # low, medium, high
    max_position_ratio: float  # Maximum position size (0.0 to 1.0)
    trading_frequency: str  # low, medium, high
    description: str  # Brief description of the personality


# Personality definitions
CONSERVATIVE: Personality = {
    "risk_tolerance": "low",
    "max_position_ratio": 0.2,
    "trading_frequency": "low",
    "description": "Capital preservation focused. Low risk tolerance with small positions and quick exits on weakness."
}

AGGRESSIVE: Personality = {
    "risk_tolerance": "high",
    "max_position_ratio": 0.5,
    "trading_frequency": "high",
    "description": "Growth oriented. High risk tolerance seeking maximum returns with larger positions and higher trading frequency."
}

PASSIVE: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.33,
    "trading_frequency": "low",
    "description": "Index-style passive investing. Follows market trends with minimal trading and periodic rebalancing."
}

BALANCED: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.33,
    "trading_frequency": "medium",
    "description": "Balanced approach with moderate risk. Default investment style balancing growth and stability."
}

SMART_BETA_PASSIVE: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.33,
    "trading_frequency": "low",
    "description": "Smart Beta index enhancement strategy. Uses quantitative factor models to enhance returns while maintaining low tracking error to benchmark."
}

FOF: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.15,
    "trading_frequency": "low",
    "description": "Fund-of-funds meta allocator. Diversifies across multiple personality sleeves and emphasizes drawdown control over single-style conviction."
}

MACRO_TACTICAL: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.2,
    "trading_frequency": "medium",
    "description": "Macro-tactical allocation paradigm scaffold. Applies top-down regime-aware sleeve tilts over a diversified FOF-style allocation base."
}

FUNDAMENTAL_VALUE: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.25,
    "trading_frequency": "low",
    "description": "Fundamental value paradigm scaffold. Emphasizes valuation discipline, balance-sheet quality, and lower-turnover accumulation pending dedicated value filters."
}

BEHAVIORAL_MOMENTUM: Personality = {
    "risk_tolerance": "high",
    "max_position_ratio": 0.4,
    "trading_frequency": "high",
    "description": "Behavioral momentum paradigm scaffold. Emphasizes trend, sentiment, and narrative-driven positioning pending dedicated volatility scaling and crash controls."
}

EQUAL_WEIGHT_INDEX: Personality = {
    "risk_tolerance": "medium",
    "max_position_ratio": 0.02,  # 1/50 = 0.02 for 50 stocks equal weight
    "trading_frequency": "low",  # Only rebalance semi-annually
    "description": "Strict equal-weight index tracker. Pure passive strategy that maintains equal weight across all constituents, rebalances semi-annually (June/December), minimizes tracking error. No subjective analysis or market timing."
}


# Canonical personality/profile registry
_CANONICAL_PERSONALITIES: dict[str, Personality] = {
    "conservative": CONSERVATIVE,
    "aggressive": AGGRESSIVE,
    "passive": PASSIVE,
    "balanced": BALANCED,
    "fof": FOF,
    "macro_tactical": MACRO_TACTICAL,
    "fundamental_value": FUNDAMENTAL_VALUE,
    "behavioral_momentum": BEHAVIORAL_MOMENTUM,
    "smart_beta_passive": SMART_BETA_PASSIVE,
    "equal_weight_index": EQUAL_WEIGHT_INDEX,
}
PERSONALITIES: dict[str, Personality] = {
    alias: _CANONICAL_PERSONALITIES[canonical]
    for alias, canonical in PROFILE_ALIASES.items()
    if canonical in _CANONICAL_PERSONALITIES
}


def get_personality(personality_name: str) -> Personality:
    """
    Get a personality definition by name.

    Args:
        personality_name: Name of the personality (conservative, aggressive, passive, balanced)

    Returns:
        Personality definition dictionary

    Raises:
        ValueError: If personality name is not found
    """
    personality_name = personality_name.lower()
    if personality_name not in PERSONALITIES:
        valid_names = ", ".join(PERSONALITIES.keys())
        raise ValueError(
            f"Unknown personality: {personality_name}. "
            f"Valid options are: {valid_names}"
        )
    return PERSONALITIES[personality_name]


def list_personalities() -> list[str]:
    """Return a list of available personality names."""
    return list(PERSONALITIES.keys())
