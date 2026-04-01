from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from parity.models import (
    BehaviorChangeManifest,
    EvalCase,
    EvalAnalysisManifest,
    EvalProposalManifest,
    RawChangeData,
)


def test_raw_change_data_validates_and_computes_counts() -> None:
    model = RawChangeData.model_validate(
        {
            "pr_number": 142,
            "pr_title": "Add citation requirement",
            "pr_body": "Body",
            "pr_labels": ["prompts"],
            "base_branch": "main",
            "head_sha": "abc123",
            "repo_full_name": "org/repo",
            "all_changed_files": [
                {"path": "prompts/citation.md", "change_kind": "modification"},
                {"path": "src/config.py", "change_kind": "modification"},
            ],
            "hint_matched_artifacts": [
                {
                    "path": "prompts/citation.md",
                    "artifact_class": "behavior_defining",
                    "artifact_type": "system_prompt",
                    "change_kind": "modification",
                    "before_content": "before",
                    "after_content": "after",
                    "raw_diff": "@@ -1 +1 @@",
                    "before_sha": "sha256:1",
                    "after_sha": "sha256:2",
                }
            ],
            "unchanged_hint_matches": [],
            "has_changes": False,
            "artifact_count": 0,
        }
    )

    assert model.has_changes is True
    assert model.artifact_count == 2


def test_eval_case_snapshot_populates_normalized_projection() -> None:
    case = EvalCase.model_validate(
        {
            "case_id": "case_1",
            "source_platform": "promptfoo",
            "source_target_id": "promptfoo::demo",
            "source_target_name": "demo",
            "target_locator": "evals/promptfooconfig.yaml",
            "method_kind": "judge",
            "native_input": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
            "native_output": {"answer": "Hi"},
            "native_assertions": [
                {
                    "assertion_id": "case_1:judge",
                    "assertion_kind": "judge",
                    "operator": "llm-rubric",
                    "rubric": "The answer greets the user.",
                }
            ],
            "method_confidence": 0.8,
        }
    )

    assert case.normalized_projection.is_conversational is True
    assert case.normalized_projection.input_text == "USER: Hello\nASSISTANT: Hi"
    assert case.normalized_projection.expected_text == "Hi"


def test_behavior_change_manifest_rejects_true_without_changes() -> None:
    with pytest.raises(ValidationError):
        BehaviorChangeManifest.model_validate(
            {
                "run_id": "run",
                "pr_number": 1,
                "commit_sha": "abc",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "has_changes": True,
                "overall_risk": "medium",
                "pr_intent_summary": "summary",
                "pr_description_alignment": "confirmed",
                "compound_change_detected": False,
                "changes": [],
                "compound_changes": [],
            }
        )


def test_behavior_change_manifest_normalizes_selector_qualified_artifact_paths() -> None:
    manifest = BehaviorChangeManifest.model_validate(
        {
            "run_id": "run",
            "pr_number": 1,
            "commit_sha": "abc",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "has_changes": True,
            "overall_risk": "medium",
            "pr_intent_summary": "summary",
            "pr_description_alignment": "confirmed",
            "compound_change_detected": False,
            "changes": [
                {
                    "artifact_path": "app/graph.py::GENERATE_PROMPT",
                    "artifact_type": "python_variable",
                    "artifact_class": "behavior_defining",
                    "change_type": "modification",
                    "inferred_intent": "Require citations",
                    "pr_description_alignment": "confirmed",
                    "unintended_risk_flags": [],
                    "affected_components": [],
                    "false_negative_risks": [],
                    "false_positive_risks": [],
                    "change_summary": "Added citation instruction",
                }
            ],
            "compound_changes": [
                {
                    "artifact_paths": ["app/graph.py::GENERATE_PROMPT"],
                    "summary": "Prompt changed",
                }
            ],
        }
    )

    assert manifest.changes[0].artifact_path == "app/graph.py"
    assert "app/graph.py::GENERATE_PROMPT" in manifest.changes[0].affected_components
    assert manifest.compound_changes[0].artifact_paths == ["app/graph.py"]


