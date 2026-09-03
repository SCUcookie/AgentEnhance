#!/usr/bin/env python3
"""Validate the complete pre-result WMA table bundle v3."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "comparisons" / "wma-table-bundle-manifest.v3.json"
SPEC = ROOT / "comparisons" / "wma-main-table-spec.v4.json"
BLOCKED = {
    "wma-memory-r1": "CODE_NOT_RELEASED",
    "wma-apex-mem": "OFFICIAL_CODE_UNVERIFIED",
    "wma-lightmem": "OFFICIAL_CODE_UNVERIFIED",
    "wma-hela-mem": "LICENSE_BLOCKED",
}
DEVELOPMENT_ONLY = {"wma-mmfu-single", "wma-simplemem", "wma-m2a", "wma-vilomem"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def expected_status(implementation_id: str) -> str:
    if implementation_id == "agentenhance-ceu":
        return "LOCKED_UNTIL_BASELINES_ACCEPTED"
    if implementation_id in BLOCKED:
        return BLOCKED[implementation_id]
    if implementation_id in DEVELOPMENT_ONLY:
        return "DEVELOPMENT_ACCEPTED_NOT_MAIN"
    return "PENDING"


def assert_result_free(rows: list[dict[str, str]], identity_fields: set[str]) -> None:
    for row in rows:
        populated = {key for key, value in row.items() if value and key not in identity_fields}
        if populated:
            raise SystemExit(f"pre-result template has numeric/artifact content: {populated}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-no-admitted-results", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if manifest["status"] != "FROZEN_BEFORE_MAIN_COMPARISON_RESULTS":
        raise SystemExit("bundle is not frozen")
    if spec["status"] != "FROZEN_BEFORE_NUMERIC_RESULTS":
        raise SystemExit("table spec is not frozen")
    if sha256_file(SPEC) != manifest["table_spec"]["sha256"]:
        raise SystemExit("table spec digest mismatch")
    inherited = ROOT / spec["supersedes"]["path"]
    if sha256_file(inherited) != spec["supersedes"]["sha256"]:
        raise SystemExit("inherited table spec digest mismatch")
    execution = ROOT / manifest["method_corpus"]["execution_matrix"]
    if sha256_file(execution) != manifest["method_corpus"]["execution_matrix_sha256"]:
        raise SystemExit("execution matrix digest mismatch")
    _, execution_rows = read_csv(execution)
    expected_ids = [row["implementation_id"] for row in execution_rows]
    if len(expected_ids) != len(set(expected_ids)) or len(expected_ids) != 30:
        raise SystemExit("execution matrix must contain 30 unique implementations")
    recent_ids = spec["recent_same_track_public_candidates"]["implementation_ids"]
    if len(recent_ids) != len(set(recent_ids)) or len(recent_ids) != 16:
        raise SystemExit("recent same-track corpus must contain 16 unique methods")
    if not set(recent_ids).issubset(expected_ids):
        raise SystemExit("recent same-track method is absent from execution matrix")
    if spec["blocked_statuses"] != BLOCKED or manifest["blocked_statuses"] != BLOCKED:
        raise SystemExit("blocked method statuses disagree")

    checked = []
    for panel in manifest["panels"]:
        path = ROOT / panel["path"]
        if sha256_file(path) != panel["sha256"]:
            raise SystemExit(f"panel digest mismatch: {path}")
        fields, rows = read_csv(path)
        if len(rows) != panel["rows"] or len(fields) != panel["columns"]:
            raise SystemExit(f"panel shape mismatch: {path}")
        if panel["name"] == "all_frozen_slices_long_form":
            if len(rows) != 30 * 53:
                raise SystemExit("slice panel cardinality mismatch")
            for implementation_id in expected_ids:
                method_rows = [row for row in rows if row["implementation_id"] == implementation_id]
                if len(method_rows) != 53 or any(row["run_status"] != expected_status(implementation_id) for row in method_rows):
                    raise SystemExit(f"slice coverage/status mismatch: {implementation_id}")
            assert_result_free(
                rows,
                {"implementation_id", "display_name", "run_status", "slice_family", "slice_value", "n_expected"},
            )
        else:
            if [row["implementation_id"] for row in rows] != expected_ids:
                raise SystemExit(f"method order mismatch: {path}")
            for row in rows:
                if row["run_status"] != expected_status(row["implementation_id"]):
                    raise SystemExit(f"method status mismatch: {row['implementation_id']}")
            identities = {"implementation_id", "display_name", "run_status"}
            if panel["name"] == "main_quality":
                identities.update({"year", "scope"})
            assert_result_free(rows, identities)
        checked.append(panel["name"])

    results_path = ROOT / "comparisons" / "reproduced-results.v1.csv"
    _, result_rows = read_csv(results_path)
    if args.require_no_admitted_results and result_rows:
        raise SystemExit("pre-result bundle expects zero admitted local result rows")
    if any(row.get("status") != "ACCEPTED" for row in result_rows):
        raise SystemExit("non-accepted row present in reproduced-results")
    print(json.dumps({
        "status": "PASS",
        "methods": len(expected_ids),
        "recent_same_track_public_candidates": len(recent_ids),
        "blocked_public_rows": len(BLOCKED),
        "panels": checked,
        "slice_rows": manifest["panels"][3]["rows"],
        "admitted_main_result_rows": len(result_rows),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
