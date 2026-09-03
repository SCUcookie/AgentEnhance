#!/usr/bin/env python3
"""Materialize v2 result-free WMA panels with explicit blocked-row status."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


RETRIEVAL_MEMORY_FIELDS = [
    "implementation_id", "display_name", "run_status", "n_samples", "n_qa",
    "retrieval_hit_rate", "retrieval_recall_at_1", "retrieval_recall_at_5",
    "retrieval_recall_at_10", "retrieval_ndcg_at_1", "retrieval_ndcg_at_5",
    "retrieval_ndcg_at_10", "retrieval_num_covered", "retrieval_num_gold",
    "memory_avg_recall", "memory_avg_weighted_recall", "memory_pooled_weighted_recall",
    "memory_avg_correctness", "memory_avg_hallucination", "memory_avg_irrelevant",
    "memory_itemwise_correctness", "memory_itemwise_hallucination",
    "memory_update_handling", "memory_interference_rejection", "memory_total_memories",
    "n_failed", "run_id", "artifact_sha256",
]

EFFICIENCY_FIELDS = [
    "implementation_id", "display_name", "run_status", "n_samples", "n_qa",
    "storage_seconds", "retrieval_seconds", "answer_seconds", "end_to_end_seconds",
    "retrieval_latency_p50_ms", "retrieval_latency_p95_ms",
    "end_to_end_latency_p50_ms", "end_to_end_latency_p95_ms",
    "storage_prompt_tokens", "storage_completion_tokens", "storage_total_tokens",
    "retrieval_prompt_tokens", "retrieval_completion_tokens", "retrieval_total_tokens",
    "answer_prompt_tokens", "answer_completion_tokens", "answer_total_tokens",
    "judge_prompt_tokens", "judge_completion_tokens", "judge_total_tokens",
    "all_prompt_tokens", "all_completion_tokens", "all_total_tokens",
    "memory_storage_bytes", "peak_driver_ram_gib", "peak_vram_gib", "gpu_hours",
    "n_expected", "n_observed", "n_failed", "failure_rate", "run_id", "artifact_sha256",
]

SLICE_FIELDS = [
    "implementation_id", "display_name", "run_status", "slice_family", "slice_value",
    "n_expected", "n_valid", "correct_ratio", "hallucination_ratio", "omission_ratio",
    "answer_f1", "answer_bleu1", "retrieval_hit_rate", "retrieval_recall_at_10",
    "retrieval_ndcg_at_10", "run_id", "artifact_sha256",
]


def write_rows(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    if path.exists():
        raise SystemExit(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("execution_matrix", type=Path)
    parser.add_argument("slice_inventory", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    with args.execution_matrix.open(encoding="utf-8", newline="") as handle:
        methods = list(csv.DictReader(handle))
    slices = json.loads(args.slice_inventory.read_text(encoding="utf-8"))
    def initial_status(implementation_id: str) -> str:
        if implementation_id == "agentenhance-ceu":
            return "LOCKED_UNTIL_BASELINES_ACCEPTED"
        if implementation_id == "wma-hela-mem":
            return "LICENSE_BLOCKED"
        return "PENDING"

    identities = [
        {
            "implementation_id": row["implementation_id"],
            "display_name": row["display_name"],
            "run_status": initial_status(row["implementation_id"]),
        }
        for row in methods
    ]

    retrieval_rows = [dict(identity) for identity in identities]
    efficiency_rows = [dict(identity) for identity in identities]
    slice_values: list[tuple[str, str, int]] = [("overall", "overall", int(slices["question_count"]))]
    for value, count in slices["question_type_questions"].items():
        slice_values.append(("question_type", value, int(count)))
    for value, count in slices["scope_questions"].items():
        slice_values.append(("scope", value, int(count)))
    for value, count in slices["family_questions"].items():
        slice_values.append(("task_family", value, int(count)))
    for value, count in slices["difficulty_questions"].items():
        slice_values.append(("difficulty", value, int(count)))
    for value, count in slices["evidence_modality_questions"].items():
        slice_values.append(("evidence_modality", value, int(count)))
    for value, counts in slices["subcategories"].items():
        slice_values.append(("subcategory", value, int(counts["questions"])))

    slice_rows = [
        {
            **identity,
            "slice_family": family,
            "slice_value": value,
            "n_expected": count,
        }
        for identity in identities
        for family, value, count in slice_values
    ]
    write_rows(args.output_dir / "wma-retrieval-memory-table-template.v2.csv", RETRIEVAL_MEMORY_FIELDS, retrieval_rows)
    write_rows(args.output_dir / "wma-efficiency-reliability-table-template.v2.csv", EFFICIENCY_FIELDS, efficiency_rows)
    write_rows(args.output_dir / "wma-slice-table-template.v2.csv", SLICE_FIELDS, slice_rows)
    print(json.dumps({
        "status": "PASS",
        "methods": len(methods),
        "slice_values_per_method": len(slice_values),
        "slice_rows": len(slice_rows),
        "retrieval_memory_columns": len(RETRIEVAL_MEMORY_FIELDS),
        "efficiency_columns": len(EFFICIENCY_FIELDS),
        "slice_columns": len(SLICE_FIELDS),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
