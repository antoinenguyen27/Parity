from __future__ import annotations

from typing import Any

from parity.models import NativeAssertion
from parity.models.eval_case import flatten_expected_output


def serialize_native_assertions(assertions: list[NativeAssertion]) -> list[dict[str, Any]]:
    return [assertion.model_dump(mode="json", exclude_none=True) for assertion in assertions]


def parse_native_assertions(
    raw_assertions: Any,
    *,
    assertion_id_prefix: str,
    default_metadata: dict[str, Any] | None = None,
) -> list[NativeAssertion]:
    if not isinstance(raw_assertions, list):
        return []
    assertions: list[NativeAssertion] = []
    for index, raw_assertion in enumerate(raw_assertions):
        if not isinstance(raw_assertion, dict):
            continue
        payload = dict(raw_assertion)
        payload.setdefault("assertion_id", f"{assertion_id_prefix}:{index}")
        merged_metadata = dict(default_metadata or {})
        merged_metadata.update(payload.get("metadata") or {})
        payload["metadata"] = merged_metadata
        assertions.append(NativeAssertion.model_validate(payload))
    return assertions


def infer_method_kind_from_assertions(assertions: list[NativeAssertion]) -> str:
    kinds = {assertion.assertion_kind for assertion in assertions}
    if "trajectory" in kinds:
        return "trajectory"
    if "pairwise" in kinds:
        return "pairwise"
    if "human_review" in kinds:
        return "human_review"
    if "judge" in kinds and "deterministic" in kinds:
        return "hybrid"
    if "hybrid" in kinds:
        return "hybrid"
    if "judge" in kinds:
        return "judge"
    if "deterministic" in kinds:
        return "deterministic"
    return "unknown"


def legacy_assertions(
    *,
    assertion_id_prefix: str,
    metadata: dict[str, Any],
    expected_output: Any,
    assertion_type: str | None = None,
    rubric: str | None = None,
    deterministic_operator: str = "contains",
) -> list[NativeAssertion]:
    assertions: list[NativeAssertion] = []
    expected_text = flatten_expected_output(expected_output)
    if assertion_type in {"llm-rubric", "llm_rubric"} or rubric:
        assertions.append(
            NativeAssertion.model_validate(
                {
                    "assertion_id": f"{assertion_id_prefix}:judge",
                    "assertion_kind": "judge",
                    "operator": assertion_type or "llm-rubric",
                    "rubric": rubric or expected_text,
                    "metadata": metadata,
                }
            )
        )
    if expected_text:
        assertions.append(
            NativeAssertion.model_validate(
                {
                    "assertion_id": f"{assertion_id_prefix}:expected",
                    "assertion_kind": "deterministic",
                    "operator": (
                        assertion_type
                        if assertion_type and assertion_type not in {"llm-rubric", "llm_rubric"}
                        else deterministic_operator
                    ),
                    "expected_value": expected_text,
                    "metadata": metadata,
                }
            )
        )
    return assertions


def normalized_tags(*sources: Any) -> list[str]:
    tags: list[str] = []
    for source in sources:
        if isinstance(source, list):
            candidates = source
        elif isinstance(source, tuple):
            candidates = list(source)
        else:
            candidates = [source]
        for candidate in candidates:
            if isinstance(candidate, str):
                normalized = candidate.strip()
                if normalized and normalized not in tags:
                    tags.append(normalized)
    return tags
