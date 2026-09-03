#!/usr/bin/env python3
"""Validate frozen WMA table identities, shapes, and result-free state."""

from __future__ import annotations

import csv
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "comparisons/wma-table-bundle-manifest.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-no-admitted-results", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["status"] != "FROZEN_BEFORE_MAIN_COMPARISON_RESULTS":
        raise SystemExit("table bundle is not frozen")
    execution = ROOT / manifest["method_corpus"]["execution_matrix"]
    if sha256_file(execution) != manifest["method_corpus"]["execution_matrix_sha256"]:
        raise SystemExit("execution matrix digest mismatch")
    with execution.open(encoding="utf-8", newline="") as handle:
        expected_methods = [row["implementation_id"] for row in csv.DictReader(handle)]

    checked = []
    for panel in manifest["panels"]:
        path = ROOT / panel["path"]
        if sha256_file(path) != panel["sha256"]:
            raise SystemExit(f"panel digest mismatch: {path}")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        if len(rows) != panel["rows"] or len(reader.fieldnames or []) != panel["columns"]:
            raise SystemExit(f"panel shape mismatch: {path}")
        if panel["name"] != "all_frozen_slices_long_form":
            methods = [row["implementation_id"] for row in rows]
            if methods != expected_methods:
                raise SystemExit(f"method order mismatch: {path}")
        checked.append(panel["name"])

    results_path = ROOT / "comparisons/reproduced-results.v1.csv"
    with results_path.open(encoding="utf-8", newline="") as handle:
        result_rows = list(csv.DictReader(handle))
    if args.require_no_admitted_results and result_rows:
        raise SystemExit("this frozen pre-result bundle validator expects zero admitted main-result rows")
    if any(row.get("status") != "ACCEPTED" for row in result_rows):
        raise SystemExit("non-accepted row present in reproduced-results")
    print(json.dumps({
        "status": "PASS",
        "panels": checked,
        "methods": len(expected_methods),
        "slice_rows": manifest["panels"][3]["rows"],
        "admitted_main_result_rows": len(result_rows),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
