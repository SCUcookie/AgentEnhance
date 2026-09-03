#!/usr/bin/env python3
"""Compute one frozen AgentEnhance WMA pairwise comparison from accepted runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from wma_pairwise_sufficient_stats import PAIRED_METRIC_KEYS, RatioStat, group_sample_stats


EXPECTED_SEEDS = {0, 1, 2}
EXPECTED_SAMPLES = 150
EXPECTED_QA = 7906
FROZEN_RESAMPLES = 10_000
FROZEN_BOOTSTRAP_SEED = 20_260_903


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise SystemExit(f"missing inventory: {inventory}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        raw_path = raw_path.lstrip("*")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.is_file() or sha256_file(candidate) != expected:
            raise SystemExit(f"inventory mismatch: {candidate}")
    return sha256_file(inventory)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SystemExit(f"missing record file: {path}")
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


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


def load_summary(root: Path, implementation_id: str) -> dict[str, Any]:
    if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
        raise SystemExit(f"summary root is not terminal-accepted: {root}")
    inventory_sha256 = verify_inventory(root)
    summary = json.loads((root / "method-seed-summary.json").read_text(encoding="utf-8"))
    if (
        summary.get("status") != "TERMINAL_ACCEPTED"
        or not summary.get("main_comparison_eligible")
        or summary.get("implementation_id") != implementation_id
        or summary.get("seed_count") != 3
        or set(summary.get("seeds", [])) != EXPECTED_SEEDS
        or summary.get("n_samples") != EXPECTED_SAMPLES
        or summary.get("n_qa") != EXPECTED_QA
    ):
        raise SystemExit(f"ineligible summary: {root}")
    return {"payload": summary, "inventory_sha256": inventory_sha256}


def load_aggregate_roots(
    roots: list[Path], implementation_id: str, summary: dict[str, Any]
) -> dict[int, dict[str, Any]]:
    if len(roots) != 3:
        raise SystemExit(f"exactly three aggregate roots required for {implementation_id}")
    expected_evidence = {
        int(row["seed"]): row["artifact_inventory_sha256"]
        for row in summary["payload"]["source_evidence"]
    }
    loaded: dict[int, dict[str, Any]] = {}
    for root in roots:
        if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"aggregate root is not terminal-accepted: {root}")
        inventory_sha256 = verify_inventory(root)
        audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
        if (
            audit.get("status") != "TERMINAL_ACCEPTED"
            or not audit.get("main_comparison_eligible")
            or (audit.get("n_observed"), audit.get("n_failed"), audit.get("n_qa"))
            != (EXPECTED_SAMPLES, 0, EXPECTED_QA)
        ):
            raise SystemExit(f"ineligible aggregate: {root}")
        seed = int(audit["seed"])
        if seed in loaded:
            raise SystemExit(f"duplicate seed for {implementation_id}: {seed}")
        if expected_evidence.get(seed) != inventory_sha256:
            raise SystemExit(f"summary-to-aggregate inventory mismatch: {root}")
        qa_records = read_jsonl(root / "qa_records.jsonl")
        session_records = read_jsonl(root / "session_records.jsonl")
        sample_stats = group_sample_stats(qa_records, session_records)
        aggregate = flatten_numeric(
            json.loads((root / "aggregate_metrics.json").read_text(encoding="utf-8"))
        )
        for metric in PAIRED_METRIC_KEYS:
            pooled = RatioStat(
                sum(row[metric].numerator for row in sample_stats.values()),
                sum(row[metric].denominator for row in sample_stats.values()),
            ).value
            if not math.isclose(pooled, aggregate[metric], rel_tol=1e-12, abs_tol=1e-12):
                raise SystemExit(
                    f"raw-to-aggregate mismatch: {implementation_id} seed={seed} "
                    f"metric={metric} raw={pooled} aggregate={aggregate[metric]}"
                )
        loaded[seed] = {
            "audit": audit,
            "inventory_sha256": inventory_sha256,
            "sample_stats": sample_stats,
        }
    if set(loaded) != EXPECTED_SEEDS:
        raise SystemExit(f"seed set mismatch for {implementation_id}: {sorted(loaded)}")
    return loaded


def paired_bootstrap(
    stats_a: dict[int, dict[str, dict[str, RatioStat]]],
    stats_b: dict[int, dict[str, dict[str, RatioStat]]],
    sample_ids: list[str],
    *,
    resamples: int,
    bootstrap_seed: int,
) -> dict[str, dict[str, float]]:
    """Return A-B estimates; every draw keeps all records within a sample together."""
    n_samples = len(sample_ids)
    probabilities = np.full(n_samples, 1.0 / n_samples, dtype=np.float64)
    weights = np.random.default_rng(bootstrap_seed).multinomial(
        n_samples, probabilities, size=resamples
    )
    methods = (stats_a, stats_b)
    numerators = np.empty((2, 3, len(PAIRED_METRIC_KEYS), n_samples), dtype=np.float64)
    denominators = np.empty_like(numerators)
    for method_index, method_stats in enumerate(methods):
        for seed in sorted(EXPECTED_SEEDS):
            for metric_index, metric in enumerate(PAIRED_METRIC_KEYS):
                numerators[method_index, seed, metric_index] = [
                    method_stats[seed][sample_id][metric].numerator for sample_id in sample_ids
                ]
                denominators[method_index, seed, metric_index] = [
                    method_stats[seed][sample_id][metric].denominator for sample_id in sample_ids
                ]
    flat_num = numerators.reshape(-1, n_samples)
    flat_den = denominators.reshape(-1, n_samples)
    bootstrap_num = weights @ flat_num.T
    bootstrap_den = weights @ flat_den.T
    bootstrap_values = np.divide(
        bootstrap_num,
        bootstrap_den,
        out=np.zeros_like(bootstrap_num),
        where=bootstrap_den != 0,
    ).reshape(resamples, 2, 3, len(PAIRED_METRIC_KEYS))
    differences = bootstrap_values[:, 0].mean(axis=1) - bootstrap_values[:, 1].mean(axis=1)

    point_values = np.divide(
        flat_num.sum(axis=1),
        flat_den.sum(axis=1),
        out=np.zeros(flat_num.shape[0], dtype=np.float64),
        where=flat_den.sum(axis=1) != 0,
    ).reshape(2, 3, len(PAIRED_METRIC_KEYS))
    point_differences = point_values[0].mean(axis=0) - point_values[1].mean(axis=0)
    intervals = np.quantile(differences, (0.025, 0.975), axis=0, method="linear")
    return {
        metric: {
            "point_difference": float(point_differences[index]),
            "ci95_low": float(intervals[0, index]),
            "ci95_high": float(intervals[1, index]),
        }
        for index, metric in enumerate(PAIRED_METRIC_KEYS)
    }


def template_rows(path: Path, implementation_a: str, implementation_b: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["implementation_a"] == implementation_a
            and row["implementation_b"] == implementation_b
        ]
    if len(rows) != 55 or len({row["metric_key"] for row in rows}) != 55:
        raise SystemExit("pairwise template must contain exactly 55 unique rows for the requested pair")
    paired = {row["metric_key"] for row in rows if row["analysis_unit"] == "paired_original_sample_cluster"}
    if paired != set(PAIRED_METRIC_KEYS):
        raise SystemExit("paired metric surface differs from sufficient-stat implementation")
    return rows


def summary_mean(summary: dict[str, Any], metric: str) -> float:
    try:
        return float(summary["payload"]["metrics"][metric]["mean"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"missing summary mean: {metric}") from exc


def evidence_digest(*inventories: str) -> str:
    payload = json.dumps(sorted(inventories), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render(value: float) -> str:
    return format(value, ".12g")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairwise-template", type=Path, required=True)
    parser.add_argument("--implementation-a", required=True)
    parser.add_argument("--summary-root-a", type=Path, required=True)
    parser.add_argument("--aggregate-root-a", type=Path, action="append", required=True)
    parser.add_argument("--implementation-b", required=True)
    parser.add_argument("--summary-root-b", type=Path, required=True)
    parser.add_argument("--aggregate-root-b", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.implementation_a != "agentenhance-ceu":
        raise SystemExit("implementation A must be frozen as agentenhance-ceu")
    if args.output_root.exists():
        raise SystemExit(f"refusing existing output root: {args.output_root}")

    rows = template_rows(args.pairwise_template, args.implementation_a, args.implementation_b)
    summary_a = load_summary(args.summary_root_a, args.implementation_a)
    summary_b = load_summary(args.summary_root_b, args.implementation_b)
    aggregates_a = load_aggregate_roots(args.aggregate_root_a, args.implementation_a, summary_a)
    aggregates_b = load_aggregate_roots(args.aggregate_root_b, args.implementation_b, summary_b)
    provenance = [row["audit"] for row in aggregates_a.values()] + [
        row["audit"] for row in aggregates_b.values()
    ]
    if len({row.get("source_commit") for row in provenance}) != 1:
        raise SystemExit("source commit differs across paired runs")
    if len({row.get("dataset_manifest_sha256") for row in provenance}) != 1:
        raise SystemExit("dataset manifest differs across paired runs")
    sample_sets = [set(row["sample_stats"]) for row in aggregates_a.values()] + [
        set(row["sample_stats"]) for row in aggregates_b.values()
    ]
    if any(samples != sample_sets[0] for samples in sample_sets[1:]):
        raise SystemExit("sample identities differ across paired runs")
    sample_ids = sorted(sample_sets[0])
    if len(sample_ids) != EXPECTED_SAMPLES:
        raise SystemExit(f"expected {EXPECTED_SAMPLES} paired samples, found {len(sample_ids)}")

    paired = paired_bootstrap(
        {seed: row["sample_stats"] for seed, row in aggregates_a.items()},
        {seed: row["sample_stats"] for seed, row in aggregates_b.items()},
        sample_ids,
        resamples=FROZEN_RESAMPLES,
        bootstrap_seed=FROZEN_BOOTSTRAP_SEED,
    )
    output_rows: list[dict[str, Any]] = []
    for row in rows:
        metric = row["metric_key"]
        if row["analysis_unit"] == "paired_original_sample_cluster":
            values = paired[metric]
            direction = row["direction"]
            superiority = (
                values["ci95_low"] > 0 if direction == "higher" else values["ci95_high"] < 0
            )
            output_rows.append({
                "metric_key": metric,
                "analysis_unit": row["analysis_unit"],
                "direction": direction,
                "point_difference": render(values["point_difference"]),
                "ci95_low": render(values["ci95_low"]),
                "ci95_high": render(values["ci95_high"]),
                "superiority_supported": superiority,
            })
        else:
            output_rows.append({
                "metric_key": metric,
                "analysis_unit": "seed_level_descriptive",
                "direction": row["direction"],
                "point_difference": render(summary_mean(summary_a, metric) - summary_mean(summary_b, metric)),
                "ci95_low": None,
                "ci95_high": None,
                "superiority_supported": None,
            })

    inventories = [summary_a["inventory_sha256"], summary_b["inventory_sha256"]] + [
        row["inventory_sha256"] for row in aggregates_a.values()
    ] + [row["inventory_sha256"] for row in aggregates_b.values()]
    result = {
        "schema_version": "agentenhance.wma_pairwise_result.v1",
        "status": "TERMINAL_ACCEPTED",
        "implementation_a": args.implementation_a,
        "implementation_b": args.implementation_b,
        "difference_orientation": "a_minus_b",
        "seed_set": [0, 1, 2],
        "paired_clusters": EXPECTED_SAMPLES,
        "bootstrap": {
            "method": "two-sided percentile paired original-sample cluster bootstrap",
            "rng": "numpy.random.Generator(PCG64)",
            "resamples": FROZEN_RESAMPLES,
            "seed": FROZEN_BOOTSTRAP_SEED,
        },
        "official_values_used": False,
        "evidence_digest": evidence_digest(*inventories),
        "source_commit": provenance[0]["source_commit"],
        "dataset_manifest_sha256": provenance[0]["dataset_manifest_sha256"],
        "run_id_a": summary_a["payload"]["run_id"],
        "run_id_b": summary_b["payload"]["run_id"],
        "rows": output_rows,
    }
    args.output_root.mkdir(parents=True)
    result_path = args.output_root / "pairwise-result.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit = {
        "schema_version": "agentenhance.wma_pairwise_audit.v1",
        "status": "TERMINAL_ACCEPTED",
        "paired_metric_count": len(PAIRED_METRIC_KEYS),
        "descriptive_metric_count": 55 - len(PAIRED_METRIC_KEYS),
        "raw_to_aggregate_checks": 2 * 3 * len(PAIRED_METRIC_KEYS),
        "post_result_metric_selection": "none",
        "result_sha256": sha256_file(result_path),
    }
    audit_path = args.output_root / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (args.output_root / "SHA256SUMS").open("w", encoding="utf-8") as handle:
        for path in (audit_path, result_path):
            handle.write(f"{sha256_file(path)}  {path.name}\n")
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(audit, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
