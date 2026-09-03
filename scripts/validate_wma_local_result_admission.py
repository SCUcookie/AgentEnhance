#!/usr/bin/env python3
"""Validate the frozen, result-free WMA local result admission interface."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons/wma-local-result-admission-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(entry: dict[str, object]) -> Path:
    path = ROOT / str(entry["path"])
    if sha256_file(path) != entry["sha256"]:
        raise SystemExit(f"frozen source digest mismatch: {path}")
    return path


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_ANY_LOCAL_RESULT_ADMISSION":
        raise SystemExit("local result admission contract is not frozen")
    policy = resolve(contract["frozen_sources"]["baseline_evidence_policy"])
    matrix = resolve(contract["frozen_sources"]["execution_matrix"])
    metric_template = resolve(contract["frozen_sources"]["metric_catalog"])
    promoter = resolve(contract["implementation"]["promoter"])
    synthetic_test = resolve(contract["implementation"]["synthetic_test"])
    if not all(path.is_file() for path in (policy, matrix, metric_template, promoter, synthetic_test)):
        raise SystemExit("frozen admission dependency missing")

    historical = ROOT / contract["supersession"]["historical_result_file"]
    successor = ROOT / contract["supersession"]["successor_template"]
    if sha256_file(historical) != contract["supersession"]["historical_result_file_sha256"]:
        raise SystemExit("historical result ledger changed")
    if sha256_file(successor) != contract["supersession"]["successor_template_sha256"]:
        raise SystemExit("successor result template changed")
    with historical.open(encoding="utf-8", newline="") as handle:
        if list(csv.DictReader(handle)):
            raise SystemExit("historical result ledger is no longer result-free")
    with successor.open(encoding="utf-8", newline="") as handle:
        successor_reader = csv.DictReader(handle)
        successor_fields = list(successor_reader.fieldnames or [])
        if list(successor_reader):
            raise SystemExit("successor template is no longer result-free")
    required_output_fields = {
        "run_id",
        "implementation_id",
        "method_id",
        "benchmark_id",
        "track_id",
        "dataset_digest",
        "code_commit",
        "backbone_id",
        "retriever_id",
        "evaluator_id",
        "seed",
        "n_expected",
        "n_observed",
        "n_failed",
        "metric",
        "value",
        "direction",
        "unit",
        "status",
        "artifact_sha256",
    }
    if not required_output_fields.issubset(successor_fields):
        raise SystemExit("successor ledger omits required evidence fields")

    with matrix.open(encoding="utf-8", newline="") as handle:
        matrix_rows = list(csv.DictReader(handle))
    if len(matrix_rows) != 30 or len({row["implementation_id"] for row in matrix_rows}) != 30:
        raise SystemExit("execution matrix cardinality mismatch")
    with metric_template.open(encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    directions: dict[str, str] = {}
    for row in metric_rows:
        old = directions.setdefault(row["metric_key"], row["direction"])
        if old != row["direction"]:
            raise SystemExit(f"metric direction conflict: {row['metric_key']}")
    if len(directions) != 55 or set(directions.values()) != {"higher", "lower", "descriptive"}:
        raise SystemExit("metric catalog cardinality mismatch")

    if contract["admission"]["official_values_used"] is not False:
        raise SystemExit("official values are not prohibited")
    if contract["admission"]["source_reported_results_read"] is not False:
        raise SystemExit("source-reported result access is not prohibited")
    if contract["implementation"]["synthetic_test"]["accepted_rows_per_method"] != 3 * 55:
        raise SystemExit("accepted row cardinality mismatch")
    print(
        json.dumps(
            {
                "status": "PASS",
                "matrix_methods": len(matrix_rows),
                "fixed_metrics": len(directions),
                "seeds": 3,
                "rows_per_accepted_method": 165,
                "admitted_rows_at_freeze": 0,
                "official_values_used": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
