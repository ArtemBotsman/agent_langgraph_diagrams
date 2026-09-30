"""Isolated stock OpenCode runner with a loopback-only, budgeted model gateway.

The gateway buffers a non-streaming upstream reply and frames it as SSE. It does
not change prompts, model text, tool arguments, or add any repair/critic loop.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jury_stage13_providers import PROFILES, ROOT, credential
from run_fair_baseline_experiment import ExperimentPaused, dump_new

CLI = ROOT / ".private_tools/opencode-1.18.33/node_modules/.bin/opencode"


def as_sse(data):
    choice = data["choices"][0]
    message = choice["message"]
    delta = {
        k: v
        for k, v in message.items()
        if k in {"role", "content", "tool_calls", "reasoning_content"} and v is not None
    }
    if "tool_calls" in delta:
        delta["tool_calls"] = [{"index": i, **c} for i, c in enumerate(delta["tool_calls"])]
    base = {
        "id": data["id"],
        "object": "chat.completion.chunk",
        "created": data.get("created", int(time.time())),
        "model": data["model"],
    }
    chunks = [
        dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
        dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]),
        dict(base, choices=[], usage=data["usage"]),
    ]
    return (
        "".join("data: " + json.dumps(c, ensure_ascii=False) + "\n\n" for c in chunks)
        + "data: [DONE]\n\n"
    ).encode()


class Gateway:
    def __init__(self, budget, folder, run_id, *, temperature=0.2, mock=False):
        self.budget, self.folder, self.run_id = budget, folder, run_id
        self.temperature, self.mock = temperature, mock
        self.token = secrets.token_hex(24)
        self.calls, self.errors = [], []
        self.lock = threading.Lock()
        folder.mkdir(parents=True, exist_ok=True)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                if (
                    self.path != "/v1/chat/completions"
                    or self.headers.get("Authorization") != "Bearer " + owner.token
                ):
                    self.send_error(403)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 2_000_000:
                    self.send_error(413)
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    data = owner.call(payload)
                    raw = as_sse(data) if payload.get("stream") else json.dumps(data).encode()
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "text/event-stream" if payload.get("stream") else "application/json",
                    )
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except Exception as exc:
                    owner.errors.append({"type": type(exc).__name__})
                    self.send_error(400, type(exc).__name__)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def call(self, original):
        with self.lock:
            if self.errors or self.budget.exhausted:
                raise ExperimentPaused("Gateway is stopped")
            if original.get("model") != "deepseek-flash":
                raise ValueError("Unexpected model")
            if len(self.calls) >= 512:
                raise ValueError("Run call ceiling reached")
            payload = dict(original)
            payload.update(
                model="deepseek-flash",
                stream=False,
                max_tokens=64000,
                temperature=self.temperature,
                thinking={"type": "disabled"},
            )
            for key in ("stream_options", "max_completion_tokens", "reasoning_effort"):
                payload.pop(key, None)
            body = json.dumps(payload, ensure_ascii=False).encode()
            input_upper = len(body) + 1024
            if sum(c["total_tokens"] for c in self.calls) + input_upper + 64000 > 2_000_000:
                raise ValueError("Run token ceiling reached")
            number = len(self.calls) + 1
            key = f"{self.run_id}:gateway-{number}"
            reserve = (input_upper * 0.30 + 64000 * 1.20) / 1e6
            self.budget.reserve(key, reserve)
            started = time.perf_counter()
            cost = None
            try:
                dump_new(self.folder / f"{number:04d}-cli-request.json", original)
                dump_new(self.folder / f"{number:04d}-upstream-request.json", payload)
                if self.mock:
                    data = {
                        "id": "mock",
                        "model": "deepseek-flash",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": '{"mock":true}'},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 10,
                            "total_tokens": 110,
                        },
                    }
                else:
                    req = urllib.request.Request(
                        "https://api.deepseek.com/chat/completions",
                        data=body,
                        headers={
                            "Authorization": "Bearer " + credential(PROFILES["deepseek"]),
                            "Content-Type": "application/json",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=600) as response:
                        data = json.load(response)
                dump_new(self.folder / f"{number:04d}-response.json", data)
                u = data.get("usage", {})
                counts = [u.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
                if (
                    not all(type(n) is int and n >= 0 for n in counts)
                    or counts[0] + counts[1] != counts[2]
                    or counts[0] == 0
                ):
                    raise ValueError("Missing or invalid usage")
                cost = 0.0 if self.mock else (counts[0] * 0.30 + counts[1] * 1.20) / 1e6
                row = {
                    "call_id": number,
                    "prompt_tokens": counts[0],
                    "completion_tokens": counts[1],
                    "total_tokens": counts[2],
                    "estimated_cost_usd": cost,
                    "finish_reason": data["choices"][0]["finish_reason"],
                    "model": data["model"],
                    "temperature": self.temperature,
                    "max_output_tokens": 64000,
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "mock": self.mock,
                    "prompt_sha256": hashlib.sha256(body).hexdigest(),
                }
                self.calls.append(row)
                with (self.folder / "calls.jsonl").open("a") as f:
                    f.write(json.dumps(row) + "\n")
                return data
            finally:
                self.budget.settle(key, cost)
                if cost is None:
                    self.budget.pause("Unknown external planner API cost; review required")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def run_cli(packet, folder, budget, run_id, *, temperature=0.2, mock=False):
    folder.mkdir(parents=True, exist_ok=True)
    gateway = Gateway(budget, folder / "gateway", run_id, temperature=temperature, mock=mock)
    try:
        with tempfile.TemporaryDirectory(prefix="jury-opencode-") as work:
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
                "model": "budget/deepseek-flash",
                "small_model": "budget/deepseek-flash",
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
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "Budget gateway",
                        "options": {
                            "baseURL": f"http://127.0.0.1:{gateway.server.server_port}/v1",
                            "apiKey": gateway.token,
                        },
                        "models": {
                            "deepseek-flash": {
                                "name": "DeepSeek Flash",
                                "tool_call": True,
                                "temperature": True,
                                "reasoning": False,
                                "limit": {"context": 1000000, "output": 64000},
                                "cost": {"input": 0.3, "output": 1.2},
                            }
                        },
                    }
                },
            }
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            safe = json.loads(json.dumps(config))
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
                "budget/deepseek-flash",
                "--title",
                run_id,
                "--file",
                str(work / "task.json"),
                "--",
                "Solve the task in the attached task.json. Preserve your stock planning workflow; "
                "return the requested final JSON package. Do not ask interactive questions; "
                "report unstated requirements as such.",
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
                    "mock": mock,
                },
            )
            return gateway.calls, result.returncode
    finally:
        gateway.close()
