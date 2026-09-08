from __future__ import annotations

import json

import pytest

from traceable_spec.llm.openai_compatible import (
    LLMBudgetExceededError,
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)


def _config(**updates: object) -> OpenAICompatibleConfig:
    values: dict[str, object] = {
        "provider": "test-provider",
        "api_base": "https://example.invalid/v1",
        "model": "test-model",
        "api_key": "secret-not-for-logs",
        "max_retries": 0,
    }
    values.update(updates)
    return OpenAICompatibleConfig(**values)  # type: ignore[arg-type]


def test_client_builds_chat_request_and_records_sanitized_usage() -> None:
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
            "model": "resolved-test-model",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(_config(), transport=transport)
    text = client.complete(
        messages=[{"role": "user", "content": "Return JSON"}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    assert text == "{}"
    assert observed["url"] == "https://example.invalid/v1/chat/completions"
    assert observed["payload"]["model"] == "test-model"  # type: ignore[index]
    assert client.calls[0]["total_tokens"] == 15
    assert "api_key" not in client.calls[0]
    assert "secret-not-for-logs" not in json.dumps(client.calls)


def test_client_enforces_local_call_budget_before_transport() -> None:
    client = OpenAICompatibleLLMClient(
        _config(max_calls_per_process=0),
        transport=lambda *_: pytest.fail("transport must not run"),
    )
    with pytest.raises(LLMBudgetExceededError):
        client.complete(messages=[{"role": "user", "content": "x"}])
