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
from pathlib import Path
from typing import Any

from traceable_spec.llm.protocol import LLMNotConfiguredError


class LLMBudgetExceededError(RuntimeError):
    """Raised before a call when the configured local safety budget is exhausted."""


Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    provider: str
    api_base: str
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 90.0
    max_retries: int = 2
    max_output_tokens: int = 8000
    max_calls_per_process: int = 100
    max_total_tokens_per_process: int = 500_000
    telemetry_path: Path | None = None

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
            max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "8000")),
            max_calls_per_process=int(os.environ.get("LLM_MAX_CALLS_PER_PROCESS", "100")),
            max_total_tokens_per_process=int(
                os.environ.get("LLM_MAX_TOTAL_TOKENS_PER_PROCESS", "500000")
            ),
            telemetry_path=Path(telemetry) if telemetry else None,
        )


def _default_transport(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout: float,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read()


class OpenAICompatibleLLMClient:
    """Minimal live adapter that satisfies ``LLMClient`` and records token usage."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _default_transport
        self.calls: list[dict[str, Any]] = []
        self.total_tokens = 0

    def _check_budget(self) -> None:
        if len(self.calls) >= self.config.max_calls_per_process:
            raise LLMBudgetExceededError("Local LLM call-count budget exhausted")
        if self.total_tokens >= self.config.max_total_tokens_per_process:
            raise LLMBudgetExceededError("Local LLM token budget exhausted")

    def _write_telemetry(self, record: dict[str, Any]) -> None:
        path = self.config.telemetry_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

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
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format is not None:
            payload["response_format"] = response_format
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        prompt_hash = hashlib.sha256(body).hexdigest()
        url = f"{self.config.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        started = datetime.now(UTC)
        started_clock = time.perf_counter()
        last_error: Exception | None = None
        attempts = 0

        for attempt in range(self.config.max_retries + 1):
            attempts = attempt + 1
            try:
                status, raw = self._transport(
                    url,
                    headers,
                    body,
                    self.config.timeout_seconds,
                )
                if status >= 400:
                    raise RuntimeError(f"LLM endpoint returned HTTP {status}")
                data = json.loads(raw.decode("utf-8"))
                choice = data["choices"][0]
                content = str(choice["message"]["content"])
                usage = data.get("usage") or {}
                total_tokens = int(usage.get("total_tokens") or 0)
                self.total_tokens += total_tokens
                record = {
                    "provider": self.config.provider,
                    "api_base": self.config.api_base,
                    "requested_model": requested_model,
                    "resolved_model": data.get("model"),
                    "call_started_utc": started.isoformat(),
                    "latency_ms": round((time.perf_counter() - started_clock) * 1000, 3),
                    "attempts": attempts,
                    "http_status": status,
                    "prompt_sha256": prompt_hash,
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
                        "reasoning_tokens"
                    ),
                    "cached_tokens": (usage.get("prompt_tokens_details") or {}).get(
                        "cached_tokens"
                    ),
                    "total_tokens": total_tokens,
                    "finish_reason": choice.get("finish_reason"),
                    "status": "success",
                }
                self.calls.append(record)
                self._write_telemetry(record)
                return content
            except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, ValueError) as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                time.sleep(0.5 * (2**attempt))

        record = {
            "provider": self.config.provider,
            "api_base": self.config.api_base,
            "requested_model": requested_model,
            "call_started_utc": started.isoformat(),
            "latency_ms": round((time.perf_counter() - started_clock) * 1000, 3),
            "attempts": attempts,
            "prompt_sha256": prompt_hash,
            "status": "failed",
            "error_type": type(last_error).__name__ if last_error else "UnknownError",
        }
        self.calls.append(record)
        self._write_telemetry(record)
        raise RuntimeError("OpenAI-compatible LLM call failed") from last_error
