from __future__ import annotations

import pytest

from traceable_spec.evaluation.scaling import classify_fr_count, summarize_scaling_rows


@pytest.mark.parametrize(
    ("fr_count", "expected"),
    [
        (5, "G1_SMALL"),
        (10, "G1_SMALL"),
        (11, "G2_GROWING"),
        (20, "G2_GROWING"),
        (21, "G3_MEDIUM"),
        (50, "G3_MEDIUM"),
        (51, "G4_LARGE"),
        (75, "G4_LARGE"),
    ],
)
def test_classify_fr_count_boundaries(fr_count: int, expected: str) -> None:
    assert classify_fr_count(fr_count).id == expected


def test_classify_fr_count_rejects_outside_protocol() -> None:
    with pytest.raises(ValueError):
        classify_fr_count(4)


def test_scaling_summary_keeps_quality_and_repeat_stability() -> None:
    rows = [
        {
            "condition": "B0_RULE",
            "size_group": "G1_SMALL",
            "size_label_ru": "небольшие",
            "case_id": "SCALE-001",
            "end_to_end_success": 1.0,
            "schema_validity": 1.0,
            "fr_coverage": 1.0,
            "trace_completeness": 1.0,
            "uc_element_trace_coverage": 1.0,
            "activity_element_trace_coverage": 1.0,
            "actor_f1": 0.9,
            "uc_f1": 0.8,
            "milestone_recall": 0.7,
            "branch_recall": 0.6,
            "trace_f1": 0.95,
            "semantic_composite": semantic,
            "hallucination_rate": 0.1,
            "fr_count": 6,
            "nfr_count": 13,
            "latency_ms": latency,
            "llm_calls": 0,
            "total_tokens": 0,
            "repair_attempts": 0,
            "use_case_count": 1,
            "activity_diagram_count": 1,
            "activity_node_count": 8,
            "activity_edge_count": 7,
            "trace_link_count": 30,
            "output_bytes": 1000,
            "output_sha256": "same",
        }
        for latency, semantic in ((10.0, 0.80), (14.0, 0.84))
    ]
    summary = summarize_scaling_rows(rows)[0]
    assert summary["e2e_success_rate"] == 1.0
    assert summary["mean_latency_ms"] == 12.0
    assert summary["repeat_exact_match_rate"] == 1.0
    assert summary["actor_f1"] == 0.9
    assert summary["mean_semantic_stability"] == pytest.approx(0.96)


def test_scaling_summary_retains_usage_from_failed_live_run() -> None:
    rows = [
        {
            "condition": "B1_ONESHOT",
            "size_group": "G1_SMALL",
            "size_label_ru": "небольшие",
            "case_id": "SCALE-001",
            "end_to_end_success": 0.0,
            "fr_count": 6,
            "nfr_count": 4,
            "latency_ms": 100.0,
            "llm_calls": 1,
            "total_tokens": 8000,
        }
    ]
    summary = summarize_scaling_rows(rows)[0]
    assert summary["successful_runs"] == 0
    assert summary["mean_llm_calls"] == 1.0
    assert summary["mean_total_tokens"] == 8000.0
