from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "score_expert_review.py"
    spec = importlib.util.spec_from_file_location("score_expert_review", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weighted_kappa_is_one_for_identical_ratings() -> None:
    scorer = _module()
    assert scorer._weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0


def test_weighted_kappa_penalizes_reversed_ratings() -> None:
    scorer = _module()
    assert scorer._weighted_kappa([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) < 0.0
