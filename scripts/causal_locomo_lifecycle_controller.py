#!/usr/bin/env python3
"""Synthetic-only composition gate for the Causal-LoCoMo raw pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.causal_locomo_five_method_overlay import protocol_blocked_row, run_method
from scripts.causal_locomo_inference_view import build_inference_view
from scripts.causal_locomo_raw_run_writer import METHOD_ORDER, RawRunWriter


class LifecycleError(RuntimeError):
    """Lifecycle composition failed before real execution was authorized."""


def _canonical_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_records(records: Sequence[Mapping[str, Any]]) -> list[str]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
        raise LifecycleError("source records must be a nonempty sequence")
    qids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise LifecycleError("every source record must be an object")
        qid = record.get("example_id")
        if not isinstance(qid, str) or not qid:
            raise LifecycleError("every source record must have a nonempty example_id")
        qids.append(qid)
    if len(qids) != len(set(qids)):
        raise LifecycleError("source example IDs must be unique")
    return qids


def run_lifecycle(
    output_root: Path,
    *,
    mode: str,
    records: Sequence[Mapping[str, Any]],
    answer: Any,
    embed: Any,
) -> dict[str, Any]:
    """Compose all three seeds using injected mocks; real mode is unavailable."""
    if mode != "synthetic":
        raise LifecycleError("real lifecycle mode is not implemented or authorized")
    if not output_root.is_absolute() or output_root.is_symlink():
        raise LifecycleError("output_root must be an absolute non-symlink path")
    if output_root.exists():
        raise LifecycleError("output_root already exists")
    qids = _validate_records(records)
    views = [build_inference_view(record) for record in records]
    if [view["example_id"] for view in views] != qids:
        raise LifecycleError("inference view changed qid order")

    output_root.mkdir()
    seed_summaries: list[dict[str, Any]] = []
    for seed in (0, 1, 2):
        writer = RawRunWriter(output_root / f"seed-{seed}", seed=seed, qid_order=qids)
        for view in views:
            for method_id in METHOD_ORDER:
                if method_id in {"cmi-reflection-memory", "cmi"}:
                    row = protocol_blocked_row(view, method_id=method_id, seed=seed)
                else:
                    row = run_method(
                        view,
                        method_id=method_id,
                        seed=seed,
                        answer=answer,
                        embed=embed,
                    )
                writer.append(row)
        seed_summaries.append(writer.finalize())

    summary = {
        "schema_version": "agentenhance.causal_locomo_lifecycle_summary.v1",
        "mode": "synthetic",
        "seeds": [0, 1, 2],
        "qids": len(qids),
        "methods": len(METHOD_ORDER),
        "rows": sum(item["rows"] for item in seed_summaries),
        "accepted_rows": sum(item["accepted_rows"] for item in seed_summaries),
        "failed_rows": sum(item["failed_rows"] for item in seed_summaries),
        "protocol_blocked_rows": sum(item["protocol_blocked_rows"] for item in seed_summaries),
        "method_execution_failed_rows": sum(item["method_execution_failed_rows"] for item in seed_summaries),
        "seed_summaries": seed_summaries,
    }
    summary_path = output_root / "lifecycle-summary.json"
    summary_path.write_bytes(_canonical_bytes(summary))
    inventory_members = [summary_path]
    for seed in (0, 1, 2):
        seed_root = output_root / f"seed-{seed}"
        inventory_members.extend(
            [
                seed_root / "SHA256SUMS",
                seed_root / "TERMINAL_ACCEPTED",
                seed_root / "identity.json",
                seed_root / "summary.json",
            ]
        )
    inventory = "".join(
        f"{_sha256_file(path)}  {path.relative_to(output_root).as_posix()}\n"
        for path in sorted(inventory_members, key=lambda item: item.relative_to(output_root).as_posix())
    )
    (output_root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
    (output_root / "TERMINAL_ACCEPTED").touch(exist_ok=False)
    return summary

