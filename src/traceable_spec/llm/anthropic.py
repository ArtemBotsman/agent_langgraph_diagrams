"""Native Anthropic Messages API adapter with sanitized local telemetry."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.llm.openai_compatible import (
    LLMBudgetExceededError,
    LLMHTTPStatusError,
    LLMOutputTruncatedError,
    _parse_retry_after,
)
from traceable_spec.llm.protocol import LLMNotConfiguredError
from traceable_spec.prompts.use_cases import detect_llm_role

Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]
Sleep = Callable[[float], None]

_RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


def _requires_default_temperature(model: str) -> bool:
    """Return whether Anthropic only accepts its default sampling temperature."""

    default_only_prefixes = (
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
    )
    return model.startswith(default_only_prefixes)


@dataclass(frozen=True)
class AnthropicConfig:
    """Configuration read from the same provider-neutral LLM_* variables."""

    provider: str
    api_base: str
    model: str
    api_key: str = field(repr=False)
    anthropic_version: str = "2023-06-01"
    timeout_seconds: float = 600.0
    max_retries: int = 1
    retry_base_delay_seconds: float = 1.0
    max_retry_delay_seconds: float = 30.0
    max_output_tokens: int = 12_000
    max_calls_per_process: int = 3
    max_total_tokens_per_process: int = 45_000
    input_price_usd_per_million: float | None = None
    output_price_usd_per_million: float | None = None
    max_estimated_cost_usd: float | None = None
    reasoning_effort: str | None = "low"
    telemetry_path: Path | None = None
    raw_capture_dir: Path | None = None

    @classmethod
    def from_env(cls) -> AnthropicConfig:
        key_env = os.environ.get("LLM_API_KEY_ENV", "ANTHROPIC_API_KEY")
        api_key = os.environ.get(key_env, "")
        api_base = os.environ.get("LLM_API_BASE", "")
        model = os.environ.get("LLM_MODEL", "")
        if not api_key or not api_base or not model:
            raise LLMNotConfiguredError(
                "Claude requires LLM_API_BASE, LLM_MODEL and the key named by "
                f"LLM_API_KEY_ENV (currently {key_env})."
            )
        telemetry = os.environ.get("LLM_CALL_LOG_PATH")
        return cls(
            provider=os.environ.get("LLM_PROVIDER", "anthropic"),
            api_base=api_base,
            model=model,
            api_key=api_key,
            anthropic_version=os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
            timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "600")),
            max_retries=int(os.environ.get("LLM_MAX_RETRIES", "1")),
            retry_base_delay_seconds=float(
                os.environ.get("LLM_RETRY_BASE_DELAY_SECONDS", "1")
            ),
            max_retry_delay_seconds=float(
                os.environ.get("LLM_MAX_RETRY_DELAY_SECONDS", "30")
            ),
            max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "12000")),
            max_calls_per_process=int(os.environ.get("LLM_MAX_CALLS_PER_PROCESS", "3")),
            max_total_tokens_per_process=int(
                os.environ.get("LLM_MAX_TOTAL_TOKENS_PER_PROCESS", "45000")
            ),
            input_price_usd_per_million=(
                float(os.environ["LLM_INPUT_PRICE_USD_PER_MILLION"])
                if os.environ.get("LLM_INPUT_PRICE_USD_PER_MILLION")
                else None
            ),
            output_price_usd_per_million=(
                float(os.environ["LLM_OUTPUT_PRICE_USD_PER_MILLION"])
                if os.environ.get("LLM_OUTPUT_PRICE_USD_PER_MILLION")
                else None
            ),
            max_estimated_cost_usd=(
                float(os.environ["LLM_MAX_ESTIMATED_COST_USD"])
                if os.environ.get("LLM_MAX_ESTIMATED_COST_USD")
                else None
            ),
            reasoning_effort=os.environ.get("LLM_REASONING_EFFORT") or None,
            telemetry_path=Path(telemetry) if telemetry else None,
        )


def _default_transport(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        retry_after = _parse_retry_after(
            exc.headers.get("Retry-After") if exc.headers is not None else None
        )
        raise LLMHTTPStatusError(int(exc.code), retry_after, exc.read()) from exc


class AnthropicLLMClient:
    """LLMClient implementation for ``POST /v1/messages``."""

    def __init__(
        self,
        config: AnthropicConfig,
        *,
        transport: Transport | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _default_transport
        self._sleep = sleep or time.sleep
        self.calls: list[dict[str, Any]] = []
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def _check_budget(self) -> None:
        if len(self.calls) >= self.config.max_calls_per_process:
            raise LLMBudgetExceededError("Local LLM call-count budget exhausted")
        if self.total_tokens >= self.config.max_total_tokens_per_process:
            raise LLMBudgetExceededError("Local LLM token budget exhausted")
        if self.config.max_estimated_cost_usd is not None:
            if (
                self.config.input_price_usd_per_million is None
                or self.config.output_price_usd_per_million is None
            ):
                raise LLMBudgetExceededError(
                    "Cost budget requires configured input and output token prices"
                )
            if self.total_cost_usd >= self.config.max_estimated_cost_usd:
                raise LLMBudgetExceededError("Local estimated-cost budget exhausted")

    def _write_telemetry(self, record: dict[str, Any]) -> None:
        path = self.config.telemetry_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_raw_capture(self, filename: str, content: bytes) -> None:
        root = self.config.raw_capture_dir
        if root is None:
            return
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        target = root / filename
        target.write_bytes(content)
        os.chmod(target, 0o600)

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self._check_budget()
        requested_model = model or self.config.model
        system = "\n\n".join(
            item["content"] for item in messages if item.get("role") == "system"
        )
        api_messages = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": requested_model,
            "max_tokens": self.config.max_output_tokens,
            "messages": api_messages,
        }
        if system:
            payload["system"] = system
        requested_temperature = temperature
        temperature_omitted_for_compatibility = (
            temperature is not None
            and temperature != 1
            and _requires_default_temperature(requested_model)
        )
        effective_temperature = (
            None if temperature_omitted_for_compatibility else temperature
        )
        if effective_temperature is not None:
            payload["temperature"] = effective_temperature
        output_config: dict[str, Any] = {}
        if self.config.reasoning_effort:
            output_config["effort"] = self.config.reasoning_effort
        if response_format and response_format.get("type") == "json_schema":
            schema = response_format.get("schema") or response_format.get("json_schema")
            if isinstance(schema, dict) and "schema" in schema:
                schema = schema["schema"]
            if isinstance(schema, dict):
                output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            payload["output_config"] = output_config

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        prompt_hash = hashlib.sha256(body).hexdigest()
        llm_role = detect_llm_role(messages)
        call_id = f"CALL-{len(self.calls) + 1:06d}"
        self._write_raw_capture(f"{call_id}-request.json", body)
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
            "content-type": "application/json",
        }
        url = f"{self.config.api_base.rstrip('/')}/v1/messages"
        started = datetime.now(UTC)
        started_clock = time.perf_counter()
        last_error: Exception | None = None
        retry_events: list[dict[str, Any]] = []
        attempts = 0

        for attempt in range(self.config.max_retries + 1):
            attempts = attempt + 1
            try:
                status, raw = self._transport(url, headers, body, self.config.timeout_seconds)
                self._write_raw_capture(
                    f"{call_id}-attempt-{attempts:02d}-response.json", raw
                )
                if status >= 400:
                    raise LLMHTTPStatusError(status)
                data = json.loads(raw.decode("utf-8"))
                text_blocks = [
                    str(block.get("text", ""))
                    for block in data.get("content", [])
                    if block.get("type") == "text"
                ]
                content = "".join(text_blocks)
                if not content:
                    raise ValueError("Anthropic response contained no text block")
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("input_tokens") or 0)
                completion_tokens = int(usage.get("output_tokens") or 0)
                total_tokens = prompt_tokens + completion_tokens
                estimated_cost_usd: float | None = None
                if (
                    self.config.input_price_usd_per_million is not None
                    and self.config.output_price_usd_per_million is not None
                ):
                    estimated_cost_usd = (
                        prompt_tokens * self.config.input_price_usd_per_million
                        + completion_tokens * self.config.output_price_usd_per_million
                    ) / 1_000_000
                    self.total_cost_usd += estimated_cost_usd
                self.total_tokens += total_tokens
                record = {
                    "call_id": call_id,
                    "provider": self.config.provider,
                    "api_base": self.config.api_base,
                    "requested_model": requested_model,
                    "resolved_model": data.get("model"),
                    "requested_temperature": requested_temperature,
                    "effective_temperature": effective_temperature,
                    "temperature_omitted_for_compatibility": (
                        temperature_omitted_for_compatibility
                    ),
                    "llm_role": llm_role,
                    "call_started_utc": started.isoformat(),
                    "latency_ms": round((time.perf_counter() - started_clock) * 1000, 3),
                    "attempts": attempts,
                    "http_status": status,
                    "prompt_sha256": prompt_hash,
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "reasoning_tokens": (usage.get("output_tokens_details") or {}).get(
                        "thinking_tokens"
                    ),
                    "cached_tokens": usage.get("cache_read_input_tokens"),
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "stop_reason": data.get("stop_reason"),
                    "retry_events": retry_events,
                    "status": "success",
                    "raw_capture_persisted": self.config.raw_capture_dir is not None,
                }
                self.calls.append(record)
                self._write_telemetry(record)
                if data.get("stop_reason") == "max_tokens":
                    raise LLMOutputTruncatedError(
                        "Claude output was truncated at max_output_tokens="
                        f"{self.config.max_output_tokens}"
                    )
                return content
            except LLMOutputTruncatedError:
                raise
            except (LLMHTTPStatusError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if isinstance(exc, LLMHTTPStatusError) and exc.response_body is not None:
                    self._write_raw_capture(
                        f"{call_id}-attempt-{attempts:02d}-response.json",
                        exc.response_body,
                    )
            except (RuntimeError, KeyError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc

            retryable = isinstance(last_error, urllib.error.URLError | TimeoutError)
            status_code: int | None = None
            retry_after_seconds: float | None = None
            if isinstance(last_error, LLMHTTPStatusError):
                status_code = last_error.status_code
                retry_after_seconds = last_error.retry_after_seconds
                retryable = status_code in _RETRYABLE_HTTP_STATUSES
            event: dict[str, Any] = {
                "attempt": attempts,
                "error_type": type(last_error).__name__,
                "http_status": status_code,
                "retryable": retryable,
            }
            can_retry = retryable and attempt < self.config.max_retries
            if can_retry:
                delay = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else self.config.retry_base_delay_seconds * (2**attempt)
                )
                delay = min(max(0.0, delay), self.config.max_retry_delay_seconds)
                event["retry_delay_seconds"] = delay
                retry_events.append(event)
                self._sleep(delay)
            else:
                retry_events.append(event)
                break

        record = {
            "call_id": call_id,
            "provider": self.config.provider,
            "api_base": self.config.api_base,
            "requested_model": requested_model,
            "requested_temperature": requested_temperature,
            "effective_temperature": effective_temperature,
            "temperature_omitted_for_compatibility": (
                temperature_omitted_for_compatibility
            ),
            "llm_role": llm_role,
            "call_started_utc": started.isoformat(),
            "latency_ms": round((time.perf_counter() - started_clock) * 1000, 3),
            "attempts": attempts,
            "http_status": (
                last_error.status_code if isinstance(last_error, LLMHTTPStatusError) else None
            ),
            "prompt_sha256": prompt_hash,
            "status": "failed",
            "error_type": type(last_error).__name__ if last_error else "UnknownError",
            "retry_events": retry_events,
            "raw_capture_persisted": self.config.raw_capture_dir is not None,
        }
        self.calls.append(record)
        self._write_telemetry(record)
        raise RuntimeError("Anthropic LLM call failed") from last_error
