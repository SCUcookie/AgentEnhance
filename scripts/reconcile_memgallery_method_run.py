#!/usr/bin/env python3
"""Reconcile one Mem-Gallery method/seed against the frozen 1711-QID surface."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_METHODS = {
    "a-mem",
    "memoryos",
    "universalrag",
    "ngm",
    "augustus",
    "m2a",
    "v-mem",
    "no-memory",
    "full-memory-text",
    "full-memory-mm",
    "fifo-recent",
    "bm25",
    "naive-rag",
    "hybrid-rag",
}
ALLOWED_SEEDS = {0, 1, 2}
ALLOWED_RUN_SCOPES = (
    Path("/data1/2026/ldh/AgentEnhance/runs"),
    Path("/data2/2026/ldh/AgentEnhance/runs"),
)
ANSWER_MODEL = {
    "repository": "Qwen/Qwen3-VL-8B-Instruct",
    "revision": "5d854aab08710c16b980ec6d603d863b3821b915",
    "served_model": "Qwen3-VL-8B-Instruct",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith("\n"):
                raise ValueError(f"JSONL line lacks newline terminator: {path}:{line_number}")
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL: {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row must be an object: {path}:{line_number}")
            rows.append(row)
    return rows


def validate_under_scope(path: Path, scopes: tuple[Path, ...], label: str) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be absolute and not a symlink: {path}")
    if not any(path == scope or scope in path.parents for scope in scopes):
        raise ValueError(f"{label} is outside allowed run scopes: {path}")


def validate_exact_child(path: Path, scopes: tuple[Path, ...], label: str) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{label} must be absolute and not a symlink: {path}")
    if not any(path.parent == scope and path.name for scope in scopes):
        raise ValueError(f"{label} must be an exact child of an allowed run scope: {path}")


def validate_identity(identity: dict[str, Any], dataset: dict[str, Any]) -> tuple[str, int]:
    if identity.get("schema_version") != "agentenhance.memgallery_raw_run_identity.v1":
        raise ValueError("raw run identity schema drift")
    if identity.get("status") != "TERMINAL_RAW_COMPLETE":
        raise ValueError("raw run is not terminal-complete")
    if identity.get("track_id") != "memgallery-static-matched-v1":
        raise ValueError("raw run track drift")
    method_id = identity.get("method_id")
    seed = identity.get("seed")
    if method_id not in ALLOWED_METHODS:
        raise ValueError(f"unregistered Mem-Gallery method: {method_id}")
    if seed not in ALLOWED_SEEDS:
        raise ValueError(f"unregistered seed: {seed}")
    if identity.get("answer_model") != ANSWER_MODEL:
        raise ValueError("answer model identity drift")
    decoding = identity.get("decoding")
    if not isinstance(decoding, dict) or decoding.get("temperature") != 0.0:
        raise ValueError("temperature must be frozen at 0.0")
    if decoding.get("max_output_tokens") != 128:
        raise ValueError("max output token budget drift")
    budget = identity.get("memory_budget")
    if not isinstance(budget, dict) or budget.get("prospectively_frozen") is not True:
        raise ValueError("method memory budget is not prospectively frozen")
    stable = dataset.get("stable_identity", {})
    if identity.get("dataset_semantic_identity_sha256") != dataset.get(
        "dataset_semantic_identity_sha256"
    ):
        raise ValueError("dataset semantic identity drift")
    if identity.get("qid_order_sha256") != stable.get("qid_order_sha256"):
        raise ValueError("QID order identity drift")
    if identity.get("questions_expected") != stable.get("questions"):
        raise ValueError("raw run question denominator drift")
    if identity.get("official_values_used") is not False:
        raise ValueError("official values are prohibited in a raw local run")
    source = identity.get("method_source")
    if not isinstance(source, dict) or source.get("identity_frozen") is not True:
        raise ValueError("method source identity is not frozen")
    if not isinstance(source.get("implementation_sha256"), str) or len(
        source["implementation_sha256"]
    ) != 64:
        raise ValueError("method implementation SHA-256 is invalid")
    return str(method_id), int(seed)


def reconcile(
    dataset: dict[str, Any],
    question_rows: list[dict[str, Any]],
    qid_bytes: bytes,
    identity: dict[str, Any],
    predictions: list[dict[str, Any]],
) -> tuple[dict[str, Any], bytes]:
    if dataset.get("status") != "TERMINAL_ACCEPTED":
        raise ValueError("dataset integrity is not terminal-accepted")
    stable = dataset.get("stable_identity", {})
    qids = [row.get("qid") for row in question_rows]
    if any(not isinstance(qid, str) or not qid for qid in qids):
        raise ValueError("question index contains an invalid qid")
    if len(qids) != len(set(qids)):
        raise ValueError("question index contains duplicate qids")
    expected_qid_bytes = "".join(f"{qid}\n" for qid in qids).encode("utf-8")
    if qid_bytes != expected_qid_bytes:
        raise ValueError("QID_ORDER.txt differs from question-index.jsonl")
    if sha256_bytes(qid_bytes) != stable.get("qid_order_sha256"):
        raise ValueError("QID order SHA-256 differs from dataset integrity")
    canonical_question_index = b"".join(canonical_json_bytes(row) for row in question_rows)
    if sha256_bytes(canonical_question_index) != stable.get("question_index_sha256"):
        raise ValueError("question index SHA-256 differs from dataset integrity")
    if len(qids) != stable.get("questions"):
        raise ValueError("question index denominator differs from dataset integrity")

    method_id, seed = validate_identity(identity, dataset)
    prediction_qids = [row.get("qid") for row in predictions]
    if prediction_qids != qids:
        missing = sorted(set(qids) - set(prediction_qids))[:5]
        extra = sorted(set(prediction_qids) - set(qids))[:5]
        raise ValueError(
            f"prediction QIDs/order differ from frozen surface: missing={missing}, extra={extra}"
        )

    failures: Counter[str] = Counter()
    accepted = 0
    empty_answers = 0
    total_latency = 0.0
    total_retrieved = 0
    reconciled: list[dict[str, Any]] = []
    for index, row in enumerate(predictions):
        if row.get("schema_version") != "agentenhance.memgallery_prediction.v1":
            raise ValueError(f"prediction schema drift at index {index}")
        if row.get("method_id") != method_id or row.get("seed") != seed:
            raise ValueError(f"prediction method/seed drift at qid {qids[index]}")
        status = row.get("status")
        prediction = row.get("prediction")
        if status not in {"ACCEPTED", "FAILED"} or not isinstance(prediction, str):
            raise ValueError(f"invalid prediction status or answer at qid {qids[index]}")
        latency = row.get("latency_seconds")
        if not isinstance(latency, (int, float)) or isinstance(latency, bool):
            raise ValueError(f"invalid latency at qid {qids[index]}")
        latency = float(latency)
        if not math.isfinite(latency) or latency < 0:
            raise ValueError(f"non-finite or negative latency at qid {qids[index]}")
        retrieved = row.get("retrieved_memory_ids")
        if not isinstance(retrieved, list) or any(
            not isinstance(item, str) or not item for item in retrieved
        ):
            raise ValueError(f"invalid retrieved-memory IDs at qid {qids[index]}")
        if len(retrieved) != len(set(retrieved)):
            raise ValueError(f"duplicate retrieved-memory ID at qid {qids[index]}")
        if row.get("retrieval_count") != len(retrieved):
            raise ValueError(f"retrieval count drift at qid {qids[index]}")
        error_type = row.get("error_type")
        error = row.get("error")
        if status == "ACCEPTED":
            if not prediction.strip():
                raise ValueError(f"empty answer must be recorded as FAILED at qid {qids[index]}")
            if error_type is not None or error is not None:
                raise ValueError(f"accepted row contains an error at qid {qids[index]}")
            accepted += 1
        else:
            if not isinstance(error_type, str) or not error_type:
                raise ValueError(f"failed row lacks error_type at qid {qids[index]}")
            if not isinstance(error, str) or not error:
                raise ValueError(f"failed row lacks error at qid {qids[index]}")
            failures[error_type] += 1
            if not prediction.strip():
                empty_answers += 1
        total_latency += latency
        total_retrieved += len(retrieved)
        reconciled.append(
            {
                "qid": qids[index],
                "method_id": method_id,
                "seed": seed,
                "status": status,
                "prediction": prediction,
                "error_type": error_type,
                "error": error,
                "retrieved_memory_ids": retrieved,
                "retrieval_count": len(retrieved),
                "latency_seconds": latency,
            }
        )

    failed = len(reconciled) - accepted
    if accepted + failed != stable.get("questions"):
        raise ValueError("accepted plus failed rows do not equal the frozen denominator")
    reconciled_bytes = b"".join(canonical_json_bytes(row) for row in reconciled)
    summary = {
        "schema_version": "agentenhance.memgallery_run_reconciliation.v1",
        "status": "TERMINAL_ACCEPTED",
        "track_id": "memgallery-static-matched-v1",
        "method_id": method_id,
        "seed": seed,
        "dataset_semantic_identity_sha256": dataset["dataset_semantic_identity_sha256"],
        "qid_order_sha256": stable["qid_order_sha256"],
        "question_index_sha256": stable["question_index_sha256"],
        "questions_expected": stable["questions"],
        "prediction_rows": len(reconciled),
        "accepted_rows": accepted,
        "failed_rows": failed,
        "empty_answer_rows": empty_answers,
        "failure_types": dict(sorted(failures.items())),
        "total_latency_seconds": total_latency,
        "mean_latency_seconds": total_latency / len(reconciled),
        "total_retrieved_memories": total_retrieved,
        "mean_retrieved_memories": total_retrieved / len(reconciled),
        "reconciled_predictions_sha256": sha256_bytes(reconciled_bytes),
        "official_values_used": False,
        "main_comparison_numerical_authorization": False,
    }
    return summary, reconciled_bytes


def atomic_write(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-integrity", type=Path, required=True)
    parser.add_argument("--question-index", type=Path, required=True)
    parser.add_argument("--qid-order", type=Path, required=True)
    parser.add_argument("--run-identity", type=Path, required=True)
    parser.add_argument("--raw-predictions", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    inputs = [
        args.dataset_integrity.resolve(),
        args.question_index.resolve(),
        args.qid_order.resolve(),
        args.run_identity.resolve(),
        args.raw_predictions.resolve(),
    ]
    for path in inputs:
        validate_under_scope(path, ALLOWED_RUN_SCOPES, "reconciliation input")
        if not path.is_file():
            raise SystemExit(f"missing reconciliation input: {path}")
    if inputs[3].parent != inputs[4].parent:
        raise SystemExit("run identity and raw predictions must share one immutable run root")
    output_root = args.output_root.resolve()
    validate_exact_child(output_root, ALLOWED_RUN_SCOPES, "reconciliation output root")
    if output_root.exists():
        raise SystemExit(f"refusing existing reconciliation output root: {output_root}")

    output_root.mkdir(parents=False)
    started_at = now()
    try:
        dataset = json.loads(inputs[0].read_text(encoding="utf-8"))
        questions = read_jsonl(inputs[1])
        qid_bytes = inputs[2].read_bytes()
        identity = json.loads(inputs[3].read_text(encoding="utf-8"))
        predictions = read_jsonl(inputs[4])
        summary, reconciled = reconcile(dataset, questions, qid_bytes, identity, predictions)
        summary.update(
            {
                "started_at": started_at,
                "finished_at": now(),
                "inputs": [
                    {"path": str(path), "sha256": sha256_file(path)} for path in inputs
                ],
            }
        )
        summary_path = output_root / "reconciliation.json"
        predictions_path = output_root / "reconciled-predictions.jsonl"
        atomic_write(summary_path, json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        atomic_write(predictions_path, reconciled)
        inventory_path = output_root / "EVIDENCE_SHA256SUMS"
        atomic_write(
            inventory_path,
            (
                f"{sha256_file(summary_path)}  {summary_path}\n"
                f"{sha256_file(predictions_path)}  {predictions_path}\n"
            ).encode("utf-8"),
        )
        (output_root / "TERMINAL_ACCEPTED").touch()
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "agentenhance.memgallery_run_reconciliation_failure.v1",
            "status": "TERMINAL_REJECTED",
            "started_at": started_at,
            "finished_at": now(),
            "inputs": [
                {"path": str(path), "sha256": sha256_file(path)} for path in inputs
            ],
            "error_type": type(exc).__name__,
            "error": str(exc),
            "raw_run_retained": True,
            "cleanup_authorized": False,
            "main_comparison_numerical_authorization": False,
        }
        failure_path = output_root / "reconciliation-failure.json"
        atomic_write(failure_path, json.dumps(failure, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        atomic_write(
            output_root / "EVIDENCE_SHA256SUMS",
            f"{sha256_file(failure_path)}  {failure_path}\n".encode("utf-8"),
        )
        (output_root / "TERMINAL_REJECTED").touch()
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
