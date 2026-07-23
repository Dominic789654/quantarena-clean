"""
Smart Beta Configuration

Configuration for the Smart Beta Index Enhancement System.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict
import yaml
from pathlib import Path


@dataclass
class SmartBetaConfig:
    """
    Configuration for Smart Beta strategy.

    Attributes:
        index_code: Target index code (e.g., "000300.SH" for CSI 300)
        rebalance_frequency: Rebalancing frequency ("monthly" or "quarterly")
        lookback_days: Historical data lookback period for factor calculation
        ivol_percentile: IVOL percentile threshold for negative screening
        amihud_threshold: Amihud illiquidity threshold for negative screening
        tracking_error_limit: Maximum acceptable tracking error
        max_stock_weight: Maximum weight for any single stock
        turnover_limit: Maximum portfolio turnover per rebalance
        macro_adjustment_range: Range for macro-based beta adjustment
        vix_threshold: VIX threshold for news freeze mechanism
        freeze_duration_days: Duration of trading freeze in days
        risk_free_rate: Annual risk-free rate for calculations
        market_days_per_year: Trading days per year (252 for CN market)
    """

    # Index Configuration
    index_code: str = "000300.SH"  # CSI 300
    rebalance_frequency: str = "monthly"  # "monthly" or "quarterly"

    # Factor Configuration
    lookback_days: int = 252  # ~1 year of trading data
    ivol_percentile: float = 0.80  # Exclude stocks in top 20% IVOL
    amihud_threshold: float = 0.01  # Max acceptable Amihud ratio

    # Optimizer Configuration
    tracking_error_limit: float = 0.03  # 3% max tracking error
    max_stock_weight: float = 0.05  # 5% max single stock weight
    turnover_limit: float = 0.30  # 30% max turnover per rebalance
    min_weight: float = 0.001  # Minimum weight threshold

    # Downside Risk Constraints
    downside_beta_gamma: float = 0.1  # Portfolio β⁻ <= Benchmark β⁻ - γ
    require_downside_protection: bool = True

    # Macro Adjustment Configuration
    macro_adjustment_range: tuple = (-0.3, 0.3)  # Beta adjustment range
    expansion_beta_target: float = 1.1  # Beta target in expansion
    slowdown_beta_target: float = 1.0  # Beta target in slowdown
    recession_beta_target: float = 0.8  # Beta target in recession
    recovery_beta_target: float = 1.2  # Beta target in recovery

    # News Freeze Configuration
    vix_threshold: float = 30.0  # VIX level to trigger freeze
    market_drop_threshold: float = -0.05  # Single-day drop to trigger freeze
    freeze_duration_days: int = 5  # Trading freeze duration
    crisis_keywords: list = field(default_factory=lambda: [
        "crisis", "collapse", "panic", "black swan",
        "systemic risk", "credit crunch", "liquidity crisis"
    ])

    # Market Parameters
    risk_free_rate: float = 0.03  # 3% annual risk-free rate
    market_days_per_year: int = 252  # Trading days per year

    # Factor Weights (for composite scoring)
    factor_weights: Dict[str, float] = field(default_factory=lambda: {
        "dimson_beta": 0.25,
        "downside_beta": 0.25,
        "ivol": 0.25,
        "amihud": 0.25
    })

    # LLM Integration
    llm_adjustment_enabled: bool = True  # Enable LLM-based fine-tuning
    llm_weight_cap: float = 0.1  # Max 10% adjustment from LLM

    def validate(self) -> None:
        """Validate configuration parameters."""
        if self.ivol_percentile <= 0 or self.ivol_percentile >= 1:
            raise ValueError("ivol_percentile must be between 0 and 1")

        if self.tracking_error_limit <= 0:
            raise ValueError("tracking_error_limit must be positive")

        if self.max_stock_weight <= 0 or self.max_stock_weight > 1:
            raise ValueError("max_stock_weight must be between 0 and 1")

        if self.rebalance_frequency not in ["monthly", "quarterly"]:
            raise ValueError("rebalance_frequency must be 'monthly' or 'quarterly'")

        # Validate factor weights sum to 1
        weight_sum = sum(self.factor_weights.values())
        if abs(weight_sum - 1.0) > 0.001:
            raise ValueError(f"Factor weights must sum to 1.0, got {weight_sum}")

    def get_beta_target(self, macro_state: str) -> float:
        """
        Get target beta based on macro state.

        Args:
            macro_state: One of "expansion", "slowdown", "recession", "recovery"

        Returns:
            Target beta value
        """
        beta_targets = {
            "expansion": self.expansion_beta_target,
            "slowdown": self.slowdown_beta_target,
            "recession": self.recession_beta_target,
            "recovery": self.recovery_beta_target,
        }
        return beta_targets.get(macro_state.lower(), 1.0)

    @classmethod
    def from_yaml(cls, config_path: str) -> "SmartBetaConfig":
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            SmartBetaConfig instance
        """
        with open(config_path, "r") as f:
            config_dict = yaml.safe_load(f)

        return cls(**config_dict)

    def to_yaml(self, config_path: str) -> None:
        """
        Save configuration to YAML file.

        Args:
            config_path: Path to save YAML configuration
        """
        with open(config_path, "w") as f:
            yaml.dump(self.__dict__, f, default_flow_style=False)


# Default configuration instance
_default_config: Optional[SmartBetaConfig] = None


def get_smart_beta_config(config_path: Optional[str] = None) -> SmartBetaConfig:
    """
    Get Smart Beta configuration.

    Args:
        config_path: Optional path to custom configuration file.
                     If not provided, uses default configuration.

    Returns:
        SmartBetaConfig instance
    """
    global _default_config

    if config_path:
        return SmartBetaConfig.from_yaml(config_path)

    if _default_config is None:
        # Try to load from default path
        default_path = Path(__file__).parent.parent / "config" / "smart_beta.yaml"
        if default_path.exists():
            _default_config = SmartBetaConfig.from_yaml(str(default_path))
        else:
            _default_config = SmartBetaConfig()

    return _default_config


def set_smart_beta_config(config: SmartBetaConfig) -> None:
    """
    Set the global Smart Beta configuration.

    Args:
        config: SmartBetaConfig instance to set as default
    """
    global _default_config
    _default_config = config
