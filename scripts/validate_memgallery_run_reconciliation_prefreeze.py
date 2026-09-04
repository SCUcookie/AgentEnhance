#!/usr/bin/env python3
"""Validate the frozen Mem-Gallery per-run reconciliation implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-run-reconciliation-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_IMPLEMENTATION_ONLY_AWAITING_DATA_INTEGRITY":
        raise SystemExit("Mem-Gallery reconciliation is not frozen before data integrity")
    for row in contract["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"Mem-Gallery reconciliation dependency drift: {row['path']}")

    surface = contract["registered_surface"]
    expected_methods = [
        "a-mem",
        "memoryos",
        "universalrag",
        "ngm",
        "augustus",
        "m2a",
        "v-mem",
        "no-memory",
        "full-memory-text",
        "full-memory-mm",
        "fifo-recent",
        "bm25",
        "naive-rag",
        "hybrid-rag",
    ]
    if surface["methods"] != expected_methods or surface["seeds"] != [0, 1, 2]:
        raise SystemExit("Mem-Gallery reconciliation method/seed surface drift")
    if (surface["method_seed_runs"], surface["questions_per_run"], surface["prediction_rows_if_surface_is_complete"]) != (
        42,
        1711,
        71862,
    ):
        raise SystemExit("Mem-Gallery reconciliation cardinality drift")
    if surface["drop_after_score_observation_allowed"]:
        raise SystemExit("Mem-Gallery reconciliation permits post-score dropping")

    model = contract["matched_answer_model"]
    if (
        model["revision"],
        model["temperature"],
        model["max_output_tokens"],
        model["shared_preexisting_model"],
        model["cleanup_eligible"],
    ) != (
        "5d854aab08710c16b980ec6d603d863b3821b915",
        0.0,
        128,
        True,
        False,
    ):
        raise SystemExit("Mem-Gallery matched answer-model contract drift")
    schema = contract["raw_prediction_schema"]
    if schema["status_values"] != ["ACCEPTED", "FAILED"]:
        raise SystemExit("Mem-Gallery prediction status schema drift")
    if "must be FAILED" not in schema["empty_answer_rule"]:
        raise SystemExit("empty-answer denominator rule missing")
    for phrase in ("byte-for-byte", "accepted_rows plus failed_rows", "no row is dropped"):
        if phrase not in contract["reconciliation_rule"]:
            raise SystemExit(f"reconciliation rule is incomplete: {phrase}")
    if contract["validation"]["tests_passed"] != 5:
        raise SystemExit("reconciliation test count drift")
    current = contract["current_state"]
    if any(current[key] != 0 for key in ("raw_runs_started", "reconciled_runs", "prediction_rows_admitted")):
        raise SystemExit("reconciliation freeze contains premature results")
    if current["data_integrity_accepted"] or current["official_values_used"]:
        raise SystemExit("reconciliation freeze falsely accepts data or official values")
    if "main_comparison_numerical_authorization=false" not in contract["downstream_gate"]:
        raise SystemExit("reconciliation stage accidentally authorizes numerical admission")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(PATH),
                "implementation_sha256": sha256_file(
                    ROOT / "scripts" / "reconcile_memgallery_method_run.py"
                ),
                "methods": len(expected_methods),
                "seeds": len(surface["seeds"]),
                "method_seed_runs": surface["method_seed_runs"],
                "questions_per_run": surface["questions_per_run"],
                "prediction_rows_at_freeze": current["prediction_rows_admitted"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
