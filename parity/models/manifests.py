from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from parity.models._base import ParityModel
from parity.models.analysis import EvalAnalysisManifest, CoverageGap, CoverageTargetSummary, NearestCompatibleCase

RiskLevel = Literal["low", "medium", "high"]
Alignment = Literal["confirmed", "contradicted", "unknown"]


class BehaviorChange(ParityModel):
    artifact_path: str
    artifact_type: str
    artifact_class: str
    change_type: str
    inferred_intent: str
    pr_description_alignment: Alignment
    unintended_risk_flags: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    false_negative_risks: list[str] = Field(default_factory=list)
    false_positive_risks: list[str] = Field(default_factory=list)
    change_summary: str
    behavioral_signatures: list[str] = Field(default_factory=list)
    changed_entities: list["ChangedEntity"] = Field(default_factory=list)
    observable_delta: "ObservableBehaviorDelta | None" = None
    eval_search_hints: list[str] = Field(default_factory=list)
    validation_focus: list[str] = Field(default_factory=list)
    evidence_snippets: list["EvidenceSnippet"] = Field(default_factory=list)
    before_hash: str | None = None
    after_hash: str | None = None


class ChangedEntity(ParityModel):
    entity_kind: str
    name: str
    operation: Literal["added", "removed", "modified", "reconfigured"]
    why_it_matters: str | None = None


class ObservableBehaviorDelta(ParityModel):
    before_behavior: str | None = None
    after_behavior: str
    user_visible_effect: str | None = None


class EvidenceSnippet(ParityModel):
    label: str
    summary: str
    before_text: str | None = None
    after_text: str | None = None


class CompoundChange(ParityModel):
    artifact_paths: list[str] = Field(default_factory=list)
    summary: str


class BehaviorChangeManifest(ParityModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    pr_number: int
    commit_sha: str
    timestamp: datetime
    has_changes: bool
    overall_risk: RiskLevel
    pr_intent_summary: str
    pr_description_alignment: Alignment
    compound_change_detected: bool
    changes: list[BehaviorChange] = Field(default_factory=list)
    compound_changes: list[CompoundChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_change_gate_consistency(self) -> "BehaviorChangeManifest":
        if self.has_changes and not self.changes:
            raise ValueError("has_changes cannot be true when changes is empty")
        if not self.has_changes:
            self.changes = []
        return self


BehaviorChange.model_rebuild()


__all__ = [
    "Alignment",
    "BehaviorChange",
    "BehaviorChangeManifest",
    "ChangedEntity",
    "CompoundChange",
    "EvalAnalysisManifest",
    "EvidenceSnippet",
    "ObservableBehaviorDelta",
    "CoverageGap",
    "CoverageTargetSummary",
    "NearestCompatibleCase",
    "RiskLevel",
]
