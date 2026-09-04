#!/usr/bin/env python3
"""Validate the result-free Causal-LoCoMo real-model integrity freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-real-model-integrity-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("state") != "FROZEN_STATIC_ONLY_AWAITING_WMA_RELEASE":
        raise SystemExit("Causal-LoCoMo integrity state drift")
    for row in contract["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"bound input drift: {row['path']}")

    source = contract["source_identity"]
    if (source["records"], source["unique_example_ids"]) != (87, 87):
        raise SystemExit("dataset denominator drift")
    if len(source["dataset_sha256"]) != 64 or len(source["example_id_order_sha256"]) != 64:
        raise SystemExit("dataset identity is incomplete")
    if len(source["audited_source_files"]) != 5 or any(
        len(digest) != 64 for digest in source["audited_source_files"].values()
    ):
        raise SystemExit("upstream source audit surface drift")

    firewall = contract["inference_firewall"]
    if firewall["builder"] != "scripts/causal_locomo_inference_view.py":
        raise SystemExit("inference-view builder drift")
    if set(firewall["evaluator_only_top_level"]) != {
        "bad_memory_ids", "context_dependent_memory_ids", "gold_behavior",
        "gold_memory_ids", "intervention_tests", "metadata", "quality_status",
        "scoring_criteria",
    }:
        raise SystemExit("top-level evaluation firewall drift")
    if not {"label", "type", "expected_effect", "causal_role", "derivation", "synthetic"}.issubset(
        firewall["evaluator_only_memory_fields"]
    ):
        raise SystemExit("memory evaluation firewall is incomplete")

    protocol = contract["matched_protocol"]
    expected_methods = [
        "cmi-no-memory", "cmi-full-history", "cmi-vector-memory",
        "cmi-summary-memory", "cmi-reflection-memory", "cmi-graph-memory", "cmi",
    ]
    if protocol["method_order"] != expected_methods:
        raise SystemExit("method order drift")
    if (
        protocol["examples"], protocol["seeds"],
        protocol["method_example_pairs_per_seed"], protocol["registered_prediction_rows"],
        protocol["answer_temperature"], protocol["retrieval_top_k"],
        protocol["automatic_retries"], protocol["official_or_development_values_allowed"],
    ) != (87, [0, 1, 2], 609, 1827, 0.0, 5, 0, False):
        raise SystemExit("matched protocol drift")

    methods = contract["method_integrity"]
    if [row["method_id"] for row in methods] != expected_methods:
        raise SystemExit("method-integrity order drift")
    statuses = {row["method_id"]: row["main_status"] for row in methods}
    blocked = {method for method, status in statuses.items() if status.startswith("BLOCKED_")}
    if blocked != {"cmi-reflection-memory", "cmi"}:
        raise SystemExit("gold/label blocker surface drift")
    if statuses["cmi-vector-memory"] != "ELIGIBLE_AFTER_BLIND_FAIL_CLOSED_OVERLAY":
        raise SystemExit("embedding fallback blocker missing")

    state = contract["current_state"]
    if state["wma_release_accepted"]:
        raise SystemExit("premature WMA release acceptance")
    if any(state[key] != 0 for key in (
        "real_model_lifecycle_runs_started", "real_model_prediction_rows_observed",
        "real_model_scores_observed",
    )):
        raise SystemExit("prefreeze contains premature numerical evidence")
    if (state["main_eligible_methods"], state["blocked_upstream_methods"]) != (5, 2):
        raise SystemExit("eligibility count drift")
    if "authorizes no server materialization" not in contract["authorization"]:
        raise SystemExit("authorization boundary missing")

    print(json.dumps({
        "status": "PASS",
        "contract_sha256": sha256_file(PATH),
        "registered_rows": protocol["registered_prediction_rows"],
        "eligible_methods": state["main_eligible_methods"],
        "blocked_methods": state["blocked_upstream_methods"],
        "observed_real_model_rows": state["real_model_prediction_rows_observed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

