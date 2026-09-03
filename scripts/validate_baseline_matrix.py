#!/usr/bin/env python3
"""Validate the frozen baseline and metric contracts without third parties."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "comparisons" / "baseline-matrix.v1.json"
METRICS = ROOT / "comparisons" / "metric-contract.v1.json"
LEDGER = ROOT / "comparisons" / "reproduction-ledger.v1.csv"


def fail(message: str) -> None:
    raise SystemExit(f"baseline contract validation failed: {message}")


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    with LEDGER.open(encoding="utf-8", newline="") as handle:
        ledger = list(csv.DictReader(handle))

    if matrix.get("status") != "FROZEN" or metrics.get("status") != "FROZEN":
        fail("matrix and metric contract must both be FROZEN")

    rows = matrix.get("rows", [])
    method_ids = [row.get("method_id") for row in rows]
    if len(method_ids) != len(set(method_ids)):
        fail("duplicate method_id")
    ledger_ids = [row.get("method_id") for row in ledger]
    if len(ledger_ids) != len(set(ledger_ids)):
        fail("duplicate ledger method_id")
    if set(method_ids) != set(ledger_ids):
        fail(f"matrix/ledger row mismatch: {sorted(set(method_ids) ^ set(ledger_ids))}")

    required = {row["method_id"] for row in rows if row["required_in_primary_table"]}
    must_have = {
        "no-memory",
        "full-memory-text",
        "full-memory-mm",
        "fifo-recent",
        "bm25",
        "naive-rag",
        "hybrid-rag",
        "murag",
        "a-mem",
        "memoryos",
        "universalrag",
        "mirix",
        "m2a",
        "v-mem",
        "cmi",
        "agentenhance-ceu",
    }
    if not must_have.issubset(required):
        fail(f"required comparison rows missing: {sorted(must_have - required)}")

    directions = metrics.get("metric_directions", {})
    high = directions.get("higher_is_better", [])
    low = directions.get("lower_is_better", [])
    if set(high) & set(low):
        fail("metric appears in both direction lists")
    if len(high) < 15 or len(low) < 15:
        fail("metric surface is unexpectedly narrow")
    if metrics.get("statistical_contract", {}).get("minimum_seeds", 0) < 3:
        fail("stochastic comparisons require at least three seeds")

    prohibited = set(matrix.get("primary_benchmarks", [{}])[0])
    if "machine_path" in prohibited:
        fail("machine-private path leaked into baseline contract")

    print(
        json.dumps(
            {
                "status": "PASS",
                "matrix_id": matrix["matrix_id"],
                "method_count": len(rows),
                "required_primary_count": len(required),
                "metric_count": len(high) + len(low),
                "slice_count": len(metrics.get("required_slices", [])),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
