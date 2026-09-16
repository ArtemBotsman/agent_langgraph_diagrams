from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_size_scaling_gold_candidate.py"
SPEC = importlib.util.spec_from_file_location("build_size_scaling_gold_candidate", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_normalize_gold = MODULE._normalize_gold


def test_normalize_gold_derives_complete_trace_contract() -> None:
    request = {
        "functional_requirements": ["Первое", "Второе"],
        "non_functional_requirements": ["Нефункциональное"],
    }
    annotation = {
        "actor_slots": [{"canonical": "Пользователь", "any_of": ["Клиент"]}],
        "use_case_slots": [
            {
                "name": "Выполнить действие",
                "name_aliases": [],
                "primary_actor": "Пользователь",
                "source_fr_ids": ["FR-001", "FR-002"],
                "required_milestones": ["Действие выполнено"],
                "required_branches": [],
            }
        ],
        "known_ambiguity": [],
        "forbidden_assumptions": ["Оплата"],
    }

    gold = _normalize_gold(annotation, request)

    assert gold["fr_coverage"] == {
        "FR-001": "expected_covered",
        "FR-002": "expected_covered",
    }
    assert gold["trace_expectations"] == [
        {"source_fr_id": "FR-001", "allowed_target_uc_slots": ["GUC-001"]},
        {"source_fr_id": "FR-002", "allowed_target_uc_slots": ["GUC-001"]},
    ]
    assert gold["nfr_expectations"] == {"NFR-001": "preserve"}


def test_normalize_gold_rejects_missing_fr() -> None:
    request = {
        "functional_requirements": ["Первое", "Второе"],
        "non_functional_requirements": [],
    }
    annotation = {
        "actor_slots": [{"canonical": "Пользователь", "any_of": []}],
        "use_case_slots": [
            {
                "name": "Выполнить действие",
                "primary_actor": "Пользователь",
                "source_fr_ids": ["FR-001"],
                "required_milestones": ["Действие выполнено"],
            }
        ],
    }
    try:
        _normalize_gold(annotation, request)
    except ValueError as exc:
        assert "FR-002" in str(exc)
    else:
        raise AssertionError("missing FR must be rejected")
