#!/usr/bin/env python3
"""Promote accepted three-seed WMA evidence into a canonical local-result ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


EXPECTED_SEEDS = {0, 1, 2}
EXPECTED_SAMPLES = 150
EXPECTED_QA = 7906
EXPECTED_BENCHMARK = "worldmemarena-2026"
EXPECTED_TRACK = "wma-lifecycle-matched-v1"
EXPECTED_SPLIT = "small"

FIELDS = [
    "run_id",
    "implementation_id",
    "method_id",
    "benchmark_id",
    "track_id",
    "split",
    "dataset_digest",
    "code_commit",
    "adapter_code_identity",
    "backbone_id",
    "retriever_id",
    "evaluator_id",
    "seed",
    "n_expected",
    "n_observed",
    "n_failed",
    "n_qa",
    "metric",
    "value",
    "direction",
    "unit",
    "status",
    "artifact_sha256",
    "summary_artifact_sha256",
    "identity_sha256",
    "notes",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise SystemExit(f"missing inventory: {inventory}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_absolute():
            path = root / path
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"inventory mismatch: {path}")
    return sha256_file(inventory)


def flatten_numeric(value: Any, prefix: str = "") -> dict[str, float]:
    output: dict[str, float] = {}
    if isinstance(value, dict):
        for key, child in sorted(value.items()):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            output.update(flatten_numeric(child, child_prefix))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise SystemExit(f"non-finite metric: {prefix}={value}")
        output[prefix] = numeric
    return output


def render(value: float) -> str:
    return format(value, ".17g")


def metric_unit(metric: str) -> str:
    if metric.endswith("_seconds") or metric.startswith("runtime."):
        return "seconds"
    if metric.endswith("_ms"):
        return "milliseconds"
    if metric.endswith("_bytes"):
        return "bytes"
    if metric.endswith("_gib"):
        return "GiB"
    if metric.endswith("gpu_hours"):
        return "GPU-hours"
    if metric.startswith("token_usage."):
        return "tokens"
    if metric.endswith("num_valid") or metric.endswith("num_covered") or metric.endswith("num_total"):
        return "questions"
    if metric.endswith("total_memories"):
        return "memories"
    return "ratio"


def load_metric_catalog(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    catalog: dict[str, dict[str, str]] = {}
    for row in rows:
        key = row["metric_key"]
        entry = {"direction": row["direction"], "unit": metric_unit(key)}
        if key in catalog and catalog[key] != entry:
            raise SystemExit(f"inconsistent metric catalog entry: {key}")
        catalog[key] = entry
    if len(catalog) != 55 or {entry["direction"] for entry in catalog.values()} != {
        "higher",
        "lower",
        "descriptive",
    }:
        raise SystemExit("frozen metric catalog surface mismatch")
    return catalog


def load_method_matrix(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    matrix = {row["implementation_id"]: row for row in rows}
    if len(rows) != 30 or len(matrix) != 30:
        raise SystemExit("execution matrix surface mismatch")
    return matrix


def validate_identity(path: Path, summary: dict[str, Any], matrix_row: dict[str, str]) -> dict[str, Any]:
    identity = read_json(path)
    required = {
        "implementation_id",
        "run_id",
        "benchmark_id",
        "track_id",
        "split",
        "dataset_digest",
        "code_commit",
        "adapter_code_identity",
        "backbone_id",
        "retriever_id",
        "evaluator_id",
    }
    if identity.get("status") != "FROZEN_BEFORE_NUMERIC_RUN" or not required.issubset(identity):
        raise SystemExit(f"identity is incomplete or not pre-result frozen: {path}")
    if identity["implementation_id"] != summary.get("implementation_id"):
        raise SystemExit(f"identity implementation mismatch: {path}")
    if identity["run_id"] != summary.get("run_id"):
        raise SystemExit(f"identity run mismatch: {path}")
    if identity["benchmark_id"] != EXPECTED_BENCHMARK or identity["track_id"] != EXPECTED_TRACK:
        raise SystemExit(f"identity benchmark/track mismatch: {path}")
    if identity["split"] != EXPECTED_SPLIT:
        raise SystemExit(f"identity split mismatch: {path}")
    if matrix_row["implementation_id"] != identity["implementation_id"]:
        raise SystemExit(f"identity absent from execution matrix: {path}")
    for field in required - {"implementation_id", "run_id", "benchmark_id", "track_id", "split"}:
        if not isinstance(identity[field], str) or not identity[field].strip():
            raise SystemExit(f"blank identity field {field}: {path}")
    if len(identity["dataset_digest"]) != 64 or len(identity["code_commit"]) != 40:
        raise SystemExit(f"invalid frozen digest identity: {path}")
    return identity


def load_one_summary(
    root: Path,
    identity_path: Path,
    matrix: dict[str, dict[str, str]],
    catalog: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise SystemExit(f"summary root is not terminal-accepted: {root}")
    summary_inventory_sha256 = verify_inventory(root)
    summary = read_json(root / "method-seed-summary.json")
    combine_audit = read_json(root / "audit.json")
    implementation_id = str(summary.get("implementation_id"))
    if implementation_id not in matrix:
        raise SystemExit(f"unregistered implementation: {implementation_id}")
    matrix_row = matrix[implementation_id]
    if matrix_row["adapter_gate"] in {
        "code-not-released",
        "no-official-code-verified",
        "license-audit-blocked",
        "not-started",
    }:
        raise SystemExit(f"blocked or proposed implementation: {implementation_id}")
    identity = validate_identity(identity_path, summary, matrix_row)
    identity_sha256 = sha256_file(identity_path)
    if (
        summary.get("status") != "TERMINAL_ACCEPTED"
        or summary.get("main_comparison_eligible") is not True
        or summary.get("seed_count") != 3
        or summary.get("seeds") != [0, 1, 2]
        or summary.get("n_samples") != EXPECTED_SAMPLES
        or summary.get("n_qa") != EXPECTED_QA
        or combine_audit.get("status") != "TERMINAL_ACCEPTED"
        or combine_audit.get("seed_set") != [0, 1, 2]
    ):
        raise SystemExit(f"ineligible three-seed summary: {root}")
    summary_metrics = summary.get("metrics", {})
    if not set(catalog).issubset(summary_metrics):
        raise SystemExit(f"summary misses frozen metrics: {sorted(set(catalog) - set(summary_metrics))}")
    evidence_by_seed = {int(row["seed"]): row for row in summary.get("source_evidence", [])}
    if set(evidence_by_seed) != EXPECTED_SEEDS:
        raise SystemExit(f"summary source evidence seed mismatch: {root}")

    output_rows: list[dict[str, str]] = []
    seed_roots: dict[str, dict[str, str]] = {}
    for seed in sorted(EXPECTED_SEEDS):
        evidence = evidence_by_seed[seed]
        seed_root = Path(evidence["aggregate_root"])
        if not (seed_root / "TERMINAL_ACCEPTED").is_file() or (seed_root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"seed root is not terminal-accepted: {seed_root}")
        seed_inventory_sha256 = verify_inventory(seed_root)
        if seed_inventory_sha256 != evidence.get("artifact_inventory_sha256"):
            raise SystemExit(f"seed inventory identity mismatch: {seed_root}")
        seed_audit = read_json(seed_root / "audit.json")
        if (
            seed_audit.get("status") != "TERMINAL_ACCEPTED"
            or seed_audit.get("main_comparison_eligible") is not True
            or seed_audit.get("baseline") != summary.get("baseline")
            or seed_audit.get("seed") != seed
            or (seed_audit.get("n_expected"), seed_audit.get("n_observed"), seed_audit.get("n_failed"))
            != (EXPECTED_SAMPLES, EXPECTED_SAMPLES, 0)
            or seed_audit.get("n_qa") != EXPECTED_QA
            or seed_audit.get("source_commit") != identity["code_commit"]
            or seed_audit.get("dataset_manifest_sha256") != identity["dataset_digest"]
        ):
            raise SystemExit(f"seed audit/identity mismatch: {seed_root}")
        seed_metrics = flatten_numeric(read_json(seed_root / "aggregate_metrics.json"))
        for metric, semantics in sorted(catalog.items()):
            if metric not in seed_metrics:
                raise SystemExit(f"seed misses frozen metric {metric}: {seed_root}")
            summary_value = float(summary_metrics[metric]["seed_values"][str(seed)])
            if seed_metrics[metric] != summary_value:
                raise SystemExit(f"summary/raw metric mismatch: seed={seed} metric={metric}")
            output_rows.append(
                {
                    "run_id": identity["run_id"],
                    "implementation_id": implementation_id,
                    "method_id": matrix_row["method_id"],
                    "benchmark_id": identity["benchmark_id"],
                    "track_id": identity["track_id"],
                    "split": identity["split"],
                    "dataset_digest": identity["dataset_digest"],
                    "code_commit": identity["code_commit"],
                    "adapter_code_identity": identity["adapter_code_identity"],
                    "backbone_id": identity["backbone_id"],
                    "retriever_id": identity["retriever_id"],
                    "evaluator_id": identity["evaluator_id"],
                    "seed": str(seed),
                    "n_expected": str(EXPECTED_SAMPLES),
                    "n_observed": str(EXPECTED_SAMPLES),
                    "n_failed": "0",
                    "n_qa": str(EXPECTED_QA),
                    "metric": metric,
                    "value": render(seed_metrics[metric]),
                    "direction": semantics["direction"],
                    "unit": semantics["unit"],
                    "status": "ACCEPTED_LOCAL_3SEED",
                    "artifact_sha256": seed_inventory_sha256,
                    "summary_artifact_sha256": summary_inventory_sha256,
                    "identity_sha256": identity_sha256,
                    "notes": "local matched-protocol seed metric; official values not used",
                }
            )
        seed_roots[str(seed)] = {
            "aggregate_root": str(seed_root.resolve()),
            "artifact_inventory_sha256": seed_inventory_sha256,
        }
    return output_rows, {
        "implementation_id": implementation_id,
        "method_id": matrix_row["method_id"],
        "run_id": identity["run_id"],
        "identity_path": str(identity_path.resolve()),
        "identity_sha256": identity_sha256,
        "summary_root": str(root.resolve()),
        "summary_artifact_sha256": summary_inventory_sha256,
        "seed_roots": seed_roots,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-root", type=Path, action="append", required=True)
    parser.add_argument("--identity", type=Path, action="append", required=True)
    parser.add_argument(
        "--execution-matrix",
        type=Path,
        default=Path("comparisons/wma-execution-matrix.v3.csv"),
    )
    parser.add_argument(
        "--metric-template",
        type=Path,
        default=Path("comparisons/wma-method-seed-statistics-template.v1.csv"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if len(args.summary_root) != len(args.identity):
        raise SystemExit("one --identity is required for each --summary-root, in matching order")
    if args.output_root.exists():
        raise SystemExit(f"refusing existing output root: {args.output_root}")

    matrix = load_method_matrix(args.execution_matrix)
    catalog = load_metric_catalog(args.metric_template)
    rows: list[dict[str, str]] = []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root, identity_path in zip(args.summary_root, args.identity):
        promoted, source = load_one_summary(
            root.resolve(), identity_path.resolve(), matrix, catalog
        )
        if source["implementation_id"] in seen:
            raise SystemExit(f"duplicate implementation: {source['implementation_id']}")
        seen.add(source["implementation_id"])
        rows.extend(promoted)
        sources.append(source)

    args.output_root.mkdir(parents=True)
    ledger = args.output_root / "reproduced-results.v2.csv"
    with ledger.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["implementation_id"], int(row["seed"]), row["metric"])))
    manifest = {
        "schema_version": "agentenhance.wma_local_result_admission.v2",
        "status": "TERMINAL_ACCEPTED",
        "benchmark_id": EXPECTED_BENCHMARK,
        "track_id": EXPECTED_TRACK,
        "split": EXPECTED_SPLIT,
        "accepted_implementations": sorted(seen),
        "seed_set": [0, 1, 2],
        "metrics_per_seed": len(catalog),
        "rows": len(rows),
        "ledger_sha256": sha256_file(ledger),
        "execution_matrix_sha256": sha256_file(args.execution_matrix),
        "metric_template_sha256": sha256_file(args.metric_template),
        "source_evidence": sorted(sources, key=lambda row: row["implementation_id"]),
        "official_values_used": False,
        "source_reported_results_read": False,
        "admission_rule": "terminal-accepted complete three-seed local aggregates only",
    }
    manifest_path = args.output_root / "admission-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence_files = [ledger, manifest_path]
    (args.output_root / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path}\n" for path in evidence_files),
        encoding="utf-8",
    )
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
