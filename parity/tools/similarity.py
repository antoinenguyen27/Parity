from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np

from parity.models.analysis import CoverageGap
from parity.models.proposal import ProbeIntent


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_vector = np.asarray(list(left), dtype=float)
    right_vector = np.asarray(list(right), dtype=float)
    if left_vector.size == 0 or right_vector.size == 0:
        return 0.0
    left_norm = np.linalg.norm(left_vector)
    right_norm = np.linalg.norm(right_vector)
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left_vector, right_vector) / (left_norm * right_norm))


def classify_similarity(
    score: float,
    *,
    duplicate_threshold: float,
    boundary_threshold: float,
) -> str:
    if score >= duplicate_threshold:
        return "duplicate"
    if score >= boundary_threshold:
        return "boundary"
    if score >= 0.50:
        return "related"
    return "novel"


def classify_embedding_against_corpus(
    candidate_embedding: Iterable[float],
    corpus: list[dict[str, Any]],
    *,
    candidate_id: str,
    duplicate_threshold: float,
    boundary_threshold: float,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in corpus:
        score = cosine_similarity(candidate_embedding, item["embedding"])
        results.append(
            {
                "corpus_id": item["id"],
                "similarity": score,
                "classification": classify_similarity(
                    score,
                    duplicate_threshold=duplicate_threshold,
                    boundary_threshold=boundary_threshold,
                ),
            }
        )

    results.sort(key=lambda item: item["similarity"], reverse=True)
    top_match = results[0] if results else None
    return {
        "candidate_id": candidate_id,
        "results": results,
        "top_match": top_match,
        "max_similarity": top_match["similarity"] if top_match else 0.0,
        "overall_classification": top_match["classification"] if top_match else "novel",
    }


def classify_embeddings_against_corpus(
    candidates: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    *,
    duplicate_threshold: float,
    boundary_threshold: float,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for candidate in candidates:
        payloads.append(
            classify_embedding_against_corpus(
                candidate["embedding"],
                corpus,
                candidate_id=candidate["id"],
                duplicate_threshold=duplicate_threshold,
                boundary_threshold=boundary_threshold,
            )
        )
    return payloads


def score_intent(intent: ProbeIntent, gaps: list[CoverageGap]) -> float:
    weights = {
        "specificity": 0.25,
        "testability": 0.20,
        "novelty": 0.15,
        "realism": 0.15,
        "risk_alignment": 0.10,
        "target_fit": 0.15,
    }
    gap = next((candidate for candidate in gaps if candidate.gap_id == intent.gap_id), None)
    risk_alignment = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(
        gap.priority if gap else "medium",
        0.6,
    )
    return (
        weights["specificity"] * intent.specificity_confidence
        + weights["testability"] * intent.testability_confidence
        + weights["novelty"] * intent.novelty_confidence
        + weights["realism"] * intent.realism_confidence
        + weights["risk_alignment"] * risk_alignment
        + weights["target_fit"] * intent.target_fit_confidence
    )


def apply_intent_diversity_limit(intents: list[ProbeIntent], *, limit_per_gap: int) -> list[ProbeIntent]:
    counts: dict[str, int] = defaultdict(int)
    filtered: list[ProbeIntent] = []
    for intent in intents:
        if counts[intent.gap_id] >= limit_per_gap:
            continue
        filtered.append(intent)
        counts[intent.gap_id] += 1
    return filtered


def rank_probe_intents(intents: list[ProbeIntent], gaps: list[CoverageGap]) -> list[ProbeIntent]:
    return sorted(intents, key=lambda intent: score_intent(intent, gaps), reverse=True)
