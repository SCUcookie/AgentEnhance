#!/usr/bin/env python3
"""Capture real, result-free NaiveRAG encoder probes in fresh evidence roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import audit_memgallery_naiverag_encoder_parity as parity
import memgallery_embedding_client as embedding_client


MODEL_MANIFEST_SHA256 = "b86b62467296f6df19daadbe88e83d40e54872152dae48b1774798f9fd342230"
EXPECTED_MODEL_FILES = 24
EXPECTED_MODEL_BYTES = 8_848_245_026
ENDPOINT = "http://127.0.0.1:18322/v1/embeddings"
BACKENDS = ("official_direct_lmencoder", "vllm_openai_input")


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


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _load_regular_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be an absolute regular non-symlink file")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw


def _validate_project_path(path: Path, required_parts: tuple[str, ...], label: str) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be an absolute non-symlink path")
    resolved = path.resolve()
    parts = resolved.parts
    matches = [index for index in range(len(parts)) if tuple(parts[index : index + len(required_parts)]) == required_parts]
    if len(matches) != 1:
        raise ValueError(f"{label} must be under {'/'.join(required_parts)}")
    return resolved


def _validate_inventory_file(path: Path, expected: Mapping[str, str]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing regular inventory: {path}")
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        pieces = line.split("  ", 1)
        if len(pieces) != 2 or not _is_sha256(pieces[0]) or pieces[1] in rows:
            raise ValueError(f"malformed inventory row: {path}")
        rows[pieces[1]] = pieces[0]
    if rows != dict(expected):
        raise ValueError(f"inventory identity drift: {path}")


def validate_model_snapshot(
    model_path: Path,
    materialization_root: Path,
    prefetch_manifest: Path,
) -> dict[str, Any]:
    """Revalidate every model byte against the accepted materialization evidence."""
    resolved_model = _validate_project_path(model_path, ("AgentEnhance", "cache", "models"), "model_path")
    resolved_materialization = _validate_project_path(
        materialization_root, ("AgentEnhance", "runs"), "materialization_root"
    )
    if not resolved_model.is_dir() or not resolved_materialization.is_dir():
        raise ValueError("model and materialization roots must exist as directories")
    if not (resolved_materialization / "TERMINAL_ACCEPTED").is_file():
        raise ValueError("model materialization is not terminal-accepted")
    if (resolved_materialization / "TERMINAL_REJECTED").exists():
        raise ValueError("model materialization has a rejection marker")

    manifest, manifest_bytes = _load_regular_json(prefetch_manifest, "prefetch_manifest")
    if sha256_bytes(manifest_bytes) != MODEL_MANIFEST_SHA256:
        raise ValueError("model prefetch manifest hash drift")
    candidates = [
        row
        for row in manifest.get("models", [])
        if row.get("repository") == parity.MODEL_REPOSITORY
        and row.get("revision") == parity.MODEL_REVISION
    ]
    if len(candidates) != 1:
        raise ValueError("frozen GME manifest row is missing or ambiguous")
    frozen = candidates[0]
    expected_paths = [row.get("path") for row in frozen.get("expected_files", [])]
    if (
        len(expected_paths) != EXPECTED_MODEL_FILES
        or expected_paths != sorted(expected_paths)
        or len(set(expected_paths)) != EXPECTED_MODEL_FILES
        or frozen.get("expected_total_bytes") != EXPECTED_MODEL_BYTES
    ):
        raise ValueError("frozen GME manifest denominator drift")

    record_path = resolved_materialization / "model-materialization.json"
    sums_path = resolved_materialization / "MODEL_SHA256SUMS"
    evidence_sums_path = resolved_materialization / "EVIDENCE_SHA256SUMS"
    record, record_bytes = _load_regular_json(record_path, "model materialization record")
    if record.get("schema_version") != "agentenhance.hf_model_materialization.v4":
        raise ValueError("model materialization schema drift")
    expected_record = {
        "status": "TERMINAL_ACCEPTED",
        "repository": parity.MODEL_REPOSITORY,
        "revision": parity.MODEL_REVISION,
        "target": str(resolved_model),
        "source_manifest_sha256": MODEL_MANIFEST_SHA256,
        "network_retry_count": 0,
        "logical_requests_per_file": 1,
        "file_count": EXPECTED_MODEL_FILES,
        "total_bytes": EXPECTED_MODEL_BYTES,
    }
    for field, value in expected_record.items():
        if record.get(field) != value:
            raise ValueError(f"model materialization identity drift: {field}")
    rows = record.get("files")
    if not isinstance(rows, list) or [row.get("path") for row in rows] != expected_paths:
        raise ValueError("model materialization file order drift")

    observed_paths: list[str] = []
    inventory: dict[str, str] = {}
    total_bytes = 0
    for row in rows:
        relative = row.get("path")
        digest = row.get("sha256")
        size = row.get("bytes")
        if not isinstance(relative, str) or not _is_sha256(digest) or not isinstance(size, int):
            raise ValueError("invalid model materialization file evidence")
        candidate = resolved_model.joinpath(*Path(relative).parts)
        try:
            candidate.resolve().relative_to(resolved_model)
        except ValueError as exc:
            raise ValueError(f"materialized model path escapes the snapshot: {relative}") from exc
        relative_parts = Path(relative).parts
        parents = [resolved_model.joinpath(*relative_parts[:index]) for index in range(1, len(relative_parts))]
        if candidate.is_symlink() or any(parent.is_symlink() for parent in parents) or not candidate.is_file():
            raise ValueError(f"invalid materialized model file: {relative}")
        if candidate.stat().st_size != size or sha256_file(candidate) != digest:
            raise ValueError(f"materialized model byte drift: {relative}")
        observed_paths.append(relative)
        inventory[str(candidate)] = digest
        total_bytes += size
    actual_paths = sorted(
        str(path.relative_to(resolved_model))
        for path in resolved_model.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if observed_paths != expected_paths or actual_paths != expected_paths or total_bytes != EXPECTED_MODEL_BYTES:
        raise ValueError("materialized model tree denominator drift")
    _validate_inventory_file(sums_path, inventory)
    _validate_inventory_file(
        evidence_sums_path,
        {
            str(record_path): sha256_bytes(record_bytes),
            str(sums_path): sha256_file(sums_path),
        },
    )
    if sha256_file(resolved_model / "config.json") != parity.MODEL_CONFIG_SHA256:
        raise ValueError("model config byte drift")
    if sha256_file(resolved_model / "1_Pooling" / "config.json") != parity.POOLING_CONFIG_SHA256:
        raise ValueError("pooling config byte drift")
    snapshot_identity = sha256_bytes(
        canonical_json_bytes(
            [{"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in rows]
        )
    )
    return {
        "model_path": str(resolved_model),
        "model_materialization_root": str(resolved_materialization),
        "model_materialization_sha256": sha256_bytes(record_bytes),
        "model_inventory_sha256": sha256_file(sums_path),
        "model_snapshot_sha256": snapshot_identity,
        "model_files": EXPECTED_MODEL_FILES,
        "model_bytes": EXPECTED_MODEL_BYTES,
    }


def validate_service_ready(
    service_ready_path: Path,
    *,
    model_identity: Mapping[str, Any],
    endpoint: str,
) -> dict[str, Any]:
    payload, raw = _load_regular_json(service_ready_path, "service_ready")
    expected = {
        "schema_version": "agentenhance.memgallery_naiverag_float32_service_ready.v1",
        "status": "READY_FOR_PARITY_PROBE",
        "endpoint": endpoint,
        "served_model": "gme-Qwen2-VL-2B-Instruct",
        "model_repository": parity.MODEL_REPOSITORY,
        "model_revision": parity.MODEL_REVISION,
        "model_path": model_identity["model_path"],
        "model_snapshot_sha256": model_identity["model_snapshot_sha256"],
        "dtype": "float32",
        "runner": "pooling",
        "convert": "embed",
        "tensor_parallel_size": 1,
        "automatic_retries": 0,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(f"service-ready identity drift: {field}")
    if not isinstance(payload.get("pid"), int) or payload["pid"] <= 1:
        raise ValueError("service-ready pid is invalid")
    if not _is_sha256(payload.get("models_response_sha256")):
        raise ValueError("service-ready models response identity is invalid")
    return {"service_ready_sha256": sha256_bytes(raw), "service_ready": payload}


def _validate_vectors(vectors: object) -> list[list[float]]:
    if not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes)) or len(vectors) != len(parity.PROBES):
        raise ValueError("captured probe denominator drift")
    validated: list[list[float]] = []
    for index, vector in enumerate(vectors):
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)) or len(vector) != parity.DIMENSIONS:
            raise ValueError(f"captured probe vector dimension drift at {index}")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
            raise ValueError(f"captured probe vector contains nonnumeric values at {index}")
        parsed = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in parsed):
            raise ValueError(f"captured probe vector contains non-finite values at {index}")
        norm = math.sqrt(sum(value * value for value in parsed))
        if not math.isfinite(norm) or norm == 0.0:
            raise ValueError(f"captured probe vector has invalid norm at {index}")
        validated.append(parsed)
    return validated


def build_probe_evidence(
    backend: str,
    vectors: object,
    *,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    if backend not in BACKENDS:
        raise ValueError("unsupported probe backend")
    validated = _validate_vectors(vectors)
    rows = [
        {**identity, "vector": vector}
        for identity, vector in zip(parity.probe_identity(), validated)
    ]
    return {
        "schema_version": "agentenhance.memgallery_naiverag_encoder_probe.v1",
        "backend": backend,
        "method_id": parity.METHOD_ID,
        "source_revision": parity.SOURCE_REVISION,
        "encoder_source_sha256": parity.ENCODER_SOURCE_SHA256,
        "function_config_sha256": parity.FUNCTION_CONFIG_SHA256,
        "model_repository": parity.MODEL_REPOSITORY,
        "model_revision": parity.MODEL_REVISION,
        "model_config_sha256": parity.MODEL_CONFIG_SHA256,
        "pooling_config_sha256": parity.POOLING_CONFIG_SHA256,
        "dimensions": parity.DIMENSIONS,
        "pooling": "last_token",
        "normalization": "cosine_after_encoding",
        "precision": "float32",
        "probe_set_sha256": parity.PROBE_SET_SHA256,
        "batch_size": 1 if backend == "official_direct_lmencoder" else parity.ENDPOINT_BATCH_SIZE,
        "vectors": rows,
        "runtime": dict(runtime),
        "scores_observed": 0,
    }


def capture_direct(model_path: Path) -> tuple[list[list[float]], dict[str, Any]]:
    if os.environ.get("TRANSFORMERS_OFFLINE") != "1" or os.environ.get("HF_HUB_OFFLINE") != "1":
        raise RuntimeError("direct capture requires TRANSFORMERS_OFFLINE=1 and HF_HUB_OFFLINE=1")
    import torch
    import transformers
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("official direct capture requires CUDA")
    device = torch.device("cuda")
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModel.from_pretrained(str(model_path)).to(device)
    model.eval()
    parameter = next(model.parameters())
    if parameter.dtype != torch.float32:
        raise RuntimeError(f"direct model dtype drift: {parameter.dtype}")
    vectors: list[list[float]] = []
    output_dtypes: set[str] = set()
    with torch.no_grad():
        for probe in parity.PROBES:
            inputs = tokenizer(probe["text"], return_tensors="pt").to(device)
            embedding = model(**inputs).last_hidden_state[:, -1, :]
            output_dtypes.add(str(embedding.dtype))
            vectors.append(embedding.detach().cpu().tolist()[0])
    if output_dtypes != {"torch.float32"}:
        raise RuntimeError(f"direct output dtype drift: {sorted(output_dtypes)}")
    return vectors, {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "device": str(device),
        "model_dtype": str(parameter.dtype),
        "output_dtypes": sorted(output_dtypes),
        "tokenizer_calls": len(parity.PROBES),
        "model_forward_calls": len(parity.PROBES),
        "network_requests": 0,
        "automatic_retries": 0,
    }


def capture_endpoint(endpoint: str) -> tuple[list[list[float]], dict[str, Any]]:
    vectors, call = embedding_client.execute_embedding_batch(
        [probe["text"] for probe in parity.PROBES],
        method_id=parity.METHOD_ID,
        seed=0,
        input_role="document",
        endpoint=endpoint,
        timeout_seconds=300.0,
    )
    if call.get("status") != "ACCEPTED" or call.get("attempts") != 1 or call.get("retry_count") != 0:
        raise RuntimeError("endpoint call was not one-shot accepted")
    return vectors, {
        "python": platform.python_version(),
        "endpoint_call": call,
        "endpoint_requests": 1,
        "automatic_retries": 0,
    }


def _atomic_create(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing capture file: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_inventory(root: Path, names: Sequence[str]) -> None:
    _atomic_create(
        root / "EVIDENCE_SHA256SUMS",
        "".join(f"{sha256_file(root / name)}  {name}\n" for name in names).encode("utf-8"),
    )


def capture_to_fresh_root(
    backend: str,
    output_root: Path,
    *,
    allowed_run_scopes: Sequence[Path],
    model_identity: Mapping[str, Any],
    capture: Callable[[], tuple[list[list[float]], Mapping[str, Any]]],
    service_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if backend not in BACKENDS:
        raise ValueError("unsupported probe backend")
    if backend == "vllm_openai_input" and service_identity is None:
        raise ValueError("endpoint capture requires a validated service identity")
    if backend == "official_direct_lmencoder" and service_identity is not None:
        raise ValueError("direct capture cannot bind an endpoint service")
    if not output_root.is_absolute() or output_root.is_symlink():
        raise ValueError("output_root must be absolute and not a symlink")
    scopes = [scope.resolve() for scope in allowed_run_scopes]
    if not scopes or not any(output_root.parent.resolve() == scope for scope in scopes):
        raise ValueError("output_root must be an exact child of an allowed run scope")
    if output_root.exists():
        raise ValueError("refusing existing output root")
    for field in (
        "model_path",
        "model_materialization_root",
        "model_materialization_sha256",
        "model_inventory_sha256",
        "model_snapshot_sha256",
        "model_files",
        "model_bytes",
    ):
        if field not in model_identity:
            raise ValueError(f"model identity lacks {field}")

    output_root.mkdir(parents=False)
    started = now()
    record = {
        "schema_version": "agentenhance.memgallery_naiverag_encoder_capture_record.v1",
        "status": "RUNNING",
        "backend": backend,
        "started_at": started,
        "probe_set_sha256": parity.PROBE_SET_SHA256,
        "probe_count": len(parity.PROBES),
        "model_identity": dict(model_identity),
        "service_identity": dict(service_identity) if service_identity is not None else None,
        "scores_observed": 0,
    }
    record_path = output_root / "capture-record.json"
    _atomic_create(record_path, json.dumps(record, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
    try:
        vectors, runtime = capture()
        evidence = build_probe_evidence(backend, vectors, runtime=runtime)
        evidence_path = output_root / "probe-evidence.json"
        _atomic_create(
            evidence_path,
            json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n",
        )
        summary = {
            "schema_version": "agentenhance.memgallery_naiverag_encoder_capture_summary.v1",
            "status": "TERMINAL_ACCEPTED",
            "backend": backend,
            "started_at": started,
            "finished_at": now(),
            "probe_set_sha256": parity.PROBE_SET_SHA256,
            "probe_count": len(parity.PROBES),
            "dimensions": parity.DIMENSIONS,
            "probe_evidence_sha256": sha256_file(evidence_path),
            "scores_observed": 0,
            "claim_eligible": False,
        }
        summary_path = output_root / "capture-summary.json"
        _atomic_create(summary_path, json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        _write_inventory(output_root, ("capture-record.json", "probe-evidence.json", "capture-summary.json"))
        _atomic_create(output_root / "TERMINAL_ACCEPTED", b"")
        return summary
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.memgallery_naiverag_encoder_capture_failure.v1",
            "status": "TERMINAL_REJECTED",
            "backend": backend,
            "started_at": started,
            "finished_at": now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "partial_root_retained": True,
            "same_root_retry_allowed": False,
            "scores_observed": 0,
        }
        endpoint_call = getattr(exc, "record", None)
        if backend == "vllm_openai_input" and isinstance(endpoint_call, Mapping):
            failure["endpoint_call"] = dict(endpoint_call)
        failure_path = output_root / "capture-failure.json"
        _atomic_create(failure_path, json.dumps(failure, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        _write_inventory(output_root, ("capture-record.json", "capture-failure.json"))
        _atomic_create(output_root / "TERMINAL_REJECTED", b"")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--materialization-root", type=Path, required=True)
    parser.add_argument("--prefetch-manifest", type=Path, required=True)
    parser.add_argument("--service-ready", type=Path)
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--allowed-run-scope", type=Path, action="append", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model_identity = validate_model_snapshot(
        args.model_path, args.materialization_root, args.prefetch_manifest
    )
    if args.backend == "official_direct_lmencoder":
        if args.service_ready is not None or args.endpoint != ENDPOINT:
            raise SystemExit("direct backend cannot accept service or endpoint overrides")
        service_identity = None
        capture = lambda: capture_direct(Path(model_identity["model_path"]))
    else:
        if args.service_ready is None or args.endpoint != ENDPOINT:
            raise SystemExit(f"endpoint backend requires --service-ready and exact endpoint {ENDPOINT}")
        service_identity = validate_service_ready(
            args.service_ready, model_identity=model_identity, endpoint=args.endpoint
        )
        capture = lambda: capture_endpoint(args.endpoint)
    summary = capture_to_fresh_root(
        args.backend,
        args.output_root,
        allowed_run_scopes=args.allowed_run_scope,
        model_identity=model_identity,
        service_identity=service_identity,
        capture=capture,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
