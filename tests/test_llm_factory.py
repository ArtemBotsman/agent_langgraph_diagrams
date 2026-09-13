from __future__ import annotations

from traceable_spec.llm.anthropic import AnthropicConfig, AnthropicLLMClient
from traceable_spec.llm.factory import (
    create_instrumented_client,
    provider_config_from_env,
)
from traceable_spec.llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)


def test_factory_selects_native_anthropic_client(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_BASE", "https://api.anthropic.com")
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5")
    monkeypatch.setenv("LLM_API_KEY_ENV", "ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret")

    config = provider_config_from_env()
    client = create_instrumented_client(config)

    assert isinstance(config, AnthropicConfig)
    assert isinstance(client, AnthropicLLMClient)


def test_factory_keeps_openai_compatible_providers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_BASE", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("LLM_API_KEY_ENV", "DEEPSEEK_API_KEY")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")

    config = provider_config_from_env()
    client = create_instrumented_client(config)

    assert isinstance(config, OpenAICompatibleConfig)
    assert isinstance(client, OpenAICompatibleLLMClient)