def test_coverage_analysis_manifest_validates_similarity_bounds() -> None:
    with pytest.raises(ValidationError):
        EvalAnalysisManifest.model_validate(
            {
                "run_id": "run",
                "stage1_run_id": "stage1",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "coverage_by_target": [
                    {
                        "target_id": "target",
                        "method_kind": "deterministic",
                        "coverage_ratio": 0.5,
                    }
                ],
                "gaps": [
                    {
                        "gap_id": "gap_1",
                        "artifact_path": "prompts/citation.md",
                        "target_id": "target",
                        "method_kind": "deterministic",
                        "gap_type": "uncovered",
                        "related_risk_flag": "flag",
                        "description": "desc",
                        "priority": "high",
                        "profile_status": "confirmed",
                        "compatible_nearest_cases": [
                            {
                                "case_id": "case_1",
                                "target_id": "target",
                                "input_normalized": "question",
                                "similarity": 1.5,
                                "classification": "related",
                                "method_kind": "deterministic",
                            }
                        ],
                    }
                ],
            }
        )


def test_coverage_target_summary_requires_reason_in_bootstrap_mode() -> None:
    with pytest.raises(ValidationError):
        EvalAnalysisManifest.model_validate(
            {
                "run_id": "run",
                "stage1_run_id": "stage1",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "coverage_by_target": [
                    {
                        "target_id": "target",
                        "method_kind": "unknown",
                        "coverage_ratio": 0.0,
                        "mode": "bootstrap",
                        "corpus_status": "empty",
                    }
                ],
                "gaps": [],
            }
        )


def test_eval_analysis_manifest_requires_degradation_reason_when_degraded() -> None:
    with pytest.raises(ValidationError):
        EvalAnalysisManifest.model_validate(
            {
                "run_id": "run",
                "stage1_run_id": "stage1",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "analysis_status": "degraded",
                "resolved_targets": [],
                "coverage_by_target": [],
                "gaps": [],
            }
        )


def test_eval_analysis_manifest_rejects_duplicate_target_ids() -> None:
    with pytest.raises(ValidationError):
        EvalAnalysisManifest.model_validate(
            {
                "run_id": "stage2",
                "stage1_run_id": "stage1",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "resolved_targets": [
                    {
                        "profile": {
                            "target_id": "same",
                            "platform": "promptfoo",
                            "locator": "a.yaml",
                            "target_name": "a.yaml",
                            "artifact_paths": ["prompts/a.md"],
                            "resolution_source": "config_rule",
                            "access_mode": "file",
                            "write_capability": "native_ready",
                            "profile_confidence": 0.8,
                        },
                        "method_profile": {
                            "method_kind": "deterministic",
                            "input_shape": "string",
                            "assertion_style": "deterministic",
                            "uses_judge": False,
                            "supports_multi_assert": False,
                            "renderability_status": "native_ready",
                            "confidence": 0.8,
                        },
                        "samples": [],
                    },
                    {
                        "profile": {
                            "target_id": "same",
                            "platform": "promptfoo",
                            "locator": "b.yaml",
                            "target_name": "b.yaml",
                            "artifact_paths": ["prompts/b.md"],
                            "resolution_source": "config_rule",
                            "access_mode": "file",
                            "write_capability": "native_ready",
                            "profile_confidence": 0.7,
                        },
                        "method_profile": {
                            "method_kind": "deterministic",
                            "input_shape": "string",
                            "assertion_style": "deterministic",
                            "uses_judge": False,
                            "supports_multi_assert": False,
                            "renderability_status": "native_ready",
                            "confidence": 0.7,
                        },
                        "samples": [],
                    }
                ]
            }
        )


def test_eval_proposal_manifest_rejects_missing_target_reference() -> None:
    with pytest.raises(ValidationError):
        EvalProposalManifest.model_validate(
            {
                "run_id": "stage3",
                "stage1_run_id": "stage1",
                "stage2_run_id": "stage2",
                "stage3_run_id": "stage3",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "pr_number": 1,
                "commit_sha": "abc",
                "intent_count": 1,
                "targets": [],
                "intents": [
                    {
                        "intent_id": "intent_1",
                        "gap_id": "gap_1",
                        "target_id": "missing",
                        "method_kind": "deterministic",
                        "intent_type": "edge_case",
                        "title": "Title",
                        "is_conversational": False,
                        "input": "Hello",
                        "input_format": "string",
                        "behavior_under_test": "Behavior",
                        "pass_criteria": "Pass",
                        "failure_mode": "Fail",
                        "probe_rationale": "Why",
                        "related_risk_flag": "flag",
                        "specificity_confidence": 0.9,
                        "testability_confidence": 0.8,
                        "novelty_confidence": 0.7,
                        "realism_confidence": 0.7,
                        "target_fit_confidence": 0.9
                    }
                ],
                "renderings": [],
                "render_artifacts": [],
                "warnings": []
            }
        )


