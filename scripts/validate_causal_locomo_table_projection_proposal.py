#!/usr/bin/env python3
"""Validate the result-free Causal-LoCoMo table projection proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-table-projection-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_RESULT_FREE_REAL_USE_NOT_AUTHORIZED":
        raise SystemExit("Causal-LoCoMo projection proposal state drift")
    for parent in proposal["parents"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"Causal-LoCoMo projection parent drift: {parent['path']}")
    if sha256(ROOT / proposal["implementation"]) != proposal["implementation_sha256"]:
        raise SystemExit("Causal-LoCoMo projection implementation drift")
    template = proposal["template"]
    if sha256(ROOT / template["path"]) != template["sha256"]:
        raise SystemExit("Causal-LoCoMo projection template drift")
    if (template["methods"], template["metric_columns"], template["populated_metric_cells_after_valid_baseline_projection"]) != (8, 21, 105):
        raise SystemExit("Causal-LoCoMo projection table cardinality drift")
    gate = proposal["input_gate"]
    if (
        gate["required_mode"] != "real"
        or gate["seeds"] != [0, 1, 2]
        or (gate["qids"], gate["methods"], gate["score_rows"], gate["rows_per_method"]) != (87, 7, 1827, 261)
        or gate["protocol_blocked_rows"] != 522
        or gate["missing_rows"] != 0
        or gate["dropped_failed_rows"] != 0
        or gate["official_values_used"]
        or not gate["nested_hash_verification"]
    ):
        raise SystemExit("Causal-LoCoMo projection input gate drift")
    policy = proposal["projection_policy"]
    if (
        len(policy["numeric_rows"]) != 5
        or len(policy["blank_protocol_blocker_rows"]) != 2
        or policy["blank_locked_rows"] != ["agentenhance-ceu"]
        or any(policy[key] for key in (
            "manual_metric_selection", "manual_result_entry",
            "ranking_or_best_value_highlighting", "superiority_or_sota_claim_generation",
        ))
    ):
        raise SystemExit("Causal-LoCoMo projection policy drift")
    observed = proposal["current_observations"]
    if any(observed[key] != 0 for key in (
        "real_evaluation_roots_loaded", "real_rows_projected",
        "real_metric_cells_populated", "superiority_claims_emitted",
    )) or observed["official_values_used"]:
        raise SystemExit("Causal-LoCoMo projection proposal contains real observations")
    if "no real evaluator input" not in proposal["authorization"]:
        raise SystemExit("Causal-LoCoMo projection authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "methods": template["methods"],
        "metrics": template["metric_columns"],
        "future_local_metric_cells": template["populated_metric_cells_after_valid_baseline_projection"],
        "implementation_sha256": proposal["implementation_sha256"],
        "proposal_sha256": sha256(PATH),
        "real_rows_projected": observed["real_rows_projected"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
