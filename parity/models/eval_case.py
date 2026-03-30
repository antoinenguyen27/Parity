from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from parity.models._base import ParityModel

ConversationRole = Literal["system", "user", "assistant", "tool"]
InputLike = str | dict[str, Any] | list[dict[str, Any]]
MethodKind = Literal[
    "deterministic",
    "judge",
    "hybrid",
    "pairwise",
    "human_review",
    "trajectory",
    "unknown",
]
SourcePlatform = Literal["langsmith", "braintrust", "phoenix", "promptfoo", "bootstrap"]

PRIORITY_INPUT_KEYS = (
    "query",
    "input",
    "question",
    "message",
    "user_message",
    "prompt",
)
PRIORITY_EXPECTATION_KEYS = (
    "expected_behavior",
    "answer",
    "output",
    "expected",
    "response",
    "expected_output",
)


class ConversationMessage(ParityModel):
    role: ConversationRole
    content: str


def normalize_conversational(messages: list[dict[str, Any]] | list[ConversationMessage]) -> str:
    normalized_messages = []
    for message in messages:
        role = message.role if isinstance(message, ConversationMessage) else message.get("role")
        content = message.content if isinstance(message, ConversationMessage) else message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError("Conversation messages must include string role and content fields")
        normalized_messages.append(f"{role.upper()}: {content}")
    return "\n".join(normalized_messages)


def is_conversation_input(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict) and {"role", "content"} <= set(item) for item in value
    )


def normalize_input(value: Any) -> str:
    if isinstance(value, str):
        return value
    if is_conversation_input(value):
        return normalize_conversational(value)
    if isinstance(value, dict):
        for key in PRIORITY_INPUT_KEYS:
            if key in value:
                return normalize_input(value[key])
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def flatten_expected_output(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in PRIORITY_EXPECTATION_KEYS:
            selected = value.get(key)
            if isinstance(selected, str):
                return selected
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


class NativeAssertion(ParityModel):
    assertion_id: str
    assertion_kind: MethodKind
    operator: str | None = None
    expected_value: str | None = None
    rubric: str | None = None
    evaluator_name: str | None = None
    pass_threshold: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("pass_threshold")
    @classmethod
    def validate_threshold(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not 0.0 <= value <= 1.0:
            raise ValueError("pass_threshold must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> "NativeAssertion":
        if self.assertion_kind == "deterministic":
            if self.expected_value is None and not self.metadata:
                raise ValueError("deterministic assertions require expected_value or metadata")
        elif self.assertion_kind == "judge":
            if self.rubric is None:
                raise ValueError("judge assertions require rubric")
        elif self.assertion_kind == "hybrid":
            if self.expected_value is None and self.rubric is None:
                raise ValueError("hybrid assertions require expected_value or rubric")
        return self


class NormalizedProjection(ParityModel):
    input_text: str
    expected_text: str | None = None
    comparison_text: str
    is_conversational: bool = False

    @model_validator(mode="after")
    def populate_comparison_text(self) -> "NormalizedProjection":
        if not self.comparison_text:
            comparison_parts = [self.input_text]
            if self.expected_text:
                comparison_parts.append(self.expected_text)
            self.comparison_text = "\n\n".join(part for part in comparison_parts if part)
        return self


class EvalCaseSnapshot(ParityModel):
    case_id: str
    source_platform: SourcePlatform
    source_target_id: str
    source_target_name: str
    target_locator: str
    project: str | None = None
    method_kind: MethodKind = "unknown"
    native_case: dict[str, Any] = Field(default_factory=dict)
    native_input: InputLike | None = None
    native_output: Any | None = None
    normalized_projection: NormalizedProjection
    native_assertions: list[NativeAssertion] = Field(default_factory=list)
    method_hints: list[str] = Field(default_factory=list)
    method_confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None
    embedding_model: str | None = None

    @field_validator("embedding")
    @classmethod
    def ensure_embedding_values(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("embedding vectors must not be empty")
        return value

    @field_validator("method_confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("method_confidence must be between 0 and 1")
        return value

    @model_validator(mode="before")
    @classmethod
    def populate_projection(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        native_input = value.get("native_input")
        if native_input is None and "input_raw" in value:
            native_input = value.get("input_raw")
            value.setdefault("native_input", native_input)
        native_output = value.get("native_output")
        if native_output is None and "expected_output" in value:
            native_output = value.get("expected_output")
            value.setdefault("native_output", native_output)
        projection = value.get("normalized_projection")
        if not isinstance(projection, dict):
            input_text = normalize_input(native_input)
            expected_text = flatten_expected_output(native_output)
            value["normalized_projection"] = {
                "input_text": input_text,
                "expected_text": expected_text,
                "comparison_text": "\n\n".join(
                    part for part in (input_text, expected_text) if isinstance(part, str) and part
                ),
                "is_conversational": is_conversation_input(native_input),
            }
        return value

    @model_validator(mode="after")
    def validate_method_assertions(self) -> "EvalCaseSnapshot":
        if self.method_kind == "deterministic" and any(
            assertion.assertion_kind == "judge" for assertion in self.native_assertions
        ):
            raise ValueError("deterministic case snapshots cannot contain judge assertions")
        if self.method_kind == "judge" and not any(
            assertion.assertion_kind == "judge" for assertion in self.native_assertions
        ):
            raise ValueError("judge case snapshots require at least one judge assertion")
        return self


# Backward-compatible alias inside the codebase while the rest of the runtime migrates.
EvalCase = EvalCaseSnapshot
