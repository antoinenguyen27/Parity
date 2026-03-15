from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from probegen.models._base import ProbegenModel

ArtifactClass = Literal["behavior_defining", "guardrail"]
ChangeKind = Literal["addition", "modification", "deletion", "rename"]


def content_sha256(content: str) -> str:
    return f"sha256:{sha256(content.encode('utf-8')).hexdigest()}"


class ChangedFile(ProbegenModel):
    path: str
    change_kind: ChangeKind
    renamed_from: str | None = None


class HintPatterns(ProbegenModel):
    behavior_paths: list[str] = Field(default_factory=list)
    guardrail_paths: list[str] = Field(default_factory=list)
    behavior_python_patterns: list[str] = Field(default_factory=list)
    guardrail_python_patterns: list[str] = Field(default_factory=list)


class ChangedArtifact(ProbegenModel):
    path: str
    artifact_class: ArtifactClass
    artifact_type: str = Field(min_length=1)
    change_kind: ChangeKind
    before_content: str
    after_content: str
    raw_diff: str
    before_sha: str
    after_sha: str


class RawChangeData(ProbegenModel):
    schema_version: Literal["1.0"] = "1.0"
    pr_number: int
    pr_title: str
    pr_body: str
    pr_labels: list[str] = Field(default_factory=list)
    base_branch: str
    head_sha: str
    repo_full_name: str
    all_changed_files: list[ChangedFile] = Field(default_factory=list)
    hint_matched_artifacts: list[ChangedArtifact] = Field(default_factory=list)
    hint_patterns: HintPatterns = Field(default_factory=HintPatterns)
    unchanged_hint_matches: list[str] = Field(default_factory=list)
    has_changes: bool = False
    artifact_count: int = 0

    @model_validator(mode="after")
    def validate_counts(self) -> "RawChangeData":
        if self.has_changes != bool(self.all_changed_files):
            self.has_changes = bool(self.all_changed_files)
        self.artifact_count = len(self.all_changed_files)
        return self
