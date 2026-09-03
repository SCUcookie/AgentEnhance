#!/usr/bin/env python3
"""Materialize pre-result WMA seed-variability and paired-comparison tables."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
from typing import Any


METHOD_FIELDS = [
    "implementation_id",
    "display_name",
    "run_status",
    "metric_key",
    "panels",
    "direction",
    "analysis_unit",
    "seed_count",
    "mean",
    "sample_standard_deviation",
    "seed_0",
    "seed_1",
    "seed_2",
    "n_samples",
    "n_qa",
    "run_id",
    "artifact_sha256",
]

PAIRWISE_FIELDS = [
    "implementation_a",
    "display_name_a",
    "implementation_b",
    "display_name_b",
    "run_status",
    "metric_key",
    "direction",
    "difference_orientation",
    "analysis_unit",
    "seed_count_a",
    "seed_count_b",
    "paired_clusters",
    "point_difference",
    "ci95_low",
    "ci95_high",
    "bootstrap_resamples",
    "bootstrap_seed",
    "superiority_supported",
    "run_id_a",
    "run_id_b",
    "artifact_sha256",
]

SLICE_FIELDS = [
    "implementation_id",
    "display_name",
    "run_status",
    "slice_family",
    "slice_value",
    "n_expected",
    "metric_key",
    "direction",
    "analysis_unit",
    "seed_count",
    "mean",
    "sample_standard_deviation",
    "seed_0",
    "seed_1",
    "seed_2",
    "run_id",
    "artifact_sha256",
]

EXTRA_METRICS = {
    "question_answering.notmention_when_retrieved_ratio": "quality",
    "question_answering.num_valid": "reliability",
    "timing.total_seconds": "efficiency",
}


def load_projection_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("wma_projection", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import projection module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metric_registry(module: Any) -> list[dict[str, str]]:
    panels: dict[str, set[str]] = {}
    for panel, mapping in (
        ("main", module.MAIN_METRICS),
        ("retrieval_memory", module.RETRIEVAL_MEMORY_METRICS),
        ("efficiency_reliability", module.EFFICIENCY_METRICS),
    ):
        for key in mapping.values():
            panels.setdefault(key, set()).add(panel)
    for key, panel in EXTRA_METRICS.items():
        panels.setdefault(key, set()).add(panel)

    lower_tokens = (
        "hallucination",
        "omission",
        "irrelevant",
        "notmention",
        "seconds",
        "latency",
        "tokens",
        "storage_bytes",
        "ram_gib",
        "vram_gib",
        "gpu_hours",
        "num_failed",
        "failure_rate",
    )
    neutral_tokens = ("num_valid", "num_covered", "num_total", "total_memories")
    rows = []
    for key in sorted(panels):
        if any(token in key for token in neutral_tokens):
            direction = "descriptive"
        elif any(token in key for token in lower_tokens):
            direction = "lower"
        else:
            direction = "higher"
        if (
            direction == "descriptive"
            or key.startswith("derived_resources.")
            or key.startswith("derived_runtime.")
            or key.startswith("runtime.")
            or key.startswith("timing.")
            or key.startswith("token_usage.")
        ):
            pairwise_analysis_unit = "seed_level_descriptive"
        else:
            pairwise_analysis_unit = "paired_original_sample_cluster"
        rows.append(
            {
                "metric_key": key,
                "panels": "+".join(sorted(panels[key])),
                "direction": direction,
                "pairwise_analysis_unit": pairwise_analysis_unit,
            }
        )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    if path.exists():
        raise SystemExit(f"refusing existing output: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-matrix", type=Path, required=True)
    parser.add_argument("--slice-template", type=Path, required=True)
    parser.add_argument("--projection-script", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.execution_matrix.open(encoding="utf-8", newline="") as handle:
        methods = list(csv.DictReader(handle))
    with args.slice_template.open(encoding="utf-8", newline="") as handle:
        slices = list(csv.DictReader(handle))
    module = load_projection_module(args.projection_script)
    metrics = metric_registry(module)

    method_rows = []
    for method in methods:
        for metric in metrics:
            method_rows.append(
                {
                    "implementation_id": method["implementation_id"],
                    "display_name": method["display_name"],
                    "run_status": (
                        "LOCKED_UNTIL_BASELINES_ACCEPTED"
                        if method["implementation_id"] == "agentenhance-ceu"
                        else "PENDING"
                    ),
                    "metric_key": metric["metric_key"],
                    "panels": metric["panels"],
                    "direction": metric["direction"],
                    "analysis_unit": "model_seed",
                }
            )

    proposed = next(row for row in methods if row["implementation_id"] == "agentenhance-ceu")
    pairwise_rows = []
    for comparator in methods:
        if comparator["implementation_id"] == proposed["implementation_id"]:
            continue
        for metric in metrics:
            pairwise_rows.append(
                {
                    "implementation_a": proposed["implementation_id"],
                    "display_name_a": proposed["display_name"],
                    "implementation_b": comparator["implementation_id"],
                    "display_name_b": comparator["display_name"],
                    "run_status": "LOCKED_UNTIL_BOTH_METHODS_ACCEPTED",
                    "metric_key": metric["metric_key"],
                    "direction": metric["direction"],
                    "difference_orientation": "a_minus_b",
                    "analysis_unit": metric["pairwise_analysis_unit"],
                    "bootstrap_resamples": (
                        10000
                        if metric["pairwise_analysis_unit"] == "paired_original_sample_cluster"
                        else ""
                    ),
                    "bootstrap_seed": (
                        20260903
                        if metric["pairwise_analysis_unit"] == "paired_original_sample_cluster"
                        else ""
                    ),
                }
            )

    slice_metric_directions = {
        "correct_ratio": "higher",
        "hallucination_ratio": "lower",
        "omission_ratio": "lower",
        "answer_f1": "higher",
        "answer_bleu1": "higher",
        "retrieval_hit_rate": "higher",
        "retrieval_recall_at_10": "higher",
        "retrieval_ndcg_at_10": "higher",
    }
    slice_rows = []
    for row in slices:
        for metric_key, direction in slice_metric_directions.items():
            slice_rows.append(
                {
                    "implementation_id": row["implementation_id"],
                    "display_name": row["display_name"],
                    "run_status": row["run_status"],
                    "slice_family": row["slice_family"],
                    "slice_value": row["slice_value"],
                    "n_expected": row["n_expected"],
                    "metric_key": metric_key,
                    "direction": direction,
                    "analysis_unit": "model_seed",
                }
            )

    write_csv(
        args.output_dir / "wma-method-seed-statistics-template.v1.csv",
        METHOD_FIELDS,
        method_rows,
    )
    write_csv(
        args.output_dir / "wma-agentenhance-pairwise-template.v1.csv",
        PAIRWISE_FIELDS,
        pairwise_rows,
    )
    write_csv(
        args.output_dir / "wma-slice-seed-statistics-template.v1.csv",
        SLICE_FIELDS,
        slice_rows,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "methods": len(methods),
                "metrics": len(metrics),
                "method_rows": len(method_rows),
                "pairwise_rows": len(pairwise_rows),
                "slice_rows": len(slice_rows),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
