from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from parity.context import count_tokens
from parity.errors import CacheError, EmbeddingError

EMBEDDING_MODEL_PRICES_USD_PER_1M_INPUT_TOKENS = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


_OPENAI_EMBEDDING_ERROR_ACTIONS: dict[str, str] = {
    "provider_invalid_request": (
        "Check embedding input size, empty-string inputs, model name, and dimensions before retrying."
    ),
    "authentication": "Verify the OpenAI API key used for embeddings, then retry.",
    "permission": "Check that the OpenAI project and key can access the requested embedding model, then retry.",
    "provider_not_found": "Check the embedding model identifier and retry.",
    "provider_unprocessable": "Adjust the embedding request payload, then retry.",
    "quota_or_billing": "Increase OpenAI quota or billing budget, or wait for quota reset, then retry.",
    "rate_limit": "Retry later. OpenAI rate limiting is temporary.",
    "provider_internal": "Retry the embedding request. If it persists, contact OpenAI support with the request ID.",
    "connection": "Check network connectivity to OpenAI and retry.",
    "timeout": "Retry the embedding request. If timeouts persist, reduce batch size or review network conditions.",
    "provider_error": "Inspect the OpenAI error details and request ID, then retry once resolved.",
    "unknown": "Inspect the embedding diagnostics and retry once the underlying issue is resolved.",
}


def _safe_preview(value: Any, *, limit: int = 240) -> str:
    preview = str(value or "")[:limit]
    return preview.replace("\n", "\\n")


