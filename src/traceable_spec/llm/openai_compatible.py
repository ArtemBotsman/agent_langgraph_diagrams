"""Provider-neutral Chat Completions client with local sanitized telemetry.

The adapter supports DeepSeek and other OpenAI-compatible endpoints. It does
not persist API keys or raw prompts/responses. Network calls only happen when
``complete`` is invoked by an explicitly wired live graph.
"""

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
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from traceable_spec.llm.protocol import LLMNotConfiguredError
from traceable_spec.prompts.use_cases import detect_llm_role


class LLMBudgetExceededError(RuntimeError):
    """Raised before a call when the configured local safety budget is exhausted."""


class LLMOutputTruncatedError(RuntimeError):
    """Raised after telemetry is saved when the provider stops at the output limit."""


class LLMHTTPStatusError(RuntimeError):
    """HTTP error with retry metadata but without provider response content."""

    def __init__(
        self,
        status_code: int,
        retry_after_seconds: float | None = None,
        response_body: bytes | None = None,
    ) -> None:
        super().__init__(f"LLM endpoint returned HTTP {status_code}")
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.response_body = response_body


Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]
Sleep = Callable[[float], None]

_RETRYABLE_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


def _parse_retry_after(value: str | None) -> float | None:
    """Parse Retry-After seconds or HTTP date; invalid values are ignored."""

    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    provider: str
    api_base: str
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 90.0
    max_retries: int = 2
    retry_base_delay_seconds: float = 0.5
    max_retry_delay_seconds: float = 60.0
    max_output_tokens: int = 8000
    max_calls_per_process: int = 100
    max_total_tokens_per_process: int = 500_000
    input_price_usd_per_million: float | None = None
    output_price_usd_per_million: float | None = None
    max_estimated_cost_usd: float | None = None
    thinking_enabled: bool = False
    reasoning_effort: str | None = None
    telemetry_path: Path | None = None
    raw_capture_dir: Path | None = None

    @classmethod
    def from_env(cls) -> OpenAICompatibleConfig:
        key_env = os.environ.get("LLM_API_KEY_ENV", "DEEPSEEK_API_KEY")
        api_key = os.environ.get(key_env, "")
        api_base = os.environ.get("LLM_API_BASE", "")
        model = os.environ.get("LLM_MODEL", "")
        if not api_key or not api_base or not model:
            raise LLMNotConfiguredError(
                "Live LLM requires LLM_API_BASE, LLM_MODEL and the key named by "
                f"LLM_API_KEY_ENV (currently {key_env})."
            )
        telemetry = os.environ.get("LLM_CALL_LOG_PATH")
        return cls(
            provider=os.environ.get("LLM_PROVIDER", "openai-compatible"),
            api_base=api_base,
            model=model,
            api_key=api_key,
            timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "90")),
            max_retries=int(os.environ.get("LLM_MAX_RETRIES", "2")),
            retry_base_delay_seconds=float(
                os.environ.get("LLM_RETRY_BASE_DELAY_SECONDS", "0.5")
            ),
            max_retry_delay_seconds=float(
                os.environ.get("LLM_MAX_RETRY_DELAY_SECONDS", "60")
            ),
            max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "8000")),
            max_calls_per_process=int(os.environ.get("LLM_MAX_CALLS_PER_PROCESS", "100")),
            max_total_tokens_per_process=int(
                os.environ.get("LLM_MAX_TOTAL_TOKENS_PER_PROCESS", "500000")
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
            thinking_enabled=os.environ.get("LLM_THINKING", "disabled").casefold() == "enabled",
            reasoning_effort=os.environ.get("LLM_REASONING_EFFORT") or None,
            telemetry_path=Path(telemetry) if telemetry else None,
            raw_capture_dir=None,
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


class OpenAICompatibleLLMClient:
    """Minimal live adapter that satisfies ``LLMClient`` and records token usage."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
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
        """Persist opt-in raw evidence with private filesystem permissions."""

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
        payload: dict[str, Any] = {
            "model": requested_model,
            "messages": messages,
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
        }
        provider = self.config.provider.casefold()
        if provider == "deepseek":
            payload["thinking"] = {
                "type": "enabled" if self.config.thinking_enabled else "disabled"
            }
        elif provider == "groq":
            payload["reasoning_effort"] = self.config.reasoning_effort or (
                "default" if self.config.thinking_enabled else "none"
            )
            payload["reasoning_format"] = "hidden"
        elif self.config.reasoning_effort is not None:
            payload["reasoning_effort"] = self.config.reasoning_effort
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format is not None:
            payload["response_format"] = response_format
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        llm_role = detect_llm_role(messages)
        prompt_hash = hashlib.sha256(body).hexdigest()
        call_id = f"CALL-{len(self.calls) + 1:06d}"
        self._write_raw_capture(f"{call_id}-request.json", body)
        url = f"{self.config.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        started = datetime.now(UTC)
        started_clock = time.perf_counter()
        last_error: Exception | None = None
        attempts = 0
        retry_events: list[dict[str, Any]] = []

        for attempt in range(self.config.max_retries + 1):
            attempts = attempt + 1
            try:
                status, raw = self._transport(
                    url,
                    headers,
                    body,
                    self.config.timeout_seconds,
                )
                self._write_raw_capture(
                    f"{call_id}-attempt-{attempts:02d}-response.json",
                    raw,
                )
                if status >= 400:
                    raise LLMHTTPStatusError(status)
                data = json.loads(raw.decode("utf-8"))
                choice = data["choices"][0]
                content = str(choice["message"]["content"])
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or 0)
                self.total_tokens += total_tokens
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
                record = {
                    "call_id": call_id,
                    "provider": self.config.provider,
                    "api_base": self.config.api_base,
                    "requested_model": requested_model,
                    "llm_role": llm_role,
                    "resolved_model": data.get("model"),
                    "call_started_utc": started.isoformat(),
                    "latency_ms": round((time.perf_counter() - started_clock) * 1000, 3),
                    "attempts": attempts,
                    "http_status": status,
                    "prompt_sha256": prompt_hash,
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    ),
                    "cached_tokens": (usage.get("prompt_tokens_details") or {}).get(
                        "cached_tokens"
                    ),
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "finish_reason": choice.get("finish_reason"),
                    "retry_events": retry_events,
                    "status": "success",
                    "raw_capture_persisted": self.config.raw_capture_dir is not None,
                }
                self.calls.append(record)
                self._write_telemetry(record)
                if choice.get("finish_reason") == "length":
                    raise LLMOutputTruncatedError(
                        "LLM output was truncated at max_output_tokens="
                        f"{self.config.max_output_tokens}"
                    )
                return content
            except LLMOutputTruncatedError:
                raise
            except urllib.error.HTTPError as exc:
                last_error = LLMHTTPStatusError(
                    int(exc.code),
                    _parse_retry_after(
                        exc.headers.get("Retry-After") if exc.headers is not None else None
                    ),
                )
            except (LLMHTTPStatusError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if isinstance(exc, LLMHTTPStatusError) and exc.response_body is not None:
                    self._write_raw_capture(
                        f"{call_id}-attempt-{attempts:02d}-response.json",
                        exc.response_body,
                    )
            except (RuntimeError, KeyError, ValueError) as exc:
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
            delay = 0.0
            if can_retry:
                delay = (
                    retry_after_seconds
                    if retry_after_seconds is not None
                    else self.config.retry_base_delay_seconds * (2**attempt)
                )
                delay = min(max(0.0, delay), self.config.max_retry_delay_seconds)
                event["retry_delay_seconds"] = delay
            retry_events.append(event)
            if not can_retry:
                break
            self._sleep(delay)

        record = {
            "call_id": call_id,
            "provider": self.config.provider,
            "api_base": self.config.api_base,
            "requested_model": requested_model,
            "llm_role": llm_role,
            "call_started_utc": started.isoformat(),
            "latency_ms": round((time.perf_counter() - started_clock) * 1000, 3),
            "attempts": attempts,
            "http_status": (
                last_error.status_code
                if isinstance(last_error, LLMHTTPStatusError)
                else None
            ),
            "prompt_sha256": prompt_hash,
            "status": "failed",
            "error_type": type(last_error).__name__ if last_error else "UnknownError",
            "retry_events": retry_events,
            "raw_capture_persisted": self.config.raw_capture_dir is not None,
        }
        self.calls.append(record)
        self._write_telemetry(record)
        raise RuntimeError("OpenAI-compatible LLM call failed") from last_error
