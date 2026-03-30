from __future__ import annotations

from parity.models.analysis import CoverageGap
from parity.models.proposal import ProbeIntent
from parity.tools.similarity import apply_intent_diversity_limit, rank_probe_intents


def _intent(
    intent_id: str,
    gap_id: str,
    specificity: float,
    testability: float,
    novelty: float,
    realism: float,
    target_fit: float,
) -> ProbeIntent:
    return ProbeIntent.model_validate(
        {
            "intent_id": intent_id,
            "gap_id": gap_id,
            "target_id": "target_1",
            "method_kind": "judge",
            "intent_type": "boundary_probe",
            "title": intent_id,
            "is_conversational": False,
            "input": "input",
            "input_format": "string",
            "behavior_under_test": "behavior",
            "pass_criteria": "rubric",
            "failure_mode": "fail",
            "probe_rationale": "why",
            "related_risk_flag": "flag",
            "nearest_existing_case_id": "case_1",
            "nearest_existing_similarity": 0.2,
            "specificity_confidence": specificity,
            "testability_confidence": testability,
            "novelty_confidence": novelty,
            "realism_confidence": realism,
            "target_fit_confidence": target_fit,
        }
    )


def test_rank_probe_intents_prefers_higher_composite_score() -> None:
    gaps = [
        CoverageGap.model_validate(
            {
                "gap_id": "gap_high",
                "artifact_path": "prompts/a.md",
                "target_id": "target_1",
                "method_kind": "judge",
                "gap_type": "uncovered",
                "related_risk_flag": "flag",
                "description": "desc",
                "compatible_nearest_cases": [],
                "priority": "high",
                "profile_status": "confirmed",
                "guardrail_direction": None,
                "is_conversational": False,
            }
        )
    ]
    intents = [
        _intent("intent_low", "gap_high", 0.6, 0.6, 0.6, 0.6, 0.6),
        _intent("intent_high", "gap_high", 0.9, 0.9, 0.9, 0.9, 0.9),
    ]

    ranked = rank_probe_intents(intents, gaps)

    assert ranked[0].intent_id == "intent_high"


def test_apply_intent_diversity_limit_caps_intents_per_gap() -> None:
    intents = [
        _intent("i1", "gap1", 0.9, 0.9, 0.9, 0.9, 0.9),
        _intent("i2", "gap1", 0.8, 0.8, 0.8, 0.8, 0.8),
        _intent("i3", "gap1", 0.7, 0.7, 0.7, 0.7, 0.7),
        _intent("i4", "gap2", 0.9, 0.9, 0.9, 0.9, 0.9),
    ]

    limited = apply_intent_diversity_limit(intents, limit_per_gap=2)

    assert [intent.intent_id for intent in limited] == ["i1", "i2", "i4"]
