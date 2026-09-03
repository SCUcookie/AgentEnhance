#!/usr/bin/env python3
"""Validate exhaustive, disjoint coverage of recent baseline reproduction plans."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "comparisons/recent-method-reproduction-roadmap.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    roadmap = json.loads(ROADMAP.read_text(encoding="utf-8"))
    if roadmap["status"] != "FROZEN_BEFORE_ANY_ACCEPTED_WMA_MAIN_RESULT":
        raise SystemExit("roadmap is not frozen")
    for path_key, sha_key in (
        ("baseline_register", "baseline_register_sha256"),
        ("wma_execution_matrix", "wma_execution_matrix_sha256"),
        ("evidence_policy", "evidence_policy_sha256"),
        ("retention_policy", "retention_policy_sha256"),
    ):
        path = ROOT / roadmap["source_identities"][path_key]
        if sha256_file(path) != roadmap["source_identities"][sha_key]:
            raise SystemExit(f"source identity mismatch: {path_key}")
    validator = ROOT / roadmap["validator"]["path"]
    if sha256_file(validator) != roadmap["validator"]["sha256"]:
        raise SystemExit("validator digest mismatch")

    register_path = ROOT / roadmap["source_identities"]["baseline_register"]
    with register_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {
        row["method_id"]
        for row in rows
        if row["year"] in {"2025", "2026"} and row["method_id"] != "agentenhance-ceu"
    }
    grouped = [method for group in roadmap["groups"] for method in group["methods"]]
    if len(grouped) != len(set(grouped)):
        raise SystemExit("a recent method appears in more than one roadmap group")
    if set(grouped) != expected:
        raise SystemExit(
            f"recent method coverage mismatch; missing={sorted(expected-set(grouped))}, "
            f"extra={sorted(set(grouped)-expected)}"
        )
    if roadmap["coverage"]["recent_public_methods"] != len(expected):
        raise SystemExit("recent method count mismatch")
    with_repo = sum(bool(row["official_repo"]) for row in rows if row["method_id"] in expected)
    if roadmap["coverage"]["with_repository_recorded"] != with_repo:
        raise SystemExit("repository coverage count mismatch")
    wma_candidates = {
        row["method_id"]
        for row in rows
        if row["method_id"] in expected and "wma-lifecycle-matched-v1" in row["common_track"]
    }
    if roadmap["coverage"]["wma_track_candidates"] != len(wma_candidates):
        raise SystemExit("WMA candidate count mismatch")
    if any(not group["next_gate"] or not group["numeric_policy"] for group in roadmap["groups"]):
        raise SystemExit("roadmap group lacks a gate or numeric policy")
    if [group["order"] for group in roadmap["groups"]] != list(
        range(1, len(roadmap["groups"]) + 1)
    ):
        raise SystemExit("roadmap order is not consecutive")
    print(
        json.dumps(
            {
                "status": "PASS",
                "recent_public_methods": len(expected),
                "groups": len(roadmap["groups"]),
                "with_repository_recorded": with_repo,
                "wma_track_candidates": len(wma_candidates),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
