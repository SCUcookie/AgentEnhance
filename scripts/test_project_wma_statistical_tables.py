#!/usr/bin/env python3
"""Synthetic acceptance test for WMA statistical-table projection."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("statistics_projection", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stats(value: float) -> dict[str, object]:
    return {
        "mean": value + 1.0,
        "sample_standard_deviation": 1.0,
        "seed_values": {"0": value, "1": value + 1.0, "2": value + 2.0},
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    module = load_module(ROOT / "scripts/project_wma_statistical_tables.py")
    with tempfile.TemporaryDirectory(prefix="wma_stats_projection_") as raw:
        temp = Path(raw)
        summary_root = temp / "summary"
        output_root = temp / "output"
        summary_root.mkdir()

        with (ROOT / "comparisons/wma-method-seed-statistics-template.v1.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            method_rows = [
                row for row in csv.DictReader(handle) if row["implementation_id"] == "wma-dummy"
            ]
        method_metrics = {row["metric_key"]: stats(index) for index, row in enumerate(method_rows)}

        with (ROOT / "comparisons/wma-slice-seed-statistics-template.v1.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            slice_rows = [
                row for row in csv.DictReader(handle) if row["implementation_id"] == "wma-dummy"
            ]
        slice_metrics = {}
        index = 0
        for row in slice_rows:
            if row["slice_family"] == "overall":
                continue
            key = f"{row['slice_family']}.{row['slice_value']}.{row['metric_key']}"
            slice_metrics[key] = stats(index)
            index += 1

        method_payload = {
            "status": "TERMINAL_ACCEPTED",
            "main_comparison_eligible": True,
            "implementation_id": "wma-dummy",
            "run_id": "synthetic-three-seed-v1",
            "seed_count": 3,
            "n_samples": 150,
            "n_qa": 7906,
            "metrics": method_metrics,
        }
        slice_payload = {
            "implementation_id": "wma-dummy",
            "run_id": "synthetic-three-seed-v1",
            "seed_count": 3,
            "metrics": slice_metrics,
        }
        method_path = summary_root / "method-seed-summary.json"
        slice_path = summary_root / "slice-seed-summary.json"
        method_path.write_text(json.dumps(method_payload), encoding="utf-8")
        slice_path.write_text(json.dumps(slice_payload), encoding="utf-8")
        inventory = summary_root / "SHA256SUMS"
        inventory.write_text(
            f"{sha256_file(method_path)}  {method_path}\n"
            f"{sha256_file(slice_path)}  {slice_path}\n",
            encoding="utf-8",
        )
        (summary_root / "TERMINAL_ACCEPTED").touch()

        accepted = module.load_summaries([summary_root])
        output_root.mkdir()
        module.project_methods(
            ROOT / "comparisons/wma-method-seed-statistics-template.v1.csv",
            output_root / "method.csv",
            accepted,
        )
        module.project_slices(
            ROOT / "comparisons/wma-slice-seed-statistics-template.v1.csv",
            output_root / "slice.csv",
            accepted,
        )

        pairwise_root = temp / "pairwise"
        pairwise_root.mkdir()
        with (ROOT / "comparisons/wma-agentenhance-pairwise-template.v1.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            template_pair_rows = [
                row
                for row in csv.DictReader(handle)
                if row["implementation_b"] == "wma-dummy"
            ]
        result_rows = []
        for index, row in enumerate(template_pair_rows):
            paired = row["analysis_unit"] == "paired_original_sample_cluster"
            point = 0.25 if row["direction"] == "higher" else -0.25
            result_rows.append(
                {
                    "metric_key": row["metric_key"],
                    "analysis_unit": row["analysis_unit"],
                    "direction": row["direction"],
                    "point_difference": format(point, ".12g"),
                    "ci95_low": format(point - 0.05, ".12g") if paired else None,
                    "ci95_high": format(point + 0.05, ".12g") if paired else None,
                    "superiority_supported": True if paired else None,
                }
            )
        pairwise_payload = {
            "status": "TERMINAL_ACCEPTED",
            "implementation_a": "agentenhance-ceu",
            "implementation_b": "wma-dummy",
            "difference_orientation": "a_minus_b",
            "seed_set": [0, 1, 2],
            "paired_clusters": 150,
            "official_values_used": False,
            "bootstrap": {"resamples": 10000, "seed": 20260903},
            "run_id_a": "synthetic-agentenhance-v1",
            "run_id_b": "synthetic-dummy-v1",
            "rows": result_rows,
        }
        pair_result_path = pairwise_root / "pairwise-result.json"
        pair_result_path.write_text(json.dumps(pairwise_payload), encoding="utf-8")
        pair_audit_path = pairwise_root / "audit.json"
        pair_audit_path.write_text(
            json.dumps(
                {
                    "status": "TERMINAL_ACCEPTED",
                    "result_sha256": sha256_file(pair_result_path),
                }
            ),
            encoding="utf-8",
        )
        pair_inventory = pairwise_root / "SHA256SUMS"
        pair_inventory.write_text(
            f"{sha256_file(pair_audit_path)}  audit.json\n"
            f"{sha256_file(pair_result_path)}  pairwise-result.json\n",
            encoding="utf-8",
        )
        (pairwise_root / "TERMINAL_ACCEPTED").touch()
        loaded_pairwise = module.load_pairwise_results([pairwise_root])
        module.project_pairwise(
            ROOT / "comparisons/wma-agentenhance-pairwise-template.v1.csv",
            output_root / "pairwise.csv",
            loaded_pairwise,
            {"agentenhance-ceu", "wma-dummy"},
        )

        with (output_root / "method.csv").open(encoding="utf-8", newline="") as handle:
            projected_methods = [
                row for row in csv.DictReader(handle) if row["implementation_id"] == "wma-dummy"
            ]
        with (output_root / "slice.csv").open(encoding="utf-8", newline="") as handle:
            projected_slices = [
                row for row in csv.DictReader(handle) if row["implementation_id"] == "wma-dummy"
            ]
        with (output_root / "pairwise.csv").open(encoding="utf-8", newline="") as handle:
            projected_pairs = [
                row for row in csv.DictReader(handle) if row["implementation_b"] == "wma-dummy"
            ]
        assert len(projected_methods) == 55
        assert len(projected_slices) == 53 * 8
        assert all(row["run_status"] == "LOCAL_3SEED_ACCEPTED" for row in projected_methods)
        assert all(row["seed_count"] == "3" for row in projected_methods + projected_slices)
        assert all(row["mean"] and row["sample_standard_deviation"] for row in projected_methods)
        assert all(row["mean"] and row["sample_standard_deviation"] for row in projected_slices)
        assert len(projected_pairs) == 55
        assert all(row["run_status"] == "LOCAL_PAIRWISE_ACCEPTED" for row in projected_pairs)
        assert all(row["point_difference"] for row in projected_pairs)
        paired_rows = [
            row for row in projected_pairs if row["analysis_unit"] == "paired_original_sample_cluster"
        ]
        descriptive_rows = [
            row for row in projected_pairs if row["analysis_unit"] == "seed_level_descriptive"
        ]
        assert len(paired_rows) == 23 and len(descriptive_rows) == 32
        assert all(row["ci95_low"] and row["ci95_high"] for row in paired_rows)
        assert all(not row["ci95_low"] and not row["ci95_high"] for row in descriptive_rows)
    print("synthetic-statistical-projection=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
