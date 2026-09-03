#!/usr/bin/env python3
"""Project accepted local baseline summaries into the complete WMA bundle v3."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from project_wma_method_summaries import (
    EFFICIENCY_METRICS,
    MAIN_METRICS,
    RETRIEVAL_MEMORY_METRICS,
    load_metadata_corrections,
    project_panel,
    project_slices,
    sha256_file,
    verify_inventory,
)


BUNDLE_SHA256 = "e7faa9d42e314b30d21542b90071bea4763014779b6674a00c234d7dc7d80914"
SPEC_SHA256 = "f3a233b6e62419fa054557e18a326d7b2ba59210184bf782556dd1920f8c4937"
BUNDLE_NAME = "wma-table-bundle-manifest.v3.json"
BLOCKED = {"wma-memory-r1", "wma-apex-mem", "wma-lightmem", "wma-hela-mem"}
PROPOSED = "agentenhance-ceu"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_bundle(comparisons_root: Path) -> tuple[dict[str, Any], set[str]]:
    bundle_path = comparisons_root / BUNDLE_NAME
    if sha256_file(bundle_path) != BUNDLE_SHA256:
        raise SystemExit("WMA table bundle v3 identity mismatch")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if bundle.get("status") != "FROZEN_BEFORE_MAIN_COMPARISON_RESULTS":
        raise SystemExit("WMA table bundle v3 is not frozen")
    spec_path = comparisons_root.parent / bundle["table_spec"]["path"]
    if sha256_file(spec_path) != SPEC_SHA256 or SPEC_SHA256 != bundle["table_spec"]["sha256"]:
        raise SystemExit("WMA table spec v4 identity mismatch")
    execution_path = comparisons_root.parent / bundle["method_corpus"]["execution_matrix"]
    if sha256_file(execution_path) != bundle["method_corpus"]["execution_matrix_sha256"]:
        raise SystemExit("WMA execution matrix v3 identity mismatch")
    rows = read_csv_rows(execution_path)
    identifiers = {row["implementation_id"] for row in rows}
    if len(rows) != len(identifiers) or len(rows) != 30:
        raise SystemExit("WMA execution matrix v3 cardinality mismatch")
    if not BLOCKED.issubset(identifiers) or PROPOSED not in identifiers:
        raise SystemExit("blocked or proposed method is missing from the fixed surface")
    for panel in bundle["panels"]:
        path = comparisons_root.parent / panel["path"]
        if sha256_file(path) != panel["sha256"]:
            raise SystemExit(f"WMA template identity mismatch: {path}")
    return bundle, identifiers - BLOCKED - {PROPOSED}


def load_accepted_summary(root: Path, allowed: set[str]) -> tuple[str, dict[str, Any]]:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise SystemExit(f"summary root is not terminal-accepted: {root}")
    artifact_sha256 = verify_inventory(root)
    summary = json.loads((root / "method-seed-summary.json").read_text(encoding="utf-8"))
    slices = json.loads((root / "slice-seed-summary.json").read_text(encoding="utf-8"))
    audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
    implementation_id = str(summary.get("implementation_id"))
    if implementation_id not in allowed:
        raise SystemExit(f"implementation is blocked, proposed, or unregistered: {implementation_id}")
    if summary.get("status") != "TERMINAL_ACCEPTED":
        raise SystemExit(f"summary status is not terminal accepted: {root}")
    if not summary.get("main_comparison_eligible") or summary.get("seed_count") != 3:
        raise SystemExit(f"summary is not complete three-seed evidence: {root}")
    if summary.get("n_samples") != 150 or summary.get("n_qa") != 7906:
        raise SystemExit(f"summary denominator mismatch: {root}")
    if (
        audit.get("status") != "TERMINAL_ACCEPTED"
        or audit.get("seed_count") != 3
        or audit.get("seed_set") != [0, 1, 2]
        or audit.get("n_samples") != 150
        or audit.get("n_qa") != 7906
    ):
        raise SystemExit(f"summary combine audit mismatch: {root}")
    slice_metric_keys = [key for key in slices.get("metrics", {}) if key.endswith(".n_valid")]
    if len(slice_metric_keys) != 52:
        raise SystemExit(f"summary does not cover all 52 non-overall frozen slices: {root}")
    return implementation_id, {
        "summary": summary,
        "slices": slices,
        "artifact_sha256": artifact_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparisons-root", type=Path, required=True)
    parser.add_argument("--summary-root", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--metadata-corrections", type=Path)
    args = parser.parse_args()
    comparisons_root = args.comparisons_root.resolve()
    if args.output_root.exists():
        raise SystemExit(f"refusing existing output root: {args.output_root}")
    bundle, allowed = validate_bundle(comparisons_root)
    corrections_path = args.metadata_corrections or (
        comparisons_root / "wma-bibliographic-corrections.v1.json"
    )
    metadata_corrections, corrections_sha256 = load_metadata_corrections(corrections_path)

    accepted: dict[str, dict[str, Any]] = {}
    for root in args.summary_root:
        implementation_id, payload = load_accepted_summary(root.resolve(), allowed)
        if implementation_id in accepted:
            raise SystemExit(f"duplicate implementation summary: {implementation_id}")
        accepted[implementation_id] = payload
    args.output_root.mkdir(parents=True)
    panel_by_name = {row["name"]: comparisons_root.parent / row["path"] for row in bundle["panels"]}
    project_panel(
        panel_by_name["main_quality"],
        args.output_root / "wma-main-table.csv",
        accepted,
        MAIN_METRICS,
        metadata_corrections,
    )
    project_panel(
        panel_by_name["retrieval_and_memory"],
        args.output_root / "wma-retrieval-memory-table.csv",
        accepted,
        RETRIEVAL_MEMORY_METRICS,
    )
    project_panel(
        panel_by_name["efficiency_and_reliability"],
        args.output_root / "wma-efficiency-reliability-table.csv",
        accepted,
        EFFICIENCY_METRICS,
    )
    project_slices(
        panel_by_name["all_frozen_slices_long_form"],
        args.output_root / "wma-slice-table.csv",
        accepted,
    )
    output_manifest = {
        "schema_version": "agentenhance.wma_projected_table_bundle.v2",
        "status": "TERMINAL_ACCEPTED",
        "accepted_implementations": sorted(accepted),
        "source_bundle": str(comparisons_root / BUNDLE_NAME),
        "source_bundle_sha256": BUNDLE_SHA256,
        "admission": "only terminal-accepted complete three-seed local public-baseline summaries",
        "official_values_used": False,
        "blocked_or_proposed_values_used": False,
        "bibliographic_corrections": {
            "path": str(corrections_path),
            "sha256": corrections_sha256,
            "implementation_ids": sorted(metadata_corrections),
        },
        "files": {},
    }
    for path in sorted(args.output_root.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            row_count = sum(1 for _ in reader)
        output_manifest["files"][path.name] = {
            "sha256": sha256_file(path),
            "rows": row_count,
            "columns": len(header),
        }
    manifest_path = args.output_root / "manifest.json"
    manifest_path.write_text(json.dumps(output_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence_files = sorted(path for path in args.output_root.iterdir() if path.is_file())
    (args.output_root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path}\n" for path in evidence_files),
        encoding="utf-8",
    )
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(output_manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
