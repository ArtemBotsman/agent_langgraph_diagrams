"""Scripted/fake LLMClient for offline orchestration tests — NOT a real AI call.

Replace with a LiteLLM / OpenAI-compatible adapter implementing LLMClient later;
the Use Cases graph nodes do not need to change.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from traceable_spec.prompts.use_cases import detect_llm_role


class ScriptedLLMClient:
    """Deterministic fake client that returns queued responses by prompt role.

    This is intentionally named and documented as scripted/fake. It does not
    contact any network endpoint and must not be presented as a live model.
    """

    def __init__(
        self,
        scripts: dict[str, list[str]] | None = None,
        *,
        default_response: str | None = None,
    ) -> None:
        self._queues: dict[str, deque[str]] = defaultdict(deque)
        if scripts:
            for role, responses in scripts.items():
                self._queues[role].extend(responses)
        self._default_response = default_response
        self.calls: list[dict[str, Any]] = []

    def enqueue(self, role: str, response: str) -> None:
        self._queues[role].append(response)

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        role = detect_llm_role(messages) or "unknown"
        self.calls.append(
            {
                "role": role,
                "model": model,
                "temperature": temperature,
                "response_format": response_format,
                "message_count": len(messages),
            }
        )
        queue = self._queues.get(role)
        if queue:
            return queue.popleft()
        if self._default_response is not None:
            return self._default_response
        raise RuntimeError(
            f"ScriptedLLMClient has no queued response for role={role!r}. "
            "This fake client is for orchestration tests only."
        )
