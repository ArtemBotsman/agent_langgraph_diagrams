"""Gold-aware semantic metrics for the synthetic benchmark candidate.

The evaluator compares semantic slots rather than rendered pixels or generated
identifiers. It is deliberately separate from schema/structural validators and
from human/LLM-as-a-judge evaluation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any

WORD_RE = re.compile(r"[\w]+", flags=re.UNICODE)
SimilarityFn = Callable[[str, str], float]


def _normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(text.casefold()))


def _similarity(left: str, right: str) -> float:
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    token_f1 = 2 * len(a_tokens & b_tokens) / (len(a_tokens) + len(b_tokens))
    return max(token_f1, SequenceMatcher(None, a, b).ratio())


def _prf(matched: int, predicted: int, expected: int) -> dict[str, float]:
    precision = matched / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = matched / expected if expected else 1.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def _max_slot_matches(
    predicted_labels: list[str],
    gold_slots: list[dict[str, Any]],
    *,
    threshold: float = 0.62,
    similarity: SimilarityFn = _similarity,
) -> tuple[int, dict[int, int]]:
    """Greedy one-to-one label/alias matching with deterministic tie breaking."""

    candidates: list[tuple[float, int, int]] = []
    for pred_idx, label in enumerate(predicted_labels):
        for gold_idx, slot in enumerate(gold_slots):
            accepted = [slot.get("canonical") or slot.get("name") or ""]
            accepted.extend(slot.get("any_of") or slot.get("name_aliases") or [])
            score = max((similarity(label, item) for item in accepted), default=0.0)
            if score >= threshold:
                candidates.append((score, pred_idx, gold_idx))

    used_pred: set[int] = set()
    used_gold: set[int] = set()
    mapping: dict[int, int] = {}
    for _, pred_idx, gold_idx in sorted(candidates, key=lambda row: (-row[0], row[1], row[2])):
        if pred_idx in used_pred or gold_idx in used_gold:
            continue
        used_pred.add(pred_idx)
        used_gold.add(gold_idx)
        mapping[pred_idx] = gold_idx
    return len(mapping), mapping


def _map_use_cases(
    predicted: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    allow_split_merge: bool,
    similarity: SimilarityFn,
) -> tuple[dict[str, float], dict[int, int]]:
    """Match UC semantics and optionally accept supported split/merge boundaries."""

    if not allow_split_merge:
        matched, one_to_one_mapping = _max_slot_matches(
            [str(item.get("name", "")) for item in predicted],
            gold,
            threshold=0.55,
            similarity=similarity,
        )
        return _prf(matched, len(predicted), len(gold)), one_to_one_mapping

    mapping: dict[int, int] = {}
    for pred_idx, predicted_uc in enumerate(predicted):
        predicted_frs = {str(item) for item in predicted_uc.get("source_fr_ids", [])}
        candidates: list[tuple[float, int]] = []
        for gold_idx, gold_uc in enumerate(gold):
            gold_frs = {str(item) for item in gold_uc.get("source_fr_ids", [])}
            intersection = len(predicted_frs & gold_frs)
            union = len(predicted_frs | gold_frs)
            fr_jaccard = intersection / union if union else 0.0
            names = [str(gold_uc.get("name", "")), *map(str, gold_uc.get("name_aliases", []))]
            name_score = max(
                (similarity(str(predicted_uc.get("name", "")), name) for name in names),
                default=0.0,
            )
            supported_boundary = bool(intersection) and (
                predicted_frs <= gold_frs or gold_frs <= predicted_frs
            )
            if name_score >= 0.55 or supported_boundary:
                candidates.append((0.65 * fr_jaccard + 0.35 * name_score, gold_idx))
        if candidates:
            mapping[pred_idx] = max(candidates, key=lambda item: (item[0], -item[1]))[1]
    precision = len(mapping) / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = len(set(mapping.values())) / len(gold) if gold else 1.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}, mapping


def evaluate_semantic_projection(
    prediction: dict[str, Any],
    gold: dict[str, Any],
    *,
    similarity: SimilarityFn | None = None,
    similarity_name: str = "lexical_sequence_candidate",
) -> dict[str, float | str]:
    """Score a provider-neutral projection against semantic gold slots.

    Expected prediction format:
    ``actors: list[str]`` and ``use_cases`` with ``name``, ``source_fr_ids``,
    ``milestones`` and ``branches`` (condition + outcomes). Diagram coordinates,
    Mermaid syntax, generated IDs and harmless action-node splitting are ignored.
    """

    similarity_fn = similarity or _similarity
    predicted_actors = [str(item) for item in prediction.get("actors", [])]
    actor_slots = list(gold.get("actor_slots", []))
    actor_matches, _ = _max_slot_matches(
        predicted_actors,
        actor_slots,
        similarity=similarity_fn,
    )
    actor_scores = _prf(actor_matches, len(predicted_actors), len(actor_slots))

    predicted_ucs = list(prediction.get("use_cases", []))
    gold_ucs = list(gold.get("use_case_slots", []))
    uc_scores, uc_mapping = _map_use_cases(
        predicted_ucs,
        gold_ucs,
        allow_split_merge=bool(
            gold.get("equivalence_policy", {}).get("allow_uc_split_merge", False)
        ),
        similarity=similarity_fn,
    )
    uc_matches = len(uc_mapping)

    matched_milestones = 0
    predicted_milestones = sum(len(uc.get("milestones", [])) for uc in predicted_ucs)
    expected_milestones = sum(len(uc.get("required_milestones", [])) for uc in gold_ucs)
    matched_branches = 0
    predicted_branches = sum(len(uc.get("branches", [])) for uc in predicted_ucs)
    expected_branches = sum(len(uc.get("required_branches", [])) for uc in gold_ucs)
    predicted_trace: set[tuple[str, str]] = set()
    expected_trace: set[tuple[str, str]] = set()

    for gold_uc in gold_ucs:
        for fr_id in gold_uc.get("source_fr_ids", []):
            expected_trace.add((str(fr_id), str(gold_uc["slot_id"])))

    for gold_idx, gold_uc in enumerate(gold_ucs):
        mapped_predictions = [
            predicted_uc
            for pred_idx, predicted_uc in enumerate(predicted_ucs)
            if uc_mapping.get(pred_idx) == gold_idx
        ]
        if not mapped_predictions:
            continue
        milestone_slots = [
            {"canonical": item, "any_of": []} for item in gold_uc.get("required_milestones", [])
        ]
        current_matches, _ = _max_slot_matches(
            [
                str(item)
                for predicted_uc in mapped_predictions
                for item in predicted_uc.get("milestones", [])
            ],
            milestone_slots,
            similarity=similarity_fn,
        )
        matched_milestones += current_matches

        gold_branches = list(gold_uc.get("required_branches", []))
        branch_slots = [
            {
                "canonical": " ".join(
                    [str(item.get("condition", "")), *map(str, item.get("required_outcomes", []))]
                ),
                "any_of": [],
            }
            for item in gold_branches
        ]
        predicted_branch_labels = [
            " ".join([str(item.get("condition", "")), *map(str, item.get("outcomes", []))])
            for predicted_uc in mapped_predictions
            for item in predicted_uc.get("branches", [])
        ]
        current_branch_matches, _ = _max_slot_matches(
            predicted_branch_labels,
            branch_slots,
            threshold=0.55,
            similarity=similarity_fn,
        )
        matched_branches += current_branch_matches

        for predicted_uc in mapped_predictions:
            for fr_id in predicted_uc.get("source_fr_ids", []):
                predicted_trace.add((str(fr_id), str(gold_uc["slot_id"])))

    milestone_scores = _prf(
        matched_milestones,
        predicted_milestones,
        expected_milestones,
    )
    branch_scores = _prf(matched_branches, predicted_branches, expected_branches)
    trace_matches = len(predicted_trace & expected_trace)
    trace_scores = _prf(trace_matches, len(predicted_trace), len(expected_trace))

    total_predicted = (
        len(predicted_actors)
        + len(predicted_ucs)
        + predicted_milestones
        + predicted_branches
        + len(predicted_trace)
    )
    total_matched = (
        actor_matches + uc_matches + matched_milestones + matched_branches + trace_matches
    )
    hallucination_rate = (
        (total_predicted - total_matched) / total_predicted if total_predicted else 0.0
    )

    # Dashboard-only composite. Research claims must report the dimensions above.
    composite = (
        0.15 * actor_scores["f1"]
        + 0.25 * uc_scores["f1"]
        + 0.25 * milestone_scores["f1"]
        + 0.15 * branch_scores["f1"]
        + 0.20 * trace_scores["f1"]
    )
    return {
        "actor_precision": actor_scores["precision"],
        "actor_recall": actor_scores["recall"],
        "actor_f1": actor_scores["f1"],
        "uc_precision": uc_scores["precision"],
        "uc_recall": uc_scores["recall"],
        "uc_f1": uc_scores["f1"],
        "milestone_precision": milestone_scores["precision"],
        "milestone_recall": milestone_scores["recall"],
        "milestone_f1": milestone_scores["f1"],
        "branch_precision": branch_scores["precision"],
        "branch_recall": branch_scores["recall"],
        "branch_f1": branch_scores["f1"],
        "trace_precision": trace_scores["precision"],
        "trace_recall": trace_scores["recall"],
        "trace_f1": trace_scores["f1"],
        "hallucination_rate": hallucination_rate,
        "semantic_composite": composite,
        "metric_status": "automatic_slot_match_candidate",
        "semantic_similarity_backend": similarity_name,
    }
