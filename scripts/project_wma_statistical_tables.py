#!/usr/bin/env python3
"""Project accepted WMA three-seed summaries into frozen statistical tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


OVERALL_SLICE_KEYS = {
    "correct_ratio": "question_answering.correct_ratio",
    "hallucination_ratio": "question_answering.hallucination_ratio",
    "omission_ratio": "question_answering.omission_ratio",
    "answer_f1": "question_answering.answer_matching.avg_f1",
    "answer_bleu1": "question_answering.answer_matching.avg_bleu1",
    "retrieval_hit_rate": "question_answering.retrieval_coverage.hit_rate",
    "retrieval_recall_at_10": "question_answering.retrieval_ranking.recall_at.10",
    "retrieval_ndcg_at_10": "question_answering.retrieval_ranking.ndcg_at.10",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inventory(root: Path) -> str:
    inventory = root / "SHA256SUMS"
    if not inventory.is_file():
        raise SystemExit(f"missing summary inventory: {inventory}")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_absolute():
            path = root / path
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"summary inventory mismatch: {path}")
    return sha256_file(inventory)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def render(value: Any) -> str:
    return format(float(value), ".12g")


def statistic(payload: dict[str, Any], key: str) -> dict[str, Any]:
    try:
        row = payload["metrics"][key]
        if set(row["seed_values"]) != {"0", "1", "2"}:
            raise KeyError("seed_values")
        return row
    except (KeyError, TypeError) as exc:
        raise SystemExit(f"missing three-seed statistic: {key}") from exc


def load_summaries(roots: list[Path]) -> dict[str, dict[str, Any]]:
    accepted: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"summary root is not terminal-accepted: {root}")
        artifact_sha256 = verify_inventory(root)
        method = json.loads((root / "method-seed-summary.json").read_text(encoding="utf-8"))
        slices = json.loads((root / "slice-seed-summary.json").read_text(encoding="utf-8"))
        if not method.get("main_comparison_eligible") or method.get("seed_count") != 3:
            raise SystemExit(f"summary is not eligible: {root}")
        implementation_id = str(method["implementation_id"])
        if implementation_id in accepted:
            raise SystemExit(f"duplicate summary: {implementation_id}")
        accepted[implementation_id] = {
            "method": method,
            "slices": slices,
            "artifact_sha256": artifact_sha256,
        }
    return accepted


def load_pairwise_results(roots: list[Path]) -> dict[str, dict[str, Any]]:
    accepted: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"pairwise root is not terminal-accepted: {root}")
        artifact_sha256 = verify_inventory(root)
        result_path = root / "pairwise-result.json"
        audit = json.loads((root / "audit.json").read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if (
            audit.get("status") != "TERMINAL_ACCEPTED"
            or audit.get("result_sha256") != sha256_file(result_path)
            or result.get("status") != "TERMINAL_ACCEPTED"
            or result.get("implementation_a") != "agentenhance-ceu"
            or result.get("difference_orientation") != "a_minus_b"
            or result.get("seed_set") != [0, 1, 2]
            or result.get("paired_clusters") != 150
            or result.get("official_values_used") is not False
            or result.get("bootstrap", {}).get("resamples") != 10000
            or result.get("bootstrap", {}).get("seed") != 20260903
        ):
            raise SystemExit(f"ineligible pairwise result: {root}")
        implementation_b = str(result["implementation_b"])
        if implementation_b in accepted:
            raise SystemExit(f"duplicate pairwise result: {implementation_b}")
        rows = result.get("rows", [])
        if len(rows) != 55 or len({row.get("metric_key") for row in rows}) != 55:
            raise SystemExit(f"pairwise result metric surface mismatch: {root}")
        paired = [row for row in rows if row.get("analysis_unit") == "paired_original_sample_cluster"]
        descriptive = [row for row in rows if row.get("analysis_unit") == "seed_level_descriptive"]
        if len(paired) != 23 or len(descriptive) != 32:
            raise SystemExit(f"pairwise result analysis-unit mismatch: {root}")
        for row in paired:
            low = float(row["ci95_low"])
            point = float(row["point_difference"])
            high = float(row["ci95_high"])
            if (
                not all(math.isfinite(value) for value in (low, point, high))
                or low > high
                or row.get("direction") not in {"higher", "lower"}
            ):
                raise SystemExit(f"invalid paired confidence interval: {row.get('metric_key')}")
            expected = low > 0 if row["direction"] == "higher" else high < 0
            if row.get("superiority_supported") is not expected:
                raise SystemExit(f"invalid superiority decision: {row.get('metric_key')}")
        if any(
            row.get("ci95_low") is not None
            or row.get("ci95_high") is not None
            or row.get("superiority_supported") is not None
            for row in descriptive
        ):
            raise SystemExit(f"descriptive row contains inferential fields: {root}")
        accepted[implementation_b] = {
            "result": result,
            "artifact_sha256": artifact_sha256,
            "rows": {row["metric_key"]: row for row in rows},
        }
    return accepted


def fill_stat_fields(row: dict[str, str], stats: dict[str, Any]) -> None:
    row["seed_count"] = "3"
    row["mean"] = render(stats["mean"])
    row["sample_standard_deviation"] = render(stats["sample_standard_deviation"])
    row["seed_0"] = render(stats["seed_values"]["0"])
    row["seed_1"] = render(stats["seed_values"]["1"])
    row["seed_2"] = render(stats["seed_values"]["2"])


def project_methods(
    template: Path,
    output: Path,
    accepted: dict[str, dict[str, Any]],
) -> None:
    fields, rows = read_csv(template)
    matched: set[str] = set()
    for row in rows:
        payload = accepted.get(row["implementation_id"])
        if payload is None:
            continue
        matched.add(row["implementation_id"])
        method = payload["method"]
        fill_stat_fields(row, statistic(method, row["metric_key"]))
        row.update(
            {
                "run_status": "LOCAL_3SEED_ACCEPTED",
                "n_samples": str(method["n_samples"]),
                "n_qa": str(method["n_qa"]),
                "run_id": str(method["run_id"]),
                "artifact_sha256": payload["artifact_sha256"],
            }
        )
    if matched != set(accepted):
        raise SystemExit(f"accepted methods absent from statistics template: {sorted(set(accepted) - matched)}")
    write_csv(output, fields, rows)


def project_slices(
    template: Path,
    output: Path,
    accepted: dict[str, dict[str, Any]],
) -> None:
    fields, rows = read_csv(template)
    counts = {implementation_id: 0 for implementation_id in accepted}
    for row in rows:
        payload = accepted.get(row["implementation_id"])
        if payload is None:
            continue
        counts[row["implementation_id"]] += 1
        if row["slice_family"] == "overall":
            key = OVERALL_SLICE_KEYS[row["metric_key"]]
            stats = statistic(payload["method"], key)
        else:
            key = f"{row['slice_family']}.{row['slice_value']}.{row['metric_key']}"
            stats = statistic(payload["slices"], key)
        fill_stat_fields(row, stats)
        row.update(
            {
                "run_status": "LOCAL_3SEED_ACCEPTED",
                "run_id": str(payload["method"]["run_id"]),
                "artifact_sha256": payload["artifact_sha256"],
            }
        )
    if any(count != 53 * 8 for count in counts.values()):
        raise SystemExit(f"expected 424 slice-metric rows per accepted method: {counts}")
    write_csv(output, fields, rows)


def project_pairwise(
    template: Path,
    output: Path,
    pairwise: dict[str, dict[str, Any]],
    accepted_methods: set[str],
) -> None:
    fields, rows = read_csv(template)
    counts = {implementation_id: 0 for implementation_id in pairwise}
    for implementation_b, payload in pairwise.items():
        if {"agentenhance-ceu", implementation_b} - accepted_methods:
            raise SystemExit(
                f"pairwise result requires both method summaries in the same projection: {implementation_b}"
            )
        result = payload["result"]
        for row in rows:
            if row["implementation_b"] != implementation_b:
                continue
            counts[implementation_b] += 1
            metric = payload["rows"].get(row["metric_key"])
            if metric is None:
                raise SystemExit(f"missing pairwise metric: {implementation_b}:{row['metric_key']}")
            if (
                metric["analysis_unit"] != row["analysis_unit"]
                or metric["direction"] != row["direction"]
            ):
                raise SystemExit(f"pairwise template mismatch: {implementation_b}:{row['metric_key']}")
            row.update(
                {
                    "run_status": "LOCAL_PAIRWISE_ACCEPTED",
                    "seed_count_a": "3",
                    "seed_count_b": "3",
                    "point_difference": str(metric["point_difference"]),
                    "run_id_a": str(result["run_id_a"]),
                    "run_id_b": str(result["run_id_b"]),
                    "artifact_sha256": payload["artifact_sha256"],
                }
            )
            if row["analysis_unit"] == "paired_original_sample_cluster":
                row.update(
                    {
                        "paired_clusters": "150",
                        "ci95_low": str(metric["ci95_low"]),
                        "ci95_high": str(metric["ci95_high"]),
                        "bootstrap_resamples": "10000",
                        "bootstrap_seed": "20260903",
                        "superiority_supported": str(metric["superiority_supported"]).lower(),
                    }
                )
    if any(count != 55 for count in counts.values()):
        raise SystemExit(f"expected 55 rows per pairwise result: {counts}")
    write_csv(output, fields, rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparisons-root", type=Path, required=True)
    parser.add_argument("--summary-root", type=Path, action="append", default=[])
    parser.add_argument("--pairwise-result-root", type=Path, action="append", default=[])
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.output_root.exists():
        raise SystemExit(f"refusing existing output root: {args.output_root}")

    accepted = load_summaries(args.summary_root)
    pairwise = load_pairwise_results(args.pairwise_result_root)
    args.output_root.mkdir(parents=True)
    project_methods(
        args.comparisons_root / "wma-method-seed-statistics-template.v1.csv",
        args.output_root / "wma-method-seed-statistics.csv",
        accepted,
    )
    project_slices(
        args.comparisons_root / "wma-slice-seed-statistics-template.v1.csv",
        args.output_root / "wma-slice-seed-statistics.csv",
        accepted,
    )
    project_pairwise(
        args.comparisons_root / "wma-agentenhance-pairwise-template.v1.csv",
        args.output_root / "wma-agentenhance-pairwise.csv",
        pairwise,
        set(accepted),
    )

    output_manifest = {
        "schema_version": "agentenhance.wma_projected_statistical_tables.v1",
        "status": "TERMINAL_ACCEPTED",
        "accepted_implementations": sorted(accepted),
        "official_values_used": False,
        "accepted_pairwise_comparators": sorted(pairwise),
        "pairwise_status": (
            "PARTIALLY_OR_FULLY_PROJECTED_FROM_LOCAL_PAIRED_RESULTS"
            if pairwise
            else "LOCKED_UNTIL_AGENTENHANCE_AND_COMPARATOR_ACCEPTED"
        ),
        "files": {},
    }
    for path in sorted(args.output_root.glob("*.csv")):
        fields, rows = read_csv(path)
        output_manifest["files"][path.name] = {
            "sha256": sha256_file(path),
            "rows": len(rows),
            "columns": len(fields),
        }
    manifest_path = args.output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(output_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(path for path in args.output_root.iterdir() if path.is_file())
    with (args.output_root / "SHA256SUMS").open("w", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"{sha256_file(path)}  {path}\n")
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(output_manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
