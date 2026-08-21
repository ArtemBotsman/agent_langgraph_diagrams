"""LLM client Protocol — no provider lock-in; no real calls in this scaffold."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """OpenAI-compatible / LiteLLM-shaped interface for future LLM nodes."""

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Return assistant text content. Must not be called by stub nodes."""
        ...


class LLMNotConfiguredError(RuntimeError):
    """Raised when a real LLM node is invoked without a configured client."""
