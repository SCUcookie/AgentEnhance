#!/usr/bin/env python3
"""Append-only raw-run evidence writer for the matched Mem-Gallery track."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


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
ANSWER_MODEL = {
    "repository": "Qwen/Qwen3-VL-8B-Instruct",
    "revision": "5d854aab08710c16b980ec6d603d863b3821b915",
    "served_model": "Qwen3-VL-8B-Instruct",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def count_nonempty_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line)


class RawRunWriter:
    def __init__(
        self,
        output_root: Path,
        *,
        allowed_run_scopes: Sequence[Path],
        method_id: str,
        seed: int,
        expected_qids: Sequence[str],
        dataset_semantic_identity_sha256: str,
        qid_order_sha256: str,
        question_index_sha256: str,
        method_source: Mapping[str, Any],
        memory_budget: Mapping[str, Any],
    ) -> None:
        if method_id not in ALLOWED_METHODS or seed not in {0, 1, 2}:
            raise ValueError("unregistered method or seed")
        if (
            not expected_qids
            or any(not isinstance(qid, str) or not qid for qid in expected_qids)
            or len(expected_qids) != len(set(expected_qids))
        ):
            raise ValueError("expected_qids must be unique nonempty strings")
        for label, digest in (
            ("dataset semantic identity", dataset_semantic_identity_sha256),
            ("qid order", qid_order_sha256),
            ("question index", question_index_sha256),
        ):
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError(f"invalid {label} SHA-256")
        if method_source.get("identity_frozen") is not True:
            raise ValueError("method source identity is not frozen")
        implementation_sha256 = method_source.get("implementation_sha256")
        if not isinstance(implementation_sha256, str) or len(implementation_sha256) != 64:
            raise ValueError("invalid method implementation SHA-256")
        if memory_budget.get("prospectively_frozen") is not True:
            raise ValueError("memory budget is not prospectively frozen")
        if not output_root.is_absolute() or output_root.is_symlink():
            raise ValueError("output_root must be absolute and not a symlink")
        scopes = [scope.resolve() for scope in allowed_run_scopes]
        if not scopes or not any(output_root.parent.resolve() == scope for scope in scopes):
            raise ValueError("output_root must be an exact child of an allowed run scope")
        if output_root.exists():
            raise ValueError(f"refusing existing output root: {output_root}")
        output_root.mkdir(parents=False)

        self.root = output_root
        self.method_id = method_id
        self.seed = seed
        self.expected_qids = list(expected_qids)
        self.dataset_identity = dataset_semantic_identity_sha256
        self.qid_order_sha256 = qid_order_sha256
        self.question_index_sha256 = question_index_sha256
        self.method_source = dict(method_source)
        self.memory_budget = dict(memory_budget)
        self.observed_qids: list[str] = []
        self.terminal = False
        self.started_at = now()
        self.predictions_path = self.root / "raw-predictions.jsonl"
        self.traces_path = self.root / "retrieval-traces.jsonl"
        self.calls_path = self.root / "call-records.jsonl"
        self.events_path = self.root / "events.jsonl"
        for path in (self.predictions_path, self.traces_path, self.calls_path, self.events_path):
            atomic_create(path, b"")
        atomic_create(
            self.root / "run-record.json",
            json.dumps(
                {
                    "schema_version": "agentenhance.memgallery_raw_run_record.v1",
                    "status": "RUNNING",
                    "track_id": "memgallery-static-matched-v1",
                    "method_id": method_id,
                    "seed": seed,
                    "started_at": self.started_at,
                    "output_root": str(output_root),
                    "questions_expected": len(self.expected_qids),
                    "dataset_semantic_identity_sha256": self.dataset_identity,
                    "qid_order_sha256": self.qid_order_sha256,
                    "question_index_sha256": self.question_index_sha256,
                    "official_values_used": False,
                    "cleanup_authorized": False,
                },
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n",
        )
        append_jsonl(
            self.events_path,
            [
                {
                    "schema_version": "agentenhance.memgallery_raw_run_event.v1",
                    "event": "STARTED",
                    "at": self.started_at,
                    "method_id": method_id,
                    "seed": seed,
                }
            ],
        )

    def append_scenario(self, result: Mapping[str, Any]) -> None:
        if self.terminal:
            raise ValueError("raw run is already terminal")
        if result.get("status") != "TERMINAL_SCENARIO_COMPLETE":
            raise ValueError("scenario result is not terminal-complete")
        if result.get("method_id") != self.method_id or result.get("seed") != self.seed:
            raise ValueError("scenario method/seed drift")
        predictions = result.get("predictions")
        traces = result.get("retrieval_traces")
        calls = result.get("call_records")
        if not isinstance(predictions, list) or not isinstance(traces, list) or not isinstance(calls, list):
            raise ValueError("scenario evidence lists are missing")
        if len(predictions) != len(traces) or result.get("questions") != len(predictions):
            raise ValueError("scenario prediction/trace denominator drift")
        qids = [row.get("qid") for row in predictions]
        expected_slice = self.expected_qids[len(self.observed_qids) : len(self.observed_qids) + len(qids)]
        if qids != expected_slice:
            raise ValueError("scenario prediction QIDs differ from the next frozen order slice")
        if [row.get("qid") for row in traces] != qids:
            raise ValueError("retrieval trace QIDs differ from predictions")
        for row in predictions:
            if (
                row.get("schema_version") != "agentenhance.memgallery_prediction.v1"
                or row.get("method_id") != self.method_id
                or row.get("seed") != self.seed
                or row.get("status") not in {"ACCEPTED", "FAILED"}
            ):
                raise ValueError("prediction schema or identity drift")
        qid_set = set(qids)
        for call in calls:
            if (
                call.get("qid") not in qid_set
                or call.get("method_id") != self.method_id
                or call.get("seed") != self.seed
                or call.get("call_category") != "final_answer"
                or call.get("status") not in {"ACCEPTED", "FAILED"}
                or call.get("attempts") != 1
                or call.get("retry_count") != 0
            ):
                raise ValueError("call record identity or retry drift")
        append_jsonl(self.predictions_path, predictions)
        append_jsonl(self.traces_path, traces)
        append_jsonl(self.calls_path, calls)
        self.observed_qids.extend(qids)
        append_jsonl(
            self.events_path,
            [
                {
                    "schema_version": "agentenhance.memgallery_raw_run_event.v1",
                    "event": "SCENARIO_APPENDED",
                    "at": now(),
                    "scenario": result.get("scenario"),
                    "rows": len(qids),
                    "cumulative_rows": len(self.observed_qids),
                }
            ],
        )

    def _write_inventory(self, paths: Sequence[Path]) -> None:
        atomic_create(
            self.root / "EVIDENCE_SHA256SUMS",
            "".join(f"{sha256_file(path)}  {path}\n" for path in paths).encode("utf-8"),
        )

    def finalize(self) -> dict[str, Any]:
        if self.terminal:
            raise ValueError("raw run is already terminal")
        if self.observed_qids != self.expected_qids:
            raise ValueError("cannot finalize before the full frozen QID order is present")
        finished_at = now()
        prediction_rows = count_nonempty_lines(self.predictions_path)
        trace_rows = count_nonempty_lines(self.traces_path)
        call_rows = count_nonempty_lines(self.calls_path)
        identity = {
            "schema_version": "agentenhance.memgallery_raw_run_identity.v1",
            "status": "TERMINAL_RAW_COMPLETE",
            "track_id": "memgallery-static-matched-v1",
            "method_id": self.method_id,
            "seed": self.seed,
            "answer_model": ANSWER_MODEL,
            "decoding": {"temperature": 0.0, "max_output_tokens": 128},
            "memory_budget": self.memory_budget,
            "dataset_semantic_identity_sha256": self.dataset_identity,
            "qid_order_sha256": self.qid_order_sha256,
            "question_index_sha256": self.question_index_sha256,
            "questions_expected": len(self.expected_qids),
            "method_source": self.method_source,
            "official_values_used": False,
            "started_at": self.started_at,
            "finished_at": finished_at,
        }
        identity_path = self.root / "run-identity.json"
        atomic_create(identity_path, json.dumps(identity, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        summary = {
            "schema_version": "agentenhance.memgallery_raw_run_summary.v1",
            "status": "TERMINAL_RAW_COMPLETE",
            "method_id": self.method_id,
            "seed": self.seed,
            "prediction_rows": prediction_rows,
            "retrieval_trace_rows": trace_rows,
            "final_answer_call_rows": call_rows,
            "questions_expected": len(self.expected_qids),
            "failed_prediction_rows": sum(
                json.loads(line)["status"] == "FAILED"
                for line in self.predictions_path.read_text(encoding="utf-8").splitlines()
            ),
            "scores_observed": 0,
            "cleanup_authorized": False,
        }
        summary_path = self.root / "raw-run-summary.json"
        atomic_create(summary_path, json.dumps(summary, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        append_jsonl(
            self.events_path,
            [
                {
                    "schema_version": "agentenhance.memgallery_raw_run_event.v1",
                    "event": "TERMINAL_RAW_COMPLETE",
                    "at": finished_at,
                    "prediction_rows": prediction_rows,
                }
            ],
        )
        signed = [
            self.root / "run-record.json",
            identity_path,
            summary_path,
            self.predictions_path,
            self.traces_path,
            self.calls_path,
            self.events_path,
        ]
        self._write_inventory(signed)
        atomic_create(self.root / "TERMINAL_RAW_COMPLETE", b"")
        self.terminal = True
        return identity

    def reject(self, exc: Exception) -> dict[str, Any]:
        if self.terminal:
            raise ValueError("raw run is already terminal")
        failure = {
            "schema_version": "agentenhance.memgallery_raw_run_failure.v1",
            "status": "TERMINAL_REJECTED",
            "method_id": self.method_id,
            "seed": self.seed,
            "started_at": self.started_at,
            "finished_at": now(),
            "rows_retained": len(self.observed_qids),
            "questions_expected": len(self.expected_qids),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "same_root_retry_allowed": False,
            "cleanup_authorized": False,
        }
        failure_path = self.root / "raw-run-failure.json"
        atomic_create(failure_path, json.dumps(failure, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        append_jsonl(
            self.events_path,
            [
                {
                    "schema_version": "agentenhance.memgallery_raw_run_event.v1",
                    "event": "TERMINAL_REJECTED",
                    "at": failure["finished_at"],
                    "error_type": failure["error_type"],
                }
            ],
        )
        signed = [
            self.root / "run-record.json",
            failure_path,
            self.predictions_path,
            self.traces_path,
            self.calls_path,
            self.events_path,
        ]
        self._write_inventory(signed)
        atomic_create(self.root / "TERMINAL_REJECTED", b"")
        self.terminal = True
        return failure
