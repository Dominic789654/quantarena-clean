"""
Smart Beta Index Enhancement System

A dual-layer architecture combining:
1. Rule-Based Quantitative Engine: Factor calculation, negative screening, quadratic optimization
2. Prompt-Based Cognitive Fine-tuning: Macro state analysis, news freeze mechanism

Supported Factors:
- Dimson Beta: Corrects non-synchronous trading bias
- Downside Beta (β⁻): Calculated using only down days
- Idiosyncratic Volatility (IVOL): Fama-French three-factor residual volatility
- Amihud Illiquidity: Price impact per unit trading volume
"""

from .config import SmartBetaConfig, get_smart_beta_config
from .factor_engine import FactorEngine, FactorData
from .optimizer import SmartBetaOptimizer, OptimizationResult
from .index_constituents import IndexConstituentsProvider
from .macro_analyzer import MacroStateAnalyzer, MacroState
from .news_freeze import NewsFreezeMechanism, FreezeStatus
from .smart_beta_allocator import SmartBetaAllocator, AllocationResult

__all__ = [
    # Configuration
    "SmartBetaConfig",
    "get_smart_beta_config",
    # Factor Engine
    "FactorEngine",
    "FactorData",
    # Optimizer
    "SmartBetaOptimizer",
    "OptimizationResult",
    # Index Data
    "IndexConstituentsProvider",
    # Macro Analysis
    "MacroStateAnalyzer",
    "MacroState",
    # News Freeze
    "NewsFreezeMechanism",
    "FreezeStatus",
    # Allocator
    "SmartBetaAllocator",
    "AllocationResult",
]
