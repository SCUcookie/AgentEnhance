#!/usr/bin/env python3
"""One-shot loopback transport proposed for Causal-LoCoMo local models."""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


CHAT_MODEL = "Qwen3-VL-8B-Instruct"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class EndpointCallError(RuntimeError):
    """Exactly one failed endpoint attempt and its durable call record."""

    def __init__(self, message: str, record: Mapping[str, Any]):
        super().__init__(message)
        self.record = dict(record)


def canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_loopback_endpoint(endpoint: str, expected_path: str) -> str:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != expected_path
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
    ):
        raise ValueError(f"endpoint must be http://127.0.0.1:<high-port>{expected_path}")
    return endpoint


def _token_usage(payload: object) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        raise ValueError("endpoint response lacks token usage")
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
        result[key] = value
    if result["prompt_tokens"] + result["completion_tokens"] != result["total_tokens"]:
        raise ValueError("endpoint token usage does not sum exactly")
    return result


def validate_answer_request(request: Mapping[str, Any]) -> None:
    if set(request) != {"model", "temperature", "max_tokens", "seed", "messages"}:
        raise ValueError("answer request fields drifted from the frozen overlay")
    if request["model"] != CHAT_MODEL or request["temperature"] != 0.0 or request["max_tokens"] != 600:
        raise ValueError("answer model or decoding configuration drift")
    if request["seed"] not in {0, 1, 2}:
        raise ValueError("answer seed must be one of 0, 1, or 2")
    messages = request["messages"]
    if (
        not isinstance(messages, list)
        or len(messages) != 1
        or not isinstance(messages[0], Mapping)
        or messages[0].get("role") != "user"
        or not isinstance(messages[0].get("content"), str)
        or not messages[0]["content"]
    ):
        raise ValueError("answer request must contain exactly one nonempty user message")


def _parse_chat(payload: object) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("chat response must be an object")
    if payload.get("model") != CHAT_MODEL:
        raise ValueError("chat response model identity drift")
    response_id = payload.get("id")
    choices = payload.get("choices")
    if not isinstance(response_id, str) or not response_id:
        raise ValueError("chat response lacks a nonempty id")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ValueError("chat response must contain exactly one choice")
    message = choices[0].get("message")
    finish_reason = choices[0].get("finish_reason")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise ValueError("chat response lacks textual content")
    text = message["content"]
    if not text.strip():
        raise ValueError("chat response is empty")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise ValueError("chat response lacks finish_reason")
    return text, {"response_id": response_id, "finish_reason": finish_reason, **_token_usage(payload.get("usage"))}


def _parse_embedding(payload: object) -> tuple[list[list[float]], dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ValueError("embedding response must be an object")
    if payload.get("model") != EMBEDDING_MODEL:
        raise ValueError("embedding response model identity drift")
    response_id = payload.get("id")
    data = payload.get("data")
    if not isinstance(response_id, str) or not response_id:
        raise ValueError("embedding response lacks a nonempty id")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        raise ValueError("embedding response must contain exactly one item")
    if data[0].get("index") != 0:
        raise ValueError("embedding response index drift")
    raw_vector = data[0].get("embedding")
    if not isinstance(raw_vector, list) or len(raw_vector) != EMBEDDING_DIMENSIONS:
        raise ValueError("embedding response dimension drift")
    vector = [float(value) for value in raw_vector]
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("embedding response contains non-finite values")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("embedding response has invalid norm")
    return [vector], {"response_id": response_id, "dimensions": len(vector), **_token_usage(payload.get("usage"))}


def _one_shot_json(
    request_payload: Mapping[str, Any],
    *,
    endpoint: str,
    endpoint_path: str,
    category: str,
    timeout_seconds: float,
    parser: Callable[[object], tuple[Any, dict[str, Any]]],
    api_key: str,
    opener: Callable[..., Any],
    clock: Callable[[], float],
) -> tuple[Any, dict[str, Any]]:
    validate_loopback_endpoint(endpoint, endpoint_path)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("api_key must be a nonempty placeholder")
    request_bytes = canonical_bytes(request_payload)
    started = clock()
    base = {
        "schema_version": "agentenhance.causal_locomo_endpoint_call.v1",
        "call_category": category,
        "endpoint": endpoint,
        "model": request_payload["model"],
        "request_sha256": _sha256(request_bytes),
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
            status = getattr(response, "status", None)
            if status != 200:
                raise ValueError(f"endpoint returned HTTP status {status!r}")
            response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        if not response_bytes:
            raise ValueError("endpoint returned an empty response")
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError("endpoint response exceeds byte ceiling")
        try:
            payload = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"endpoint returned invalid UTF-8 JSON: {exc}") from exc
        value, parsed = parser(payload)
        elapsed = float(clock() - started)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("endpoint clock produced invalid duration")
        return value, {
            **base,
            "status": "ACCEPTED",
            "http_status": 200,
            "response_sha256": _sha256(response_bytes),
            "response_bytes": len(response_bytes),
            "wall_seconds": elapsed,
            **parsed,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:
        elapsed = float(clock() - started)
        record = {
            **base,
            "status": "FAILED",
            "http_status": getattr(exc, "code", None),
            "response_sha256": None,
            "response_bytes": 0,
            "wall_seconds": elapsed if math.isfinite(elapsed) and elapsed >= 0 else None,
            "response_id": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        raise EndpointCallError(str(exc), record) from exc


def execute_answer(
    request: Mapping[str, Any],
    *,
    endpoint: str,
    timeout_seconds: float,
    api_key: str = "EMPTY",
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    validate_answer_request(request)
    text, call = _one_shot_json(
        request,
        endpoint=endpoint,
        endpoint_path="/v1/chat/completions",
        category="final_answer",
        timeout_seconds=timeout_seconds,
        parser=_parse_chat,
        api_key=api_key,
        opener=opener,
        clock=clock,
    )
    return {"text": text, "call": call}


def execute_embedding(
    texts: Sequence[str],
    seed: int,
    *,
    endpoint: str,
    timeout_seconds: float,
    api_key: str = "EMPTY",
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if seed not in {0, 1, 2}:
        raise ValueError("embedding seed must be one of 0, 1, or 2")
    if (
        not isinstance(texts, Sequence)
        or isinstance(texts, (str, bytes))
        or len(texts) != 1
        or not isinstance(texts[0], str)
        or not texts[0]
    ):
        raise ValueError("embedding input must contain exactly one nonempty text")
    request = {"model": EMBEDDING_MODEL, "input": [texts[0]], "encoding_format": "float"}
    vectors, call = _one_shot_json(
        request,
        endpoint=endpoint,
        endpoint_path="/v1/embeddings",
        category="text_embedding",
        timeout_seconds=timeout_seconds,
        parser=_parse_embedding,
        api_key=api_key,
        opener=opener,
        clock=clock,
    )
    call["seed"] = seed
    return {"vectors": vectors, "call": call}

