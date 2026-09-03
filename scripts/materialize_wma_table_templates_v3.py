#!/usr/bin/env python3
"""Materialize v3 result-free WMA panels from the expanded method surface."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from materialize_wma_table_templates_v2 import (
    EFFICIENCY_FIELDS,
    RETRIEVAL_MEMORY_FIELDS,
    SLICE_FIELDS,
    write_rows,
)


MAIN_FIELDS = [
    "implementation_id", "display_name", "year", "scope", "run_status",
    "n_samples", "n_qa", "qa_correct_ratio", "qa_hallucination_ratio",
    "qa_omission_ratio", "answer_f1", "answer_bleu1", "retrieval_recall_at_10",
    "retrieval_ndcg_at_10", "memory_avg_recall", "memory_avg_correctness",
    "memory_update_handling", "memory_interference_rejection", "total_tokens",
    "end_to_end_seconds", "end_to_end_latency_p95_ms", "memory_storage_bytes",
    "peak_ram_gib", "peak_vram_gib", "gpu_hours", "n_failed", "run_id",
    "artifact_sha256",
]

DEVELOPMENT_ONLY = {"wma-mmfu-single", "wma-simplemem", "wma-m2a", "wma-vilomem"}
BLOCKED_STATUS = {
    "wma-memory-r1": "CODE_NOT_RELEASED",
    "wma-apex-mem": "OFFICIAL_CODE_UNVERIFIED",
    "wma-lightmem": "OFFICIAL_CODE_UNVERIFIED",
    "wma-hela-mem": "LICENSE_BLOCKED",
}


def initial_status(implementation_id: str) -> str:
    if implementation_id == "agentenhance-ceu":
        return "LOCKED_UNTIL_BASELINES_ACCEPTED"
    if implementation_id in BLOCKED_STATUS:
        return BLOCKED_STATUS[implementation_id]
    if implementation_id in DEVELOPMENT_ONLY:
        return "DEVELOPMENT_ACCEPTED_NOT_MAIN"
    return "PENDING"


def display_scope(origin: str) -> str:
    if origin == "local project":
        return "proposed"
    if "benchmark-native" in origin:
        return "benchmark-native"
    if "bundled" in origin:
        return "bundled-mem-gallery"
    return "external-adapter"


def slice_values(payload: dict) -> list[tuple[str, str, int]]:
    values: list[tuple[str, str, int]] = [("overall", "overall", int(payload["question_count"]))]
    for family, key in (
        ("question_type", "question_type_questions"),
        ("scope", "scope_questions"),
        ("task_family", "family_questions"),
        ("difficulty", "difficulty_questions"),
        ("evidence_modality", "evidence_modality_questions"),
    ):
        for value, count in payload[key].items():
            values.append((family, value, int(count)))
    for value, counts in payload["subcategories"].items():
        values.append(("subcategory", value, int(counts["questions"])))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("execution_matrix", type=Path)
    parser.add_argument("slice_inventory", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    with args.execution_matrix.open(encoding="utf-8", newline="") as handle:
        methods = list(csv.DictReader(handle))
    slices = json.loads(args.slice_inventory.read_text(encoding="utf-8"))
    identities = [
        {
            "implementation_id": row["implementation_id"],
            "display_name": row["display_name"],
            "run_status": initial_status(row["implementation_id"]),
        }
        for row in methods
    ]
    main_rows = [
        {
            **identity,
            "year": row["publication_year"],
            "scope": display_scope(row["implementation_origin"]),
        }
        for row, identity in zip(methods, identities)
    ]
    retrieval_rows = [dict(identity) for identity in identities]
    efficiency_rows = [dict(identity) for identity in identities]
    values = slice_values(slices)
    long_rows = [
        {
            **identity,
            "slice_family": family,
            "slice_value": value,
            "n_expected": count,
        }
        for identity in identities
        for family, value, count in values
    ]
    write_rows(args.output_dir / "wma-main-table-template.v4.csv", MAIN_FIELDS, main_rows)
    write_rows(
        args.output_dir / "wma-retrieval-memory-table-template.v3.csv",
        RETRIEVAL_MEMORY_FIELDS,
        retrieval_rows,
    )
    write_rows(
        args.output_dir / "wma-efficiency-reliability-table-template.v3.csv",
        EFFICIENCY_FIELDS,
        efficiency_rows,
    )
    write_rows(args.output_dir / "wma-slice-table-template.v3.csv", SLICE_FIELDS, long_rows)
    print(json.dumps({
        "status": "PASS",
        "methods": len(methods),
        "slice_values_per_method": len(values),
        "slice_rows": len(long_rows),
        "main_columns": len(MAIN_FIELDS),
        "retrieval_memory_columns": len(RETRIEVAL_MEMORY_FIELDS),
        "efficiency_columns": len(EFFICIENCY_FIELDS),
        "slice_columns": len(SLICE_FIELDS),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
