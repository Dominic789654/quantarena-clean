"""Contract tests for the shared LLM provider credential registry.

Pins that both consumers (deepfund langchain provider, deepear agno factory)
resolve credentials through shared/config/llm_providers and that historical
behavior — including the intentional Ark endpoint divergence — is preserved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

from shared.config.llm_providers import (  # noqa: E402
    PROVIDER_CREDENTIALS,
    get_provider_credentials,
)
from deepfund.src.llm.provider import Provider  # noqa: E402


def test_registry_covers_every_deepfund_provider():
    for member in Provider:
        assert get_provider_credentials(member.value) is not None, (
            f"{member.value} missing from the shared credential registry"
        )


def test_registry_covers_every_deepear_provider():
    from deepear.src.utils.llm.factory import PROVIDERS as DEEPEAR_PROVIDERS

    for key in DEEPEAR_PROVIDERS:
        if key == "openai" or key == "ollama":
            continue  # covered, key-optional cases
        assert get_provider_credentials(key) is not None, (
            f"deepear provider {key!r} missing from the shared credential registry"
        )


def test_api_key_fallback_order(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("QWEN_API_KEY", "qwen-secret")

    assert get_provider_credentials("dashscope").resolve_api_key() == "qwen-secret"
    assert get_provider_credentials("alibaba").resolve_api_key() == "qwen-secret"

    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-secret")
    # Each provider prefers its own primary key when both are present.
    assert get_provider_credentials("dashscope").resolve_api_key() == "dash-secret"
    assert get_provider_credentials("alibaba").resolve_api_key() == "qwen-secret"


def test_ark_endpoint_divergence_is_preserved(monkeypatch):
    """deepfund targets the coding endpoint; deepear the standard endpoint."""
    monkeypatch.setenv("ARK_API_KEY", "test-ark")
    monkeypatch.delenv("ARK_BASE_URL", raising=False)

    deepfund_url = Provider.ARK.config.base_url
    assert deepfund_url == "https://ark.cn-beijing.volces.com/api/coding/v3"

    from deepear.src.utils.llm.factory import PROVIDERS as DEEPEAR_PROVIDERS
    deepear_url = DEEPEAR_PROVIDERS["ark"].get_base_url("ark")
    assert deepear_url == "https://ark.cn-beijing.volces.com/api/v3"

    # Both honor the shared ARK_BASE_URL override.
    monkeypatch.setenv("ARK_BASE_URL", "https://example.test/override")
    assert Provider.ARK.config.base_url == "https://example.test/override"
    assert DEEPEAR_PROVIDERS["ark"].get_base_url("ark") == "https://example.test/override"


def test_deepfund_model_config_resolves_through_registry(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-secret")
    config = Provider.DEEPSEEK.config

    assert config.requires_api_key
    assert config.env_key == "DEEPSEEK_API_KEY"
    assert config.resolve_api_key() == "ds-secret"

    ollama = Provider.OLLAMA.config
    assert not ollama.requires_api_key


def test_no_registry_entry_is_orphaned():
    """Every registry entry should be consumable by at least one stack."""
    from deepear.src.utils.llm.factory import PROVIDERS as DEEPEAR_PROVIDERS

    deepfund_keys = {member.value.lower() for member in Provider}
    deepear_keys = set(DEEPEAR_PROVIDERS)
    for key in PROVIDER_CREDENTIALS:
        assert key in deepfund_keys | deepear_keys, f"registry entry {key!r} has no consumer"


def test_missing_api_key_raises_with_all_expected_envs(monkeypatch):
    from deepfund.src.llm.inference import get_model, LLMConfig

    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ZHIPU_API_KEY"):
        get_model(LLMConfig(provider="ZhiPu", model="glm-5"))
