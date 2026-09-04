#!/usr/bin/env python3
"""Fail-closed batched embedding transport for Mem-Gallery dense controls."""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


MAX_BATCH_ITEMS = 64
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024

METHOD_PROFILES = {
    "naive-rag": {
        "profile": "gme1536",
        "model": "gme-Qwen2-VL-2B-Instruct",
        "dimensions": 1536,
    },
    "hybrid-rag": {
        "profile": "qwen1024",
        "model": "Qwen3-VL-Embedding-2B",
        "dimensions": 1024,
    },
}


class EndpointCallError(RuntimeError):
    """One failed endpoint attempt with a result-free call record."""

    def __init__(self, message: str, record: Mapping[str, Any]):
        super().__init__(message)
        self.record = dict(record)


class EmbeddingBatchError(RuntimeError):
    """Terminal multi-batch failure retaining all attempted call records."""

    def __init__(
        self,
        message: str,
        call_records: Sequence[Mapping[str, Any]],
        partial_vectors: Sequence[Sequence[float]],
    ):
        super().__init__(message)
        self.call_records = [dict(record) for record in call_records]
        self.partial_vectors = [list(vector) for vector in partial_vectors]


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_local_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1/embeddings"
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
    ):
        raise ValueError("endpoint must be http://127.0.0.1:<high-port>/v1/embeddings")
    return endpoint


def _profile(method_id: str) -> Mapping[str, Any]:
    try:
        return METHOD_PROFILES[method_id]
    except KeyError as exc:
        raise ValueError(f"unsupported dense control method: {method_id!r}") from exc


def _validate_inputs(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise ValueError("embedding input must be a sequence of texts")
    if not 1 <= len(texts) <= MAX_BATCH_ITEMS:
        raise ValueError(f"embedding batch must contain 1..{MAX_BATCH_ITEMS} items")
    validated: list[str] = []
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"embedding input item {index} must be nonempty text")
        validated.append(text)
    return validated


def _validate_surface(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence) or not texts:
        raise ValueError("embedding surface must be a nonempty sequence")
    validated: list[str] = []
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"embedding surface item {index} must be nonempty text")
        validated.append(text)
    return validated


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _parse_token_usage(payload: object) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        raise ValueError("embedding response lacks token usage")
    prompt_tokens = _nonnegative_int(payload.get("prompt_tokens"), "prompt_tokens")
    total_tokens = _nonnegative_int(payload.get("total_tokens"), "total_tokens")
    completion_tokens = payload.get("completion_tokens", 0)
    completion_tokens = _nonnegative_int(completion_tokens, "completion_tokens")
    if completion_tokens != 0:
        raise ValueError("embedding completion_tokens must be zero")
    if prompt_tokens != total_tokens:
        raise ValueError("embedding token usage does not sum exactly")
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def parse_embedding_response(
    payload: object,
    *,
    expected_model: str,
    expected_dimensions: int,
    expected_items: int,
) -> tuple[list[list[float]], dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("embedding response must be an object")
    if payload.get("model") != expected_model:
        raise ValueError("embedding response model identity drift")
    response_id = payload.get("id")
    if not isinstance(response_id, str) or not response_id:
        raise ValueError("embedding response lacks a nonempty id")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != expected_items:
        raise ValueError("embedding response item count drift")

    vectors: list[list[float]] = []
    for expected_index, item in enumerate(data):
        if not isinstance(item, Mapping) or item.get("index") != expected_index:
            raise ValueError("embedding response index/order drift")
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list) or len(raw_vector) != expected_dimensions:
            raise ValueError("embedding response dimension drift")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw_vector):
            raise ValueError("embedding response contains a nonnumeric value")
        vector = [float(value) for value in raw_vector]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("embedding response contains non-finite values")
        norm = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(norm) or norm == 0.0:
            raise ValueError("embedding response has invalid norm")
        vectors.append(vector)

    return vectors, {
        "response_id": response_id,
        "dimensions": expected_dimensions,
        **_parse_token_usage(payload.get("usage")),
    }


