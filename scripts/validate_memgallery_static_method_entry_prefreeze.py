#!/usr/bin/env python3
"""Validate the frozen 14-method Mem-Gallery source and budget mapping."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-static-method-entry-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_SOURCE_MAPPING_ONLY_AWAITING_WAVE1_DATA_AND_MODELS":
        raise SystemExit("Mem-Gallery method entry is not frozen before execution")
    for row in contract["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"Mem-Gallery method-entry dependency drift: {row['path']}")

    sources = {row["source_id"]: row for row in contract["source_bindings"]}
    if set(sources) != {
        "mem-gallery-official", "a-mem-official", "memoryos-official",
        "m2a-official", "v-mem-official",
    }:
        raise SystemExit("method source surface drift")
    methods = contract["methods"]
    expected = [
        "a-mem", "memoryos", "universalrag", "ngm", "augustus", "m2a", "v-mem",
        "no-memory", "full-memory-text", "full-memory-mm", "fifo-recent", "bm25",
        "naive-rag", "hybrid-rag",
    ]
    if [row["method_id"] for row in methods] != expected:
        raise SystemExit("method order or membership drift")
    for row in methods:
        if row["source_id"] != "project-control" and row["source_id"] not in sources:
            raise SystemExit(f"unbound method source: {row['method_id']}")
        if not row["frozen_budget"]:
            raise SystemExit(f"missing frozen method budget: {row['method_id']}")

    protocol = contract["matched_protocol"]
    if (
        protocol["dataset_questions"], protocol["seeds"],
        protocol["answer_temperature"], protocol["answer_max_output_tokens"],
        protocol["retrieved_evidence_k"], protocol["official_values_allowed"],
        protocol["post_score_method_or_budget_dropping_allowed"],
    ) != (1711, [0, 1, 2], 0.0, 128, 10, False, False):
        raise SystemExit("matched protocol drift")
    if "N_text + 256*N_images <= 4096" not in protocol["answer_memory_budget"]:
        raise SystemExit("answer-memory budget drift")
    if "secondary" not in next(row for row in methods if row["method_id"] == "v-mem")["fidelity_companion"]:
        raise SystemExit("V-Mem matched/native budget boundary missing")
    if "constant 60" not in next(row for row in methods if row["method_id"] == "hybrid-rag")["control_definition"]:
        raise SystemExit("hybrid RRF definition drift")

    accounting = contract["required_call_accounting"]
    for phrase in ("final_answer", "memory_write_llm", "router_or_anchor_llm", "image_embedding", "peak CPU RAM"):
        if not any(phrase in row for row in accounting):
            raise SystemExit(f"missing call accounting family: {phrase}")
    state = contract["current_state"]
    if state["data_integrity_accepted"] or state["required_models_ready"] or state["official_values_used"]:
        raise SystemExit("method entry contains premature acceptance")
    if any(state[key] != 0 for key in (
        "adapter_lifecycle_runs_started", "numerical_runs_started",
        "prediction_rows_observed", "scores_observed",
    )):
        raise SystemExit("method entry contains premature numerical observations")
    if "does not authorize lifecycle execution" not in contract["authorization"]:
        raise SystemExit("method-entry authorization boundary missing")

    print(json.dumps({
        "status": "PASS",
        "contract_sha256": sha256_file(PATH),
        "sources": len(sources),
        "methods": len(methods),
        "method_seed_runs": len(methods) * len(protocol["seeds"]),
        "prediction_rows_at_freeze": state["prediction_rows_observed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
