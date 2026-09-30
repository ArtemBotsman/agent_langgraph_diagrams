"""DeepSeek-only diagnostic: cache-aware settlement, no cumulative token cap.

Money is reserved at peak uncached prices BEFORE transmission. Unknown usage
retains the whole reservation and pauses. Stock CLI messages/tools are unchanged.
Old experiment gateway and ledgers are never edited.
"""

import hashlib
import json
import time
import urllib.request

from audit_jury_stage40_resources import price
from jury_opencode_multimodel_v2 import Gateway, as_sse, payload_for
from jury_stage13_providers import PROFILES, credential
from run_fair_baseline_experiment import ExperimentPaused, dump_new


class CacheAwareGateway(Gateway):
    def __init__(self, provider, *args, **kwargs):
        if provider != "deepseek":
            raise ValueError("Stage41 is authorized only for DeepSeek")
        super().__init__(provider, *args, **kwargs)

    def call(self, original):
        with self.lock:
            if self.errors or self.budget.exhausted:
                raise ExperimentPaused("Gateway stopped")
            if len(self.calls) >= self.max_run_calls:
                self.resource_stop(
                    "calls", dict(observed=len(self.calls), ceiling=self.max_run_calls)
                )
            payload = payload_for(original, "deepseek", self.temperature, self.output_tokens)
            body = json.dumps(payload, ensure_ascii=False).encode()
            input_upper = len(body) + 2048
            reserved = (input_upper * 0.30 + self.output_tokens * 1.20) / 1e6
            admission = dict(
                cumulative_token_ceiling=None,
                observed_tokens=sum(c["total_tokens"] for c in self.calls),
                input_upper_bytes=input_upper,
                output_reserved=self.output_tokens,
                money_reserved_usd=reserved,
                money_cap_usd=self.budget.ceiling,
                settled_usd=self.budget.spent,
            )
            with (self.folder / "admissions.jsonl").open("a") as handle:
                handle.write(json.dumps(admission) + "\n")
            number = len(self.calls) + 1
            key = f"{self.run_id}:opencode-{number}"
            self.budget.reserve(key, reserved)
            started, cost = time.perf_counter(), None
            try:
                dump_new(self.folder / f"{number:04d}-cli-request.json", original)
                dump_new(self.folder / f"{number:04d}-upstream-request.json", payload)
                if self.transport:
                    raw = self.transport(payload)
                else:
                    p = PROFILES["deepseek"]
                    request = urllib.request.Request(
                        p["api_base"] + "/chat/completions",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": "Bearer " + credential(p),
                        },
                    )
                    with urllib.request.urlopen(request, timeout=600) as response:
                        raw = response.read()
                (self.folder / f"{number:04d}-native-response.bin").write_bytes(raw)
                data = json.loads(raw)
                calculated = price(data["usage"], data["created"])
                # Fail closed if the provider violates the reservation assumptions.
                # A returned bill is still recorded even if an invariant fails.
                cost = calculated["cache_aware_tariff_estimate_usd"]
                if cost > reserved + 1e-10:
                    self.budget.pause("Returned cost exceeds pre-call reservation")
                    raise ValueError("Reservation invariant failed")
                row = dict(
                    **calculated,
                    prompt_tokens=calculated["input_tokens"],
                    completion_tokens=calculated["output_tokens"],
                    total_tokens=data["usage"]["total_tokens"],
                    estimated_cost_usd=cost,
                    finish_reason=data["choices"][0]["finish_reason"],
                    model=data["model"],
                    call_id=number,
                    provider="deepseek",
                    temperature=self.temperature,
                    max_output_tokens=self.output_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    prompt_sha256=hashlib.sha256(body).hexdigest(),
                )
                self.calls.append(row)
                with (self.folder / "calls.jsonl").open("a") as handle:
                    handle.write(json.dumps(row) + "\n")
                if row["model"] != PROFILES["deepseek"]["model"]:
                    raise ValueError("Returned model mismatch")
                stream = bool(original.get("stream"))
                return (as_sse(data) if stream else raw), stream
            finally:
                self.budget.settle(key, cost)
                if cost is None:
                    self.errors.append({"type": "UnknownUsage"})
                    self.budget.pause("Unknown API usage; full reservation charged conservatively")
