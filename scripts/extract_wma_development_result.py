#!/usr/bin/env python3
"""Validate and extract all numeric metrics from an accepted WMA smoke run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def flatten_numeric(value: Any, prefix: str = "") -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    if isinstance(value, dict):
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten_numeric(value[key], child))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[prefix] = value
    return out


def verify_inventory(method_root: Path) -> str:
    inventory = method_root / "SHA256SUMS"
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_absolute():
            path = method_root / path
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"artifact inventory mismatch: {path}")
    return sha256_file(inventory)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("method_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--implementation-id", required=True)
    parser.add_argument("--expected-sample-id", required=True)
    parser.add_argument("--expected-sessions", required=True, type=int)
    parser.add_argument("--expected-qa", required=True, type=int)
    parser.add_argument("--dataset-manifest-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--backbone-id", required=True)
    parser.add_argument("--retriever-id", required=True)
    args = parser.parse_args()

    root = args.method_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    if root in output.parents:
        raise SystemExit("output must be outside the immutable method run root")
    if not (root / "TERMINAL_ACCEPTED").is_file():
        raise SystemExit("method run is not terminal-accepted")

    aggregate_path = root / "output" / "aggregate_metrics.json"
    sessions_path = root / "output" / "session_records.jsonl"
    qa_path = root / "output" / "qa_records.jsonl"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    sessions = read_jsonl(sessions_path)
    qa = read_jsonl(qa_path)
    if len(sessions) != args.expected_sessions or len(qa) != args.expected_qa:
        raise SystemExit(
            f"record count mismatch: sessions={len(sessions)}/{args.expected_sessions} "
            f"qa={len(qa)}/{args.expected_qa}"
        )
    sample_ids = sorted({str(row.get("sample_id")) for row in [*sessions, *qa]})
    if sample_ids != [args.expected_sample_id]:
        raise SystemExit(f"sample ID mismatch: {sample_ids}")

    inventory_sha = verify_inventory(root)
    report = {
        "schema_version": "agentenhance.wma_development_result.v1",
        "status": "ACCEPTED_DEVELOPMENT",
        "evidence_role": "development-foundation",
        "main_comparison_eligible": False,
        "run_id": args.run_id,
        "implementation_id": args.implementation_id,
        "benchmark_id": "worldmemarena-2026",
        "track_id": "wma-lifecycle-matched-v1",
        "source_commit": args.source_commit,
        "dataset_manifest_sha256": args.dataset_manifest_sha256,
        "backbone_id": args.backbone_id,
        "retriever_id": args.retriever_id,
        "sample_ids": sample_ids,
        "n_samples": 1,
        "n_sessions": len(sessions),
        "n_qa": len(qa),
        "n_failed": 0,
        "metrics": flatten_numeric(aggregate),
        "artifact_inventory_sha256": inventory_sha,
        "source_files": {
            "aggregate_metrics_sha256": sha256_file(aggregate_path),
            "session_records_sha256": sha256_file(sessions_path),
            "qa_records_sha256": sha256_file(qa_path),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "implementation_id": args.implementation_id,
        "metric_count": len(report["metrics"]),
        "artifact_inventory_sha256": inventory_sha,
        "output": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
