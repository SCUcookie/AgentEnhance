#!/usr/bin/env python3
"""Append-only raw evidence writer for one Causal-LoCoMo seed."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


METHOD_ORDER = (
    "cmi-no-memory",
    "cmi-full-history",
    "cmi-vector-memory",
    "cmi-summary-memory",
    "cmi-reflection-memory",
    "cmi-graph-memory",
    "cmi",
)
ALLOWED_FAILURE_KINDS = {"METHOD_EXECUTION", "PROTOCOL_BLOCKED"}


class RawRunError(RuntimeError):
    """A raw run violates its frozen identity, order, or row contract."""


def canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_prediction_row(row: Mapping[str, Any], *, qid: str, method_id: str, seed: int) -> None:
    if row.get("schema_version") != "agentenhance.causal_locomo_prediction.v1":
        raise RawRunError("prediction schema drift")
    if (row.get("example_id"), row.get("method_id"), row.get("seed")) != (qid, method_id, seed):
        raise RawRunError("prediction identity or order drift")
    if not isinstance(row.get("task_family"), str) or not row["task_family"]:
        raise RawRunError("prediction lacks task_family")
    status = row.get("status")
    if status not in {"ACCEPTED", "FAILED"}:
        raise RawRunError("prediction status must be ACCEPTED or FAILED")
    for key in ("selected_memory_ids", "retrieved_memory_ids", "rejected_memory_ids", "calls"):
        if not isinstance(row.get(key), list):
            raise RawRunError(f"prediction {key} must be a list")
    if len(row["selected_memory_ids"]) != len(set(row["selected_memory_ids"])):
        raise RawRunError("selected memory IDs must be unique")
    for call in row["calls"]:
        if not isinstance(call, Mapping):
            raise RawRunError("call record must be an object")
        if call.get("attempts") != 1 or call.get("retry_count") != 0:
            raise RawRunError("call record violates one-shot semantics")
        if call.get("status") not in {"ACCEPTED", "FAILED"}:
            raise RawRunError("call record status drift")
    if status == "ACCEPTED":
        if not isinstance(row.get("response"), str) or not row["response"].strip():
            raise RawRunError("accepted prediction must have a nonempty response")
        if row.get("error_type") is not None or row.get("error") is not None or row.get("failure_kind") is not None:
            raise RawRunError("accepted prediction contains failure fields")
        if not isinstance(row.get("prompt_sha256"), str) or len(row["prompt_sha256"]) != 64:
            raise RawRunError("accepted prediction lacks prompt identity")
    else:
        if row.get("response") != "" or row.get("prompt_sha256") is not None:
            raise RawRunError("failed prediction must not contain response or prompt identity")
        if row.get("failure_kind") not in ALLOWED_FAILURE_KINDS:
            raise RawRunError("failed prediction lacks a registered failure kind")
        if not isinstance(row.get("error_type"), str) or not row["error_type"]:
            raise RawRunError("failed prediction lacks error_type")
        if not isinstance(row.get("error"), str) or not row["error"]:
            raise RawRunError("failed prediction lacks error detail")
        if row["failure_kind"] == "PROTOCOL_BLOCKED":
            if method_id not in {"cmi-reflection-memory", "cmi"} or row["calls"]:
                raise RawRunError("protocol-blocked row method or call surface drift")


class RawRunWriter:
    """Write an exact qid-major seven-method surface into one fresh seed root."""

    def __init__(self, root: Path, *, seed: int, qid_order: Sequence[str]):
        if seed not in {0, 1, 2}:
            raise RawRunError("seed must be one of 0, 1, or 2")
        if not root.is_absolute() or root.is_symlink():
            raise RawRunError("run root must be an absolute non-symlink path")
        if root.exists():
            raise RawRunError("run root already exists")
        qids = list(qid_order)
        if not qids or any(not isinstance(qid, str) or not qid for qid in qids) or len(qids) != len(set(qids)):
            raise RawRunError("qid order must contain unique nonempty strings")
        root.mkdir()
        self.root = root
        self.seed = seed
        self.qids = qids
        self.expected = [(qid, method) for qid in qids for method in METHOD_ORDER]
        self.index = 0
        self.predictions = root / "predictions.jsonl"
        self.events = root / "events.jsonl"
        self.predictions.touch(exist_ok=False)
        identity = {
            "schema_version": "agentenhance.causal_locomo_raw_run_identity.v1",
            "seed": seed,
            "qid_count": len(qids),
            "method_order": list(METHOD_ORDER),
            "expected_rows": len(self.expected),
            "qid_order_sha256": _sha256_bytes(("\n".join(qids) + "\n").encode("utf-8")),
        }
        (root / "identity.json").write_bytes(canonical_bytes(identity))
        self.events.write_bytes(canonical_bytes({"event": "STARTED", "row_index": 0, "seed": seed}))

    def append(self, row: Mapping[str, Any]) -> None:
        if (self.root / "TERMINAL_ACCEPTED").exists():
            raise RawRunError("cannot append after terminal acceptance")
        if self.index >= len(self.expected):
            raise RawRunError("prediction surface already complete")
        qid, method_id = self.expected[self.index]
        validate_prediction_row(row, qid=qid, method_id=method_id, seed=self.seed)
        with self.predictions.open("ab") as handle:
            handle.write(canonical_bytes(dict(row)))
            handle.flush()
            os.fsync(handle.fileno())
        self.index += 1
        with self.events.open("ab") as handle:
            handle.write(
                canonical_bytes(
                    {
                        "event": "ROW_APPENDED",
                        "row_index": self.index,
                        "example_id": qid,
                        "method_id": method_id,
                        "status": row["status"],
                    }
                )
            )
            handle.flush()
            os.fsync(handle.fileno())

    def finalize(self) -> dict[str, Any]:
        if self.index != len(self.expected):
            raise RawRunError(f"run is incomplete: {self.index}/{len(self.expected)} rows")
        rows = [json.loads(line) for line in self.predictions.read_text(encoding="utf-8").splitlines()]
        if len(rows) != len(self.expected):
            raise RawRunError("durable prediction row count drift")
        accepted = sum(row["status"] == "ACCEPTED" for row in rows)
        blocked = sum(row.get("failure_kind") == "PROTOCOL_BLOCKED" for row in rows)
        failed = len(rows) - accepted
        expected_blocked = len(self.qids) * 2
        if blocked != expected_blocked:
            raise RawRunError("protocol-blocked denominator drift")
        summary = {
            "schema_version": "agentenhance.causal_locomo_raw_run_summary.v1",
            "seed": self.seed,
            "qids": len(self.qids),
            "methods": len(METHOD_ORDER),
            "rows": len(rows),
            "accepted_rows": accepted,
            "failed_rows": failed,
            "protocol_blocked_rows": blocked,
            "method_execution_failed_rows": failed - blocked,
        }
        (self.root / "summary.json").write_bytes(canonical_bytes(summary))
        with self.events.open("ab") as handle:
            handle.write(canonical_bytes({"event": "FINALIZED", **summary}))
            handle.flush()
            os.fsync(handle.fileno())
        inventory_paths = [self.events, self.root / "identity.json", self.predictions, self.root / "summary.json"]
        inventory = "".join(
            f"{_sha256_file(path)}  {path.relative_to(self.root).as_posix()}\n"
            for path in sorted(inventory_paths, key=lambda item: item.relative_to(self.root).as_posix())
        )
        (self.root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
        (self.root / "TERMINAL_ACCEPTED").touch(exist_ok=False)
        return summary

