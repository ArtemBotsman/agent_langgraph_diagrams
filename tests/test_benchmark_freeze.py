from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_freeze_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts/freeze_synthetic_benchmark.py"
    spec = importlib.util.spec_from_file_location("freeze_synthetic_benchmark", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load freeze script from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


freeze = _load_freeze_module()


def _point_freeze_script_at(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    monkeypatch.setattr(freeze, "BENCHMARK_DIR", directory)
    monkeypatch.setattr(freeze, "CASES_PATH", directory / "cases.json")
    monkeypatch.setattr(freeze, "MANIFEST_PATH", directory / "manifest.json")
    monkeypatch.setattr(freeze, "FREEZE_RECORD_PATH", directory / "freeze_record.json")


def test_existing_freeze_is_verified_without_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_freeze_script_at(monkeypatch, tmp_path)
    cases = [
        {"case_id": "DEV-001", "split": "development", "gold": {"actors": []}},
        {"case_id": "HID-001", "split": "hidden", "gold": {"actors": []}},
    ]
    (tmp_path / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (tmp_path / "manifest.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["freeze_synthetic_benchmark.py"])

    freeze.main()
    record_before = (tmp_path / "freeze_record.json").read_bytes()
    manifest_before = (tmp_path / "manifest.json").read_bytes()

    freeze.main()

    assert (tmp_path / "freeze_record.json").read_bytes() == record_before
    assert (tmp_path / "manifest.json").read_bytes() == manifest_before


def test_help_does_not_require_or_modify_benchmark_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_freeze_script_at(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["freeze_synthetic_benchmark.py", "--help"])

    with pytest.raises(SystemExit) as raised:
        freeze.main()

    assert raised.value.code == 0
    assert list(tmp_path.iterdir()) == []
