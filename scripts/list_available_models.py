"""List model IDs available to a local OpenAI-compatible API key."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load_local_env(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Environment file does not exist: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def _model_ids(payload: dict[str, Any]) -> list[str]:
    records = payload.get("data")
    if not isinstance(records, list):
        raise ValueError("Provider response does not contain a data list")
    return sorted(
        {
            str(record["id"])
            for record in records
            if isinstance(record, dict) and record.get("id")
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List model IDs without printing or saving the API key."
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.openai")
    parser.add_argument("--contains", default="", help="Case-insensitive ID filter")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    _load_local_env(args.env_file)
    api_base = os.environ.get("LLM_API_BASE", "").rstrip("/")
    key_name = os.environ.get("LLM_API_KEY_ENV", "OPENAI_API_KEY")
    api_key = os.environ.get(key_name, "")
    if not api_base or not api_key:
        raise SystemExit(
            "Set LLM_API_BASE, LLM_API_KEY_ENV and the referenced key in the local env file."
        )

    request = urllib.request.Request(
        f"{api_base}/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Model listing failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Model listing failed: {type(exc).__name__}") from exc

    needle = args.contains.casefold()
    ids = [model_id for model_id in _model_ids(payload) if needle in model_id.casefold()]
    if not ids:
        raise SystemExit("No model IDs matched the requested filter.")
    print("\n".join(ids))


if __name__ == "__main__":
    main()