def execute_embedding_batch(
    texts: Sequence[str],
    *,
    method_id: str,
    seed: int,
    input_role: str,
    endpoint: str,
    timeout_seconds: float,
    api_key: str = "EMPTY",
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[list[float]], dict[str, Any]]:
    """Execute exactly one ordered embedding request without automatic retry."""
    profile = _profile(method_id)
    validated = _validate_inputs(texts)
    if seed not in {0, 1, 2}:
        raise ValueError("embedding seed must be one of 0, 1, or 2")
    if input_role not in {"document", "query"}:
        raise ValueError("input_role must be document or query")
    validate_local_endpoint(endpoint)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("api_key must be a nonempty placeholder")

    request_payload = {
        "model": profile["model"],
        "input": validated,
        "encoding_format": "float",
    }
    request_bytes = canonical_json_bytes(request_payload)
    if len(request_bytes) > MAX_REQUEST_BYTES:
        raise ValueError("embedding request exceeds the frozen byte ceiling")
    started = clock()
    base_record: dict[str, Any] = {
        "schema_version": "agentenhance.memgallery_embedding_call.v1",
        "call_category": "text_embedding",
        "input_role": input_role,
        "method_id": method_id,
        "seed": seed,
        "profile": profile["profile"],
        "model": profile["model"],
        "endpoint": endpoint,
        "input_items": len(validated),
        "request_sha256": sha256_bytes(request_bytes),
        "request_bytes": len(request_bytes),
        "attempts": 1,
        "retry_count": 0,
    }
    try:
        request = urllib.request.Request(
            endpoint,
            data=request_bytes,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with opener(request, timeout=timeout_seconds) as response:
            http_status = getattr(response, "status", None)
            if http_status != 200:
                raise ValueError(f"endpoint returned HTTP status {http_status!r}")
            response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        if not response_bytes:
            raise ValueError("endpoint returned an empty body")
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError("endpoint response exceeds the frozen byte ceiling")
        try:
            response_payload = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"endpoint returned invalid UTF-8 JSON: {exc}") from exc
        vectors, parsed = parse_embedding_response(
            response_payload,
            expected_model=str(profile["model"]),
            expected_dimensions=int(profile["dimensions"]),
            expected_items=len(validated),
        )
        elapsed = float(clock() - started)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("endpoint clock produced an invalid duration")
        record = {
            **base_record,
            "status": "ACCEPTED",
            "http_status": 200,
            "response_sha256": sha256_bytes(response_bytes),
            "response_bytes": len(response_bytes),
            "wall_seconds": elapsed,
            **parsed,
            "error_type": None,
            "error": None,
        }
        return vectors, record
    except Exception as exc:
        elapsed = float(clock() - started)
        record = {
            **base_record,
            "status": "FAILED",
            "http_status": getattr(exc, "code", None),
            "response_sha256": None,
            "response_bytes": 0,
            "wall_seconds": elapsed if math.isfinite(elapsed) and elapsed >= 0 else None,
            "response_id": None,
            "dimensions": int(profile["dimensions"]),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        raise EndpointCallError(str(exc), record) from exc


def execute_embedding_batches(
    texts: Sequence[str],
    *,
    method_id: str,
    seed: int,
    input_role: str,
    endpoint: str,
    timeout_seconds: float,
    batch_size: int = MAX_BATCH_ITEMS,
    api_key: str = "EMPTY",
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Embed an ordered surface and retain every attempted batch record."""
    validated_surface = _validate_surface(texts)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= MAX_BATCH_ITEMS:
        raise ValueError(f"batch_size must be an integer in 1..{MAX_BATCH_ITEMS}")

    vectors: list[list[float]] = []
    call_records: list[dict[str, Any]] = []
    for offset in range(0, len(validated_surface), batch_size):
        batch = validated_surface[offset : offset + batch_size]
        try:
            batch_vectors, record = execute_embedding_batch(
                batch,
                method_id=method_id,
                seed=seed,
                input_role=input_role,
                endpoint=endpoint,
                timeout_seconds=timeout_seconds,
                api_key=api_key,
                opener=opener,
                clock=clock,
            )
        except EndpointCallError as exc:
            failed = {**exc.record, "batch_index": len(call_records), "input_offset": offset}
            call_records.append(failed)
            raise EmbeddingBatchError(str(exc), call_records, vectors) from exc
        record = {**record, "batch_index": len(call_records), "input_offset": offset}
        call_records.append(record)
        vectors.extend(batch_vectors)
    if len(vectors) != len(validated_surface):
        raise RuntimeError("embedding output denominator drift")
    return {"vectors": vectors, "call_records": call_records}
