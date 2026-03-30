from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parity import __version__
from parity.integrations.promptfoo import PromptfooWriter
from parity.models import (
    BehaviorChangeManifest,
    EvalAnalysisManifest,
    EvalProposalManifest,
    NativeEvalRendering,
    RenderArtifact,
)


def create_run_artifact_dir(commit_sha: str, base_dir: str | Path = ".parity/runs") -> Path:
    run_dir = Path(base_dir) / commit_sha
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def render_summary_markdown(proposal: EvalProposalManifest) -> str:
    lines = ["# Parity Eval Proposal Summary", ""]
    evaluator_plan_lookup = {plan.intent_id: plan for plan in proposal.evaluator_plans}
    for intent in proposal.intents:
        rendering = next((item for item in proposal.renderings if item.intent_id == intent.intent_id), None)
        evaluator_plan = evaluator_plan_lookup.get(intent.intent_id)
        write_status = rendering.write_status if rendering is not None else "unsupported"
        lines.extend(
            [
                f"## {intent.intent_id} ({intent.intent_type})",
                f"- Target: {intent.target_id}",
                f"- Method: {intent.method_kind}",
                f"- Write status: {write_status}",
                f"- Evaluator linkage: {evaluator_plan.action if evaluator_plan is not None else 'manual'}",
                f"- Behavior under test: {intent.behavior_under_test}",
                f"- Rationale: {intent.probe_rationale}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _group_renderings_by_target(renderings: list[NativeEvalRendering]) -> dict[str, list[NativeEvalRendering]]:
    grouped: dict[str, list[NativeEvalRendering]] = {}
    for rendering in renderings:
        if rendering.write_status not in {"native_ready", "review_only"}:
            continue
        grouped.setdefault(rendering.target_id, []).append(rendering)
    return grouped


def _sanitize_filename(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)
    return sanitized[:120] or "target"


def export_native_render_artifacts(
    proposal: EvalProposalManifest,
    *,
    output_dir: str | Path,
) -> list[RenderArtifact]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target_lookup = {target.target_id: target for target in proposal.targets}
    artifacts: list[RenderArtifact] = []

    for target_id, renderings in _group_renderings_by_target(proposal.renderings).items():
        target = target_lookup.get(target_id)
        if target is None:
            continue
        if target.platform == "promptfoo":
            writer = PromptfooWriter()
            output_path = directory / f"{_sanitize_filename(target_id)}.promptfoo.yaml"
            writer.write_renderings(
                renderings,
                test_file=output_path,
                artifact_path=", ".join(target.artifact_paths) if target.artifact_paths else target.target_name,
                pr_number=proposal.pr_number,
                version=__version__,
                commit_sha=proposal.commit_sha,
            )
            write_status = "native_ready" if all(item.write_status == "native_ready" for item in renderings) else "review_only"
            artifacts.append(
                RenderArtifact(
                    target_id=target_id,
                    artifact_kind="promptfoo_config",
                    path=str(output_path),
                    write_status=write_status,
                )
            )
            continue

        output_path = directory / f"{_sanitize_filename(target_id)}.renderings.json"
        payload = {
            "target": target.model_dump(mode="json"),
            "renderings": [rendering.model_dump(mode="json") for rendering in renderings],
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        write_status = "native_ready" if all(item.write_status == "native_ready" for item in renderings) else "review_only"
        artifacts.append(
            RenderArtifact(
                target_id=target_id,
                artifact_kind="dataset_renderings",
                path=str(output_path),
                write_status=write_status,
            )
        )

    return artifacts


def write_run_artifacts(
    *,
    run_dir: str | Path,
    stage1_manifest: BehaviorChangeManifest | None = None,
    stage2_manifest: EvalAnalysisManifest | None = None,
    proposal: EvalProposalManifest | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Path]:
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    if stage1_manifest is not None:
        path = directory / "BehaviorChangeManifest.json"
        path.write_text(stage1_manifest.model_dump_json(indent=2), encoding="utf-8")
        outputs["stage1"] = path
    if stage2_manifest is not None:
        path = directory / "EvalAnalysisManifest.json"
        path.write_text(stage2_manifest.model_dump_json(indent=2), encoding="utf-8")
        outputs["stage2"] = path
    if proposal is not None:
        proposal.render_artifacts = export_native_render_artifacts(proposal, output_dir=directory / "render_artifacts")
        raw_path = directory / "EvalProposalManifest.json"
        raw_path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        outputs["proposal"] = raw_path
        summary_path = directory / "summary.md"
        summary_path.write_text(render_summary_markdown(proposal), encoding="utf-8")
        outputs["summary"] = summary_path
        for index, artifact in enumerate(proposal.render_artifacts):
            outputs[f"render_artifact_{index}"] = Path(artifact.path)
    metadata_path = directory / "metadata.json"
    metadata_path.write_text(json.dumps(metadata or {}, indent=2), encoding="utf-8")
    outputs["metadata"] = metadata_path
    return outputs
