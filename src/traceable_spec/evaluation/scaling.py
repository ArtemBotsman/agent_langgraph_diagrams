"""Size-band metadata and aggregation for input-only scalability benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Any

from traceable_spec.entities import GeneratedSpecification


@dataclass(frozen=True)
class SizeBand:
    """Inclusive functional-requirement interval used by the benchmark."""

    id: str
    label_ru: str
    minimum_fr: int
    maximum_fr: int


SIZE_BANDS = (
    SizeBand("G1_SMALL", "небольшие", 5, 10),
    SizeBand("G2_GROWING", "увеличенные", 11, 20),
    SizeBand("G3_MEDIUM", "средние", 21, 50),
    SizeBand("G4_LARGE", "большие", 51, 75),
)


def classify_fr_count(fr_count: int) -> SizeBand:
    """Map an FR count to the single declared benchmark size band."""

    for band in SIZE_BANDS:
        if band.minimum_fr <= fr_count <= band.maximum_fr:
            return band
    raise ValueError(f"FR count {fr_count} is outside the supported range 5..75")


def artifact_counts(specification: GeneratedSpecification) -> dict[str, int]:
    """Count generated artifacts without requiring a semantic gold reference."""

    use_cases = [] if specification.use_case_set is None else specification.use_case_set.use_cases
    diagrams = [
        result.activity_diagram
        for result in specification.activity_results
        if result.activity_diagram is not None
    ]
    return {
        "use_case_count": len(use_cases),
        "user_story_count": sum(len(item.user_stories) for item in use_cases),
        "system_story_count": sum(len(item.system_stories) for item in use_cases),
        "activity_diagram_count": len(diagrams),
        "activity_node_count": sum(len(item.nodes) for item in diagrams),
        "activity_edge_count": sum(len(item.edges) for item in diagrams),
        "trace_link_count": len(specification.trace_manifest.links),
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return mean(values) if values else None


def _median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return median(values) if values else None


def summarize_scaling_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate run rows by method and size band without requiring gold labels."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["condition"]), str(row["size_group"])), []).append(row)

    order = {band.id: index for index, band in enumerate(SIZE_BANDS)}
    summaries: list[dict[str, Any]] = []
    for (condition, group_id), current in sorted(
        grouped.items(), key=lambda item: (item[0][0], order[item[0][1]])
    ):
        successful = [row for row in current if float(row.get("end_to_end_success", 0)) == 1.0]
        unique_cases = {str(row["case_id"]) for row in current}
        hashes_by_case: dict[str, set[str]] = {}
        for row in current:
            digest = row.get("output_sha256")
            if digest:
                hashes_by_case.setdefault(str(row["case_id"]), set()).add(str(digest))
        stable_cases = sum(1 for hashes in hashes_by_case.values() if len(hashes) == 1)
        summaries.append(
            {
                "condition": condition,
                "size_group": group_id,
                "size_label_ru": str(current[0]["size_label_ru"]),
                "case_count": len(unique_cases),
                "run_count": len(current),
                "successful_runs": len(successful),
                "e2e_success_rate": len(successful) / len(current),
                "schema_validity": _mean(current, "schema_validity"),
                "fr_coverage": _mean(current, "fr_coverage"),
                "trace_completeness": _mean(current, "trace_completeness"),
                "uc_element_trace_coverage": _mean(current, "uc_element_trace_coverage"),
                "activity_element_trace_coverage": _mean(
                    current, "activity_element_trace_coverage"
                ),
                "mean_fr_count": _mean(current, "fr_count"),
                "mean_nfr_count": _mean(current, "nfr_count"),
                "mean_latency_ms": _mean(current, "latency_ms"),
                "median_latency_ms": _median(current, "latency_ms"),
                "mean_llm_calls": _mean(current, "llm_calls"),
                "mean_total_tokens": _mean(current, "total_tokens"),
                "mean_repair_attempts": _mean(current, "repair_attempts"),
                "mean_use_case_count": _mean(current, "use_case_count"),
                "mean_activity_diagram_count": _mean(current, "activity_diagram_count"),
                "mean_activity_node_count": _mean(current, "activity_node_count"),
                "mean_activity_edge_count": _mean(current, "activity_edge_count"),
                "mean_trace_link_count": _mean(current, "trace_link_count"),
                "mean_output_bytes": _mean(current, "output_bytes"),
                "repeat_exact_match_rate": (
                    stable_cases / len(hashes_by_case) if hashes_by_case else None
                ),
            }
        )
    return summaries
