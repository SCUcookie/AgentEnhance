#!/usr/bin/env python3
"""Validate the result-free Causal-LoCoMo offline evaluator proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-offline-evaluator-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_SYNTHETIC_ONLY_REAL_MODE_DENIED":
        raise SystemExit("offline evaluator proposal state drift")
    for parent in proposal["parents"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"offline evaluator parent drift: {parent['path']}")
    if sha256(ROOT / proposal["implementation"]) != proposal["implementation_sha256"]:
        raise SystemExit("offline evaluator implementation drift")
    audit = proposal["pre_score_audit"]
    if (
        audit["required_seeds"] != [0, 1, 2]
        or len(audit["required_method_order"]) != 7
        or audit["missing_rows_allowed"] != 0
        or not audit["raw_and_nested_sha256_verification"]
        or audit["gold_join_before_durable_raw_completion"]
    ):
        raise SystemExit("offline evaluator audit contract drift")
    metrics = proposal["metric_surface"]
    if (len(metrics["higher_is_better"]), len(metrics["lower_is_better"]), len(metrics["descriptive_cost"])) != (9, 4, 8):
        raise SystemExit("offline evaluator metric surface drift")
    failure = proposal["failure_policy"]
    if failure["drop_failed_rows"] or failure["favorable_safety_credit_for_empty_failure_selection"]:
        raise SystemExit("offline evaluator failure policy drift")
    observations = proposal["current_observations"]
    if any(observations[key] != 0 for key in (
        "real_raw_roots_scored", "real_score_rows", "real_metric_values_observed",
    )) or observations["official_values_used"]:
        raise SystemExit("offline evaluator proposal contains real or official observations")
    if "Real evaluation mode is unimplemented and denied" not in proposal["authorization"]:
        raise SystemExit("offline evaluator authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "proposal_sha256": sha256(PATH),
        "implementation_sha256": proposal["implementation_sha256"],
        "quality_metrics": len(metrics["higher_is_better"]) + len(metrics["lower_is_better"]),
        "cost_metrics": len(metrics["descriptive_cost"]),
        "real_score_rows": observations["real_score_rows"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
