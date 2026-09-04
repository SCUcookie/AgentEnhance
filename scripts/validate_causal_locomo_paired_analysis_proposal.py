#!/usr/bin/env python3
"""Validate the result-free Causal-LoCoMo paired-analysis proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "causal-locomo-paired-analysis-proposal.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    proposal = json.loads(PATH.read_text(encoding="utf-8"))
    if proposal.get("state") != "PROPOSED_RESULT_FREE_REAL_USE_NOT_AUTHORIZED":
        raise SystemExit("paired-analysis proposal state drift")
    for parent in proposal["parents"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"paired-analysis parent drift: {parent['path']}")
    if sha256(ROOT / proposal["implementation"]) != proposal["implementation_sha256"]:
        raise SystemExit("paired-analysis implementation drift")
    surface = proposal["comparison_surface"]
    if (
        len(surface["eligible_methods"]) != 5
        or (surface["unordered_method_pairs"], surface["quality_metrics"], surface["cost_metrics"]) != (10, 13, 8)
        or (surface["quality_rows"], surface["cost_rows"]) != (130, 80)
        or len(surface["protocol_blocked_methods_excluded_from_numeric_tests"]) != 2
        or surface["agentenhance_included"]
    ):
        raise SystemExit("paired-analysis comparison surface drift")
    unit = proposal["analysis_unit"]
    if (unit["clusters"], unit["paired_seed_example_rows_per_method"]) != (87, 261):
        raise SystemExit("paired-analysis cluster unit drift")
    uncertainty = proposal["uncertainty"]
    if (
        uncertainty["bootstrap_replicates"] != 10000
        or uncertainty["permutation_replicates"] != 100000
        or uncertainty["deterministic_tie_tolerance"] != 1e-12
    ):
        raise SystemExit("paired-analysis uncertainty rule drift")
    multiplicity = proposal["multiplicity"]
    if (
        multiplicity["primary_metric"] != "task_score"
        or "Holm" not in multiplicity["primary_adjustment"]
        or multiplicity["secondary_quality_metrics"] != 12
        or "Benjamini-Hochberg" not in multiplicity["secondary_adjustment"]
        or multiplicity["post_result_comparator_selection"]
    ):
        raise SystemExit("paired-analysis multiplicity rule drift")
    observed = proposal["current_observations"]
    if any(observed[key] != 0 for key in (
        "real_evaluation_roots_analyzed", "real_quality_rows", "real_cost_rows",
        "agentenhance_values_observed", "claims_emitted",
    )) or observed["official_values_used"]:
        raise SystemExit("paired-analysis proposal contains real observations")
    if "no real result access" not in proposal["authorization"]:
        raise SystemExit("paired-analysis authorization boundary missing")
    print(json.dumps({
        "status": "PASS",
        "method_pairs": surface["unordered_method_pairs"],
        "future_rows": surface["quality_rows"] + surface["cost_rows"],
        "analysis_clusters": unit["clusters"],
        "bootstrap_replicates": uncertainty["bootstrap_replicates"],
        "permutation_replicates": uncertainty["permutation_replicates"],
        "implementation_sha256": proposal["implementation_sha256"],
        "proposal_sha256": sha256(PATH),
        "real_rows": observed["real_quality_rows"] + observed["real_cost_rows"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
