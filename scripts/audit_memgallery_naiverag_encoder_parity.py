#!/usr/bin/env python3
"""Prospective direct-LMEncoder versus vLLM parity gate for Mem-Gallery NaiveRAG."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


METHOD_ID = "naive-rag"
SOURCE_REVISION = "a93959e1e978a6a7d77798ae92c2ffe41c538c62"
ENCODER_SOURCE_SHA256 = "eb22409edf03b64eb209731afda809f56fb1f744039d034664d5f094caf2f4f7"
FUNCTION_CONFIG_SHA256 = "b33dd3be9c7d2f655bf59afb0b31027f2a6505e96675bf944d2f5fb020c71f37"
MODEL_REPOSITORY = "Alibaba-NLP/gme-Qwen2-VL-2B-Instruct"
MODEL_REVISION = "9cfa6413f704a7c1cf5064d240748e10c876b286"
MODEL_CONFIG_SHA256 = "dd18f3c69154bc6ccd1f55a6e0d0831c7edde2e29fee19d7ee91ad0e2e9f24c4"
POOLING_CONFIG_SHA256 = "f25c114f765f96fb30c843ec709c35ee6e92f24a782b8f37d95e29a32a7da5d6"
DIMENSIONS = 1536
ENDPOINT_BATCH_SIZE = 12
RETRIEVAL_TOP_K = 8
MIN_SELF_COSINE = 0.9999
MAX_NORMALIZED_COMPONENT_DELTA = 0.01
MAX_RETRIEVAL_SCORE_DELTA = 0.0001

PROBES = (
    {"probe_id": "d00", "role": "document", "text": "user: I bought a red bicycle.\nassistant: That sounds useful."},
    {"probe_id": "d01", "role": "document", "text": "user: My bicycle is blue and stored beside the garage."},
    {"probe_id": "d02", "role": "document", "text": "user: The meeting moved from Monday to Thursday at 09:30."},
    {"probe_id": "d03", "role": "document", "text": "user: Please forget the old address; the new address is 18 Pine Road."},
    {"probe_id": "d04", "role": "document", "text": "user: 图像中的杯子是绿色的。\nassistant: 我会记住这个细节。"},
    {"probe_id": "d05", "role": "document", "text": "user: Café reservations require the name Zoë and party size four."},
    {"probe_id": "d06", "role": "document", "text": "user: item_007 costs $12.50; item_008 costs $9.75."},
    {"probe_id": "d07", "role": "document", "text": "user: The photograph shows a small dog under a wooden table."},
    {"probe_id": "q00", "role": "query", "text": "What color was the bicycle I bought?"},
    {"probe_id": "q01", "role": "query", "text": "When is the rescheduled meeting?"},
    {"probe_id": "q02", "role": "query", "text": "最新地址是什么？"},
    {"probe_id": "q03", "role": "query", "text": "Which animal appeared in the photograph?"},
)


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_identity() -> list[dict[str, str]]:
    return [
        {
            "probe_id": probe["probe_id"],
            "role": probe["role"],
            "text_sha256": sha256_bytes(probe["text"].encode("utf-8")),
        }
        for probe in PROBES
    ]


PROBE_SET_SHA256 = sha256_bytes(canonical_json_bytes(probe_identity()))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _normalize(vector: object) -> list[float]:
    if not isinstance(vector, list) or len(vector) != DIMENSIONS:
        raise ValueError("probe vector dimension drift")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise ValueError("probe vector contains a nonnumeric value")
    parsed = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in parsed):
        raise ValueError("probe vector contains non-finite values")
    norm = math.sqrt(sum(value * value for value in parsed))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("probe vector has invalid norm")
    return [value / norm for value in parsed]


def _validate_evidence(payload: object, backend: str) -> list[list[float]]:
    if not isinstance(payload, Mapping):
        raise ValueError("probe evidence must be an object")
    expected = {
        "schema_version": "agentenhance.memgallery_naiverag_encoder_probe.v1",
        "backend": backend,
        "method_id": METHOD_ID,
        "source_revision": SOURCE_REVISION,
        "encoder_source_sha256": ENCODER_SOURCE_SHA256,
        "function_config_sha256": FUNCTION_CONFIG_SHA256,
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "model_config_sha256": MODEL_CONFIG_SHA256,
        "pooling_config_sha256": POOLING_CONFIG_SHA256,
        "dimensions": DIMENSIONS,
        "pooling": "last_token",
        "normalization": "cosine_after_encoding",
        "precision": "float32",
        "probe_set_sha256": PROBE_SET_SHA256,
        "scores_observed": 0,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"probe evidence identity drift: {backend}.{field}")
    expected_batch = 1 if backend == "official_direct_lmencoder" else ENDPOINT_BATCH_SIZE
    if payload.get("batch_size") != expected_batch:
        raise ValueError(f"probe evidence batch-size drift: {backend}")
    rows = payload.get("vectors")
    identities = probe_identity()
    if not isinstance(rows, list) or len(rows) != len(identities):
        raise ValueError("probe vector denominator drift")
    vectors: list[list[float]] = []
    for position, (row, identity) in enumerate(zip(rows, identities)):
        if not isinstance(row, Mapping):
            raise ValueError(f"probe vector row {position} must be an object")
        for field, value in identity.items():
            if row.get(field) != value:
                raise ValueError(f"probe vector identity/order drift at {position}: {field}")
        vectors.append(_normalize(row.get("vector")))
    return vectors


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    value = sum(a * b for a, b in zip(left, right))
    if not math.isfinite(value):
        raise ValueError("non-finite cosine score")
    return value


def _rankings(vectors: Sequence[Sequence[float]]) -> tuple[dict[str, list[str]], dict[str, dict[str, float]]]:
    documents = [(probe["probe_id"], vectors[index]) for index, probe in enumerate(PROBES) if probe["role"] == "document"]
    queries = [(probe["probe_id"], vectors[index]) for index, probe in enumerate(PROBES) if probe["role"] == "query"]
    rankings: dict[str, list[str]] = {}
    scores: dict[str, dict[str, float]] = {}
    for query_id, query_vector in queries:
        values = {document_id: _dot(query_vector, document_vector) for document_id, document_vector in documents}
        rankings[query_id] = [
            document_id
            for document_id, _ in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:RETRIEVAL_TOP_K]
        ]
        scores[query_id] = values
    return rankings, scores


def audit_parity(direct_payload: object, endpoint_payload: object) -> dict[str, Any]:
    direct = _validate_evidence(direct_payload, "official_direct_lmencoder")
    endpoint = _validate_evidence(endpoint_payload, "vllm_openai_input")
    per_probe: list[dict[str, Any]] = []
    for probe, direct_vector, endpoint_vector in zip(PROBES, direct, endpoint):
        cosine = _dot(direct_vector, endpoint_vector)
        component_delta = max(abs(left - right) for left, right in zip(direct_vector, endpoint_vector))
        per_probe.append(
            {
                "probe_id": probe["probe_id"],
                "role": probe["role"],
                "self_cosine": cosine,
                "max_normalized_component_delta": component_delta,
            }
        )
    direct_rankings, direct_scores = _rankings(direct)
    endpoint_rankings, endpoint_scores = _rankings(endpoint)
    retrieval_rows: list[dict[str, Any]] = []
    for query_id in direct_rankings:
        score_delta = max(
            abs(direct_scores[query_id][document_id] - endpoint_scores[query_id][document_id])
            for document_id in direct_scores[query_id]
        )
        retrieval_rows.append(
            {
                "query_probe_id": query_id,
                "direct_ranking": direct_rankings[query_id],
                "endpoint_ranking": endpoint_rankings[query_id],
                "ranking_exact": direct_rankings[query_id] == endpoint_rankings[query_id],
                "max_cosine_score_delta": score_delta,
            }
        )
    minimum_cosine = min(row["self_cosine"] for row in per_probe)
    maximum_component_delta = max(row["max_normalized_component_delta"] for row in per_probe)
    maximum_score_delta = max(row["max_cosine_score_delta"] for row in retrieval_rows)
    exact_rankings = all(row["ranking_exact"] for row in retrieval_rows)
    endpoint_equivalent = (
        minimum_cosine >= MIN_SELF_COSINE
        and maximum_component_delta <= MAX_NORMALIZED_COMPONENT_DELTA
        and maximum_score_delta <= MAX_RETRIEVAL_SCORE_DELTA
        and exact_rankings
    )
    decision = "ENDPOINT_EQUIVALENT" if endpoint_equivalent else "DIRECT_ENCODER_REQUIRED"
    return {
        "schema_version": "agentenhance.memgallery_naiverag_encoder_parity_audit.v1",
        "status": f"TERMINAL_ACCEPTED_{decision}",
        "decision": decision,
        "method_id": METHOD_ID,
        "probe_set_sha256": PROBE_SET_SHA256,
        "probe_count": len(PROBES),
        "document_probes": sum(probe["role"] == "document" for probe in PROBES),
        "query_probes": sum(probe["role"] == "query" for probe in PROBES),
        "minimum_self_cosine": minimum_cosine,
        "maximum_normalized_component_delta": maximum_component_delta,
        "maximum_retrieval_score_delta": maximum_score_delta,
        "exact_retrieval_rankings": exact_rankings,
        "thresholds": {
            "minimum_self_cosine": MIN_SELF_COSINE,
            "maximum_normalized_component_delta": MAX_NORMALIZED_COMPONENT_DELTA,
            "maximum_retrieval_score_delta": MAX_RETRIEVAL_SCORE_DELTA,
            "exact_retrieval_rankings": True,
        },
        "per_probe": per_probe,
        "retrieval_checks": retrieval_rows,
        "scores_observed": 0,
        "claim_eligible": False,
        "next_gate": (
            "The separately frozen real lifecycle may use the vLLM input path."
            if endpoint_equivalent
            else "The separately frozen real lifecycle must use the official direct LMEncoder path."
        ),
    }


def _atomic_create(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing audit file: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def audit_to_fresh_root(
    direct_path: Path,
    endpoint_path: Path,
    output_root: Path,
    *,
    allowed_run_scopes: Sequence[Path],
) -> dict[str, Any]:
    for label, path in (("direct", direct_path), ("endpoint", endpoint_path)):
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError(f"{label} evidence must be an absolute regular non-symlink file")
    if not output_root.is_absolute() or output_root.is_symlink():
        raise ValueError("output_root must be absolute and not a symlink")
    scopes = [scope.resolve() for scope in allowed_run_scopes]
    if not scopes or not any(output_root.parent.resolve() == scope for scope in scopes):
        raise ValueError("output_root must be an exact child of an allowed run scope")
    if output_root.exists():
        raise ValueError("refusing existing output root")
    direct_bytes = direct_path.read_bytes()
    endpoint_bytes = endpoint_path.read_bytes()
    try:
        direct = json.loads(direct_bytes)
        endpoint = json.loads(endpoint_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("probe evidence must be valid UTF-8 JSON") from exc
    result = audit_parity(direct, endpoint)
    result["inputs"] = {
        "direct": {"path": str(direct_path), "bytes": len(direct_bytes), "sha256": sha256_bytes(direct_bytes)},
        "endpoint": {"path": str(endpoint_path), "bytes": len(endpoint_bytes), "sha256": sha256_bytes(endpoint_bytes)},
    }
    output_root.mkdir(parents=False)
    result_path = output_root / "parity-audit.json"
    _atomic_create(result_path, json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
    inventory_path = output_root / "EVIDENCE_SHA256SUMS"
    _atomic_create(inventory_path, f"{sha256_file(result_path)}  {result_path.name}\n".encode("utf-8"))
    _atomic_create(output_root / result["status"], b"")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--endpoint", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--allowed-run-scope", action="append", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit_to_fresh_root(
        args.direct,
        args.endpoint,
        args.output_root,
        allowed_run_scopes=args.allowed_run_scope,
    )
    print(json.dumps({"status": result["status"], "decision": result["decision"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
