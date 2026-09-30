"""Explicit provider profiles; credentials are never serialized or printed."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "api_base": "https://api.deepseek.com",
        "input_price": 0.30,
        "output_price": 1.20,
        "env_file": ".env",
        "key_name": "DEEPSEEK_API_KEY",
        "reasoning_effort": None,
    },
    "openai": {
        "provider": "openai",
        "model": "gpt-5.1-2025-11-13",
        "api_base": "https://api.openai.com/v1",
        "input_price": 1.25,
        "output_price": 10.0,
        "env_file": ".env.openai",
        "key_name": "OPENAI_API_KEY",
        "reasoning_effort": "none",
    },
    "anthropic": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "api_base": "https://api.anthropic.com",
        "input_price": 1.0,
        "output_price": 5.0,
        "env_file": ".env.claude",
        "key_name": "ANTHROPIC_API_KEY",
        "reasoning_effort": None,
    },
}


def credential(profile):
    values = {}
    for raw in (ROOT / profile["env_file"]).read_text().splitlines():
        if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
            name, value = raw.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    key = os.environ.get(profile["key_name"]) or values.get(profile["key_name"])
    if not key:
        raise ValueError("Required provider credential is absent")
    return key


def preflight():
    rows = []
    for name, p in PROFILES.items():
        headers = {"Authorization": "Bearer " + credential(p)}
        url = p["api_base"] + "/models"
        if name == "anthropic":
            url = p["api_base"] + "/v1/models?limit=100"
            headers = {"x-api-key": credential(p), "anthropic-version": "2023-06-01"}
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=30
            ) as r:
                data = json.load(r)
            ids = [m["id"] for m in data["data"]]
            rows.append(
                {
                    "provider": name,
                    "requested_model": p["model"],
                    "available": p["model"] in ids,
                    "model_ids": ids,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "provider": name,
                    "available": False,
                    "error_type": type(exc).__name__,
                    "http_status": getattr(exc, "code", None),
                }
            )
    return rows


if __name__ == "__main__":
    print(json.dumps(preflight(), ensure_ascii=False, indent=2))
