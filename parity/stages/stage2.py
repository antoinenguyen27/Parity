from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from parity.config import ParityConfig
from parity.context import count_tokens
from parity.errors import BudgetExceededError
from parity.models import (
    CoverageGap,
    CoverageTargetSummary,
    EvalAnalysisManifest,
    EvalMethodProfile,
    EvalTargetProfile,
    ResolvedEvalTarget,
)
from parity.prompts.stage2_template import render_stage2_prompt
from parity.stages._common import StageRunResult, run_stage_with_retry, simplify_schema
from parity.stages.stage2_mcp import build_stage2_mcp_server

_STAGE2_INJECT_KEYS = {"run_id", "stage1_run_id", "timestamp", "schema_version", "runtime_metadata"}


def _dedupe_non_empty(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _build_stage2_rule_resolutions(stage1_manifest: dict, config: ParityConfig) -> list[dict[str, Any]]:
    resolutions: list[dict[str, Any]] = []
    seen_artifacts: set[str] = set()
    for change in stage1_manifest.get("changes", []):
        artifact_path = change.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path or artifact_path in seen_artifacts:
            continue
        seen_artifacts.add(artifact_path)
        rule = config.find_eval_rule(artifact_path)
        if rule is None:
            resolutions.append(
                {
                    "artifact_path": artifact_path,
                    "artifact_class": change.get("artifact_class"),
                    "rule_status": "unresolved",
                    "preferred_platform": None,
                    "preferred_target": None,
                    "preferred_project": None,
                    "allowed_methods": [],
                    "preferred_methods": [],
                    "repo_asset_hints": [],
                    "discovery_order": config.resolve_platform_discovery_order(),
                }
            )
            continue
        resolutions.append(
            {
                "artifact_path": artifact_path,
                "artifact_class": change.get("artifact_class"),
                "rule_status": "explicit",
                "preferred_platform": rule.preferred_platform,
                "preferred_target": rule.preferred_target,
                "preferred_project": rule.preferred_project,
                "allowed_methods": rule.allowed_methods,
                "preferred_methods": rule.preferred_methods,
                "repo_asset_hints": rule.repo_asset_hints,
                "discovery_order": config.resolve_platform_discovery_order(rule.preferred_platform),
            }
        )
    return resolutions


def _build_stage2_bootstrap_brief(stage1_manifest: dict) -> dict[str, Any]:
    change_briefs: list[dict[str, Any]] = []
    for change in stage1_manifest.get("changes", []):
        artifact_path = change.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path:
            continue
        risk_flags = _dedupe_non_empty(
            [
                *change.get("unintended_risk_flags", []),
                *change.get("false_negative_risks", []),
                *change.get("false_positive_risks", []),
            ]
        )
        changed_entities = [
            entity.model_dump(mode="json") if hasattr(entity, "model_dump") else entity
            for entity in change.get("changed_entities", [])
        ]
        evidence_snippets = [
            snippet.model_dump(mode="json") if hasattr(snippet, "model_dump") else snippet
            for snippet in change.get("evidence_snippets", [])
        ]
        observable_delta = change.get("observable_delta")
        if hasattr(observable_delta, "model_dump"):
            observable_delta = observable_delta.model_dump(mode="json")
        change_briefs.append(
            {
                "artifact_path": artifact_path,
                "artifact_class": change.get("artifact_class"),
                "inferred_intent": change.get("inferred_intent"),
                "change_summary": change.get("change_summary"),
                "affected_components": change.get("affected_components", []),
                "risk_flags": risk_flags,
                "behavioral_signatures": change.get("behavioral_signatures", []),
                "changed_entities": changed_entities,
                "observable_delta": observable_delta,
                "eval_search_hints": change.get("eval_search_hints", []),
                "validation_focus": change.get("validation_focus", []),
                "evidence_snippets": evidence_snippets,
            }
        )
    return {
        "overall_risk": stage1_manifest.get("overall_risk"),
        "compound_change_detected": bool(stage1_manifest.get("compound_change_detected")),
        "changes": change_briefs,
    }


def _build_bootstrap_target(change: dict[str, Any], reason: str) -> ResolvedEvalTarget:
    artifact_path = change.get("artifact_path", "unknown")
    target_id = f"bootstrap::{artifact_path}"
    profile = EvalTargetProfile(
        target_id=target_id,
        platform="bootstrap",
        locator=artifact_path,
        target_name=f"Bootstrap target for {artifact_path}",
        artifact_paths=[artifact_path],
        resolution_source="bootstrap",
        access_mode="synthetic",
        write_capability="review_only",
        profile_confidence=0.0,
    )
    method_profile = EvalMethodProfile(
        method_kind="unknown",
        input_shape="unknown",
        assertion_style="unknown",
        renderability_status="review_only",
        confidence=0.0,
        notes=[reason],
    )
    return ResolvedEvalTarget(
        profile=profile,
        method_profile=method_profile,
        samples=[],
        raw_field_patterns=[],
        aggregate_method_hints=[],
        resolution_notes=[reason],
    )


def _coerce_partial_stage2_targets(partial_payload: dict[str, Any] | None) -> list[ResolvedEvalTarget]:
    if not isinstance(partial_payload, dict):
        return []
    raw_targets = partial_payload.get("resolved_targets")
    if not isinstance(raw_targets, list):
        return []
    valid: list[ResolvedEvalTarget] = []
    seen: set[str] = set()
    for raw_target in raw_targets:
        if not isinstance(raw_target, dict):
            continue
        try:
            target = ResolvedEvalTarget.model_validate(raw_target)
        except Exception:
            continue
        if target.profile.target_id in seen:
            continue
        seen.add(target.profile.target_id)
        valid.append(target)
    return valid


def _coerce_partial_stage2_gaps(partial_payload: dict[str, Any] | None) -> list[CoverageGap]:
    if not isinstance(partial_payload, dict):
        return []
    raw_gaps = partial_payload.get("gaps")
    if not isinstance(raw_gaps, list):
        return []
    valid_gaps: list[CoverageGap] = []
    seen_gap_ids: set[str] = set()
    for raw_gap in raw_gaps:
        if not isinstance(raw_gap, dict):
            continue
        try:
            gap = CoverageGap.model_validate(raw_gap)
        except Exception:
            continue
        if gap.gap_id in seen_gap_ids:
            continue
        seen_gap_ids.add(gap.gap_id)
        valid_gaps.append(gap)
    return valid_gaps


def _coerce_partial_stage2_coverage(partial_payload: dict[str, Any] | None) -> list[CoverageTargetSummary]:
    if not isinstance(partial_payload, dict):
        return []
    raw_items = partial_payload.get("coverage_by_target")
    if not isinstance(raw_items, list):
        return []
    valid: list[CoverageTargetSummary] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        try:
            summary = CoverageTargetSummary.model_validate(raw_item)
        except Exception:
            continue
        if summary.target_id in seen:
            continue
        seen.add(summary.target_id)
        valid.append(summary)
    return valid


def _infer_guardrail_direction(change: dict[str, Any], risk_flag: str) -> str | None:
    if risk_flag in _dedupe_non_empty(change.get("false_negative_risks", [])):
        return "should_catch"
    if risk_flag in _dedupe_non_empty(change.get("false_positive_risks", [])):
        return "should_pass"
    return None


def _build_stage2_fallback_gaps(stage1_manifest: dict, reason: str) -> list[CoverageGap]:
    gaps: list[CoverageGap] = []
    overall_risk = stage1_manifest.get("overall_risk") or "medium"
    for change_index, change in enumerate(stage1_manifest.get("changes", []), start=1):
        artifact_path = change.get("artifact_path")
        if not isinstance(artifact_path, str) or not artifact_path:
            continue
        target_id = f"bootstrap::{artifact_path}"
        risk_flags = _dedupe_non_empty(
            [
                *change.get("unintended_risk_flags", []),
                *change.get("false_negative_risks", []),
                *change.get("false_positive_risks", []),
            ]
        )
        if not risk_flags:
            fallback_flag = change.get("change_summary") or change.get("inferred_intent") or "Behavior changed"
            risk_flags = [str(fallback_flag)]
        for risk_index, risk_flag in enumerate(risk_flags, start=1):
            gaps.append(
                CoverageGap(
                    gap_id=f"{target_id}::gap::{change_index:03d}:{risk_index:02d}",
                    artifact_path=artifact_path,
                    target_id=target_id,
                    method_kind="unknown",
                    gap_type="uncovered",
                    related_risk_flag=risk_flag,
                    description="Bootstrap this behavior as a new eval area because analysis did not complete.",
                    why_gap_is_real=reason,
                    existing_coverage_notes="No validated native corpus comparison was completed before the fallback.",
                    recommended_eval_area=change.get("artifact_class") or "behavior_regression",
                    recommended_eval_mode="unknown",
                    native_shape_hints=list(change.get("validation_focus", [])),
                    compatible_nearest_cases=[],
                    repo_asset_refs=[],
                    priority=overall_risk,
                    profile_status="bootstrap",
                    guardrail_direction=_infer_guardrail_direction(change, risk_flag),
                    is_conversational=False,
                    confidence=0.0,
                )
            )
    return gaps


def _build_stage2_fallback_coverage(
    stage1_manifest: dict,
    resolved_targets: list[ResolvedEvalTarget],
    reason: str,
) -> list[CoverageTargetSummary]:
    summaries: list[CoverageTargetSummary] = []
    for target in resolved_targets:
        sample_count = len(target.samples)
        summaries.append(
            CoverageTargetSummary(
                target_id=target.profile.target_id,
                method_kind=target.method_profile.method_kind,
                total_relevant_cases=sample_count,
                cases_covering_changed_behavior=0,
                coverage_ratio=0.0,
                mode="bootstrap" if sample_count == 0 or target.profile.platform == "bootstrap" else "coverage_aware",
                corpus_status="empty" if sample_count == 0 else "available",
                profile_status="bootstrap" if sample_count == 0 or target.profile.platform == "bootstrap" else "uncertain",
                retrieval_notes=reason if sample_count > 0 else None,
                bootstrap_reason=reason if sample_count == 0 or target.profile.platform == "bootstrap" else None,
                analysis_notes=[],
            )
        )
    if summaries:
        return summaries
    for change in stage1_manifest.get("changes", []):
        artifact_path = change.get("artifact_path")
        if not isinstance(artifact_path, str):
            continue
        summaries.append(
            CoverageTargetSummary(
                target_id=f"bootstrap::{artifact_path}",
                method_kind="unknown",
                total_relevant_cases=0,
                cases_covering_changed_behavior=0,
                coverage_ratio=0.0,
                mode="bootstrap",
                corpus_status="unavailable",
                profile_status="bootstrap",
                bootstrap_reason=reason,
                analysis_notes=[],
            )
        )
    return summaries


def _coerce_partial_stage2_manifest(
    *,
    partial_payload: dict[str, Any] | None,
    run_id: str,
    stage1_manifest: dict,
    timestamp: str,
    runtime_metadata: dict[str, Any],
) -> EvalAnalysisManifest | None:
    if not isinstance(partial_payload, dict):
        return None
    candidate = dict(partial_payload)
    candidate["run_id"] = run_id
    candidate["stage1_run_id"] = stage1_manifest.get("run_id", "")
    candidate["timestamp"] = timestamp
    candidate["runtime_metadata"] = runtime_metadata
    candidate.setdefault(
        "unresolved_artifacts",
        [
            change.get("artifact_path")
            for change in stage1_manifest.get("changes", [])
            if isinstance(change.get("artifact_path"), str)
        ],
    )
    try:
        return EvalAnalysisManifest.model_validate(candidate)
    except Exception:
        return None


def _build_stage2_budget_fallback(
    *,
    stage1_manifest: dict,
    run_id: str,
    timestamp: str,
    runtime_metadata: dict[str, Any],
    reason: str,
    partial_payload: dict[str, Any] | None = None,
) -> EvalAnalysisManifest:
    partial_manifest = _coerce_partial_stage2_manifest(
        partial_payload=partial_payload,
        run_id=run_id,
        stage1_manifest=stage1_manifest,
        timestamp=timestamp,
        runtime_metadata=runtime_metadata,
    )
    if partial_manifest is not None:
        return partial_manifest

    partial_targets = _coerce_partial_stage2_targets(partial_payload)
    resolved_targets = partial_targets or [
        _build_bootstrap_target(change, reason)
        for change in stage1_manifest.get("changes", [])
        if isinstance(change.get("artifact_path"), str)
    ]
    gaps = _coerce_partial_stage2_gaps(partial_payload) or _build_stage2_fallback_gaps(stage1_manifest, reason)
    coverage_by_target = _coerce_partial_stage2_coverage(partial_payload) or _build_stage2_fallback_coverage(
        stage1_manifest,
        resolved_targets,
        reason,
    )
    unresolved_artifacts = [
        change.get("artifact_path")
        for change in stage1_manifest.get("changes", [])
        if isinstance(change.get("artifact_path"), str)
    ]
    return EvalAnalysisManifest.model_validate(
        {
            "run_id": run_id,
            "stage1_run_id": stage1_manifest.get("run_id", ""),
            "timestamp": timestamp,
            "unresolved_artifacts": unresolved_artifacts,
            "resolved_targets": [target.model_dump(mode="json") for target in resolved_targets],
            "coverage_by_target": [summary.model_dump(mode="json") for summary in coverage_by_target],
            "gaps": [gap.model_dump(mode="json") for gap in gaps],
            "runtime_metadata": runtime_metadata,
        }
    )


def run_stage2(
    stage1_manifest: dict,
    config: ParityConfig,
    *,
    cwd: str | Path | None = None,
) -> StageRunResult:
    run_id = f"stage2-{int(time.time())}"
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resolved_spend = config.resolve_spend_caps()
    rule_resolutions = _build_stage2_rule_resolutions(stage1_manifest, config)
    bootstrap_brief = _build_stage2_bootstrap_brief(stage1_manifest)
    prompt = render_stage2_prompt(
        stage1_manifest,
        rule_resolutions=rule_resolutions,
        bootstrap_brief=bootstrap_brief,
    )

    change_count = len(stage1_manifest.get("changes", []))
    explicit_rule_count = sum(1 for resolution in rule_resolutions if resolution.get("rule_status") == "explicit")
    unresolved_rule_count = sum(1 for resolution in rule_resolutions if resolution.get("rule_status") == "unresolved")
    prompt_tokens = count_tokens(prompt)
    print(
        f"[stage-2] changes_from_stage1={change_count} explicit_rules={explicit_rule_count} "
        f"unresolved_rules={unresolved_rule_count} prompt_tokens={prompt_tokens}",
        file=sys.stderr,
        flush=True,
    )

    output_schema = simplify_schema(
        EvalAnalysisManifest.model_json_schema(),
        remove_keys=_STAGE2_INJECT_KEYS,
    )

    repo_root = Path(cwd or Path.cwd()).resolve()
    stage2_runtime = build_stage2_mcp_server(
        config=config,
        repo_root=repo_root,
        env=dict(os.environ),
        embedding_spend_cap_usd=resolved_spend.stage2_embedding_cap_usd,
    )
    options = ClaudeAgentOptions(
        tools=[],
        mcp_servers={
            "parity_stage2": {
                "type": "sdk",
                "name": "parity-stage2",
                "instance": stage2_runtime.server._mcp_server,
            }
        },
        max_turns=40,
        max_budget_usd=resolved_spend.stage2_agent_cap_usd,
        cwd=str(repo_root),
        output_format={"type": "json_schema", "schema": output_schema},
    )

    degraded_reason: str | None = None
    try:
        result = asyncio.run(
            run_stage_with_retry(
                stage_num=2,
                prompt=prompt,
                options=options,
                output_model=EvalAnalysisManifest,
                inject_fields={
                    "run_id": run_id,
                    "stage1_run_id": stage1_manifest.get("run_id", ""),
                    "timestamp": timestamp,
                },
            )
        )
    except BudgetExceededError as exc:
        degraded_reason = (
            "Stage 2 spend cap was exhausted before full eval analysis completed. "
            "Returning a degraded analysis manifest from partial discovery and bootstrap gaps."
        )
        print(f"[stage-2] degraded_fallback: {degraded_reason}", file=sys.stderr, flush=True)
        result = StageRunResult(
            data=_build_stage2_budget_fallback(
                stage1_manifest=stage1_manifest,
                run_id=run_id,
                timestamp=timestamp,
                runtime_metadata=stage2_runtime.toolbox.build_runtime_metadata(),
                reason=degraded_reason,
                partial_payload=exc.partial_result if isinstance(exc.partial_result, dict) else None,
            ),
            model=None,
            cost_usd=exc.cost_usd,
            duration_ms=0,
            num_turns=0,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            raw_result=None,
        )

    runtime_metadata = stage2_runtime.toolbox.build_runtime_metadata()
    result.data.runtime_metadata = runtime_metadata
    target_count = len(result.data.resolved_targets)
    gap_count = len(result.data.gaps)
    print(
        f"[stage-2] targets_resolved={target_count} gaps_identified={gap_count}",
        file=sys.stderr,
        flush=True,
    )
    for target in result.data.resolved_targets[:5]:
        print(
            f"[stage-2] target={target.profile.target_id} platform={target.profile.platform} "
            f"method={target.method_profile.method_kind} renderability={target.method_profile.renderability_status} "
            f"samples={len(target.samples)}",
            file=sys.stderr,
            flush=True,
        )

    result.extras = {
        **(result.extras or {}),
        "prompt_tokens": prompt_tokens,
        "explicit_rules": explicit_rule_count,
        "unresolved_rules": unresolved_rule_count,
        "resolved_spend_caps": {
            "analysis_total_spend_cap_usd": resolved_spend.analysis_total_spend_cap_usd,
            "stage1_agent_cap_usd": resolved_spend.stage1_agent_cap_usd,
            "stage2_agent_cap_usd": resolved_spend.stage2_agent_cap_usd,
            "stage2_embedding_cap_usd": resolved_spend.stage2_embedding_cap_usd,
            "stage3_agent_cap_usd": resolved_spend.stage3_agent_cap_usd,
            "source": resolved_spend.source,
        },
        "degraded": degraded_reason is not None,
        "degraded_reason": degraded_reason,
        **runtime_metadata,
    }
    return result

