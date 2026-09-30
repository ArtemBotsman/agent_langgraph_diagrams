from __future__ import annotations

import json

import pytest

from traceable_spec.llm.anthropic import AnthropicConfig, AnthropicLLMClient
from traceable_spec.llm.openai_compatible import LLMBudgetExceededError, LLMOutputTruncatedError


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": 0, "output_tokens": 0},
        {"input_tokens": -1, "output_tokens": 2},
        {"input_tokens": "3", "output_tokens": 2},
        {"input_tokens": True, "output_tokens": 2},
    ],
)
def test_anthropic_unknown_usage_is_not_a_free_call(usage):
    def transport(*_):
        return 200, json.dumps(
            {
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": "end_turn",
                "usage": usage,
            }
        ).encode()

    client = AnthropicLLMClient(_config(), transport=transport)
    assert client.complete(messages=[{"role": "user", "content": "x"}]) == "{}"
    assert client.calls[0]["usage_complete"] is False
    assert client.calls[0]["estimated_cost_usd"] is None
    with pytest.raises(LLMBudgetExceededError, match="Unknown token usage"):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_anthropic_cached_input_can_be_the_entire_prompt():
    def transport(*_):
        return 200, json.dumps(
            {
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "cache_read_input_tokens": 10, "output_tokens": 2},
            }
        ).encode()

    client = AnthropicLLMClient(_config(), transport=transport)
    client.complete(messages=[{"role": "user", "content": "x"}])
    assert client.calls[0]["usage_complete"] is True
    assert client.calls[0]["total_tokens"] == 12


def _config(**updates: object) -> AnthropicConfig:
    values: dict[str, object] = {
        "provider": "anthropic",
        "api_base": "https://api.anthropic.com",
        "model": "claude-opus-5",
        "api_key": "secret-not-for-logs",
        "max_retries": 0,
        "reasoning_effort": "low",
    }
    values.update(updates)
    return AnthropicConfig(**values)  # type: ignore[arg-type]


def test_anthropic_client_builds_native_messages_request() -> None:
    observed: dict[str, object] = {}

    def transport(
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        observed.update(
            {"url": url, "headers": headers, "payload": json.loads(body), "timeout": timeout}
        )
        response = {
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": "{}"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 2,
                "output_tokens_details": {"thinking_tokens": 1},
            },
        }
        return 200, json.dumps(response).encode()

    client = AnthropicLLMClient(_config(), transport=transport)
    text = client.complete(
        messages=[
            {"role": "system", "content": "Return JSON"},
            {"role": "user", "content": "Build artifacts"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    assert text == "{}"
    assert observed["url"] == "https://api.anthropic.com/v1/messages"
    payload = observed["payload"]
    assert isinstance(payload, dict)
    assert payload["system"] == "Return JSON"
    assert payload["messages"] == [{"role": "user", "content": "Build artifacts"}]
    assert payload["output_config"] == {"effort": "low"}
    assert "temperature" not in payload
    assert "response_format" not in payload
    assert client.calls[0]["total_tokens"] == 17
    assert client.calls[0]["reasoning_tokens"] == 1
    assert client.calls[0]["requested_temperature"] == 0
    assert client.calls[0]["effective_temperature"] is None
    assert client.calls[0]["temperature_omitted_for_compatibility"] is True
    assert "secret-not-for-logs" not in json.dumps(client.calls)


def test_anthropic_client_keeps_temperature_for_older_model() -> None:
    observed: dict[str, object] = {}

    def transport(
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        del url, headers, timeout
        observed.update(json.loads(body))
        response = {
            "model": "claude-haiku-4-5-20251001",
            "content": [{"type": "text", "text": "{}"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return 200, json.dumps(response).encode()

    client = AnthropicLLMClient(_config(model="claude-haiku-4-5-20251001"), transport=transport)
    client.complete(messages=[{"role": "user", "content": "Return JSON"}], temperature=0)

    assert observed["temperature"] == 0
    assert client.calls[0]["effective_temperature"] == 0


def test_anthropic_client_maps_explicit_json_schema() -> None:
    observed: dict[str, object] = {}

    def transport(
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        del url, headers, timeout
        observed.update(json.loads(body))
        response = {
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        return 200, json.dumps(response).encode()

    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    client = AnthropicLLMClient(_config(), transport=transport)
    client.complete(
        messages=[{"role": "user", "content": "Return status"}],
        response_format={"type": "json_schema", "schema": schema},
    )

    assert observed["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": schema},
    }


def test_anthropic_client_classifies_max_tokens_as_truncation() -> None:
    def transport(*_: object) -> tuple[int, bytes]:
        response = {
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": '{"partial":'}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 3, "output_tokens": 8},
        }
        return 200, json.dumps(response).encode()

    client = AnthropicLLMClient(_config(), transport=transport)
    with pytest.raises(LLMOutputTruncatedError):
        client.complete(messages=[{"role": "user", "content": "x"}])
    assert client.calls[0]["stop_reason"] == "max_tokens"
