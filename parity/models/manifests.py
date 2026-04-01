from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from parity.models._base import ParityModel
from parity.models.analysis import EvalAnalysisManifest, CoverageGap, CoverageTargetSummary, NearestCompatibleCase

RiskLevel = Literal["low", "medium", "high"]
Alignment = Literal["confirmed", "contradicted", "unknown"]
_ARTIFACT_PATH_SELECTOR_DELIMITER = "::"


def split_artifact_path(artifact_path: str) -> tuple[str, str | None]:
    normalized = artifact_path.strip()
    if not normalized:
        return normalized, None

    file_path, separator, selector = normalized.partition(_ARTIFACT_PATH_SELECTOR_DELIMITER)
    file_path = file_path.strip()
    selector = selector.strip()
    if not separator or not file_path or not selector:
        return normalized, None
    return file_path, selector


def canonicalize_artifact_path(artifact_path: str) -> str:
    file_path, _ = split_artifact_path(artifact_path)
    return file_path


def qualify_artifact_component(artifact_path: str) -> str | None:
    file_path, selector = split_artifact_path(artifact_path)
    if selector is None:
        return None
    return f"{file_path}{_ARTIFACT_PATH_SELECTOR_DELIMITER}{selector}"


def normalize_behavior_change_manifest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    raw_changes = payload.get("changes")
    if isinstance(raw_changes, list):
        normalized_changes: list[Any] = []
        for raw_change in raw_changes:
            if not isinstance(raw_change, dict):
                normalized_changes.append(raw_change)
                continue

            change = dict(raw_change)
            artifact_path = change.get("artifact_path")
            if isinstance(artifact_path, str):
                qualified_component = qualify_artifact_component(artifact_path)
                change["artifact_path"] = canonicalize_artifact_path(artifact_path)
                raw_affected_components = change.get("affected_components")
                affected_components = (
                    list(raw_affected_components)
                    if isinstance(raw_affected_components, list)
                    else []
                )
                if qualified_component and qualified_component not in affected_components:
                    affected_components.append(qualified_component)
                if affected_components:
                    change["affected_components"] = affected_components

            normalized_changes.append(change)
        normalized["changes"] = normalized_changes

    raw_compound_changes = payload.get("compound_changes")
    if isinstance(raw_compound_changes, list):
        normalized_compound_changes: list[Any] = []
        for raw_compound_change in raw_compound_changes:
            if not isinstance(raw_compound_change, dict):
                normalized_compound_changes.append(raw_compound_change)
                continue

            compound_change = dict(raw_compound_change)
            artifact_paths = compound_change.get("artifact_paths")
            if isinstance(artifact_paths, list):
                compound_change["artifact_paths"] = [
                    canonicalize_artifact_path(path) if isinstance(path, str) else path
                    for path in artifact_paths
                ]
            normalized_compound_changes.append(compound_change)
        normalized["compound_changes"] = normalized_compound_changes

    return normalized


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

    @model_validator(mode="before")
    @classmethod
    def normalize_artifact_paths(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return normalize_behavior_change_manifest_payload(value)
        return value

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
    "canonicalize_artifact_path",
    "ChangedEntity",
    "CompoundChange",
    "EvalAnalysisManifest",
    "EvidenceSnippet",
    "ObservableBehaviorDelta",
    "normalize_behavior_change_manifest_payload",
    "CoverageGap",
    "CoverageTargetSummary",
    "NearestCompatibleCase",
    "RiskLevel",
    "split_artifact_path",
]
