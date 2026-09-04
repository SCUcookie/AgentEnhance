#!/usr/bin/env python3
"""Fail-closed synthetic lifecycle controller for the Mem-Gallery static track.

This module deliberately cannot run a real endpoint.  It validates the future
release, dataset, model, service, authorization, and frozen question surfaces,
then composes the already frozen control runner and append-only raw-run writer
with an injected synthetic answer function.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from memgallery_control_adapter import validate_query_projection
from memgallery_control_runner import run_control_scenario
from memgallery_raw_run_writer import RawRunWriter


EXPECTED_REPOSITORY = "Ethan-Bei/Mem-Gallery"
EXPECTED_REVISION = "af912daba984e896e253016b7c7e334ef92c2a6f"
EXPECTED_FILES = 1515
EXPECTED_BYTES = 545845389
EXPECTED_SCENARIOS = 20
EXPECTED_QUESTIONS = 1711
EXPECTED_IMAGE_FILES = 1490

REQUIRED_MODELS = {
    "shared-qwen3-vl-8b-answer": (
        "Qwen/Qwen3-VL-8B-Instruct",
        "5d854aab08710c16b980ec6d603d863b3821b915",
    ),
    "shared-qwen3-vl-embedding-2b": (
        "Qwen/Qwen3-VL-Embedding-2B",
        "c35dddf20620fe32745cb3d01f87ba64ae316313",
    ),
    "cross-track-gme-qwen2-vl-2b": (
        "Alibaba-NLP/gme-Qwen2-VL-2B-Instruct",
        "9cfa6413f704a7c1cf5064d240748e10c876b286",
    ),
    "cross-track-all-minilm-l6-v2": (
        "sentence-transformers/all-MiniLM-L6-v2",
        "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    ),
    "memgallery-vmem-siglip2-base-patch16-384": (
        "google/siglip2-base-patch16-384",
        "f775b65a79762255128c981547af89addcfe0f88",
    ),
}


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_wave1_release(receipt: Mapping[str, Any]) -> None:
    _require(receipt.get("status") == "TERMINAL_ACCEPTED", "WMA Wave 1 is not terminal-accepted")
    _require(receipt.get("terminal_rejected") is False, "WMA Wave 1 rejection marker is present")
    for field in ("project_process_count", "project_tmux_count", "model_service_count"):
        _require(receipt.get(field) == 0, f"WMA release has nonzero {field}")
    _require(_is_sha256(receipt.get("closure_audit_sha256")), "invalid WMA closure audit SHA-256")


def _parse_inventory(evidence_root: Path) -> dict[str, str]:
    inventory_path = evidence_root / "EVIDENCE_SHA256SUMS"
    _require(inventory_path.is_file() and not inventory_path.is_symlink(), "missing dataset evidence inventory")
    observed: dict[str, str] = {}
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        _require(len(parts) == 2 and _is_sha256(parts[0]), "malformed dataset evidence inventory")
        name = Path(parts[1]).name
        _require(name not in observed, "duplicate dataset evidence inventory entry")
        observed[name] = parts[0]
    return observed


def load_dataset_evidence(evidence_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    _require(evidence_root.is_absolute() and evidence_root.is_dir(), "dataset evidence root is missing")
    _require(not evidence_root.is_symlink(), "dataset evidence root must not be a symlink")
    _require((evidence_root / "TERMINAL_ACCEPTED").is_file(), "dataset acceptance marker is missing")
    _require(not (evidence_root / "TERMINAL_REJECTED").exists(), "dataset rejection marker is present")
    required = {
        "dataset-integrity.json",
        "question-index.jsonl",
        "QID_ORDER.txt",
        "image-references.json",
    }
    inventory = _parse_inventory(evidence_root)
    _require(set(inventory) == required, "dataset evidence inventory surface drift")
    for name in sorted(required):
        path = evidence_root / name
        _require(path.is_file() and not path.is_symlink(), f"missing or linked dataset evidence: {name}")
        _require(sha256_file(path) == inventory[name], f"dataset evidence hash drift: {name}")

    identity = json.loads((evidence_root / "dataset-integrity.json").read_text(encoding="utf-8"))
    stable = identity.get("stable_identity", {})
    _require(identity.get("status") == "TERMINAL_ACCEPTED", "dataset identity is not terminal-accepted")
    expected_stable = {
        "repository": EXPECTED_REPOSITORY,
        "revision": EXPECTED_REVISION,
        "files": EXPECTED_FILES,
        "bytes": EXPECTED_BYTES,
        "dialog_files": EXPECTED_SCENARIOS,
        "image_files": EXPECTED_IMAGE_FILES,
        "questions": EXPECTED_QUESTIONS,
    }
    for field, expected in expected_stable.items():
        _require(stable.get(field) == expected, f"dataset stable identity drift: {field}")
    semantic = identity.get("dataset_semantic_identity_sha256")
    _require(_is_sha256(semantic), "invalid dataset semantic identity SHA-256")
    _require(hashlib.sha256(canonical_json_bytes(stable)).hexdigest() == semantic, "dataset semantic identity drift")

    question_path = evidence_root / "question-index.jsonl"
    questions = [json.loads(line) for line in question_path.read_text(encoding="utf-8").splitlines() if line]
    qid_path = evidence_root / "QID_ORDER.txt"
    qids = qid_path.read_text(encoding="utf-8").splitlines()
    _require(len(questions) == EXPECTED_QUESTIONS, "question-index denominator drift")
    _require(len(qids) == EXPECTED_QUESTIONS and len(set(qids)) == EXPECTED_QUESTIONS, "QID denominator drift")
    _require([row.get("qid") for row in questions] == qids, "question-index and QID order differ")
    _require(sha256_file(qid_path) == stable.get("qid_order_sha256"), "stable QID-order hash drift")
    _require(sha256_file(question_path) == stable.get("question_index_sha256"), "stable question-index hash drift")
    return identity, questions, qids


def validate_model_receipts(receipts: Mapping[str, Mapping[str, Any]]) -> None:
    _require(set(receipts) == set(REQUIRED_MODELS), "model receipt surface drift")
    for model_id, (repository, revision) in REQUIRED_MODELS.items():
        receipt = receipts[model_id]
        _require(receipt.get("status") == "TERMINAL_ACCEPTED", f"model is not accepted: {model_id}")
        _require(receipt.get("repository") == repository, f"model repository drift: {model_id}")
        _require(receipt.get("revision") == revision, f"model revision drift: {model_id}")
        _require(_is_sha256(receipt.get("inventory_sha256")), f"invalid model inventory SHA-256: {model_id}")
        _require(isinstance(receipt.get("files"), int) and receipt["files"] > 0, f"invalid model file count: {model_id}")
        _require(isinstance(receipt.get("bytes"), int) and receipt["bytes"] > 0, f"invalid model byte count: {model_id}")
        _require(receipt.get("offline_load_passed") is True, f"offline load not proven: {model_id}")
        _require(receipt.get("network_requests") == 0, f"model receipt used network during offline gate: {model_id}")
        _require(receipt.get("symlinks") == 0, f"model receipt contains symlinks: {model_id}")


def validate_service_receipt(
    receipt: Mapping[str, Any], model_receipts: Mapping[str, Mapping[str, Any]]
) -> None:
    answer = model_receipts["shared-qwen3-vl-8b-answer"]
    _require(receipt.get("status") == "TERMINAL_ACCEPTED_SYNTHETIC_INERT", "service receipt is not inert-accepted")
    _require(receipt.get("mode") == "injected_mock", "only the injected mock service is allowed")
    _require(receipt.get("served_model") == "Qwen3-VL-8B-Instruct", "served answer-model identity drift")
    _require(receipt.get("model_inventory_sha256") == answer.get("inventory_sha256"), "service/model inventory drift")
    _require(receipt.get("tokenizer_repository") == REQUIRED_MODELS["shared-qwen3-vl-8b-answer"][0], "tokenizer repository drift")
    _require(receipt.get("tokenizer_revision") == REQUIRED_MODELS["shared-qwen3-vl-8b-answer"][1], "tokenizer revision drift")
    _require(receipt.get("network_requests") == 0, "synthetic service receipt contains network requests")
    _require(receipt.get("gpu_processes_started") == 0, "synthetic service receipt contains GPU processes")
    _require(receipt.get("endpoint_requests") == 0, "synthetic service receipt contains endpoint requests")


def validate_authorization(authorization: Mapping[str, Any]) -> None:
    _require(authorization.get("status") == "AUTHORIZED_SYNTHETIC_LIFECYCLE", "synthetic lifecycle is not authorized")
    _require(authorization.get("mode") == "synthetic", "real lifecycle mode is prohibited")
    _require(authorization.get("real_model_calls") is False, "real model calls are prohibited")
    _require(authorization.get("scoring") is False, "scoring is prohibited")
    _require(authorization.get("official_values_used") is False, "official values are prohibited")
    ceilings = authorization.get("resource_ceilings", {})
    _require(ceilings.get("network_requests") == 0, "synthetic network ceiling must be zero")
    _require(ceilings.get("gpu_processes") == 0, "synthetic GPU-process ceiling must be zero")
    _require(isinstance(ceilings.get("wall_seconds"), int) and 0 < ceilings["wall_seconds"] <= 300, "invalid synthetic wall ceiling")
    _require(isinstance(ceilings.get("disk_bytes"), int) and 0 < ceilings["disk_bytes"] <= 268435456, "invalid synthetic disk ceiling")


def _validate_projection_surface(
    projections: Sequence[Mapping[str, Any]],
    question_rows: Sequence[Mapping[str, Any]],
    qids: Sequence[str],
    identity: Mapping[str, Any],
) -> None:
    _require(len(projections) == EXPECTED_SCENARIOS, "scenario denominator drift")
    registered = identity.get("scenarios")
    _require(isinstance(registered, list) and len(registered) == EXPECTED_SCENARIOS, "dataset scenario registry drift")
    cursor = 0
    flattened: list[str] = []
    observed_scenarios: list[str] = []
    for projection, expected in zip(projections, registered):
        scenario = projection.get("scenario")
        queries = projection.get("queries")
        _require(isinstance(scenario, str) and isinstance(queries, list), "invalid scenario projection")
        _require(scenario == expected.get("scenario"), "scenario order drift")
        _require(len(queries) == expected.get("questions"), f"scenario question count drift: {scenario}")
        frozen_slice = question_rows[cursor : cursor + len(queries)]
        validate_query_projection(queries, frozen_slice)
        flattened.extend(query["qid"] for query in queries)
        observed_scenarios.append(scenario)
        cursor += len(queries)
    _require(cursor == EXPECTED_QUESTIONS and flattened == list(qids), "projection QID surface drift")
    _require(len(set(observed_scenarios)) == EXPECTED_SCENARIOS, "duplicate scenario projection")


def run_synthetic_lifecycle(
    output_root: Path,
    *,
    allowed_run_scopes: Sequence[Path],
    method_id: str,
    seed: int,
    scenario_projections: Sequence[Mapping[str, Any]],
    dataset_evidence_root: Path,
    wave1_release_receipt: Mapping[str, Any],
    model_receipts: Mapping[str, Mapping[str, Any]],
    service_receipt: Mapping[str, Any],
    authorization: Mapping[str, Any],
    method_source: Mapping[str, Any],
    memory_budget: Mapping[str, Any],
    token_count: Callable[[str], int],
    answer_call: Callable[[Mapping[str, Any]], tuple[str, Mapping[str, Any]]],
    dense_document_vectors: Mapping[str, Sequence[Sequence[float]]] | None = None,
    dense_query_vector: Callable[[Mapping[str, Any]], Sequence[float]] | None = None,
) -> dict[str, Any]:
    """Run a full synthetic lifecycle; real mode has no implementation path."""
    validate_authorization(authorization)
    validate_wave1_release(wave1_release_receipt)
    identity, question_rows, qids = load_dataset_evidence(dataset_evidence_root)
    validate_model_receipts(model_receipts)
    validate_service_receipt(service_receipt, model_receipts)
    _validate_projection_surface(scenario_projections, question_rows, qids, identity)

    stable = identity["stable_identity"]
    writer = RawRunWriter(
        output_root,
        allowed_run_scopes=allowed_run_scopes,
        method_id=method_id,
        seed=seed,
        expected_qids=qids,
        dataset_semantic_identity_sha256=identity["dataset_semantic_identity_sha256"],
        qid_order_sha256=stable["qid_order_sha256"],
        question_index_sha256=stable["question_index_sha256"],
        method_source=method_source,
        memory_budget=memory_budget,
    )
    try:
        for projection in scenario_projections:
            scenario = str(projection["scenario"])
            vectors = dense_document_vectors.get(scenario) if dense_document_vectors is not None else None
            result = run_control_scenario(
                method_id,
                projection,
                seed=seed,
                token_count=token_count,
                answer_call=answer_call,
                dense_document_vectors=vectors,
                dense_query_vector=dense_query_vector,
            )
            writer.append_scenario(result)
        return writer.finalize()
    except Exception as exc:
        writer.reject(exc)
        raise
