"""Stock OpenCode 1.18.33 behind a budget gateway for three native backends.

OpenAI-compatible responses are buffered and SSE-framed without text/tool edits.
Anthropic Messages SSE bytes are passed through unchanged, including tool blocks.
No provider credentials enter the CLI environment. No retries or fallback models.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jury_opencode_gateway import CLI, as_sse
from jury_stage13_providers import PROFILES, credential
from run_fair_baseline_experiment import ExperimentPaused, dump_new

VERSION = "opencode-native-three-provider-v2-resource-audit"
OUTPUT = 64000


def payload_for(original, provider, temperature, output_tokens=OUTPUT):
    p = PROFILES[provider]
    if original.get("model") != p["model"]:
        raise ValueError("Unexpected model; no substitution")
    payload = copy.deepcopy(original)
    if (
        not isinstance(output_tokens, int)
        or not 1
        <= output_tokens
        <= {"deepseek": 131072, "openai": 128000, "anthropic": 64000}[provider]
    ):
        raise ValueError("Unsupported output ceiling")
    payload.update(temperature=temperature, max_tokens=output_tokens)
    for key in ("stream_options", "max_completion_tokens", "reasoning_effort", "thinking"):
        payload.pop(key, None)
    if provider == "anthropic":
        # Native SDK messages, tools, system and cache controls remain unaltered.
        payload["stream"] = True
    else:
        payload["stream"] = False
        if provider == "openai":
            payload["max_completion_tokens"] = payload.pop("max_tokens")
            payload["reasoning_effort"] = "none"
        else:
            payload["thinking"] = {"type": "disabled"}
    return payload


def anthropic_usage(raw):
    usage, stop, model = {}, None, None
    stopped = False
    for line in raw.decode("utf-8").splitlines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:])
        if event.get("type") == "error":
            raise ValueError("Anthropic stream error")
        if event.get("type") == "message_start":
            message = event["message"]
            model = message["model"]
            usage.update(message["usage"])
        elif event.get("type") == "message_delta":
            usage.update(event.get("usage", {}))
            stop = event.get("delta", {}).get("stop_reason", stop)
        elif event.get("type") == "message_stop":
            stopped = True
    if not stopped or stop is None or model is None:
        raise ValueError("Incomplete Anthropic stream")
    counts = [
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        usage.get("cache_creation_input_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
    ]
    if not all(type(n) is int and n >= 0 for n in counts) or sum(counts[::2]) + counts[3] == 0:
        raise ValueError("Missing Anthropic usage")
    inp, out, create, read = counts
    # Conservative upper bound: even 1-hour cache creation costs <=2x base input.
    cost = (inp + 2 * create + read + out * 5) / 1e6
    return {
        "prompt_tokens": inp + create + read,
        "completion_tokens": out,
        "total_tokens": sum(counts),
        "estimated_cost_usd": cost,
        "finish_reason": stop,
        "model": model,
        "native_usage": usage,
    }


class RunResourceStop(ExperimentPaused):
    """A local safety stop, never a model output truncation."""


class Gateway:
    def __init__(
        self,
        provider,
        budget,
        folder,
        run_id,
        *,
        temperature=0.2,
        transport=None,
        output_tokens=OUTPUT,
        max_run_tokens=8_000_000,
        max_run_calls=512,
    ):
        if provider not in PROFILES:
            raise ValueError("Unsupported provider")
        self.provider, self.budget, self.folder, self.run_id = provider, budget, folder, run_id
        self.temperature, self.transport = temperature, transport
        self.output_tokens = output_tokens
        self.max_run_tokens, self.max_run_calls = max_run_tokens, max_run_calls
        self.token, self.calls, self.errors = secrets.token_hex(24), [], []
        self.lock = threading.Lock()
        folder.mkdir(parents=True, exist_ok=True)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                expected = "/v1/messages" if provider == "anthropic" else "/v1/chat/completions"
                authorized = (
                    self.headers.get("x-api-key") == owner.token
                    if provider == "anthropic"
                    else self.headers.get("Authorization") == "Bearer " + owner.token
                )
                if self.path.split("?")[0] != expected or not authorized:
                    self.send_error(403)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 2_000_000:
                    self.send_error(413)
                    return
                try:
                    raw, stream = owner.call(json.loads(self.rfile.read(length)))
                    self.send_response(200)
                    self.send_header(
                        "Content-Type", "text/event-stream" if stream else "application/json"
                    )
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except Exception as exc:
                    owner.errors.append({"type": type(exc).__name__, "detail": str(exc)[:500]})
                    self.send_error(400, type(exc).__name__)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def call(self, original):
        with self.lock:
            if self.errors or self.budget.exhausted:
                raise ExperimentPaused("Gateway stopped")
            if len(self.calls) >= self.max_run_calls:
                self.resource_stop(
                    "calls", dict(observed=len(self.calls), ceiling=self.max_run_calls)
                )
            payload = payload_for(original, self.provider, self.temperature, self.output_tokens)
            body = json.dumps(payload, ensure_ascii=False).encode()
            inp = len(body) + 2048
            observed = sum(c["total_tokens"] for c in self.calls)
            admission = dict(
                observed_tokens=observed,
                input_upper_bytes=inp,
                output_reserved=self.output_tokens,
                ceiling=self.max_run_tokens,
            )
            with (self.folder / "admissions.jsonl").open("a") as f:
                f.write(json.dumps(admission) + "\n")
            if observed + inp + self.output_tokens > self.max_run_tokens:
                self.resource_stop("tokens", admission)
            p = PROFILES[self.provider]
            input_rate = p["input_price"] * (2 if self.provider == "anthropic" else 1)
            reserve = (inp * input_rate + self.output_tokens * p["output_price"]) / 1e6
            number = len(self.calls) + 1
            key = f"{self.run_id}:opencode-{number}"
            self.budget.reserve(key, reserve)
            started, cost = time.perf_counter(), None
            try:
                dump_new(self.folder / f"{number:04d}-cli-request.json", original)
                dump_new(self.folder / f"{number:04d}-upstream-request.json", payload)
                if self.transport:
                    raw = self.transport(payload)
                else:
                    headers = {"Content-Type": "application/json"}
                    if self.provider == "anthropic":
                        url = p["api_base"] + "/v1/messages"
                        headers.update(
                            {"x-api-key": credential(p), "anthropic-version": "2023-06-01"}
                        )
                    else:
                        url = p["api_base"] + "/chat/completions"
                        headers["Authorization"] = "Bearer " + credential(p)
                    req = urllib.request.Request(url, data=body, headers=headers)
                    with urllib.request.urlopen(req, timeout=600) as response:
                        raw = response.read()
                (self.folder / f"{number:04d}-native-response.bin").write_bytes(raw)
                if self.provider == "anthropic":
                    row = anthropic_usage(raw)
                    response_raw, stream = raw, True
                else:
                    data = json.loads(raw)
                    usage = data.get("usage", {})
                    counts = [
                        usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    ]
                    if (
                        not all(type(n) is int and n >= 0 for n in counts)
                        or counts[0] + counts[1] != counts[2]
                        or not counts[0]
                    ):
                        raise ValueError("Missing or invalid usage")
                    row = dict(
                        zip(
                            ("prompt_tokens", "completion_tokens", "total_tokens"),
                            counts,
                            strict=True,
                        )
                    )
                    row.update(
                        estimated_cost_usd=(
                            counts[0] * p["input_price"] + counts[1] * p["output_price"]
                        )
                        / 1e6,
                        finish_reason=data["choices"][0]["finish_reason"],
                        model=data["model"],
                    )
                    stream = bool(original.get("stream"))
                    response_raw = as_sse(data) if stream else raw
                cost = row["estimated_cost_usd"]
                row.update(
                    call_id=number,
                    provider=self.provider,
                    temperature=self.temperature,
                    max_output_tokens=self.output_tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    prompt_sha256=hashlib.sha256(body).hexdigest(),
                )
                self.calls.append(row)
                with (self.folder / "calls.jsonl").open("a") as f:
                    f.write(json.dumps(row) + "\n")
                if row["model"] != p["model"]:
                    raise ValueError("Returned model mismatch")
                return response_raw, stream
            finally:
                self.budget.settle(key, cost)
                if cost is None:
                    self.errors.append({"type": "UnknownUsage"})
                    self.budget.pause(
                        "Unknown external planner API cost; full reservation retained"
                    )

    def resource_stop(self, kind, details):
        record = dict(kind=kind, **details)
        dump_new(self.folder / "resource_stop.json", record)
        raise RunResourceStop(json.dumps(record))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def run_cli(packet, folder, budget, run_id, *, provider, temperature=0.2, transport=None):
    folder.mkdir(parents=True, exist_ok=True)
    gateway = Gateway(
        provider, budget, folder / "gateway", run_id, temperature=temperature, transport=transport
    )
    p = PROFILES[provider]
    try:
        with tempfile.TemporaryDirectory(prefix="jury-multimodel-") as work:
            work = Path(work)
            dump_new(work / "task.json", packet)
            env = {
                k: os.environ[k]
                for k in ("PATH", "HOME", "USER", "SHELL", "TMPDIR", "LANG")
                if k in os.environ
            }
            for kind in ("CONFIG", "DATA", "CACHE", "STATE"):
                env[f"XDG_{kind}_HOME"] = str(work / kind.lower())
            for name in (
                "AUTOUPDATE",
                "MODELS_FETCH",
                "PROJECT_CONFIG",
                "SHARE",
                "DEFAULT_PLUGINS",
                "CLAUDE_CODE",
                "EXTERNAL_SKILLS",
                "LSP_DOWNLOAD",
            ):
                env["OPENCODE_DISABLE_" + name] = "1"
            env["OPENCODE_CONFIG_DIR"] = str(work / "config")
            env["OPENCODE_DB"] = str(folder / "opencode.sqlite")
            config = {
                "$schema": "https://opencode.ai/config.json",
                "enabled_providers": ["budget"],
                "model": "budget/" + p["model"],
                "small_model": "budget/" + p["model"],
                "share": "disabled",
                "autoupdate": False,
                "snapshot": False,
                "lsp": False,
                "formatter": False,
                "plugin": [],
                "mcp": {},
                "permission": {
                    "*": "deny",
                    "read": {"*": "deny", str(work / "task.json"): "allow"},
                    "todowrite": "allow",
                    "external_directory": "deny",
                },
                "agent": {"plan": {"temperature": temperature, "steps": 512}},
                "provider": {
                    "budget": {
                        "npm": "@ai-sdk/anthropic"
                        if provider == "anthropic"
                        else "@ai-sdk/openai-compatible",
                        "name": "Budget gateway",
                        "options": {
                            "baseURL": f"http://127.0.0.1:{gateway.server.server_port}/v1",
                            "apiKey": gateway.token,
                        },
                        "models": {
                            p["model"]: {
                                "name": p["model"],
                                "tool_call": True,
                                "temperature": True,
                                "reasoning": False,
                                "limit": {
                                    "context": {
                                        "deepseek": 1000000,
                                        "openai": 400000,
                                        "anthropic": 200000,
                                    }[provider],
                                    "output": OUTPUT,
                                },
                                "cost": {"input": p["input_price"], "output": p["output_price"]},
                            }
                        },
                    }
                },
            }
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            safe = copy.deepcopy(config)
            safe["provider"]["budget"]["options"]["apiKey"] = "LOCAL_TOKEN_REDACTED"
            dump_new(folder / "config.json", safe)
            command = [
                str(CLI),
                "run",
                "--pure",
                "--format",
                "json",
                "--agent",
                "plan",
                "--model",
                "budget/" + p["model"],
                "--title",
                run_id,
                "--file",
                str(work / "task.json"),
                "--",
                "Plan the implementation of the attached task.json using your stock "
                "planning workflow. Return a clear final implementation plan as text, "
                "not code. Preserve all stated requirements. No interactive answers "
                "are available: explicitly flag necessary missing facts instead of inventing them.",
            ]
            with (
                (folder / "events.jsonl").open("w") as out,
                (folder / "stderr.txt").open("w") as err,
            ):
                result = subprocess.run(
                    command, cwd=work, env=env, stdout=out, stderr=err, timeout=3600
                )
            dump_new(
                folder / "cli_result.json",
                {
                    "returncode": result.returncode,
                    "calls": len(gateway.calls),
                    "errors": gateway.errors,
                    "provider": provider,
                },
            )
            if gateway.errors:
                raise ExperimentPaused("OpenCode gateway error; inspect saved evidence")
            return gateway.calls, result.returncode
    finally:
        gateway.close()
