from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from traceable_spec.llm.openai_compatible import (
    LLMBudgetExceededError,
    LLMHTTPStatusError,
    LLMOutputTruncatedError,
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
    assert "thinking" not in observed["payload"]  # type: ignore[operator]
    assert "reasoning_effort" not in observed["payload"]  # type: ignore[operator]
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


def test_client_enforces_configured_estimated_cost_budget() -> None:
    client = OpenAICompatibleLLMClient(
        _config(
            input_price_usd_per_million=1.0,
            output_price_usd_per_million=1.0,
            max_estimated_cost_usd=0.1,
        ),
        transport=lambda *_: pytest.fail("transport must not run"),
    )
    client.total_cost_usd = 0.1
    with pytest.raises(LLMBudgetExceededError, match="estimated-cost"):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_cost_budget_requires_prices_before_transport() -> None:
    client = OpenAICompatibleLLMClient(
        _config(max_estimated_cost_usd=0.1),
        transport=lambda *_: pytest.fail("transport must not run"),
    )
    with pytest.raises(LLMBudgetExceededError, match="requires configured"):
        client.complete(messages=[{"role": "user", "content": "x"}])


def test_client_classifies_output_truncation_without_retry() -> None:
    def transport(*_: object) -> tuple[int, bytes]:
        response = {
            "model": "test-model",
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(_config(max_retries=2), transport=transport)
    with pytest.raises(LLMOutputTruncatedError):
        client.complete(messages=[{"role": "user", "content": "x"}])
    assert len(client.calls) == 1
    assert client.calls[0]["finish_reason"] == "length"


@pytest.mark.parametrize(
    ("provider", "expected", "absent"),
    [
        ("deepseek", {"thinking": {"type": "disabled"}}, "reasoning_effort"),
        (
            "groq",
            {"reasoning_effort": "none", "reasoning_format": "hidden"},
            "thinking",
        ),
    ],
)
def test_client_uses_provider_specific_reasoning_fields(
    provider: str,
    expected: dict[str, object],
    absent: str,
) -> None:
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
            "model": "resolved-test-model",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(_config(provider=provider), transport=transport)
    client.complete(messages=[{"role": "user", "content": "Return JSON"}])

    for name, value in expected.items():
        assert observed[name] == value
    assert absent not in observed


def test_openai_reasoning_request_uses_modern_chat_fields() -> None:
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
            "model": "gpt-5.5-2026-04-23",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(
        _config(
            provider="openai",
            model="gpt-5.5-2026-04-23",
            reasoning_effort="medium",
            max_output_tokens=2400,
        ),
        transport=transport,
    )
    client.complete(
        messages=[
            {"role": "system", "content": "Return JSON"},
            {"role": "user", "content": "Evaluate"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    assert observed["max_completion_tokens"] == 2400
    assert "max_tokens" not in observed
    assert observed["reasoning_effort"] == "medium"
    assert "temperature" not in observed
    messages = observed["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "developer"


def test_client_retries_429_and_keeps_sanitized_attempt_history() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(*_: object) -> tuple[int, bytes]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return 429, b'{"error":"rate limit details must not be logged"}'
        response = {
            "model": "test-model",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(
        _config(max_retries=1),
        transport=transport,
        sleep=sleeps.append,
    )
    assert client.complete(messages=[{"role": "user", "content": "x"}]) == "{}"
    assert attempts == 2
    assert sleeps == [0.5]
    assert client.calls[0]["attempts"] == 2
    assert client.calls[0]["retry_events"] == [
        {
            "attempt": 1,
            "error_type": "LLMHTTPStatusError",
            "http_status": 429,
            "retryable": True,
            "retry_delay_seconds": 0.5,
        }
    ]
    assert "rate limit details" not in json.dumps(client.calls)


def test_client_does_not_retry_authentication_error() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(*_: object) -> tuple[int, bytes]:
        nonlocal attempts
        attempts += 1
        return 401, b'{"error":"do not persist provider response"}'

    client = OpenAICompatibleLLMClient(
        _config(max_retries=3),
        transport=transport,
        sleep=sleeps.append,
    )
    with pytest.raises(RuntimeError, match="OpenAI-compatible LLM call failed"):
        client.complete(messages=[{"role": "user", "content": "x"}])
    assert attempts == 1
    assert sleeps == []
    assert client.calls[0]["http_status"] == 401
    assert client.calls[0]["retry_events"][0]["retryable"] is False
    assert "do not persist" not in json.dumps(client.calls)


def test_client_caps_provider_retry_after_delay() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(*_: object) -> tuple[int, bytes]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise LLMHTTPStatusError(status_code=429, retry_after_seconds=120)
        response = {
            "model": "test-model",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(
        _config(max_retries=1, max_retry_delay_seconds=10),
        transport=transport,
        sleep=sleeps.append,
    )
    assert client.complete(messages=[{"role": "user", "content": "x"}]) == "{}"
    assert sleeps == [10]


def test_client_captures_raw_evidence_only_when_explicitly_enabled(tmp_path: Path) -> None:
    raw_dir = tmp_path / "private_raw"

    def transport(*_: object) -> tuple[int, bytes]:
        response = {
            "model": "test-model",
            "choices": [{"message": {"content": "{\"accepted\":true}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(
        _config(raw_capture_dir=raw_dir),
        transport=transport,
    )
    assert client.complete(messages=[{"role": "user", "content": "private requirement"}])

    request_path = raw_dir / "CALL-000001-request.json"
    response_path = raw_dir / "CALL-000001-attempt-01-response.json"
    assert request_path.exists()
    assert response_path.exists()
    assert "private requirement" in request_path.read_text(encoding="utf-8")
    assert "secret-not-for-logs" not in request_path.read_text(encoding="utf-8")
    assert json.loads(response_path.read_text(encoding="utf-8"))["model"] == "test-model"
    assert stat.S_IMODE(request_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(raw_dir.stat().st_mode) == 0o700
    assert client.calls[0]["raw_capture_persisted"] is True


def test_client_does_not_create_raw_files_by_default(tmp_path: Path) -> None:
    raw_dir = tmp_path / "must_not_exist"

    def transport(*_: object) -> tuple[int, bytes]:
        response = {
            "model": "test-model",
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return 200, json.dumps(response).encode()

    client = OpenAICompatibleLLMClient(_config(), transport=transport)
    client.complete(messages=[{"role": "user", "content": "x"}])

    assert not raw_dir.exists()
    assert client.calls[0]["raw_capture_persisted"] is False
