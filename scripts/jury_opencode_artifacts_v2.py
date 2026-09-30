"""Stock OpenCode Build with an artifact task and writes only to a disposable output folder.

No custom system prompt, FULL critic, repair loop, Gold or semantic post-processing.
Build rather than read-only Plan permits multi-file packages without one-answer truncation.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from jury_opencode_multimodel_v2 import CLI, Gateway
from jury_stage13_providers import PROFILES
from run_fair_baseline_experiment import ExperimentPaused, dump_new

from traceable_spec.entities import OneShotGenerationArtifact
from traceable_spec.reference_methods.opencode_plan import task_contract


def packet(request):
    data = task_contract(request)
    data["task"] = (
        "Prepare the complete typed Use Case and Activity specification, NOT program code. "
        "Follow the given schemas and trace rules. Use your stock agent workflow. "
        "Write final artifacts under output/. You may split work into as many tool "
        "calls and files as needed. Do not invent unsupported business rules."
    )
    data["delivery"] = {
        "single_file": "output/package.json contains the entire output_schema object",
        "split_files": "OR output/use_case_set.json contains the use_case_set object; "
        "output/activities/*.json each contains one ActivityDiagram object; "
        "optional output/trace_manifest.json contains TraceManifest object",
        "selection": "Choose exactly one format. Do not leave both a package and split UC file.",
        "other": "No tests, Gold, implementations, evaluator, shell or network access. "
        "No interactive answers. Flag missing business facts, do not assume their values.",
    }
    return data


def import_files(folder):
    single, split = folder / "package.json", folder / "use_case_set.json"
    if single.exists() == split.exists():
        raise ValueError("Expected exactly one delivery format")
    if single.exists():
        value = json.loads(single.read_text())
    else:
        value = dict(
            use_case_set=json.loads(split.read_text()),
            activity_diagrams=[
                json.loads(p.read_text()) for p in sorted((folder / "activities").glob("*.json"))
            ],
            trace_manifest=json.loads((folder / "trace_manifest.json").read_text())
            if (folder / "trace_manifest.json").exists()
            else {},
        )
    # This parses only, without repair or filling missing semantic fields.
    return OneShotGenerationArtifact.model_validate(value)


def run_artifacts(request, folder, budget, run_id, *, provider="deepseek", transport=None):
    folder.mkdir(parents=True, exist_ok=False)
    output_tokens = 131072 if provider == "deepseek" else 64000
    gateway = Gateway(
        provider,
        budget,
        folder / "gateway",
        run_id,
        temperature=0.2,
        transport=transport,
        output_tokens=output_tokens,
        max_run_tokens=8_000_000,
    )
    p = PROFILES[provider]
    try:
        with tempfile.TemporaryDirectory(prefix="jury-typed-opencode-") as temporary:
            work = Path(temporary).resolve()
            # OpenCode's edit patterns are relative to its Git worktree. Without a
            # repository it uses a global root, not the disposable cwd.
            subprocess.run(["git", "init", "--quiet", str(work)], check=True, capture_output=True)
            (work / "output").mkdir()
            dump_new(work / "task.json", packet(request))
            dump_new(folder / "task.json", packet(request))
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
            paths = {"*": "deny", "output/**": "allow", str(work / "output") + "/**": "allow"}
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
                    "read": {**paths, "task.json": "allow", str(work / "task.json"): "allow"},
                    "edit": paths,
                    "todowrite": "allow",
                    "external_directory": "deny",
                },
                "agent": {"build": {"temperature": 0.2, "steps": 512}},
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
                                    "context": 1000000 if provider == "deepseek" else 200000,
                                    "output": output_tokens,
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
                "build",
                "--model",
                "budget/" + p["model"],
                "--title",
                run_id,
                "--file",
                str(work / "task.json"),
                "--",
                "Complete the analytical artifact task in task.json. Write the complete "
                "JSON specification to the allowed output directory. Do not implement "
                "application code. Splitting into files is allowed as specified in delivery.",
            ]
            try:
                with (
                    (folder / "events.jsonl").open("w") as stdout,
                    (folder / "stderr.txt").open("w") as stderr,
                ):
                    result = subprocess.run(
                        command, cwd=work, env=env, stdout=stdout, stderr=stderr, timeout=3600
                    )
            finally:
                # Only regular output files are imported; links never cross the workspace boundary.
                target = folder / "delivered"
                target.mkdir()
                for file in (work / "output").rglob("*"):
                    if file.is_symlink():
                        raise ValueError("Output symlink rejected")
                    if file.is_file():
                        if file.stat().st_size > 32_000_000:
                            raise ValueError("Oversized artifact")
                        dest = target / file.relative_to(work / "output")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(file, dest)
            dump_new(
                folder / "cli_result.json",
                dict(returncode=result.returncode, calls=len(gateway.calls), errors=gateway.errors),
            )
            if gateway.errors:
                raise ExperimentPaused("OpenCode gateway error; reconcile before retry")
            return gateway.calls, result.returncode
    finally:
        gateway.close()
