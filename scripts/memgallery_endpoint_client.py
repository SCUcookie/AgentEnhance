#!/usr/bin/env python3
"""Fail-closed local endpoint transport for matched Mem-Gallery answering."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MIME_BY_SUFFIX = {
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class EndpointCallError(RuntimeError):
    """One terminal endpoint attempt with an attached result-free call record."""

    def __init__(self, message: str, record: Mapping[str, Any]):
        super().__init__(message)
        self.record = dict(record)


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
        or parsed.path != "/v1/chat/completions"
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
    ):
        raise ValueError("endpoint must be http://127.0.0.1:<high-port>/v1/chat/completions")
    return endpoint


def _safe_image_identity(raw: object) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ValueError("image_ref identity must be a nonempty POSIX path")
    relative = PurePosixPath(raw)
    if (
        relative.is_absolute()
        or relative.parts[:2] != ("data", "image")
        or ".." in relative.parts
        or "." in relative.parts
        or any(not part for part in relative.parts)
    ):
        raise ValueError(f"unsafe image_ref identity: {raw!r}")
    return relative


def _read_frozen_image(
    dataset_root: Path,
    identity: object,
    allowed_image_sha256: Mapping[str, str],
) -> tuple[str, bytes, str]:
    relative = _safe_image_identity(identity)
    identity_text = relative.as_posix()
    expected_sha256 = allowed_image_sha256.get(identity_text)
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError(f"image_ref is absent from the frozen image allowlist: {identity_text}")
    current = dataset_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"image_ref traverses a symlink: {identity_text}")
    if not current.is_file():
        raise ValueError(f"image_ref is not a regular file: {identity_text}")
    resolved = current.resolve(strict=True)
    if dataset_root not in resolved.parents:
        raise ValueError(f"image_ref resolves outside the dataset root: {identity_text}")
    suffix = relative.suffix.lower()
    mime = MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise ValueError(f"unsupported image suffix: {identity_text}")
    payload = current.read_bytes()
    if not payload:
        raise ValueError(f"image_ref is empty: {identity_text}")
    observed_sha256 = sha256_bytes(payload)
    if observed_sha256 != expected_sha256:
        raise ValueError(f"image_ref SHA-256 drift: {identity_text}")
    return mime, payload, observed_sha256


def prepare_transport_request(
    abstract_request: Mapping[str, Any],
    *,
    dataset_root: Path | None,
    allowed_image_sha256: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Expand image_ref items into data URLs while preserving source evidence."""
    abstract_bytes = canonical_json_bytes(abstract_request)
    try:
        transport = json.loads(abstract_bytes)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"abstract request must be JSON serializable: {exc}") from exc
    messages = transport.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError("request must contain exactly system and user messages")
    if messages[0].get("role") != "system" or not isinstance(messages[0].get("content"), str):
        raise ValueError("first message must be a textual system message")
    if messages[1].get("role") != "user" or not isinstance(messages[1].get("content"), list):
        raise ValueError("second message must contain the structured user content list")

    root: Path | None = None
    if dataset_root is not None:
        if not dataset_root.is_absolute() or dataset_root.is_symlink() or not dataset_root.is_dir():
            raise ValueError("dataset_root must be an absolute existing non-symlink directory")
        root = dataset_root.resolve(strict=True)
    image_evidence: list[dict[str, Any]] = []
    expanded: list[dict[str, Any]] = []
    for position, item in enumerate(messages[1]["content"]):
        if not isinstance(item, dict):
            raise ValueError(f"user content item {position} must be an object")
        item_type = item.get("type")
        if item_type == "text":
            if not isinstance(item.get("text"), str):
                raise ValueError(f"text content item {position} must contain a string")
            expanded.append(item)
            continue
        if item_type != "image_ref":
            raise ValueError(f"unsupported user content type at {position}: {item_type!r}")
        if root is None:
            raise ValueError("dataset_root is required when image_ref items are present")
        identity = item.get("image_id")
        mime, payload, observed_sha256 = _read_frozen_image(root, identity, allowed_image_sha256)
        encoded = base64.b64encode(payload).decode("ascii")
        expanded.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
        image_evidence.append(
            {
                "content_position": position,
                "source_identity": identity,
                "bytes": len(payload),
                "sha256": observed_sha256,
                "mime_type": mime,
            }
        )
    messages[1]["content"] = expanded
    transport_bytes = canonical_json_bytes(transport)
    evidence = {
        "abstract_request_sha256": sha256_bytes(abstract_bytes),
        "transport_request_sha256": sha256_bytes(transport_bytes),
        "image_count": len(image_evidence),
        "image_bytes": sum(item["bytes"] for item in image_evidence),
        "images": image_evidence,
    }
    return transport, evidence


def _nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def parse_chat_completion(payload: object) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("endpoint response must be an object")
    response_id = payload.get("id")
    choices = payload.get("choices")
    usage = payload.get("usage")
    if not isinstance(response_id, str) or not response_id:
        raise ValueError("endpoint response lacks a nonempty id")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("endpoint response must contain exactly one choice")
    message = choices[0].get("message")
    finish_reason = choices[0].get("finish_reason")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("endpoint response lacks textual message content")
    prediction = message["content"]
    if not prediction.strip():
        raise ValueError("endpoint response contains an empty prediction")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise ValueError("endpoint response lacks a finish reason")
    if not isinstance(usage, dict):
        raise ValueError("endpoint response lacks token usage")
    prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"), "prompt_tokens")
    completion_tokens = _nonnegative_int(usage.get("completion_tokens"), "completion_tokens")
    total_tokens = _nonnegative_int(usage.get("total_tokens"), "total_tokens")
    if prompt_tokens + completion_tokens != total_tokens:
        raise ValueError("endpoint token usage does not sum exactly")
    return prediction, {
        "response_id": response_id,
        "finish_reason": finish_reason,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def execute_chat_completion(
    transport_request: Mapping[str, Any],
    *,
    endpoint: str,
    timeout_seconds: float,
    api_key: str = "EMPTY",
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, dict[str, Any]]:
    """Perform exactly one local request; every failure is terminal to the caller."""
    validate_local_endpoint(endpoint)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("api_key must be a nonempty string")
    request_bytes = canonical_json_bytes(transport_request)
    request_sha256 = sha256_bytes(request_bytes)
    started = clock()
    base_record: dict[str, Any] = {
        "schema_version": "agentenhance.memgallery_endpoint_call.v1",
        "call_category": "final_answer",
        "endpoint": endpoint,
        "request_sha256": request_sha256,
        "attempts": 1,
        "retry_count": 0,
    }
    try:
        request = urllib.request.Request(
            endpoint,
            data=request_bytes,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with opener(request, timeout=timeout_seconds) as response:
            http_status = getattr(response, "status", None)
            if http_status != 200:
                raise ValueError(f"endpoint returned HTTP status {http_status!r}")
            response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError("endpoint response exceeds the frozen byte ceiling")
        if not response_bytes:
            raise ValueError("endpoint returned an empty body")
        try:
            response_payload = json.loads(response_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"endpoint returned invalid UTF-8 JSON: {exc}") from exc
        prediction, parsed = parse_chat_completion(response_payload)
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
        return prediction, record
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
            "finish_reason": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        raise EndpointCallError(str(exc), record) from exc

