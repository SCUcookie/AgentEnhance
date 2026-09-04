#!/usr/bin/env python3
"""Append-only embedding evidence artifact for Mem-Gallery dense controls."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


PROFILE_IDENTITIES = {
    "naive-rag": {
        "profile": "gme1536",
        "model": "gme-Qwen2-VL-2B-Instruct",
        "repository": "Alibaba-NLP/gme-Qwen2-VL-2B-Instruct",
        "revision": "9cfa6413f704a7c1cf5064d240748e10c876b286",
        "dimensions": 1536,
    },
    "hybrid-rag": {
        "profile": "qwen1024",
        "model": "Qwen3-VL-Embedding-2B",
        "repository": "Qwen/Qwen3-VL-Embedding-2B",
        "revision": "c35dddf20620fe32745cb3d01f87ba64ae316313",
        "dimensions": 1024,
    },
}
ROLES = ("document", "query")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
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


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_loopback_embedding_endpoint(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path == "/v1/embeddings"
        and parsed.port is not None
        and 1024 <= parsed.port <= 65535
    )


def atomic_create(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing evidence file: {path}")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    payload = b"".join(canonical_json_bytes(dict(row)) for row in rows)
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _contains_raw_answer(value: object) -> bool:
    if isinstance(value, Mapping):
        return "answer" in value or any(_contains_raw_answer(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_answer(item) for item in value)
    return False


def build_embedding_surface(
    projections: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]], str]:
    """Bind ordered vector identities to answer-free projection text without returning raw text in identities."""
    if not isinstance(projections, Sequence) or isinstance(projections, (str, bytes)) or not projections:
        raise ValueError("projections must be a nonempty sequence")
    if _contains_raw_answer(projections):
        raise ValueError("raw answer key is prohibited in embedding projections")
    identities = {role: [] for role in ROLES}
    texts = {role: [] for role in ROLES}
    seen_scenarios: set[str] = set()
    seen_memory_ids: set[str] = set()
    seen_qids: set[str] = set()
    for scenario_index, projection in enumerate(projections):
        if not isinstance(projection, Mapping):
            raise ValueError(f"projection {scenario_index} must be an object")
        scenario = projection.get("scenario")
        records = projection.get("memory_records")
        queries = projection.get("queries")
        if (
            not isinstance(scenario, str)
            or not scenario
            or scenario in seen_scenarios
            or not isinstance(records, list)
            or not isinstance(queries, list)
        ):
            raise ValueError(f"invalid or duplicate scenario projection at {scenario_index}")
        seen_scenarios.add(scenario)
        for record_index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise ValueError("memory record must be an object")
            memory_id = record.get("memory_id")
            text = record.get("text")
            if (
                not isinstance(memory_id, str)
                or not memory_id
                or memory_id in seen_memory_ids
                or record.get("chronological_index") != record_index
                or not isinstance(text, str)
                or not text.strip()
            ):
                raise ValueError(f"invalid memory embedding identity: {scenario}:{record_index}")
            seen_memory_ids.add(memory_id)
            identities["document"].append(
                {
                    "role": "document",
                    "ordinal": len(identities["document"]),
                    "scenario": scenario,
                    "scenario_index": scenario_index,
                    "item_index": record_index,
                    "item_id": memory_id,
                    "text_sha256": sha256_bytes(text.encode("utf-8")),
                }
            )
            texts["document"].append(text)
        for query_index, query in enumerate(queries):
            if not isinstance(query, Mapping):
                raise ValueError("query must be an object")
            qid = query.get("qid")
            text = query.get("retrieval_query_text")
            if (
                not isinstance(qid, str)
                or not qid
                or qid in seen_qids
                or query.get("scenario") != scenario
                or not isinstance(text, str)
                or not text.strip()
            ):
                raise ValueError(f"invalid query embedding identity: {scenario}:{query_index}")
            seen_qids.add(qid)
            identities["query"].append(
                {
                    "role": "query",
                    "ordinal": len(identities["query"]),
                    "scenario": scenario,
                    "scenario_index": scenario_index,
                    "item_index": query_index,
                    "item_id": qid,
                    "text_sha256": sha256_bytes(text.encode("utf-8")),
                }
            )
            texts["query"].append(text)
    surface_hash = sha256_bytes(canonical_json_bytes(identities))
    return identities, texts, surface_hash


def _validate_vector(vector: object, dimensions: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise ValueError("embedding vector dimension drift")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise ValueError("embedding vector contains a nonnumeric value")
    parsed = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in parsed):
        raise ValueError("embedding vector contains non-finite values")
    norm = math.sqrt(sum(value * value for value in parsed))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("embedding vector has invalid norm")
    return parsed


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path.name}:{line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"non-object JSONL row at {path.name}:{line_number}")
        rows.append(row)
    return rows


class EmbeddingArtifactWriter:
    def __init__(
        self,
        output_root: Path,
        *,
        allowed_run_scopes: Sequence[Path],
        method_id: str,
        seed: int,
        projections: Sequence[Mapping[str, Any]],
        dataset_semantic_identity_sha256: str,
        batch_size: int,
    ) -> None:
        if method_id not in PROFILE_IDENTITIES or seed not in {0, 1, 2}:
            raise ValueError("unregistered dense method or seed")
        if not _is_sha256(dataset_semantic_identity_sha256):
            raise ValueError("invalid dataset semantic identity SHA-256")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 64:
            raise ValueError("batch_size must be an integer in 1..64")
        if not output_root.is_absolute() or output_root.is_symlink():
            raise ValueError("output_root must be absolute and not a symlink")
        scopes = [scope.resolve() for scope in allowed_run_scopes]
        if not scopes or not any(output_root.parent.resolve() == scope for scope in scopes):
            raise ValueError("output_root must be an exact child of an allowed run scope")
        if output_root.exists():
            raise ValueError(f"refusing existing output root: {output_root}")

        identities, texts, surface_hash = build_embedding_surface(projections)
        output_root.mkdir(parents=False)
        self.root = output_root
        self.method_id = method_id
        self.seed = seed
        self.profile = PROFILE_IDENTITIES[method_id]
        self.dataset_identity = dataset_semantic_identity_sha256
        self.batch_size = batch_size
        self.identities = identities
        self.texts = texts
        self.surface_hash = surface_hash
        self.offsets = {role: 0 for role in ROLES}
        self.call_counts = {role: 0 for role in ROLES}
        self.terminal = False
        self.started_at = now()
        self.vector_paths = {
            "document": self.root / "document-vectors.jsonl",
            "query": self.root / "query-vectors.jsonl",
        }
        self.calls_path = self.root / "embedding-calls.jsonl"
        self.events_path = self.root / "events.jsonl"
        for path in (*self.vector_paths.values(), self.calls_path, self.events_path):
            atomic_create(path, b"")
        atomic_create(
            self.root / "artifact-record.json",
            json.dumps(
                {
                    "schema_version": "agentenhance.memgallery_embedding_artifact_record.v1",
                    "status": "RUNNING",
                    "method_id": method_id,
                    "seed": seed,
                    "profile": self.profile,
                    "batch_size": batch_size,
                    "document_items_expected": len(identities["document"]),
                    "query_items_expected": len(identities["query"]),
                    "dataset_semantic_identity_sha256": dataset_semantic_identity_sha256,
                    "embedding_surface_sha256": surface_hash,
                    "started_at": self.started_at,
                    "scores_observed": 0,
                    "cleanup_authorized": False,
                },
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
        )
        append_jsonl(
            self.events_path,
            [{"event": "STARTED", "at": self.started_at, "method_id": method_id, "seed": seed}],
        )

    def _expected_request(self, role: str, input_items: int) -> tuple[str, int]:
        offset = self.offsets[role]
        expected_texts = self.texts[role][offset : offset + input_items]
        if len(expected_texts) != input_items:
            raise ValueError("embedding call exceeds the frozen input surface")
        request = {
            "model": self.profile["model"],
            "input": expected_texts,
            "encoding_format": "float",
        }
        payload = canonical_json_bytes(request)
        return sha256_bytes(payload), len(payload)

    def _validate_call(self, role: str, call: Mapping[str, Any], *, accepted: bool) -> int:
        if self.terminal:
            raise ValueError("embedding artifact is already terminal")
        if role not in ROLES:
            raise ValueError("embedding role must be document or query")
        expected_status = "ACCEPTED" if accepted else "FAILED"
        required = {
            "schema_version": "agentenhance.memgallery_embedding_call.v1",
            "call_category": "text_embedding",
            "input_role": role,
            "method_id": self.method_id,
            "seed": self.seed,
            "profile": self.profile["profile"],
            "model": self.profile["model"],
            "dimensions": self.profile["dimensions"],
            "status": expected_status,
            "attempts": 1,
            "retry_count": 0,
            "batch_index": self.call_counts[role],
            "input_offset": self.offsets[role],
        }
        for field, expected in required.items():
            if call.get(field) != expected:
                raise ValueError(f"embedding call identity drift: {field}")
        input_items = call.get("input_items")
        if not isinstance(input_items, int) or isinstance(input_items, bool) or not 1 <= input_items <= self.batch_size:
            raise ValueError("embedding call item count drift")
        expected_hash, expected_bytes = self._expected_request(role, input_items)
        if call.get("request_sha256") != expected_hash or call.get("request_bytes") != expected_bytes:
            raise ValueError("embedding request does not bind the next frozen text slice")
        if not _is_loopback_embedding_endpoint(call.get("endpoint")):
            raise ValueError("embedding call endpoint drift")
        wall_seconds = call.get("wall_seconds")
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(float(wall_seconds))
            or wall_seconds < 0
        ):
            raise ValueError("embedding call duration drift")
        usage: dict[str, int] = {}
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = call.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"embedding call usage drift: {field}")
            usage[field] = value
        if usage["completion_tokens"] != 0 or usage["prompt_tokens"] != usage["total_tokens"]:
            raise ValueError("embedding call token accounting drift")
        if accepted:
            if (
                call.get("http_status") != 200
                or not isinstance(call.get("response_id"), str)
                or not call["response_id"]
                or not _is_sha256(call.get("response_sha256"))
                or not isinstance(call.get("response_bytes"), int)
                or isinstance(call.get("response_bytes"), bool)
                or call["response_bytes"] <= 0
                or call.get("error_type") is not None
                or call.get("error") is not None
            ):
                raise ValueError("accepted embedding response evidence drift")
        elif (
            call.get("response_id") is not None
            or call.get("response_sha256") is not None
            or call.get("response_bytes") != 0
            or not isinstance(call.get("error_type"), str)
            or not call["error_type"]
            or not isinstance(call.get("error"), str)
            or not call["error"]
        ):
            raise ValueError("failed embedding response evidence drift")
        return input_items

    def append_accepted_batch(
        self, role: str, vectors: Sequence[Sequence[float]], call: Mapping[str, Any]
    ) -> None:
        input_items = self._validate_call(role, call, accepted=True)
        if not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes)) or len(vectors) != input_items:
            raise ValueError("embedding vector batch denominator drift")
        offset = self.offsets[role]
        parsed_vectors = [_validate_vector(list(vector), int(self.profile["dimensions"])) for vector in vectors]
        expected = self.identities[role][offset : offset + input_items]
        rows = [
            {
                "schema_version": "agentenhance.memgallery_embedding_vector.v1",
                "method_id": self.method_id,
                "seed": self.seed,
                **identity,
                "profile": self.profile["profile"],
                "model": self.profile["model"],
                "dimensions": self.profile["dimensions"],
                "vector": vector,
            }
            for identity, vector in zip(expected, parsed_vectors)
        ]
        append_jsonl(self.vector_paths[role], rows)
        append_jsonl(self.calls_path, [call])
        self.offsets[role] += input_items
        self.call_counts[role] += 1
        append_jsonl(
            self.events_path,
            [
                {
                    "event": "BATCH_APPENDED",
                    "at": now(),
                    "role": role,
                    "input_items": input_items,
                    "cumulative_items": self.offsets[role],
                }
            ],
        )

    def append_failed_call(self, role: str, call: Mapping[str, Any]) -> None:
        self._validate_call(role, call, accepted=False)
        append_jsonl(self.calls_path, [call])
        self.call_counts[role] += 1
        append_jsonl(
            self.events_path,
            [{"event": "FAILED_CALL_APPENDED", "at": now(), "role": role, "input_offset": self.offsets[role]}],
        )

    def append_complete_surface(
        self,
        role: str,
        vectors: Sequence[Sequence[float]],
        calls: Sequence[Mapping[str, Any]],
    ) -> None:
        cursor = 0
        for call in calls:
            count = call.get("input_items") if isinstance(call, Mapping) else None
            if not isinstance(count, int) or isinstance(count, bool):
                raise ValueError("embedding call lacks an integer input_items")
            self.append_accepted_batch(role, vectors[cursor : cursor + count], call)
            cursor += count
        if cursor != len(vectors):
            raise ValueError("embedding call/vector denominator drift")

    def _write_inventory(self, paths: Sequence[Path]) -> None:
        atomic_create(
            self.root / "EVIDENCE_SHA256SUMS",
            "".join(f"{sha256_file(path)}  {path.name}\n" for path in paths).encode("utf-8"),
        )

    def finalize(self) -> dict[str, Any]:
        if self.terminal:
            raise ValueError("embedding artifact is already terminal")
        for role in ROLES:
            if self.offsets[role] != len(self.identities[role]):
                raise ValueError(f"cannot finalize before the full {role} surface is present")
        finished_at = now()
        identity = {
            "schema_version": "agentenhance.memgallery_embedding_artifact_identity.v1",
            "status": "TERMINAL_EMBEDDINGS_COMPLETE",
            "method_id": self.method_id,
            "seed": self.seed,
            "profile": self.profile,
            "batch_size": self.batch_size,
            "document_items": self.offsets["document"],
            "query_items": self.offsets["query"],
            "document_calls": self.call_counts["document"],
            "query_calls": self.call_counts["query"],
            "dataset_semantic_identity_sha256": self.dataset_identity,
            "embedding_surface_sha256": self.surface_hash,
            "started_at": self.started_at,
            "finished_at": finished_at,
            "scores_observed": 0,
            "cleanup_authorized": False,
        }
        identity_path = self.root / "artifact-identity.json"
        atomic_create(identity_path, json.dumps(identity, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        summary = {
            "schema_version": "agentenhance.memgallery_embedding_artifact_summary.v1",
            "status": "TERMINAL_EMBEDDINGS_COMPLETE",
            "method_id": self.method_id,
            "seed": self.seed,
            "document_items": self.offsets["document"],
            "query_items": self.offsets["query"],
            "embedding_calls": sum(self.call_counts.values()),
            "failed_calls": 0,
            "scores_observed": 0,
            "cleanup_authorized": False,
        }
        summary_path = self.root / "artifact-summary.json"
        atomic_create(summary_path, json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        append_jsonl(self.events_path, [{"event": "TERMINAL_EMBEDDINGS_COMPLETE", "at": finished_at}])
        signed = [
            self.root / "artifact-record.json",
            identity_path,
            summary_path,
            self.vector_paths["document"],
            self.vector_paths["query"],
            self.calls_path,
            self.events_path,
        ]
        self._write_inventory(signed)
        atomic_create(self.root / "TERMINAL_EMBEDDINGS_COMPLETE", b"")
        self.terminal = True
        return identity

    def reject(self, exc: Exception) -> dict[str, Any]:
        if self.terminal:
            raise ValueError("embedding artifact is already terminal")
        failure = {
            "schema_version": "agentenhance.memgallery_embedding_artifact_failure.v1",
            "status": "TERMINAL_REJECTED",
            "method_id": self.method_id,
            "seed": self.seed,
            "document_items_retained": self.offsets["document"],
            "query_items_retained": self.offsets["query"],
            "embedding_calls_retained": sum(self.call_counts.values()),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "same_root_retry_allowed": False,
            "scores_observed": 0,
            "cleanup_authorized": False,
            "finished_at": now(),
        }
        failure_path = self.root / "artifact-failure.json"
        atomic_create(failure_path, json.dumps(failure, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        append_jsonl(self.events_path, [{"event": "TERMINAL_REJECTED", "at": failure["finished_at"]}])
        signed = [
            self.root / "artifact-record.json",
            failure_path,
            self.vector_paths["document"],
            self.vector_paths["query"],
            self.calls_path,
            self.events_path,
        ]
        self._write_inventory(signed)
        atomic_create(self.root / "TERMINAL_REJECTED", b"")
        self.terminal = True
        return failure


def load_embedding_artifact(
    root: Path,
    *,
    method_id: str,
    seed: int,
    projections: Sequence[Mapping[str, Any]],
    dataset_semantic_identity_sha256: str,
) -> dict[str, Any]:
    """Rehash and load a complete artifact into the frozen control-runner surfaces."""
    if method_id not in PROFILE_IDENTITIES or seed not in {0, 1, 2}:
        raise ValueError("unregistered dense method or seed")
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("embedding artifact root must be an absolute existing non-symlink directory")
    if not (root / "TERMINAL_EMBEDDINGS_COMPLETE").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise ValueError("embedding artifact is not terminal-complete")
    signed_names = {
        "artifact-record.json",
        "artifact-identity.json",
        "artifact-summary.json",
        "document-vectors.jsonl",
        "query-vectors.jsonl",
        "embedding-calls.jsonl",
        "events.jsonl",
    }
    inventory_path = root / "EVIDENCE_SHA256SUMS"
    if not inventory_path.is_file() or inventory_path.is_symlink():
        raise ValueError("embedding artifact inventory is missing")
    observed: dict[str, str] = {}
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or not _is_sha256(parts[0]) or Path(parts[1]).name != parts[1]:
            raise ValueError("malformed embedding artifact inventory")
        if parts[1] in observed:
            raise ValueError("duplicate embedding artifact inventory entry")
        observed[parts[1]] = parts[0]
    if set(observed) != signed_names:
        raise ValueError("embedding artifact inventory surface drift")
    for name in sorted(signed_names):
        path = root / name
        if not path.is_file() or path.is_symlink() or sha256_file(path) != observed[name]:
            raise ValueError(f"embedding artifact hash drift: {name}")

    identities, texts, surface_hash = build_embedding_surface(projections)
    record = json.loads((root / "artifact-record.json").read_text(encoding="utf-8"))
    identity = json.loads((root / "artifact-identity.json").read_text(encoding="utf-8"))
    if (
        record.get("schema_version") != "agentenhance.memgallery_embedding_artifact_record.v1"
        or record.get("status") != "RUNNING"
        or record.get("method_id") != method_id
        or record.get("seed") != seed
        or record.get("profile") != PROFILE_IDENTITIES[method_id]
        or record.get("document_items_expected") != len(identities["document"])
        or record.get("query_items_expected") != len(identities["query"])
        or record.get("dataset_semantic_identity_sha256") != dataset_semantic_identity_sha256
        or record.get("embedding_surface_sha256") != surface_hash
        or record.get("scores_observed") != 0
        or record.get("cleanup_authorized") is not False
    ):
        raise ValueError("embedding artifact start record identity drift")
    batch_size = record.get("batch_size")
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 64:
        raise ValueError("embedding artifact batch-size drift")
    expected_identity = {
        "schema_version": "agentenhance.memgallery_embedding_artifact_identity.v1",
        "status": "TERMINAL_EMBEDDINGS_COMPLETE",
        "method_id": method_id,
        "seed": seed,
        "profile": PROFILE_IDENTITIES[method_id],
        "document_items": len(identities["document"]),
        "query_items": len(identities["query"]),
        "dataset_semantic_identity_sha256": dataset_semantic_identity_sha256,
        "embedding_surface_sha256": surface_hash,
        "scores_observed": 0,
        "cleanup_authorized": False,
    }
    for field, expected in expected_identity.items():
        if identity.get(field) != expected:
            raise ValueError(f"embedding artifact identity drift: {field}")
    if identity.get("batch_size") != batch_size:
        raise ValueError("embedding artifact identity batch-size drift")

    summary = json.loads((root / "artifact-summary.json").read_text(encoding="utf-8"))
    expected_summary = {
        "schema_version": "agentenhance.memgallery_embedding_artifact_summary.v1",
        "status": "TERMINAL_EMBEDDINGS_COMPLETE",
        "method_id": method_id,
        "seed": seed,
        "document_items": len(identities["document"]),
        "query_items": len(identities["query"]),
        "embedding_calls": identity.get("document_calls", 0) + identity.get("query_calls", 0),
        "failed_calls": 0,
        "scores_observed": 0,
        "cleanup_authorized": False,
    }
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            raise ValueError(f"embedding artifact summary drift: {field}")

    call_rows = _read_jsonl(root / "embedding-calls.jsonl")
    call_offsets = {role: 0 for role in ROLES}
    call_indices = {role: 0 for role in ROLES}
    for call in call_rows:
        role = call.get("input_role")
        if role not in ROLES:
            raise ValueError("embedding artifact call role drift")
        count = call.get("input_items")
        required_call = {
            "schema_version": "agentenhance.memgallery_embedding_call.v1",
            "call_category": "text_embedding",
            "method_id": method_id,
            "seed": seed,
            "profile": PROFILE_IDENTITIES[method_id]["profile"],
            "model": PROFILE_IDENTITIES[method_id]["model"],
            "dimensions": PROFILE_IDENTITIES[method_id]["dimensions"],
            "status": "ACCEPTED",
            "attempts": 1,
            "retry_count": 0,
            "batch_index": call_indices[role],
            "input_offset": call_offsets[role],
            "http_status": 200,
        }
        for field, expected in required_call.items():
            if call.get(field) != expected:
                raise ValueError(f"embedding artifact call identity drift: {field}")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 1 <= count <= batch_size
            or call_offsets[role] + count > len(texts[role])
            or not _is_loopback_embedding_endpoint(call.get("endpoint"))
            or not isinstance(call.get("response_id"), str)
            or not call["response_id"]
            or not _is_sha256(call.get("response_sha256"))
            or not isinstance(call.get("response_bytes"), int)
            or isinstance(call.get("response_bytes"), bool)
            or call["response_bytes"] <= 0
            or call.get("error_type") is not None
            or call.get("error") is not None
        ):
            raise ValueError("embedding artifact accepted call evidence drift")
        expected_request = canonical_json_bytes(
            {
                "model": PROFILE_IDENTITIES[method_id]["model"],
                "input": texts[role][call_offsets[role] : call_offsets[role] + count],
                "encoding_format": "float",
            }
        )
        if (
            call.get("request_sha256") != sha256_bytes(expected_request)
            or call.get("request_bytes") != len(expected_request)
        ):
            raise ValueError("embedding artifact call request/text binding drift")
        wall_seconds = call.get("wall_seconds")
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(float(wall_seconds))
            or wall_seconds < 0
        ):
            raise ValueError("embedding artifact call duration drift")
        usage = [call.get(field) for field in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if (
            any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in usage)
            or usage[1] != 0
            or usage[0] != usage[2]
        ):
            raise ValueError("embedding artifact call token accounting drift")
        call_offsets[role] += count
        call_indices[role] += 1
    for role in ROLES:
        if call_offsets[role] != len(texts[role]) or call_indices[role] != identity.get(f"{role}_calls"):
            raise ValueError(f"embedding artifact {role} call denominator drift")

    by_scenario: dict[str, list[list[float]]] = {}
    query_vectors: dict[str, list[float]] = {}
    dimensions = int(PROFILE_IDENTITIES[method_id]["dimensions"])
    for role in ROLES:
        rows = _read_jsonl(root / f"{role}-vectors.jsonl")
        if len(rows) != len(identities[role]):
            raise ValueError(f"embedding artifact {role} denominator drift")
        for row, expected in zip(rows, identities[role]):
            for field, value in expected.items():
                if row.get(field) != value:
                    raise ValueError(f"embedding artifact {role} order/identity drift: {field}")
            if (
                row.get("schema_version") != "agentenhance.memgallery_embedding_vector.v1"
                or row.get("method_id") != method_id
                or row.get("seed") != seed
                or row.get("profile") != PROFILE_IDENTITIES[method_id]["profile"]
                or row.get("model") != PROFILE_IDENTITIES[method_id]["model"]
                or row.get("dimensions") != dimensions
            ):
                raise ValueError(f"embedding artifact {role} model identity drift")
            vector = _validate_vector(row.get("vector"), dimensions)
            if role == "document":
                by_scenario.setdefault(expected["scenario"], []).append(vector)
            else:
                query_vectors[expected["item_id"]] = vector
    return {
        "identity": identity,
        "dense_document_vectors": by_scenario,
        "dense_query_vectors": query_vectors,
        "call_records": call_rows,
    }
