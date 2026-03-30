from __future__ import annotations

from typing import Any

import braintrust

from parity.errors import PlatformIntegrationError
from parity.integrations._contracts import infer_method_kind_from_assertions, legacy_assertions, normalized_tags, parse_native_assertions
from parity.models import EvalCaseSnapshot, EvaluatorBindingCandidate, NativeEvalRendering


class BraintrustReader:
    """Read access is expected to be MCP-mediated in Stage 2."""

    def fetch_examples(self, *args: Any, **kwargs: Any) -> list[EvalCaseSnapshot]:
        raise PlatformIntegrationError(
            "BraintrustReader is MCP-mediated in Stage 2; use BraintrustDirectReader as a fallback."
        )


class BraintrustDirectReader:
    def __init__(self, *, api_key: str | None = None, org_name: str | None = None) -> None:
        self.api_key = api_key
        self.org_name = org_name

    def fetch_examples(
        self,
        *,
        project: str,
        dataset_name: str,
        limit: int | None = None,
    ) -> list[EvalCaseSnapshot]:
        dataset = braintrust.init_dataset(
            project=project,
            name=dataset_name,
            api_key=self.api_key,
            org_name=self.org_name,
        )
        rows = dataset.fetch()
        examples: list[EvalCaseSnapshot] = []
        for index, row in enumerate(rows):
            if limit is not None and index >= limit:
                break
            input_raw = row.get("input")
            metadata = row.get("metadata") or {}
            expected = row.get("expected")
            native_assertions = parse_native_assertions(
                metadata.get("parity_assertions"),
                assertion_id_prefix=str(row.get("id") or f"{dataset_name}:{index}"),
                default_metadata=metadata,
            )
            if not native_assertions:
                native_assertions = legacy_assertions(
                    assertion_id_prefix=str(row.get("id") or f"{dataset_name}:{index}"),
                    metadata=metadata,
                    expected_output=expected,
                    assertion_type=metadata.get("assertion_type"),
                    rubric=metadata.get("rubric"),
                )
            method_kind = infer_method_kind_from_assertions(native_assertions)
            examples.append(
                EvalCaseSnapshot.model_validate(
                    {
                        "case_id": row.get("id") or f"{dataset_name}:{index}",
                        "source_platform": "braintrust",
                        "source_target_id": str(getattr(dataset, "id", dataset_name)),
                        "source_target_name": dataset_name,
                        "target_locator": dataset_name,
                        "project": project,
                        "method_kind": method_kind,
                        "native_case": row,
                        "native_input": input_raw,
                        "native_output": expected,
                        "native_assertions": native_assertions,
                        "metadata": metadata,
                        "tags": normalized_tags(row.get("tags"), metadata.get("tags")),
                        "embedding": metadata.get("embedding"),
                        "embedding_model": metadata.get("embedding_model"),
                        "method_hints": ["braintrust_dataset"],
                        "method_confidence": 0.75 if native_assertions else 0.25,
                    }
                )
            )
        return examples

    def discover_evaluator_bindings(
        self,
        *,
        project: str,
        dataset_name: str,
    ) -> list[EvaluatorBindingCandidate]:
        # Braintrust scorer discovery is usually repo- or API-managed rather than
        # attached to dataset rows through the dataset SDK surface we use here.
        return []

    def read_evaluator_binding(
        self,
        binding_id: str,
        *,
        project: str,
        dataset_name: str,
    ) -> dict[str, Any]:
        raise KeyError(f"Unknown Braintrust evaluator binding: {binding_id}")

    def verify_evaluator_binding(
        self,
        binding_id: str,
        *,
        project: str,
        dataset_name: str,
    ) -> dict[str, Any]:
        return {
            "platform": "braintrust",
            "binding_id": binding_id,
            "verified": False,
            "verification_status": "unsupported",
            "note": "Braintrust evaluator verification is repo/API-managed outside the dataset SDK surface used by Parity.",
        }


class BraintrustWriter:
    def __init__(self, *, api_key: str | None = None, org_name: str | None = None) -> None:
        self.api_key = api_key
        self.org_name = org_name

    def create_examples_from_renderings(
        self,
        renderings: list[NativeEvalRendering],
        *,
        project: str,
        dataset_name: str,
    ) -> Any:
        dataset = braintrust.init_dataset(
            project=project,
            name=dataset_name,
            api_key=self.api_key,
            org_name=self.org_name,
        )
        inserted_ids = []
        for rendering in renderings:
            if rendering.rendering_kind != "braintrust_record":
                continue
            payload = rendering.payload
            inserted_ids.append(
                dataset.insert(
                    input=payload.get("input"),
                    expected=payload.get("expected"),
                    metadata={
                        **(payload.get("metadata") or {}),
                        "rendering_id": rendering.rendering_id,
                        "write_status": rendering.write_status,
                    },
                    tags=list(payload.get("tags") or []),
                    id=rendering.rendering_id,
                )
            )
        if hasattr(dataset, "flush"):
            dataset.flush()
        return inserted_ids