def _summarize_embedding_request(
    items: list["EmbeddingItem"],
    *,
    model: str,
    dimensions: int | None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    input_tokens_estimate = sum(count_tokens(item.text) for item in items)
    text_characters = sum(len(item.text) for item in items)
    summary = {
        "model": model,
        "dimensions": dimensions,
        "input_count": len(items),
        "input_tokens_estimate": input_tokens_estimate,
        "text_characters": text_characters,
        "item_ids_preview": [item.id for item in items[:10]],
    }
    if elapsed_ms is not None:
        summary["elapsed_ms"] = elapsed_ms
    return summary


def _classify_embedding_failure(exc: Exception) -> dict[str, Any]:
    message = getattr(exc, "message", str(exc)).strip() or exc.__class__.__name__
    if isinstance(exc, APITimeoutError):
        return {
            "category": "timeout",
            "provider": "openai",
            "http_status": None,
            "provider_error_type": None,
            "request_id": None,
            "error_code": None,
            "param": None,
            "retryable": True,
            "user_actionable": False,
            "summary": message,
            "next_action": _OPENAI_EMBEDDING_ERROR_ACTIONS["timeout"],
            "sdk_error_class": exc.__class__.__name__,
        }
    if isinstance(exc, APIConnectionError):
        return {
            "category": "connection",
            "provider": "openai",
            "http_status": None,
            "provider_error_type": None,
            "request_id": None,
            "error_code": None,
            "param": None,
            "retryable": True,
            "user_actionable": False,
            "summary": message,
            "next_action": _OPENAI_EMBEDDING_ERROR_ACTIONS["connection"],
            "sdk_error_class": exc.__class__.__name__,
        }

    if isinstance(exc, APIStatusError):
        error_type = getattr(exc, "type", None)
        error_code = getattr(exc, "code", None)
        param = getattr(exc, "param", None)
        lowered_message = message.lower()
        quota_like = isinstance(exc, RateLimitError) and (
            error_code == "insufficient_quota"
            or "insufficient_quota" in lowered_message
            or "quota" in lowered_message
            or "billing" in lowered_message
            or "credit" in lowered_message
        )

        category = "provider_error"
        retryable = False
        user_actionable = True
        if isinstance(exc, AuthenticationError):
            category = "authentication"
        elif isinstance(exc, PermissionDeniedError):
            category = "permission"
        elif isinstance(exc, NotFoundError):
            category = "provider_not_found"
        elif isinstance(exc, BadRequestError):
            category = "provider_invalid_request"
        elif isinstance(exc, UnprocessableEntityError):
            category = "provider_unprocessable"
        elif quota_like:
            category = "quota_or_billing"
        elif isinstance(exc, RateLimitError):
            category = "rate_limit"
            retryable = True
            user_actionable = False
        elif isinstance(exc, InternalServerError) or exc.status_code >= 500:
            category = "provider_internal"
            retryable = True
            user_actionable = False

        return {
            "category": category,
            "provider": "openai",
            "http_status": exc.status_code,
            "provider_error_type": error_type,
            "request_id": getattr(exc, "request_id", None),
            "error_code": error_code,
            "param": param,
            "retryable": retryable,
            "user_actionable": user_actionable,
            "summary": message,
            "next_action": _OPENAI_EMBEDDING_ERROR_ACTIONS.get(category, _OPENAI_EMBEDDING_ERROR_ACTIONS["provider_error"]),
            "sdk_error_class": exc.__class__.__name__,
        }

    return {
        "category": "unknown",
        "provider": "openai",
        "http_status": None,
        "provider_error_type": None,
        "request_id": None,
        "error_code": None,
        "param": None,
        "retryable": False,
        "user_actionable": True,
        "summary": message,
        "next_action": _OPENAI_EMBEDDING_ERROR_ACTIONS["unknown"],
        "sdk_error_class": exc.__class__.__name__,
    }


def _format_embedding_failure_message(failure: dict[str, Any]) -> str:
    message = f"Embedding request failed: {failure.get('summary', 'Unknown OpenAI embedding error')}"
    request_id = failure.get("request_id")
    if isinstance(request_id, str) and request_id:
        message += f" Request ID: {request_id}."
    next_action = failure.get("next_action")
    if isinstance(next_action, str) and next_action:
        message += f" Action: {next_action}"
    return message


def compute_text_hash(item_id: str, text: str) -> str:
    digest = sha256(f"{item_id}{text}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_cache_key(item_id: str, text: str, model: str, dimensions: int | None = None) -> str:
    suffix = "" if dimensions is None else str(dimensions)
    digest = sha256(f"{item_id}{text}{model}{suffix}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass(slots=True)
class EmbeddingItem:
    id: str
    text: str


@dataclass(slots=True)
class EmbeddingBatchUsage:
    model: str
    request_count: int
    input_count: int
    cached_count: int
    miss_count: int
    input_tokens: int
    estimated_cost_usd: float | None
    request_id: str | None = None
    duration_ms: int | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "request_count": self.request_count,
            "input_count": self.input_count,
            "cached_count": self.cached_count,
            "miss_count": self.miss_count,
            "input_tokens": self.input_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "request_id": self.request_id,
            "duration_ms": self.duration_ms,
        }


@dataclass(slots=True)
class PlannedEmbeddingBatch:
    items: list[EmbeddingItem]
    cached_results: dict[str, dict[str, Any]]
    misses: list[EmbeddingItem]
    cache_warning: bool
    usage: EmbeddingBatchUsage


class EmbeddingCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                dimensions INTEGER,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        return connection

    def get(
        self,
        *,
        item_id: str,
        text_hash: str,
        model: str,
        dimensions: int | None = None,
    ) -> list[float] | None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            row = connection.execute(
                """
                SELECT embedding_json
                FROM embeddings
                WHERE item_id = ? AND text_hash = ? AND model = ? AND dimensions IS ?
                """,
                (item_id, text_hash, model, dimensions),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CacheError(f"Embedding cache read failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        if row is None:
            return None
        return json.loads(row[0])

    def set(
        self,
        *,
        item_id: str,
        text_hash: str,
        model: str,
        embedding: list[float],
        dimensions: int | None = None,
    ) -> None:
        cache_key = compute_cache_key(item_id, text_hash, model, dimensions)
        created_at = datetime.now(tz=timezone.utc).isoformat()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute(
                """
                INSERT OR REPLACE INTO embeddings (
                    cache_key,
                    item_id,
                    text_hash,
                    model,
                    dimensions,
                    embedding_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    item_id,
                    text_hash,
                    model,
                    dimensions,
                    json.dumps(embedding),
                    created_at,
                )
            )
            connection.commit()
        except sqlite3.Error as exc:
            raise CacheError(f"Embedding cache write failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()


def _request_embeddings(
    items: list[EmbeddingItem],
    *,
    model: str,
    dimensions: int | None = None,
    client: Any | None = None,
) -> tuple[list[list[float]], int, str | None, int]:
    openai_client = client or OpenAI()
    kwargs: dict[str, Any] = {"model": model, "input": [item.text for item in items]}
    if dimensions is not None:
        kwargs["dimensions"] = dimensions

    started_at = time.monotonic()
    try:
        response = openai_client.embeddings.create(**kwargs)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        failure = _classify_embedding_failure(exc)
        request_summary = _summarize_embedding_request(
            items,
            model=model,
            dimensions=dimensions,
            elapsed_ms=elapsed_ms,
        )
        raise EmbeddingError(
            _format_embedding_failure_message(failure),
            details={
                "request": request_summary,
                "failure": failure,
                "response_body_preview": _safe_preview(getattr(exc, "body", None)),
            },
        ) from exc

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "total_tokens", None)
    if input_tokens is None:
        input_tokens = sum(count_tokens(item.text) for item in items)

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    request_id = getattr(response, "_request_id", None)
    return [list(record.embedding) for record in response.data], int(input_tokens), request_id, elapsed_ms


def resolve_embedding_input_price_usd_per_million(model: str) -> float | None:
    return EMBEDDING_MODEL_PRICES_USD_PER_1M_INPUT_TOKENS.get(model)


def estimate_embedding_cost_usd(*, model: str, input_tokens: int) -> float | None:
    price = resolve_embedding_input_price_usd_per_million(model)
    if price is None:
        return None
    return (input_tokens / 1_000_000) * price


def _normalize_embedding_inputs(
    inputs: list[dict[str, str]] | list[EmbeddingItem],
) -> list[EmbeddingItem]:
    return [
        item if isinstance(item, EmbeddingItem) else EmbeddingItem(id=item["id"], text=item["text"])
        for item in inputs
    ]


def plan_embedding_batch(
    inputs: list[dict[str, str]] | list[EmbeddingItem],
    *,
    model: str,
    cache_path: str | Path,
    dimensions: int | None = None,
) -> PlannedEmbeddingBatch:
    items = _normalize_embedding_inputs(inputs)
    cache = EmbeddingCache(cache_path)
    cached_results: dict[str, dict[str, Any]] = {}
    misses: list[EmbeddingItem] = []
    cache_warning = False

    for item in items:
        text_hash = compute_text_hash(item.id, item.text)
        try:
            cached_embedding = cache.get(
                item_id=item.id,
                text_hash=text_hash,
                model=model,
                dimensions=dimensions,
            )
        except CacheError:
            cache_warning = True
            cached_embedding = None

        if cached_embedding is None:
            misses.append(item)
            continue

        cached_results[item.id] = {
            "id": item.id,
            "text_hash": text_hash,
            "embedding": cached_embedding,
            "model": model,
            "dimensions": len(cached_embedding),
            "cached": True,
        }

    miss_tokens = sum(count_tokens(item.text) for item in misses)
    usage = EmbeddingBatchUsage(
        model=model,
        request_count=1 if misses else 0,
        input_count=len(items),
        cached_count=len(items) - len(misses),
        miss_count=len(misses),
        input_tokens=miss_tokens,
        estimated_cost_usd=estimate_embedding_cost_usd(model=model, input_tokens=miss_tokens),
    )
    return PlannedEmbeddingBatch(
        items=items,
        cached_results=cached_results,
        misses=misses,
        cache_warning=cache_warning,
        usage=usage,
    )


def execute_planned_embedding_batch(
    plan: PlannedEmbeddingBatch,
    *,
    model: str,
    cache_path: str | Path,
    dimensions: int | None = None,
    client: Any | None = None,
) -> tuple[list[dict[str, Any]], bool, EmbeddingBatchUsage]:
    cache = EmbeddingCache(cache_path)
    results = dict(plan.cached_results)
    cache_warning = plan.cache_warning
    usage = EmbeddingBatchUsage(
        model=plan.usage.model,
        request_count=plan.usage.request_count,
        input_count=plan.usage.input_count,
        cached_count=plan.usage.cached_count,
        miss_count=plan.usage.miss_count,
        input_tokens=plan.usage.input_tokens,
        estimated_cost_usd=plan.usage.estimated_cost_usd,
        request_id=plan.usage.request_id,
        duration_ms=plan.usage.duration_ms,
    )

    if plan.misses:
        embeddings, input_tokens, request_id, duration_ms = _request_embeddings(
            plan.misses,
            model=model,
            dimensions=dimensions,
            client=client,
        )
        usage.input_tokens = input_tokens
        usage.estimated_cost_usd = estimate_embedding_cost_usd(model=model, input_tokens=input_tokens)
        usage.request_id = request_id
        usage.duration_ms = duration_ms
        for item, embedding in zip(plan.misses, embeddings, strict=True):
            text_hash = compute_text_hash(item.id, item.text)
            try:
                cache.set(
                    item_id=item.id,
                    text_hash=text_hash,
                    model=model,
                    embedding=embedding,
                    dimensions=dimensions,
                )
            except CacheError:
                cache_warning = True

            results[item.id] = {
                "id": item.id,
                "text_hash": text_hash,
                "embedding": embedding,
                "model": model,
                "dimensions": len(embedding),
                "cached": False,
            }

    ordered = [results[item.id] for item in plan.items]
    return ordered, cache_warning, usage


def embed_batch(
    inputs: list[dict[str, str]] | list[EmbeddingItem],
    *,
    model: str,
    cache_path: str | Path,
    dimensions: int | None = None,
    client: Any | None = None,
) -> tuple[list[dict[str, Any]], bool, EmbeddingBatchUsage]:
    plan = plan_embedding_batch(
        inputs,
        model=model,
        cache_path=cache_path,
        dimensions=dimensions,
    )
    return execute_planned_embedding_batch(
        plan,
        model=model,
        cache_path=cache_path,
        dimensions=dimensions,
        client=client,
    )
