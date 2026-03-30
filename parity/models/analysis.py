from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from parity.models._base import ParityModel
from parity.models.eval_case import MethodKind
from parity.models.topology import ResolvedEvalTarget

RiskLevel = Literal["low", "medium", "high"]
SimilarityClassification = Literal["duplicate", "boundary", "related", "novel"]
GapType = Literal["covered", "boundary_shift", "uncovered"]
GuardrailDirection = Literal["should_catch", "should_pass"]
CoverageMode = Literal["coverage_aware", "bootstrap"]
CorpusStatus = Literal["available", "empty", "unavailable"]
ProfileStatus = Literal["confirmed", "uncertain", "bootstrap"]


class CoverageTargetSummary(ParityModel):
    target_id: str
    method_kind: MethodKind
    total_relevant_cases: int = 0
    cases_covering_changed_behavior: int = 0
    coverage_ratio: float = 0.0
    mode: CoverageMode = "coverage_aware"
    corpus_status: CorpusStatus = "available"
    profile_status: ProfileStatus = "confirmed"
    retrieval_notes: str | None = None
    bootstrap_reason: str | None = None
    analysis_notes: list[str] = Field(default_factory=list)

    @field_validator("coverage_ratio")
    @classmethod
    def validate_ratio(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("coverage_ratio must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_bootstrap_fields(self) -> "CoverageTargetSummary":
        if self.mode == "bootstrap" and not self.bootstrap_reason:
            raise ValueError("bootstrap_reason is required when mode is bootstrap")
        if self.mode == "coverage_aware" and self.bootstrap_reason:
            raise ValueError("bootstrap_reason must be empty when mode is coverage_aware")
        return self


class NearestCompatibleCase(ParityModel):
    case_id: str
    target_id: str
    input_normalized: str
    similarity: float
    classification: SimilarityClassification
    method_kind: MethodKind
    native_shape_summary: str | None = None
    why_not_sufficient: str | None = None

    @field_validator("similarity")
    @classmethod
    def validate_similarity(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("similarity must be between 0 and 1")
        return value


class RepoAssetReference(ParityModel):
    path: str
    kind: str
    summary: str | None = None
    keys: list[str] = Field(default_factory=list)
    relevance: str | None = None


class CoverageGap(ParityModel):
    gap_id: str
    artifact_path: str
    target_id: str
    method_kind: MethodKind
    gap_type: GapType
    related_risk_flag: str
    description: str
    why_gap_is_real: str | None = None
    existing_coverage_notes: str | None = None
    recommended_eval_area: str | None = None
    recommended_eval_mode: MethodKind | None = None
    evaluator_dossier_ids: list[str] = Field(default_factory=list)
    native_shape_hints: list[str] = Field(default_factory=list)
    compatible_nearest_cases: list[NearestCompatibleCase] = Field(default_factory=list)
    repo_asset_refs: list[RepoAssetReference] = Field(default_factory=list)
    priority: RiskLevel
    profile_status: ProfileStatus = "confirmed"
    guardrail_direction: GuardrailDirection | None = None
    is_conversational: bool = False
    confidence: float = 0.0

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class EvalAnalysisManifest(ParityModel):
    schema_version: Literal["3.0"] = "3.0"
    run_id: str
    stage1_run_id: str
    timestamp: datetime
    unresolved_artifacts: list[str] = Field(default_factory=list)
    resolved_targets: list[ResolvedEvalTarget] = Field(default_factory=list)
    coverage_by_target: list[CoverageTargetSummary] = Field(default_factory=list)
    gaps: list[CoverageGap] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_unique_target_ids(self) -> "EvalAnalysisManifest":
        seen: set[str] = set()
        dossier_lookup: dict[str, set[str]] = {}
        for target in self.resolved_targets:
            if target.profile.target_id in seen:
                raise ValueError("resolved_targets must use unique target_id values")
            seen.add(target.profile.target_id)
            dossier_lookup[target.profile.target_id] = {dossier.dossier_id for dossier in target.evaluator_dossiers}
        for gap in self.gaps:
            if gap.target_id not in seen:
                raise ValueError(f"gap target_id `{gap.target_id}` does not exist in resolved_targets")
            missing = [dossier_id for dossier_id in gap.evaluator_dossier_ids if dossier_id not in dossier_lookup.get(gap.target_id, set())]
            if missing:
                raise ValueError(
                    f"gap `{gap.gap_id}` references evaluator dossiers not present on target `{gap.target_id}`: {missing}"
                )
        return self
