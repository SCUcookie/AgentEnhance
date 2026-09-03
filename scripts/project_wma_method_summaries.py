#!/usr/bin/env python3
"""Project accepted three-seed WMA summaries into every frozen comparison panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


MAIN_METRICS = {
    "qa_correct_ratio": "question_answering.correct_ratio",
    "qa_hallucination_ratio": "question_answering.hallucination_ratio",
    "qa_omission_ratio": "question_answering.omission_ratio",
    "answer_f1": "question_answering.answer_matching.avg_f1",
    "answer_bleu1": "question_answering.answer_matching.avg_bleu1",
    "retrieval_recall_at_10": "question_answering.retrieval_ranking.recall_at.10",
    "retrieval_ndcg_at_10": "question_answering.retrieval_ranking.ndcg_at.10",
    "memory_avg_recall": "memory_recall.avg_recall",
    "memory_avg_correctness": "memory_correctness.avg_correctness",
    "memory_update_handling": "update_handling.score",
    "memory_interference_rejection": "interference_rejection.score",
    "total_tokens": "token_usage.total.total_tokens",
    "end_to_end_seconds": "derived_runtime.end_to_end_seconds",
    "end_to_end_latency_p95_ms": "derived_runtime.end_to_end_latency_p95_ms",
    "memory_storage_bytes": "derived_resources.memory_storage_bytes",
    "peak_ram_gib": "derived_resources.peak_driver_ram_gib",
    "peak_vram_gib": "derived_resources.peak_allocated_vram_gib",
    "gpu_hours": "derived_resources.allocated_gpu_hours",
}

RETRIEVAL_MEMORY_METRICS = {
    "retrieval_hit_rate": "question_answering.retrieval_coverage.hit_rate",
    "retrieval_recall_at_1": "question_answering.retrieval_ranking.recall_at.1",
    "retrieval_recall_at_5": "question_answering.retrieval_ranking.recall_at.5",
    "retrieval_recall_at_10": "question_answering.retrieval_ranking.recall_at.10",
    "retrieval_ndcg_at_1": "question_answering.retrieval_ranking.ndcg_at.1",
    "retrieval_ndcg_at_5": "question_answering.retrieval_ranking.ndcg_at.5",
    "retrieval_ndcg_at_10": "question_answering.retrieval_ranking.ndcg_at.10",
    "retrieval_num_covered": "question_answering.retrieval_coverage.num_covered",
    "retrieval_num_gold": "question_answering.retrieval_coverage.num_total",
    "memory_avg_recall": "memory_recall.avg_recall",
    "memory_avg_weighted_recall": "memory_recall.avg_weighted_recall",
    "memory_pooled_weighted_recall": "memory_recall.pooled_weighted_recall",
    "memory_avg_correctness": "memory_correctness.avg_correctness",
    "memory_avg_hallucination": "memory_correctness.avg_hallucination",
    "memory_avg_irrelevant": "memory_correctness.avg_irrelevant",
    "memory_itemwise_correctness": "memory_accuracy_itemwise.avg_correctness",
    "memory_itemwise_hallucination": "memory_accuracy_itemwise.avg_hallucination",
    "memory_update_handling": "update_handling.score",
    "memory_interference_rejection": "interference_rejection.score",
    "memory_total_memories": "memory_correctness.total_memories",
}

EFFICIENCY_METRICS = {
    "storage_seconds": "runtime.storage_seconds",
    "retrieval_seconds": "runtime.retrieval_seconds",
    "answer_seconds": "runtime.answer_seconds",
    "end_to_end_seconds": "derived_runtime.end_to_end_seconds",
    "retrieval_latency_p50_ms": "derived_runtime.retrieval_latency_p50_ms",
    "retrieval_latency_p95_ms": "derived_runtime.retrieval_latency_p95_ms",
    "end_to_end_latency_p50_ms": "derived_runtime.end_to_end_latency_p50_ms",
    "end_to_end_latency_p95_ms": "derived_runtime.end_to_end_latency_p95_ms",
    "storage_prompt_tokens": "token_usage.storage.prompt_tokens",
    "storage_completion_tokens": "token_usage.storage.completion_tokens",
    "storage_total_tokens": "token_usage.storage.total_tokens",
    "retrieval_prompt_tokens": "token_usage.retrieval.prompt_tokens",
    "retrieval_completion_tokens": "token_usage.retrieval.completion_tokens",
    "retrieval_total_tokens": "token_usage.retrieval.total_tokens",
    "answer_prompt_tokens": "token_usage.answer.prompt_tokens",
    "answer_completion_tokens": "token_usage.answer.completion_tokens",
    "answer_total_tokens": "token_usage.answer.total_tokens",
    "judge_prompt_tokens": "token_usage.judge.prompt_tokens",
    "judge_completion_tokens": "token_usage.judge.completion_tokens",
    "judge_total_tokens": "token_usage.judge.total_tokens",
    "all_prompt_tokens": "token_usage.total.prompt_tokens",
    "all_completion_tokens": "token_usage.total.completion_tokens",
    "all_total_tokens": "token_usage.total.total_tokens",
    "memory_storage_bytes": "derived_resources.memory_storage_bytes",
    "peak_driver_ram_gib": "derived_resources.peak_driver_ram_gib",
    "peak_vram_gib": "derived_resources.peak_allocated_vram_gib",
    "gpu_hours": "derived_resources.allocated_gpu_hours",
}

SLICE_METRICS = {
    "correct_ratio": "correct_ratio",
    "hallucination_ratio": "hallucination_ratio",
    "omission_ratio": "omission_ratio",
    "answer_f1": "answer_f1",
    "answer_bleu1": "answer_bleu1",
    "retrieval_hit_rate": "retrieval_hit_rate",
    "retrieval_recall_at_10": "retrieval_recall_at_10",
    "retrieval_ndcg_at_10": "retrieval_ndcg_at_10",
}

OVERALL_SLICE_METRICS = {
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
    for line in inventory.read_text(encoding="utf-8").splitlines():
        expected, raw_path = line.split(maxsplit=1)
        path = Path(raw_path.lstrip("*"))
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"summary inventory mismatch: {path}")
    return sha256_file(inventory)


def mean_metric(summary: dict[str, Any], key: str) -> float:
    try:
        return float(summary["metrics"][key]["mean"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"missing combined metric: {key}") from exc


def render(value: float | int) -> str:
    return format(value, ".12g")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def project_panel(
    template: Path,
    output: Path,
    accepted: dict[str, dict[str, Any]],
    mapping: dict[str, str],
) -> None:
    fields, rows = read_csv(template)
    matched: set[str] = set()
    for row in rows:
        implementation_id = row["implementation_id"]
        payload = accepted.get(implementation_id)
        if payload is None:
            continue
        matched.add(implementation_id)
        summary = payload["summary"]
        row.update({column: render(mean_metric(summary, key)) for column, key in mapping.items()})
        row.update({
            "run_status": "LOCAL_3SEED_ACCEPTED",
            "n_samples": "150",
            "n_qa": "7906",
            "n_failed": "0",
            "run_id": str(summary["run_id"]),
            "artifact_sha256": payload["artifact_sha256"],
        })
    if matched != set(accepted):
        raise SystemExit(f"accepted implementations absent from {template.name}: {sorted(set(accepted) - matched)}")
    write_csv(output, fields, rows)


def project_slices(
    template: Path,
    output: Path,
    accepted: dict[str, dict[str, Any]],
) -> None:
    fields, rows = read_csv(template)
    matched_counts = {implementation_id: 0 for implementation_id in accepted}
    for row in rows:
        payload = accepted.get(row["implementation_id"])
        if payload is None:
            continue
        matched_counts[row["implementation_id"]] += 1
        summary = payload["summary"]
        slices = payload["slices"]
        if row["slice_family"] == "overall":
            row["n_valid"] = render(mean_metric(summary, "question_answering.num_valid"))
            for column, key in OVERALL_SLICE_METRICS.items():
                row[column] = render(mean_metric(summary, key))
        else:
            prefix = f"{row['slice_family']}.{row['slice_value']}"
            row["n_valid"] = render(mean_metric(slices, f"{prefix}.n_valid"))
            for column, suffix in SLICE_METRICS.items():
                row[column] = render(mean_metric(slices, f"{prefix}.{suffix}"))
        row.update({
            "run_status": "LOCAL_3SEED_ACCEPTED",
            "run_id": str(summary["run_id"]),
            "artifact_sha256": payload["artifact_sha256"],
        })
    if any(count != 53 for count in matched_counts.values()):
        raise SystemExit(f"expected 53 frozen slice rows per accepted implementation: {matched_counts}")
    write_csv(output, fields, rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparisons-root", type=Path, required=True)
    parser.add_argument("--summary-root", type=Path, action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.output_root.exists():
        raise SystemExit(f"refusing existing output root: {args.output_root}")

    accepted: dict[str, dict[str, Any]] = {}
    for root in args.summary_root:
        if not (root / "TERMINAL_ACCEPTED").is_file() or (root / "TERMINAL_REJECTED").exists():
            raise SystemExit(f"summary root is not terminal-accepted: {root}")
        artifact_sha256 = verify_inventory(root)
        summary = json.loads((root / "method-seed-summary.json").read_text(encoding="utf-8"))
        slices = json.loads((root / "slice-seed-summary.json").read_text(encoding="utf-8"))
        if not summary.get("main_comparison_eligible") or summary.get("seed_count") != 3:
            raise SystemExit(f"summary is not three-seed eligible: {root}")
        implementation_id = str(summary["implementation_id"])
        if implementation_id in accepted:
            raise SystemExit(f"duplicate implementation summary: {implementation_id}")
        accepted[implementation_id] = {
            "summary": summary,
            "slices": slices,
            "artifact_sha256": artifact_sha256,
        }

    args.output_root.mkdir(parents=True)
    project_panel(
        args.comparisons_root / "wma-main-table-template.v2.csv",
        args.output_root / "wma-main-table.csv",
        accepted,
        MAIN_METRICS,
    )
    project_panel(
        args.comparisons_root / "wma-retrieval-memory-table-template.v1.csv",
        args.output_root / "wma-retrieval-memory-table.csv",
        accepted,
        RETRIEVAL_MEMORY_METRICS,
    )
    project_panel(
        args.comparisons_root / "wma-efficiency-reliability-table-template.v1.csv",
        args.output_root / "wma-efficiency-reliability-table.csv",
        accepted,
        EFFICIENCY_METRICS,
    )
    project_slices(
        args.comparisons_root / "wma-slice-table-template.v1.csv",
        args.output_root / "wma-slice-table.csv",
        accepted,
    )
    manifest = {
        "schema_version": "agentenhance.wma_projected_table_bundle.v1",
        "status": "TERMINAL_ACCEPTED",
        "accepted_implementations": sorted(accepted),
        "admission": "only terminal-accepted three-seed local summaries",
        "official_values_used": false,
        "files": {},
    }
    for path in sorted(args.output_root.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            row_count = sum(1 for _ in reader)
        manifest["files"][path.name] = {
            "sha256": sha256_file(path),
            "rows": row_count,
            "columns": len(header),
        }
    (args.output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(path for path in args.output_root.iterdir() if path.is_file())
    with (args.output_root / "SHA256SUMS").open("w", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"{sha256_file(path)}  {path}\n")
    (args.output_root / "TERMINAL_ACCEPTED").touch()
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
