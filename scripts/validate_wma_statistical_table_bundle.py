#!/usr/bin/env python3
"""Validate the frozen pre-result WMA statistical table bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "comparisons/wma-statistical-table-bundle-manifest.v1.json",
    )
    parser.add_argument("--require-result-free", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN_BEFORE_ANY_ACCEPTED_MAIN_RESULT":
        raise SystemExit("statistical table bundle is not frozen")
    for name, path_key, sha_key in (
        ("execution matrix", "execution_matrix", "execution_matrix_sha256"),
        ("slice template", "slice_template", "slice_template_sha256"),
        ("metric mapping", "metric_mapping_source", "metric_mapping_source_sha256"),
    ):
        path = ROOT / manifest["source_identities"][path_key]
        if sha256_file(path) != manifest["source_identities"][sha_key]:
            raise SystemExit(f"{name} digest mismatch")
    generator = ROOT / manifest["generator"]["path"]
    if sha256_file(generator) != manifest["generator"]["sha256"]:
        raise SystemExit("generator digest mismatch")
    for name, path_key, sha_key in (
        ("projector", "projector", "projector_sha256"),
        ("validator", "validator", "validator_sha256"),
        ("synthetic test", "synthetic_test", "synthetic_test_sha256"),
    ):
        path = ROOT / manifest["projection_and_validation"][path_key]
        if sha256_file(path) != manifest["projection_and_validation"][sha_key]:
            raise SystemExit(f"{name} digest mismatch")
    for name, path_key, sha_key in (
        ("paired sufficient statistics", "implementation", "implementation_sha256"),
        ("paired sufficient-stat validation", "validation", "validation_sha256"),
    ):
        path = ROOT / manifest["paired_sufficient_statistics"][path_key]
        if sha256_file(path) != manifest["paired_sufficient_statistics"][sha_key]:
            raise SystemExit(f"{name} digest mismatch")
    for name, path_key, sha_key in (
        ("pairwise bootstrap implementation", "implementation", "implementation_sha256"),
        ("pairwise bootstrap synthetic test", "synthetic_test", "synthetic_test_sha256"),
    ):
        path = ROOT / manifest["pairwise_computation"][path_key]
        if sha256_file(path) != manifest["pairwise_computation"][sha_key]:
            raise SystemExit(f"{name} digest mismatch")

    checked: dict[str, int] = {}
    rows_by_name: dict[str, list[dict[str, str]]] = {}
    for table in manifest["tables"]:
        path = ROOT / table["path"]
        if sha256_file(path) != table["sha256"]:
            raise SystemExit(f"table digest mismatch: {path}")
        fields, rows = read_csv(path)
        if len(fields) != table["columns"] or len(rows) != table["rows"]:
            raise SystemExit(f"table shape mismatch: {path}")
        rows_by_name[table["name"]] = rows
        checked[table["name"]] = len(rows)

    method_rows = rows_by_name["method_seed_statistics"]
    methods = {row["implementation_id"] for row in method_rows}
    metrics = {row["metric_key"] for row in method_rows}
    if len(methods) != 22 or len(metrics) != 55:
        raise SystemExit("method or metric cardinality mismatch")
    if len({(row["implementation_id"], row["metric_key"]) for row in method_rows}) != len(method_rows):
        raise SystemExit("duplicate method-metric row")

    pairwise_rows = rows_by_name["agentenhance_pairwise"]
    comparators = {row["implementation_b"] for row in pairwise_rows}
    if len(comparators) != 21 or {row["implementation_a"] for row in pairwise_rows} != {"agentenhance-ceu"}:
        raise SystemExit("pairwise comparator surface mismatch")
    if len({(row["implementation_b"], row["metric_key"]) for row in pairwise_rows}) != len(pairwise_rows):
        raise SystemExit("duplicate pairwise row")
    paired_rows = [
        row for row in pairwise_rows if row["analysis_unit"] == "paired_original_sample_cluster"
    ]
    descriptive_rows = [
        row for row in pairwise_rows if row["analysis_unit"] == "seed_level_descriptive"
    ]
    if len(paired_rows) != 21 * manifest["metric_surface"]["paired_cluster_inference_metrics"]:
        raise SystemExit("paired-inference row count mismatch")
    if len(descriptive_rows) != 21 * manifest["metric_surface"]["seed_level_descriptive_metrics"]:
        raise SystemExit("seed-descriptive row count mismatch")
    if any(
        row["bootstrap_resamples"] != "10000"
        or row["bootstrap_seed"] != "20260903"
        or row["direction"] == "descriptive"
        for row in paired_rows
    ):
        raise SystemExit("invalid paired-inference configuration")
    if any(row["bootstrap_resamples"] or row["bootstrap_seed"] for row in descriptive_rows):
        raise SystemExit("descriptive row incorrectly configured for bootstrap inference")
    if {row["analysis_unit"] for row in method_rows} != {"model_seed"}:
        raise SystemExit("method seed-statistics analysis unit mismatch")

    slice_rows = rows_by_name["slice_seed_statistics"]
    if len({(row["slice_family"], row["slice_value"]) for row in slice_rows}) != 53:
        raise SystemExit("slice surface mismatch")
    if len({row["metric_key"] for row in slice_rows}) != 8:
        raise SystemExit("slice metric surface mismatch")
    if {row["analysis_unit"] for row in slice_rows} != {"model_seed"}:
        raise SystemExit("slice seed-statistics analysis unit mismatch")
    if len(
        {
            (row["implementation_id"], row["slice_family"], row["slice_value"], row["metric_key"])
            for row in slice_rows
        }
    ) != len(slice_rows):
        raise SystemExit("duplicate method-slice-metric row")

    numeric_fields = {
        "seed_count",
        "mean",
        "sample_standard_deviation",
        "seed_0",
        "seed_1",
        "seed_2",
        "point_difference",
        "ci95_low",
        "ci95_high",
        "paired_clusters",
    }
    if args.require_result_free:
        for table_name, rows in rows_by_name.items():
            for row in rows:
                for field in numeric_fields & set(row):
                    if row[field] != "":
                        raise SystemExit(
                            f"pre-result numeric field populated: {table_name}:{field}"
                        )

    print(
        json.dumps(
            {
                "status": "PASS",
                "methods": len(methods),
                "metrics": len(metrics),
                "comparators": len(comparators),
                "slice_values": 53,
                "tables": checked,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
