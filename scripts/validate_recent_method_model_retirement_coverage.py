#!/usr/bin/env python3
"""Validate recent-method coverage of the effective model-retirement graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "recent-method-model-retirement-coverage-audit.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    audit = load("comparisons/recent-method-model-retirement-coverage-audit.v1.json")
    if audit.get("status") != "TERMINAL_ACCEPTED_RESULT_FREE_NO_CLEANUP_ELIGIBILITY":
        raise SystemExit("recent-method retirement audit state drift")
    for parent in audit["bound_inputs"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"recent-method retirement parent drift: {parent['path']}")
    ledger1 = load("comparisons/baseline-model-ownership-ledger.v1.json")
    ledger2 = load("comparisons/baseline-model-ownership-ledger.v2.json")
    candidates = {row["model_id"]: dict(row) for row in ledger1["project_owned_candidates"]}
    dependencies = {
        model_id: set(row.get("required_dependents", [])) | set(row.get("conservative_endpoint_dependents", []))
        for model_id, row in candidates.items()
    }
    for delta in ledger2["expanded_project_owned_dependents"]:
        model_id = delta["model_id"]
        if model_id not in candidates:
            raise SystemExit(f"expanded model absent from v1: {model_id}")
        dependencies[model_id].update(delta["new_required_dependents"])
    for row in ledger2["new_project_owned_candidates"]:
        model_id = row["model_id"]
        if model_id in candidates:
            raise SystemExit(f"duplicate v2 candidate: {model_id}")
        candidates[model_id] = dict(row)
        dependencies[model_id] = set(row.get("required_dependents", [])) | set(row.get("conservative_endpoint_dependents", []))
    effective_edges = {f"{model_id}|{dependent}" for model_id, values in dependencies.items() for dependent in values}
    surface = audit["effective_model_surface"]
    if (
        not (len(candidates) == surface["project_owned_candidate_models"] == 8)
        or not (sum(row["expected_files"] for row in candidates.values()) == surface["project_owned_expected_files"] == 99)
        or not (sum(row["expected_bytes"] for row in candidates.values()) == surface["project_owned_expected_bytes"] == 28164467445)
        or not (len(effective_edges) == surface["effective_track_method_dependency_edges"] == 19)
        or surface["protected_shared_models"] != 2
        or surface["cleanup_eligible_now"] != 0
        or surface["real_model_files_deleted"] != 0
    ):
        raise SystemExit("effective model surface drift")
    coverage = load("comparisons/recent-method-execution-coverage-audit.v1.json")
    recent_methods = set(coverage["exhaustive_partition"]["same_protocol_numeric_route"])
    edge_map = audit["recent_edge_to_method"]
    if not set(edge_map) <= effective_edges or not set(edge_map.values()) <= recent_methods:
        raise SystemExit("recent dependency edge is absent from effective ownership graph")
    non_recent_edges = set(audit["non_recent_control_edges_that_still_block_cleanup"])
    if set(edge_map) | non_recent_edges != effective_edges or set(edge_map) & non_recent_edges:
        raise SystemExit("effective ownership edges are missing or duplicated")
    recent = audit["recent_route_coverage"]
    with_weights = set(recent["methods_with_project_owned_weight_dependencies"])
    shared_only = set(recent["shared_protected_or_no_standalone_weight_only"])
    if (
        not (len(recent_methods) == recent["same_protocol_numeric_methods"] == 15)
        or not (len(edge_map) == recent["effective_recent_track_method_model_edges"] == 17)
        or set(edge_map.values()) != with_weights
        or not (len(with_weights) == recent["methods_with_project_owned_weight_dependencies_count"] == 11)
        or not (len(shared_only) == recent["shared_protected_or_no_standalone_weight_only_count"] == 4)
        or with_weights | shared_only != recent_methods
        or with_weights & shared_only
        or recent["uncovered_recent_numeric_methods"]
    ):
        raise SystemExit("recent numeric method model disposition drift")
    retirement = audit["retirement_rule"]
    if (
        retirement["per_method_completion_is_sufficient"]
        or retirement["per_track_completion_is_sufficient"]
        or not retirement["all_three_tracks_and_all_effective_edges_required"]
        or retirement["dependent_receipts_required"] != 19
        or not retirement["fresh_project_reference_audit_required"]
        or retirement["active_process_references_allowed"] != 0
        or retirement["pending_run_references_allowed"] != 0
        or not retirement["two_phase_quarantine_then_delete_required"]
    ):
        raise SystemExit("recent method retirement rule drift")
    deletion = audit["deletion_scope"]
    if any(deletion[key] != "NEVER_DELETE" for key in (
        "datasets", "results", "logs", "environments", "source", "manifests", "archives", "shared_models",
    )):
        raise SystemExit("retained evidence deletion boundary drift")
    current = audit["current_state"]
    if (
        current["all_three_tracks_complete"]
        or current["mutation_performed"]
        or any(current[key] != 0 for key in (
            "dependent_retirement_receipts", "project_reference_audits",
            "cleanup_eligible_models", "quarantined_models", "deleted_models",
        ))
    ):
        raise SystemExit("retirement audit reports unauthorized current cleanup state")
    print(json.dumps({
        "status": "PASS",
        "recent_numeric_methods": len(recent_methods),
        "methods_with_project_owned_weights": len(with_weights),
        "shared_or_no_standalone_weight_methods": len(shared_only),
        "recent_dependency_edges": len(edge_map),
        "non_recent_control_edges": len(non_recent_edges),
        "effective_dependency_edges": len(effective_edges),
        "cleanup_eligible_models": current["cleanup_eligible_models"],
        "deleted_models": current["deleted_models"],
        "audit_sha256": sha256(PATH),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
