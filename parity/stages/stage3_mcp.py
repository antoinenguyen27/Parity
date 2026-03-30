from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

from parity.models import EvalAnalysisManifest, EvalCaseSnapshot


@dataclass(slots=True)
class Stage3MCPServerBundle:
    server: FastMCP
    toolbox: "Stage3EvidenceToolbox"


class Stage3EvidenceToolbox:
    def __init__(self, *, analysis_manifest: dict[str, Any], repo_root: str | Path) -> None:
        self.analysis = EvalAnalysisManifest.model_validate(analysis_manifest)
        self.repo_root = Path(repo_root).resolve()
        self._targets = {target.profile.target_id: target for target in self.analysis.resolved_targets}
        self._gaps = {gap.gap_id: gap for gap in self.analysis.gaps}
        self._evaluator_dossiers = {
            dossier.dossier_id: dossier
            for target in self.analysis.resolved_targets
            for dossier in target.evaluator_dossiers
        }

    def list_gap_dossiers(self) -> dict[str, Any]:
        return {
            "count": len(self.analysis.gaps),
            "gaps": [
                {
                    "gap_id": gap.gap_id,
                    "target_id": gap.target_id,
                    "method_kind": gap.method_kind,
                    "artifact_path": gap.artifact_path,
                    "gap_type": gap.gap_type,
                    "related_risk_flag": gap.related_risk_flag,
                    "description": gap.description,
                    "why_gap_is_real": gap.why_gap_is_real,
                    "confidence": gap.confidence,
                }
                for gap in self.analysis.gaps
            ],
        }

    def read_gap_dossier(self, gap_id: str) -> dict[str, Any]:
        gap = self._gaps.get(gap_id)
        if gap is None:
            raise KeyError(f"Unknown gap_id: {gap_id}")
        return gap.model_dump(mode="json")

    def list_targets(self) -> dict[str, Any]:
        return {
            "count": len(self.analysis.resolved_targets),
            "targets": [
                {
                    "target_id": target.profile.target_id,
                    "platform": target.profile.platform,
                    "locator": target.profile.locator,
                    "method_kind": target.method_profile.method_kind,
                    "evaluator_scope": target.method_profile.evaluator_scope,
                    "binding_candidate_count": len(target.method_profile.binding_candidates),
                    "evaluator_dossier_count": len(target.evaluator_dossiers),
                    "sample_count": len(target.samples),
                }
                for target in self.analysis.resolved_targets
            ],
        }

    def read_target_profile(self, target_id: str) -> dict[str, Any]:
        target = self._targets.get(target_id)
        if target is None:
            raise KeyError(f"Unknown target_id: {target_id}")
        return {
            "profile": target.profile.model_dump(mode="json"),
            "method_profile": target.method_profile.model_dump(mode="json"),
            "evaluator_dossiers": [dossier.model_dump(mode="json") for dossier in target.evaluator_dossiers],
            "raw_field_patterns": list(target.raw_field_patterns),
            "aggregate_method_hints": list(target.aggregate_method_hints),
            "resolution_notes": list(target.resolution_notes),
        }

    def list_evaluator_dossiers(self, target_id: str | None = None) -> dict[str, Any]:
        dossiers = list(self._evaluator_dossiers.values())
        if target_id is not None:
            dossiers = [dossier for dossier in dossiers if dossier.target_id == target_id]
        return {
            "count": len(dossiers),
            "evaluator_dossiers": [
                {
                    "dossier_id": dossier.dossier_id,
                    "target_id": dossier.target_id,
                    "binding_id": dossier.binding_id,
                    "label": dossier.label,
                    "discovery_mode": dossier.discovery_mode,
                    "scope": dossier.scope,
                    "execution_surface": dossier.execution_surface,
                    "explicitness": dossier.explicitness,
                    "binding_status": dossier.binding_status,
                    "verification_status": dossier.verification_status,
                    "reuse_feasibility": dossier.reuse_feasibility,
                    "confidence": dossier.confidence,
                }
                for dossier in dossiers
            ],
        }

    def read_evaluator_dossier(self, dossier_id: str) -> dict[str, Any]:
        dossier = self._evaluator_dossiers.get(dossier_id)
        if dossier is None:
            raise KeyError(f"Unknown evaluator dossier id: {dossier_id}")
        return dossier.model_dump(mode="json")

    def read_target_samples(
        self,
        target_id: str,
        *,
        limit: int = 5,
        case_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        target = self._targets.get(target_id)
        if target is None:
            raise KeyError(f"Unknown target_id: {target_id}")
        samples = target.samples
        if case_ids:
            allowed = set(case_ids)
            samples = [sample for sample in samples if sample.case_id in allowed]
        sliced = samples[: max(1, min(limit, 10))]
        return {
            "target_id": target_id,
            "count": len(sliced),
            "samples": [sample.model_dump(mode="json") for sample in sliced],
        }

    def read_case_snapshot(self, target_id: str, case_id: str) -> dict[str, Any]:
        target = self._targets.get(target_id)
        if target is None:
            raise KeyError(f"Unknown target_id: {target_id}")
        sample = next((item for item in target.samples if item.case_id == case_id), None)
        if sample is None:
            raise KeyError(f"Unknown case_id `{case_id}` for target `{target_id}`")
        return sample.model_dump(mode="json")

    def read_repo_eval_asset_excerpt(self, path: str) -> dict[str, Any]:
        resolved = (self.repo_root / path).resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError("Repo eval asset must stay within the repository root.") from exc
        if not resolved.exists():
            raise FileNotFoundError(f"Eval asset not found: {path}")
        content = resolved.read_text(encoding="utf-8")
        payload = yaml.safe_load(content) if resolved.suffix.lower() in {".yaml", ".yml"} else None
        excerpt = content[:4000]
        response: dict[str, Any] = {
            "path": resolved.relative_to(self.repo_root).as_posix(),
            "excerpt": excerpt,
        }
        if isinstance(payload, dict):
            response["keys"] = sorted(payload.keys())
        return response


def build_stage3_mcp_server(
    *,
    analysis_manifest: dict[str, Any],
    repo_root: str | Path,
) -> Stage3MCPServerBundle:
    toolbox = Stage3EvidenceToolbox(analysis_manifest=analysis_manifest, repo_root=repo_root)
    server = FastMCP("parity-stage3")

    @server.tool(name="list_gap_dossiers")
    def list_gap_dossiers_tool() -> dict[str, Any]:
        return toolbox.list_gap_dossiers()

    @server.tool(name="read_gap_dossier")
    def read_gap_dossier_tool(gap_id: str) -> dict[str, Any]:
        return toolbox.read_gap_dossier(gap_id)

    @server.tool(name="list_targets")
    def list_targets_tool() -> dict[str, Any]:
        return toolbox.list_targets()

    @server.tool(name="read_target_profile")
    def read_target_profile_tool(target_id: str) -> dict[str, Any]:
        return toolbox.read_target_profile(target_id)

    @server.tool(name="list_evaluator_dossiers")
    def list_evaluator_dossiers_tool(target_id: str | None = None) -> dict[str, Any]:
        return toolbox.list_evaluator_dossiers(target_id=target_id)

    @server.tool(name="read_evaluator_dossier")
    def read_evaluator_dossier_tool(dossier_id: str) -> dict[str, Any]:
        return toolbox.read_evaluator_dossier(dossier_id)

    @server.tool(name="read_target_samples")
    def read_target_samples_tool(
        target_id: str,
        limit: int = 5,
        case_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return toolbox.read_target_samples(target_id, limit=limit, case_ids=case_ids)

    @server.tool(name="read_case_snapshot")
    def read_case_snapshot_tool(target_id: str, case_id: str) -> dict[str, Any]:
        return toolbox.read_case_snapshot(target_id, case_id)

    @server.tool(name="read_repo_eval_asset_excerpt")
    def read_repo_eval_asset_excerpt_tool(path: str) -> dict[str, Any]:
        return toolbox.read_repo_eval_asset_excerpt(path)

    return Stage3MCPServerBundle(server=server, toolbox=toolbox)
