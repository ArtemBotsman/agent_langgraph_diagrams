"""Stage46 FULL adapter using the same accounting gateway as OpenCode.

Each method owns an ExperimentBudget of at most $1. Money is reserved before
transmission at the gateway's conservative upper tariff and settled using its
cache-aware returned-usage tariff calculation. This is not a provider invoice.
There is no cumulative token ceiling, retry or fallback model. The historical
single-fenced-JSON-object envelope policy applies only to the returned text;
gateway-native response evidence is preserved without changes.
"""

from __future__ import annotations

import copy
import json
import math
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jury_stage13_providers import PROFILES
from jury_stage41_gateway import CacheAwareGateway
from run_fair_baseline_experiment import ExperimentBudget, ExperimentPaused, dump_new
from run_jury_stage15 import json_object

from traceable_spec.llm.openai_compatible import LLMOutputTruncatedError
from traceable_spec.prompts.use_cases import detect_llm_role

MODEL = PROFILES["deepseek"]["model"]
TEMPERATURE = 0.2
OUTPUT_TOKENS = 131072
MAX_RUN_CALLS = 512
MAX_METHOD_BUDGET_USD = 1.0


class Stage46ResponseError(ValueError):
    """Returned envelope cannot safely supply the expected assistant text."""


class CacheAwareFullClient:
    """LLMClient-compatible direct gateway adapter; use as a context manager.

    ``temperature`` from a role prompt is recorded but the frozen experiment
    value 0.2 applies to every call. Optional metadata is saved locally only.
    The same json_object envelope policy as the historical PlanClient unwraps
    a single fenced JSON object. Other text is returned unchanged to the normal
    artifact parser/repair workflow; null, nontext, tool and truncated results
    are not silently converted into text. No request is retried by this adapter.
    """

    def __init__(
        self,
        budget: ExperimentBudget,
        folder: Path,
        run_id: str,
        *,
        transport: Callable[[dict[str, Any]], bytes] | None = None,
    ):
        if not math.isfinite(budget.ceiling) or not 0 < budget.ceiling <= MAX_METHOD_BUDGET_USD:
            raise ValueError("Stage46 requires a separate method budget in (0, $1]")
        folder = Path(folder)
        if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
            raise FileExistsError("Stage46 FULL evidence folder must be new or empty")
        self.budget, self.folder, self.run_id = budget, folder, run_id
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stopped = False
        self._closed = False
        self.gateway = CacheAwareGateway(
            "deepseek",
            budget,
            folder,
            run_id,
            temperature=TEMPERATURE,
            output_tokens=OUTPUT_TOKENS,
            max_run_calls=MAX_RUN_CALLS,
            max_run_tokens=None,
            transport=transport,
        )

    @property
    def call_records(self) -> list[dict[str, Any]]:
        """Accounted attempts, including conservatively settled unknown usage.

        A request rejected before reservation is not counted as an API call.
        Gateway-native rows/files remain unchanged; these are enriched copies.
        """
        return copy.deepcopy(self._records)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.call_records

    @property
    def total_tokens(self) -> int:
        """Known returned tokens only; inspect usage_complete for missing usage."""
        return sum(record.get("total_tokens") or 0 for record in self._records)

    @property
    def total_cost_usd(self) -> float:
        return sum(record["estimated_cost_usd"] for record in self._records)

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if model not in (None, MODEL):
            raise ValueError("Stage46 model is frozen; no model substitution")
        if response_format not in (None, {"type": "json_object"}):
            raise ValueError("Stage46 FULL requires response_format=json_object")
        local_metadata = copy.deepcopy(dict(metadata or {}))
        invocation = {
            "run_id": self.run_id,
            "llm_role": detect_llm_role(messages),
            "requested_temperature": temperature,
            "effective_temperature": TEMPERATURE,
            "requested_model": model,
            "effective_model": MODEL,
            "response_envelope_policy": "run_jury_stage15.json_object",
            "metadata": local_metadata,
        }
        # Validate local serialization before a possible paid transmission.
        json.dumps(invocation, ensure_ascii=False, allow_nan=False)
        original = {
            "model": MODEL,
            "messages": copy.deepcopy(messages),
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        with self._lock:
            if self._closed or self._stopped:
                raise ExperimentPaused("Stage46 FULL client is closed or stopped; inspect evidence")
            start_count = len(self.gateway.calls)
            number = start_count + 1
            spent_before = self.budget.spent
            dump_new(self.folder / f"{number:04d}-full-invocation.json", invocation)
            error: Exception | None = None
            try:
                raw, stream = self.gateway.call(original)
                if stream:
                    raise Stage46ResponseError("Unexpected streamed FULL response")
                data = json.loads(raw)
                choices = data.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    raise Stage46ResponseError("Expected exactly one assistant choice")
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    raise LLMOutputTruncatedError(
                        f"FULL output truncated at max_output_tokens={OUTPUT_TOKENS}"
                    )
                if choice.get("finish_reason") != "stop":
                    raise Stage46ResponseError("FULL response did not finish with stop")
                message = choice.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    raise Stage46ResponseError("Expected an assistant message")
                if (
                    message.get("tool_calls")
                    or message.get("function_call")
                    or message.get("refusal")
                ):
                    raise Stage46ResponseError("FULL response contains tools or refusal")
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise Stage46ResponseError("FULL response must contain nonempty text")
                return json_object(content)
            except Exception as exc:
                error = exc
                self._stopped = True
                raise
            finally:
                recent = self.gateway.calls[start_count:]
                charged = self.budget.spent - spent_before
                if recent:
                    record = copy.deepcopy(recent[-1])
                    record.update(usage_complete=True, accounting_basis="returned_usage_tariff")
                elif charged > 0:
                    # Gateway retained a reservation because usage was unknown,
                    # or settled a returned cost before an invariant failed.
                    record = {
                        "call_id": number,
                        "provider": "deepseek",
                        "model": MODEL,
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "total_tokens": None,
                        "estimated_cost_usd": charged,
                        "usage_complete": False,
                        "accounting_basis": "gateway_failure_settlement_see_budget_ledger",
                        "finish_reason": None,
                    }
                else:
                    record = None
                if record is not None:
                    record.update(
                        **invocation,
                        attempts=1,
                        http_retries=0,
                        cumulative_token_ceiling=None,
                        max_output_tokens=OUTPUT_TOKENS,
                        status="success"
                        if error is None
                        else "truncated"
                        if isinstance(error, LLMOutputTruncatedError)
                        else "error",
                        output_truncated=isinstance(error, LLMOutputTruncatedError),
                        error_type=type(error).__name__ if error is not None else None,
                    )
                    self._records.append(record)
                    dump_new(self.folder / f"{number:04d}-full-call-record.json", record)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.gateway.close()

    def __enter__(self) -> CacheAwareFullClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
