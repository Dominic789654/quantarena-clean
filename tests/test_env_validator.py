"""
Unit tests for environment variable validator.

Tests the EnvValidator class and validate_env function.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.config.validator import (
    EnvValidator,
    validate_env,
    check_env_quick,
    ValidationLevel,
    ENV_REQUIREMENTS,
)


class TestValidationLevel:
    """Test ValidationLevel enum."""
    
    def test_validation_level_values(self):
        """Test that validation levels have correct values."""
        assert ValidationLevel.ERROR.value == "error"
        assert ValidationLevel.WARNING.value == "warning"
        assert ValidationLevel.OPTIONAL.value == "optional"


class TestEnvVarRequirement:
    """Test EnvVarRequirement dataclass."""
    
    def test_requirement_creation(self):
        """Test creating a requirement."""
        req = ENV_REQUIREMENTS[0]  # Get first requirement
        assert isinstance(req.name, str)
        assert isinstance(req.level, ValidationLevel)
        assert isinstance(req.description, str)
        assert isinstance(req.used_in, list)


class TestEnvValidator:
    """Test EnvValidator class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.validator = EnvValidator()
        # Clear relevant env vars before each test
        self._clear_env_vars()
    
    def teardown_method(self):
        """Clean up after tests."""
        self._clear_env_vars()
    
    def _clear_env_vars(self):
        """Clear test environment variables."""
        vars_to_clear = [
            "REASONING_MODEL_PROVIDER",
            "REASONING_MODEL_ID",
            "MACARON_API_KEY",
            "TUSHARE_API_KEY",
            "ALPHA_VANTAGE_API_KEY",
            "FMP_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "ARK_API_KEY",
            "OPENROUTER_API_KEY",
            "TAVILY_API_KEY",
            "COMPANY_NEWS_PROVIDER",
            "DEEPFUND_US_API_SOURCE",
            "DEEPFUND_CN_API_SOURCE",
        ]
        for var in vars_to_clear:
            if var in os.environ:
                del os.environ[var]
    
    def test_explicit_fmp_source_requires_fmp_key(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha")
        monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "fmp")

        monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
        monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")
        result = validate_env(mode="deepfund", verbose=False, raise_on_error=False)

        assert result is False

    def test_explicit_alpha_source_requires_alpha_key(self, monkeypatch):
        monkeypatch.setenv("FMP_API_KEY", "fmp")
        monkeypatch.setenv("DEEPFUND_US_API_SOURCE", "alpha_vantage")

        monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
        monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")
        result = validate_env(mode="deepfund", verbose=False, raise_on_error=False)

        assert result is False

    def test_explicit_invalid_cn_source_is_rejected(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_API_KEY", "ts")
        monkeypatch.setenv("DEEPFUND_CN_API_SOURCE", "alpha_vantage")

        monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
        monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")
        result = validate_env(mode="deepfund", verbose=False, raise_on_error=False)

        assert result is False

    def test_explicit_tushare_cn_source_requires_tushare_key(self, monkeypatch):
        monkeypatch.setenv("DEEPFUND_CN_API_SOURCE", "tushare")
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha")

        monkeypatch.setenv("REASONING_MODEL_PROVIDER", "openai")
        monkeypatch.setenv("REASONING_MODEL_ID", "gpt-4o")
        result = validate_env(mode="deepfund", verbose=False, raise_on_error=False)

        assert result is False

    def test_init(self):
        """Test validator initialization."""
        validator = EnvValidator()
        assert validator.errors == []
        assert validator.warnings == []
        assert len(validator.missing) == 3
    
    def test_validate_all_required_present(self):
        """Test validation when all required vars are present."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        
        result = self.validator.validate(mode="deepear", raise_on_error=False, verbose=False)
        assert result is True
        assert len(self.validator.errors) == 0
    
    def test_validate_missing_required_error(self):
        """Test validation fails when required vars are missing."""
        # Don't set any env vars
        result = self.validator.validate(mode="deepear", raise_on_error=False, verbose=False)
        assert result is False
        assert len(self.validator.errors) > 0
        assert "REASONING_MODEL_PROVIDER" in str(self.validator.errors)
    
    def test_validate_raise_on_error(self):
        """Test that validate raises ValueError when raise_on_error=True."""
        with pytest.raises(ValueError) as exc_info:
            self.validator.validate(mode="deepear", raise_on_error=True, verbose=False)
        
        assert "Environment validation failed" in str(exc_info.value)
    
    def test_validate_mode_filtering(self):
        """Test that mode filtering works correctly."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        
        # deepear mode should pass without data provider
        result = self.validator.validate(mode="deepear", raise_on_error=False, verbose=False)
        assert result is True
        
        # deepfund mode should fail without data provider
        result = self.validator.validate(mode="deepfund", raise_on_error=False, verbose=False)
        assert result is False
        assert any("DATA_PROVIDER" in str(e) for e in self.validator.errors)
    
    def test_validate_with_data_provider(self):
        """Test validation passes with data provider for trading modes."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["TUSHARE_API_KEY"] = "test-tushare-key"
        
        result = self.validator.validate(mode="deepfund", raise_on_error=False, verbose=False)
        assert result is True

    def test_validate_with_fmp_data_provider(self):
        """Test validation passes with FMP data provider for trading modes."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["FMP_API_KEY"] = "test-fmp-key"

        result = self.validator.validate(mode="deepfund", raise_on_error=False, verbose=False)
        assert result is True
    
    def test_provider_specific_key_filtering(self):
        """Test that provider-specific keys are filtered correctly."""
        os.environ["REASONING_MODEL_PROVIDER"] = "deepseek"
        os.environ["REASONING_MODEL_ID"] = "deepseek-chat"
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        
        # Should not require OPENAI_API_KEY when provider is deepseek
        result = self.validator.validate(mode="deepear", raise_on_error=False, verbose=False)
        assert result is True

    def test_macaron_provider_rejected_for_deepear_mode(self):
        """Macaron should not pass preflight validation for deepear mode yet."""
        os.environ["REASONING_MODEL_PROVIDER"] = "macaron"
        os.environ["REASONING_MODEL_ID"] = "gpt-5.4"
        os.environ["MACARON_API_KEY"] = "test-macaron-key"

        result = self.validator.validate(mode="deepear", raise_on_error=False, verbose=False)

        assert result is False
        assert any("not supported for deepear mode yet" in msg for msg in self.validator.errors)

    def test_macaron_provider_requires_api_key_for_backtest(self):
        """Macaron backtest validation should require an explicit API key."""
        os.environ["REASONING_MODEL_PROVIDER"] = "macaron"
        os.environ["REASONING_MODEL_ID"] = "gpt-5.4"
        os.environ["TUSHARE_API_KEY"] = "test-tushare-key"

        result = self.validator.validate(mode="backtest", raise_on_error=False, verbose=False)

        assert result is False
        assert any("MACARON_API_KEY" in msg for msg in self.validator.errors)

    def test_macaron_provider_passes_for_backtest_with_api_key(self):
        """Macaron should pass backtest validation once its API key is configured."""
        os.environ["REASONING_MODEL_PROVIDER"] = "macaron"
        os.environ["REASONING_MODEL_ID"] = "gpt-5.4"
        os.environ["MACARON_API_KEY"] = "test-macaron-key"
        os.environ["TUSHARE_API_KEY"] = "test-tushare-key"

        result = self.validator.validate(mode="backtest", raise_on_error=False, verbose=False)

        assert result is True
    
    def test_is_key_for_provider(self):
        """Test _is_key_for_provider method."""
        validator = EnvValidator()
        
        # Test OpenAI
        assert validator._is_key_for_provider("OPENAI_API_KEY", "openai") is True
        assert validator._is_key_for_provider("DEEPSEEK_API_KEY", "openai") is False
        
        # Test DeepSeek
        assert validator._is_key_for_provider("DEEPSEEK_API_KEY", "deepseek") is True
        assert validator._is_key_for_provider("OPENAI_API_KEY", "deepseek") is False
        
        # Test Ark
        assert validator._is_key_for_provider("ARK_API_KEY", "ark") is True
        
        # Test OpenRouter
        assert validator._is_key_for_provider("OPENROUTER_API_KEY", "openrouter") is True

        # Test Macaron
        assert validator._is_key_for_provider("MACARON_API_KEY", "macaron") is True
    
    def test_get_missing_vars(self):
        """Test get_missing_vars method."""
        # Don't set any vars
        self.validator.validate(mode="deepear", raise_on_error=False, verbose=False)
        
        missing = self.validator.get_missing_vars(ValidationLevel.ERROR)
        assert "REASONING_MODEL_PROVIDER" in missing
        assert "REASONING_MODEL_ID" in missing
        
        all_missing = self.validator.get_missing_vars()
        assert len(all_missing) >= len(missing)


class TestValidateEnvFunction:
    """Test validate_env convenience function."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self._clear_env_vars()
    
    def teardown_method(self):
        """Clean up after tests."""
        self._clear_env_vars()
    
    def _clear_env_vars(self):
        """Clear test environment variables."""
        vars_to_clear = [
            "REASONING_MODEL_PROVIDER",
            "REASONING_MODEL_ID",
            "MACARON_API_KEY",
            "TUSHARE_API_KEY",
            "FMP_API_KEY",
            "OPENAI_API_KEY",
            "TAVILY_API_KEY",
            "COMPANY_NEWS_PROVIDER",
        ]
        for var in vars_to_clear:
            if var in os.environ:
                del os.environ[var]
    
    def test_validate_env_success(self):
        """Test validate_env with valid environment."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        
        result = validate_env(mode="deepear", raise_on_error=False, verbose=False)
        assert result is True
    
    def test_validate_env_failure(self):
        """Test validate_env with invalid environment."""
        result = validate_env(mode="deepear", raise_on_error=False, verbose=False)
        assert result is False
    
    def test_validate_env_raises(self):
        """Test validate_env raises on failure when raise_on_error=True."""
        with pytest.raises(ValueError):
            validate_env(mode="deepear", raise_on_error=True, verbose=False)


class TestCheckEnvQuick:
    """Test check_env_quick function."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self._clear_env_vars()
    
    def teardown_method(self):
        """Clean up after tests."""
        self._clear_env_vars()
    
    def _clear_env_vars(self):
        """Clear test environment variables."""
        vars_to_clear = [
            "REASONING_MODEL_PROVIDER",
            "REASONING_MODEL_ID",
            "MACARON_API_KEY",
            "FMP_API_KEY",
            "OPENAI_API_KEY",
            "TAVILY_API_KEY",
            "COMPANY_NEWS_PROVIDER",
        ]
        for var in vars_to_clear:
            if var in os.environ:
                del os.environ[var]
    
    def test_check_env_quick_true(self):
        """Test check_env_quick returns True with valid env."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        
        result = check_env_quick()
        assert result is True
    
    def test_check_env_quick_false(self):
        """Test check_env_quick returns False with invalid env."""
        result = check_env_quick()
        assert result is False
    
    def test_check_env_quick_no_exception(self):
        """Test check_env_quick never raises exception."""
        # Should not raise even with completely empty env
        try:
            result = check_env_quick()
            assert isinstance(result, bool)
        except Exception:
            pytest.fail("check_env_quick() should not raise exception")


class TestIntegration:
    """Integration tests with real environment."""
    
    def test_env_requirements_list(self):
        """Test that ENV_REQUIREMENTS list is populated."""
        assert len(ENV_REQUIREMENTS) > 0
        
        # Check that required vars are defined
        required_names = [r.name for r in ENV_REQUIREMENTS if r.level == ValidationLevel.ERROR]
        assert "REASONING_MODEL_PROVIDER" in required_names
        assert "REASONING_MODEL_ID" in required_names
    
    def test_all_modes_covered(self):
        """Test that all modes have requirements defined."""
        modes = set()
        for req in ENV_REQUIREMENTS:
            modes.update(req.used_in)
        
        assert "deepear" in modes
        assert "deepfund" in modes
        assert "backtest" in modes

    @pytest.mark.parametrize("provider", ["tavily", "tavily_strict"])
    def test_tavily_news_provider_requires_api_key_for_trading_modes(self, provider):
        """COMPANY_NEWS_PROVIDER=tavily/tavily_strict should require TAVILY_API_KEY in trading modes."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["TUSHARE_API_KEY"] = "test-tushare-key"
        os.environ["COMPANY_NEWS_PROVIDER"] = provider

        validator = EnvValidator()
        result = validator.validate(mode="backtest", raise_on_error=False, verbose=False)
        assert result is False
        assert any("TAVILY_API_KEY" in msg for msg in validator.errors)

    @pytest.mark.parametrize("provider", ["akshare", "akshare_strict"])
    def test_akshare_news_provider_does_not_require_tavily_key(self, provider):
        """AKShare providers should pass trading env validation without TAVILY_API_KEY."""
        os.environ["REASONING_MODEL_PROVIDER"] = "openai"
        os.environ["REASONING_MODEL_ID"] = "gpt-4o"
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["TUSHARE_API_KEY"] = "test-tushare-key"
        os.environ["COMPANY_NEWS_PROVIDER"] = provider

        validator = EnvValidator()
        result = validator.validate(mode="backtest", raise_on_error=False, verbose=False)
        assert result is True
        assert all("TAVILY_API_KEY" not in msg for msg in validator.errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
