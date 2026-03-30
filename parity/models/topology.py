from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from parity.models._base import ParityModel
from parity.models.eval_case import EvalCaseSnapshot, MethodKind

ResolutionSource = Literal["config_rule", "platform_discovery", "repo_asset_discovery", "bootstrap"]
AccessMode = Literal["mcp", "file", "sdk", "synthetic"]
WriteCapability = Literal["native_ready", "review_only", "unsupported"]
InputShape = Literal["string", "dict", "conversation", "structured_vars", "unknown"]
AssertionStyle = Literal["deterministic", "judge", "hybrid", "pairwise", "human_review", "trajectory", "unknown"]
EvaluatorScope = Literal["row_local", "dataset_bound", "experiment_bound", "project_bound", "repo_code", "unknown"]
ExecutionSurface = Literal["config_file", "dataset_examples", "sdk_experiment", "ui_rules", "repo_harness", "unknown"]
EvaluatorExplicitness = Literal["explicit", "inferred", "heuristic"]
EvaluatorFeasibility = Literal["confirmed", "likely", "uncertain", "unsupported"]
EvaluatorDiscoveryMode = Literal["formal", "repo_formal", "inferred", "heuristic"]
EvaluatorBindingStatus = Literal["attached", "available", "row_local", "unknown"]
EvaluatorVerificationStatus = Literal["verified", "unverified", "unsupported"]
FormalDiscoveryStatus = Literal["confirmed", "partial", "fallback", "unsupported"]


class EvaluatorBindingCandidate(ParityModel):
    binding_id: str
    label: str
    scope: EvaluatorScope = "unknown"
    execution_surface: ExecutionSurface = "unknown"
    source: str = "unknown"
    discovery_mode: EvaluatorDiscoveryMode = "heuristic"
    binding_object_id: str | None = None
    binding_location: str | None = None
    binding_status: EvaluatorBindingStatus = "unknown"
    verification_status: EvaluatorVerificationStatus = "unverified"
    mapping_hints: dict[str, str] = Field(default_factory=dict)
    reusable: bool = False
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class EvaluatorDossier(ParityModel):
    dossier_id: str
    target_id: str
    binding_id: str | None = None
    label: str
    scope: EvaluatorScope = "unknown"
    execution_surface: ExecutionSurface = "unknown"
    source: str = "unknown"
    discovery_mode: EvaluatorDiscoveryMode = "heuristic"
    binding_object_id: str | None = None
    binding_location: str | None = None
    binding_status: EvaluatorBindingStatus = "unknown"
    verification_status: EvaluatorVerificationStatus = "unverified"
    explicitness: EvaluatorExplicitness = "heuristic"
    mapping_hints: dict[str, str] = Field(default_factory=dict)
    supporting_case_ids: list[str] = Field(default_factory=list)
    supporting_repo_asset_paths: list[str] = Field(default_factory=list)
    reuse_feasibility: EvaluatorFeasibility = "uncertain"
    confidence: float = 0.0
    rationale: str | None = None
    risks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    last_verified_at: datetime | None = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value


class EvalMethodProfile(ParityModel):
    method_kind: MethodKind
    input_shape: InputShape = "unknown"
    assertion_style: AssertionStyle = "unknown"
    uses_judge: bool = False
    supports_multi_assert: bool = False
    evaluator_binding: str | None = None
    evaluator_scope: EvaluatorScope = "unknown"
    execution_surface: ExecutionSurface = "unknown"
    binding_candidates: list[EvaluatorBindingCandidate] = Field(default_factory=list)
    supports_evaluator_reuse: bool = False
    formal_discovery_status: FormalDiscoveryStatus = "fallback"
    formal_binding_count: int = 0
    metadata_conventions: dict[str, Any] = Field(default_factory=dict)
    renderability_status: WriteCapability = "unsupported"
    confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> "EvalMethodProfile":
        if self.method_kind == "judge" and not self.uses_judge:
            raise ValueError("judge method profiles must set uses_judge")
        if self.method_kind == "deterministic" and self.uses_judge:
            raise ValueError("deterministic method profiles cannot set uses_judge")
        if self.method_kind == "hybrid" and self.assertion_style not in {"hybrid", "judge", "deterministic"}:
            raise ValueError("hybrid method profiles must describe hybrid-compatible assertion_style")
        if self.evaluator_scope == "row_local" and self.execution_surface == "unknown":
            raise ValueError("row_local evaluator profiles must set execution_surface")
        return self


class EvalTargetProfile(ParityModel):
    target_id: str
    platform: str
    locator: str
    target_name: str
    dataset_id: str | None = None
    project: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    resolution_source: ResolutionSource
    access_mode: AccessMode
    write_capability: WriteCapability
    profile_confidence: float = 0.0

    @field_validator("profile_confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("profile_confidence must be between 0 and 1")
        return value


class ResolvedEvalTarget(ParityModel):
    profile: EvalTargetProfile
    method_profile: EvalMethodProfile
    samples: list[EvalCaseSnapshot] = Field(default_factory=list)
    evaluator_dossiers: list[EvaluatorDossier] = Field(default_factory=list)
    raw_field_patterns: list[str] = Field(default_factory=list)
    aggregate_method_hints: list[str] = Field(default_factory=list)
    resolution_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target_alignment(self) -> "ResolvedEvalTarget":
        for sample in self.samples:
            if sample.source_target_id != self.profile.target_id:
                raise ValueError("sample source_target_id must match profile.target_id")
        seen_dossier_ids: set[str] = set()
        for dossier in self.evaluator_dossiers:
            if dossier.target_id != self.profile.target_id:
                raise ValueError("evaluator dossier target_id must match profile.target_id")
            if dossier.dossier_id in seen_dossier_ids:
                raise ValueError("evaluator dossier ids must be unique within the target")
            seen_dossier_ids.add(dossier.dossier_id)
        return self
