"""
Environment variable validator for the unified agent trading system.

Validates required environment variables at startup to provide clear error
messages before runtime failures.

Example:
    >>> from shared.config.validator import validate_env
    >>> validate_env(mode="deepfund")  # Validates for deepfund mode
    >>> validate_env(mode="deepear")   # Validates for deepear mode
"""

import os
import sys
from enum import Enum
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Search for .env in common locations
    env_paths = [
        Path.cwd() / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass  # dotenv not installed, skip


class ValidationLevel(Enum):
    """Validation severity levels."""
    ERROR = "error"      # Must be set, app will exit
    WARNING = "warning"  # Should be set, app will warn
    OPTIONAL = "optional"  # Nice to have, no warning


@dataclass
class EnvVarRequirement:
    """Requirement definition for an environment variable."""
    name: str
    level: ValidationLevel
    description: str
    used_in: List[str] = field(default_factory=list)  # Which modes use this
    doc_url: Optional[str] = None


# Define all environment variable requirements
ENV_REQUIREMENTS: List[EnvVarRequirement] = [
    # Core LLM Configuration - Required for all modes
    EnvVarRequirement(
        name="REASONING_MODEL_PROVIDER",
        level=ValidationLevel.ERROR,
        description="LLM provider for reasoning model (e.g., openai, deepseek, ark, OpenRouter)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="REASONING_MODEL_ID",
        level=ValidationLevel.ERROR,
        description="Model ID for reasoning (e.g., gpt-4o, deepseek-chat, kimi-k2.5)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    
    # Data Providers - At least one required for trading modes
    EnvVarRequirement(
        name="TUSHARE_API_KEY",
        level=ValidationLevel.WARNING,
        description="TuShare API key for Chinese A-share market data",
        used_in=["deepfund", "backtest"],
        doc_url="https://tushare.pro/register",
    ),
    EnvVarRequirement(
        name="ALPHA_VANTAGE_API_KEY",
        level=ValidationLevel.WARNING,
        description="Alpha Vantage API key for US market data",
        used_in=["deepfund", "backtest"],
        doc_url="https://www.alphavantage.co/support/#api-key",
    ),
    EnvVarRequirement(
        name="FMP_API_KEY",
        level=ValidationLevel.WARNING,
        description="Financial Modeling Prep API key for US market data",
        used_in=["deepfund", "backtest"],
        doc_url="https://financialmodelingprep.com/",
    ),
    
    # LLM API Keys - Provider-specific
    EnvVarRequirement(
        name="OPENAI_API_KEY",
        level=ValidationLevel.WARNING,
        description="OpenAI API key (required if REASONING_MODEL_PROVIDER=openai)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="DEEPSEEK_API_KEY",
        level=ValidationLevel.WARNING,
        description="DeepSeek API key (required if REASONING_MODEL_PROVIDER=deepseek)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="ARK_API_KEY",
        level=ValidationLevel.WARNING,
        description="Volcengine Ark API key (required if REASONING_MODEL_PROVIDER=Ark)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="OPENROUTER_API_KEY",
        level=ValidationLevel.WARNING,
        description="OpenRouter API key (required if REASONING_MODEL_PROVIDER=OpenRouter)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="ANTHROPIC_API_KEY",
        level=ValidationLevel.WARNING,
        description="Anthropic API key (required if REASONING_MODEL_PROVIDER=anthropic)",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="MACARON_API_KEY",
        level=ValidationLevel.WARNING,
        description="Macaron Responses API key (required if REASONING_MODEL_PROVIDER=macaron)",
        used_in=["deepfund", "backtest"],
    ),
    
    # Optional Services
    EnvVarRequirement(
        name="JINA_API_KEY",
        level=ValidationLevel.OPTIONAL,
        description="Jina AI API key for better web extraction",
        used_in=["deepear"],
    ),
    EnvVarRequirement(
        name="TAVILY_API_KEY",
        level=ValidationLevel.OPTIONAL,
        description="Tavily API key for AI search",
        used_in=["deepear", "deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="COMPANY_NEWS_PROVIDER",
        level=ValidationLevel.OPTIONAL,
        description="DeepFund company news provider (default, replay, replay_strict, tavily, tavily_strict, akshare, akshare_strict, auto)",
        used_in=["deepfund", "backtest"],
    ),
    EnvVarRequirement(
        name="COMPANY_NEWS_REPLAY_PATH",
        level=ValidationLevel.OPTIONAL,
        description="JSON/JSONL replay fixture path for COMPANY_NEWS_PROVIDER=replay/replay_strict",
        used_in=["deepfund", "backtest"],
    ),
    
    # Tool Model Configuration
    EnvVarRequirement(
        name="TOOL_MODEL_PROVIDER",
        level=ValidationLevel.WARNING,
        description="LLM provider for tool model (defaults to ollama if not set)",
        used_in=["deepear"],
    ),
    EnvVarRequirement(
        name="TOOL_MODEL_ID",
        level=ValidationLevel.WARNING,
        description="Model ID for tool calling (defaults to qwen3:latest if not set)",
        used_in=["deepear"],
    ),
]


class EnvValidator:
    """Environment variable validator."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.missing: Dict[ValidationLevel, List[str]] = {
            ValidationLevel.ERROR: [],
            ValidationLevel.WARNING: [],
            ValidationLevel.OPTIONAL: [],
        }
    
    def validate(
        self,
        mode: Optional[str] = None,
        raise_on_error: bool = True,
        verbose: bool = True
    ) -> bool:
        """
        Validate environment variables.
        
        Args:
            mode: Filter by mode ('deepear', 'deepfund', 'backtest', or None for all)
            raise_on_error: If True, raise exception on ERROR level missing vars
            verbose: If True, print validation results
            
        Returns:
            True if validation passes (no errors), False otherwise
            
        Raises:
            ValueError: If raise_on_error=True and there are ERROR level missing vars
        """
        self.errors = []
        self.warnings = []
        self.missing = {level: [] for level in ValidationLevel}
        
        provider = os.getenv("REASONING_MODEL_PROVIDER", "").lower()
        
        for req in ENV_REQUIREMENTS:
            # Skip if not used in current mode
            if mode and mode not in req.used_in:
                continue
            
            # Check if variable is set and non-empty
            value = os.getenv(req.name, "").strip()
            is_set = bool(value)
            
            # Special handling for provider-specific API keys
            if req.level == ValidationLevel.WARNING and req.name.endswith("_API_KEY"):
                # Skip if provider doesn't match this key
                if provider and not self._is_key_for_provider(req.name, provider):
                    continue
            
            if not is_set:
                self.missing[req.level].append(req.name)
                message = self._format_message(req)
                
                if req.level == ValidationLevel.ERROR:
                    self.errors.append(message)
                elif req.level == ValidationLevel.WARNING:
                    self.warnings.append(message)

        # Current Macaron integration is scoped to the DeepFund/backtest paths.
        # DeepEar still routes through its own model factory, which does not yet
        # support the provider.
        if provider == "macaron" and mode == "deepear":
            self.errors.append(
                "  • REASONING_MODEL_PROVIDER: REASONING_MODEL_PROVIDER=macaron is not supported for deepear mode yet. "
                "Current Macaron integration is limited to DeepFund/backtest paths."
            )
            self.missing[ValidationLevel.ERROR].append("REASONING_MODEL_PROVIDER")

        # Macaron backtest integration currently depends on an explicit API key
        # at runtime, so fail preflight validation early instead of surfacing the
        # issue only when the first Responses API call is attempted.
        if provider == "macaron" and mode in {"deepfund", "backtest", None} and not os.getenv("MACARON_API_KEY", "").strip():
            self.errors.append(
                "  • MACARON_API_KEY: REASONING_MODEL_PROVIDER=macaron requires MACARON_API_KEY."
            )
            self.missing[ValidationLevel.ERROR].append("MACARON_API_KEY")
        
        # Check data provider requirement for trading modes
        if mode in ["deepfund", "backtest"]:
            has_data_provider = any([
                os.getenv("TUSHARE_API_KEY", "").strip(),
                os.getenv("ALPHA_VANTAGE_API_KEY", "").strip(),
                os.getenv("FMP_API_KEY", "").strip(),
            ])
            if not has_data_provider:
                msg = (
                    "  • DATA_PROVIDER: No data provider API key found.\n"
                    "    Set TUSHARE_API_KEY (for CN market), ALPHA_VANTAGE_API_KEY, or FMP_API_KEY (for US market)\n"
                    "    TuShare: https://tushare.pro/register\n"
                    "    Alpha Vantage: https://www.alphavantage.co/support/#api-key\n"
                    "    FMP: https://financialmodelingprep.com/"
                )
                self.errors.append(msg)
                self.missing[ValidationLevel.ERROR].append("DATA_PROVIDER")

        # Validate company news provider configuration for trading modes.
        if mode in ["deepfund", "backtest"]:
            news_provider = os.getenv("COMPANY_NEWS_PROVIDER", "default").strip().lower()
            if news_provider not in {"default", "replay", "replay_strict", "tavily", "tavily_strict", "akshare", "akshare_strict", "auto"}:
                self.warnings.append(
                    "  • COMPANY_NEWS_PROVIDER: Invalid value. "
                    "Use one of [default, replay, replay_strict, tavily, tavily_strict, akshare, akshare_strict, auto]."
                )
            if news_provider in {"tavily", "tavily_strict"} and not os.getenv("TAVILY_API_KEY", "").strip():
                self.errors.append(
                    "  • TAVILY_API_KEY: COMPANY_NEWS_PROVIDER=tavily/tavily_strict requires TAVILY_API_KEY."
                )
                self.missing[ValidationLevel.ERROR].append("TAVILY_API_KEY")
            if news_provider in {"replay", "replay_strict"} and not os.getenv("COMPANY_NEWS_REPLAY_PATH", "").strip():
                self.errors.append(
                    "  • COMPANY_NEWS_REPLAY_PATH: COMPANY_NEWS_PROVIDER=replay/replay_strict requires COMPANY_NEWS_REPLAY_PATH."
                )
                self.missing[ValidationLevel.ERROR].append("COMPANY_NEWS_REPLAY_PATH")


        if mode in ["deepfund", "backtest"]:
            explicit_us_source = os.getenv("DEEPFUND_US_API_SOURCE", "").strip().lower()
            explicit_cn_source = os.getenv("DEEPFUND_CN_API_SOURCE", "").strip().lower()

            if explicit_us_source:
                required_key_by_us_source = {
                    "fmp": "FMP_API_KEY",
                    "financialmodelingprep": "FMP_API_KEY",
                    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
                    "alphavantage": "ALPHA_VANTAGE_API_KEY",
                    "alpha": "ALPHA_VANTAGE_API_KEY",
                }
                required_key = required_key_by_us_source.get(explicit_us_source)
                if required_key and not os.getenv(required_key, "").strip():
                    self.errors.append(
                        f"  • {required_key}: DEEPFUND_US_API_SOURCE={explicit_us_source} requires {required_key}."
                    )
                    self.missing[ValidationLevel.ERROR].append(required_key)

            if explicit_cn_source and explicit_cn_source not in {"tushare"}:
                self.errors.append(
                    "  • DEEPFUND_CN_API_SOURCE: Only tushare is supported for CN market data."
                )
                self.missing[ValidationLevel.ERROR].append("DEEPFUND_CN_API_SOURCE")

            if explicit_cn_source == "tushare" and not os.getenv("TUSHARE_API_KEY", "").strip():
                self.errors.append(
                    "  • TUSHARE_API_KEY: DEEPFUND_CN_API_SOURCE=tushare requires TUSHARE_API_KEY."
                )
                self.missing[ValidationLevel.ERROR].append("TUSHARE_API_KEY")
        
        # Print summary if verbose
        if verbose:
            self._print_summary()
        
        # Raise or return
        if self.errors and raise_on_error:
            raise ValueError(
                "Environment validation failed. Please configure your .env file:\n\n"
                + "\n".join(self.errors)
            )
        
        return len(self.errors) == 0
    
    def _is_key_for_provider(self, key_name: str, provider: str) -> bool:
        """Check if an API key is for the given provider."""
        key_lower = key_name.lower()
        provider_lower = provider.lower()
        
        # Map provider names to their key patterns
        provider_key_map = {
            "openai": ["openai"],
            "deepseek": ["deepseek"],
            "ark": ["ark"],
            "openrouter": ["openrouter"],
            "anthropic": ["anthropic"],
            "macaron": ["macaron"],
            "ollama": [],  # Ollama doesn't need API key
        }
        
        # Check if key matches provider
        patterns = provider_key_map.get(provider_lower, [provider_lower])
        return any(pattern in key_lower for pattern in patterns)
    
    def _format_message(self, req: EnvVarRequirement) -> str:
        """Format a validation message."""
        lines = [f"  • {req.name}: {req.description}"]
        if req.doc_url:
            lines.append(f"    Get key at: {req.doc_url}")
        return "\n".join(lines)
    
    def _print_summary(self):
        """Print validation summary."""
        if self.errors:
            print("❌ Missing required environment variables:", file=sys.stderr)
            for msg in self.errors:
                print(msg, file=sys.stderr)
            print(file=sys.stderr)
        
        if self.warnings:
            print("⚠️  Missing recommended environment variables:", file=sys.stderr)
            for msg in self.warnings:
                print(msg, file=sys.stderr)
            print(file=sys.stderr)
        
        if not self.errors and not self.warnings:
            print("✅ All environment variables validated successfully")
        elif not self.errors:
            print("✅ Required variables present (some optional variables missing)")
    
    def get_missing_vars(self, level: Optional[ValidationLevel] = None) -> List[str]:
        """Get list of missing environment variables."""
        if level:
            return self.missing.get(level, [])
        return (
            self.missing[ValidationLevel.ERROR] +
            self.missing[ValidationLevel.WARNING] +
            self.missing[ValidationLevel.OPTIONAL]
        )


def validate_env(mode: Optional[str] = None, raise_on_error: bool = True, verbose: bool = True) -> bool:
    """
    Quick validation function.
    
    Args:
        mode: 'deepear', 'deepfund', 'backtest', or None for all
        raise_on_error: Raise exception on validation failure
        verbose: Print validation results
        
    Returns:
        True if validation passes
        
    Example:
        >>> validate_env(mode="deepfund")
        ✅ All environment variables validated successfully
        True
        
        >>> validate_env(mode="invalid")
        ❌ Missing required environment variables...
        ValueError: Environment validation failed...
    """
    validator = EnvValidator()
    return validator.validate(mode=mode, raise_on_error=raise_on_error, verbose=verbose)


def check_env_quick() -> bool:
    """
    Quick check without raising exceptions.
    
    Returns:
        True if all required variables are set, False otherwise
        
    Example:
        >>> if check_env_quick():
        ...     run_application()
        ... else:
        ...     print("Please configure .env file")
    """
    try:
        validator = EnvValidator()
        return validator.validate(mode=None, raise_on_error=False, verbose=False)
    except Exception:
        return False