def test_eval_method_profile_requires_execution_surface_for_row_local() -> None:
    with pytest.raises(ValidationError):
        EvalAnalysisManifest.model_validate(
            {
                "run_id": "stage2",
                "stage1_run_id": "stage1",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "resolved_targets": [
                    {
                        "profile": {
                            "target_id": "promptfoo::demo",
                            "platform": "promptfoo",
                            "locator": "promptfooconfig.yaml",
                            "target_name": "promptfooconfig.yaml",
                            "artifact_paths": ["prompts/demo.md"],
                            "resolution_source": "config_rule",
                            "access_mode": "file",
                            "write_capability": "native_ready",
                            "profile_confidence": 0.8,
                        },
                        "method_profile": {
                            "method_kind": "hybrid",
                            "input_shape": "conversation",
                            "assertion_style": "hybrid",
                            "uses_judge": True,
                            "supports_multi_assert": True,
                            "evaluator_scope": "row_local",
                            "execution_surface": "unknown",
                            "renderability_status": "native_ready",
                            "confidence": 0.8,
                        },
                        "samples": [],
                    }
                ],
            }
        )


def test_eval_proposal_manifest_rejects_evaluator_plan_missing_intent() -> None:
    with pytest.raises(ValidationError):
        EvalProposalManifest.model_validate(
            {
                "run_id": "stage3",
                "stage1_run_id": "stage1",
                "stage2_run_id": "stage2",
                "stage3_run_id": "stage3",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "pr_number": 1,
                "commit_sha": "abc",
                "intent_count": 0,
                "targets": [
                    {
                        "target_id": "promptfoo::demo",
                        "platform": "promptfoo",
                        "locator": "promptfooconfig.yaml",
                        "target_name": "promptfooconfig.yaml",
                        "artifact_paths": ["prompts/demo.md"],
                        "resolution_source": "config_rule",
                        "access_mode": "file",
                        "write_capability": "native_ready",
                        "profile_confidence": 0.8,
                    }
                ],
                "intents": [],
                "evaluator_plans": [
                    {
                        "plan_id": "plan-1",
                        "intent_id": "missing",
                        "target_id": "promptfoo::demo",
                        "action": "row_local",
                        "scope": "row_local",
                        "execution_surface": "config_file",
                        "confidence": 0.9,
                        "requires_opt_in": False,
                        "rationale": "Promptfoo is row-local.",
                    }
                ],
                "renderings": [],
                "render_artifacts": [],
                "warnings": [],
            }
        )


def test_eval_analysis_manifest_rejects_gap_missing_evaluator_dossier_reference() -> None:
    with pytest.raises(ValidationError):
        EvalAnalysisManifest.model_validate(
            {
                "run_id": "stage2",
                "stage1_run_id": "stage1",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "resolved_targets": [
                    {
                        "profile": {
                            "target_id": "promptfoo::demo",
                            "platform": "promptfoo",
                            "locator": "promptfooconfig.yaml",
                            "target_name": "promptfooconfig.yaml",
                            "artifact_paths": ["prompts/demo.md"],
                            "resolution_source": "config_rule",
                            "access_mode": "file",
                            "write_capability": "native_ready",
                            "profile_confidence": 0.8,
                        },
                        "method_profile": {
                            "method_kind": "hybrid",
                            "input_shape": "conversation",
                            "assertion_style": "hybrid",
                            "uses_judge": True,
                            "supports_multi_assert": True,
                            "evaluator_scope": "row_local",
                            "execution_surface": "config_file",
                            "renderability_status": "native_ready",
                            "confidence": 0.8,
                        },
                        "samples": [],
                        "evaluator_dossiers": [],
                    }
                ],
                "coverage_by_target": [],
                "gaps": [
                    {
                        "gap_id": "gap-1",
                        "artifact_path": "prompts/demo.md",
                        "target_id": "promptfoo::demo",
                        "method_kind": "hybrid",
                        "gap_type": "uncovered",
                        "related_risk_flag": "flag",
                        "description": "desc",
                        "evaluator_dossier_ids": ["missing-dossier"],
                        "priority": "medium",
                        "confidence": 0.5,
                    }
                ],
            }
        )
