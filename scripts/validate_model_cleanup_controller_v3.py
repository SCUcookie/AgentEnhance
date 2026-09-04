#!/usr/bin/env python3
"""Validate the ownership-v2-aware model-cleanup successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "model-cleanup-controller-prefreeze.v3.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    require(payload.get("status") == "FROZEN_IMPLEMENTATION_ONLY_NO_CURRENT_ELIGIBILITY", "cleanup v3 status drift")
    require(sha256_file(ROOT / payload["supersedes"]["path"]) == payload["supersedes"]["sha256"], "cleanup v2 parent drift")
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 9, "cleanup v3 bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file() and sha256_file(path) == binding["sha256"], f"cleanup v3 dependency drift: {path}")
    ownership = payload["effective_ownership"]
    require((ownership["project_owned_candidates"], ownership["project_owned_expected_files"], ownership["project_owned_expected_bytes"], ownership["effective_dependency_relations"], ownership["protected_shared_models"], ownership["cleanup_eligible_now"]) == (8, 99, 28164467445, 19, 2, 0), "effective ownership summary drift")
    tracks = payload["global_completion_gate"]["required_tracks"]
    require([(row["track_id"], row["registered_methods"]) for row in tracks] == [("wma-lifecycle-matched-v1", 29), ("memgallery-static-matched-v1", 14), ("causal-locomo-safety-v1", 7)], "cleanup v3 track surface drift")
    require(payload["global_completion_gate"]["registered_method_surface"] == 50, "cleanup v3 method surface drift")
    require(payload["dependent_retirement_contract"]["new_v2_edges_cannot_be_omitted"] is True, "v2 dependent omission guard missing")
    validation = payload["validation"]
    require(validation["synthetic_tests_passed"] == 6, "cleanup v3 test count drift")
    for field in ("server_model_files_quarantined", "server_model_files_deleted", "datasets_deleted", "results_deleted"):
        require(validation[field] == 0, f"cleanup v3 freeze contains mutation: {field}")
    current = payload["current_state"]
    require(current["project_owned_models_cleanup_eligible"] == 0 and current["mutation_performed"] is False, "cleanup v3 prematurely authorizes a model")
    source = (ROOT / "scripts/model_cleanup_controller_v3.py").read_text(encoding="utf-8")
    for phrase in ("LEDGER_V1_SHA256", "LEDGER_V2_SHA256", "resolve_effective_ownership", "validate_dependency_retirements", "validate_project_reference_audit", "validate_global_completion", "validate_no_process_references", "shutil.rmtree(quarantine_path)"):
        require(phrase in source, f"cleanup v3 implementation guard missing: {phrase}")
    require("No current cleanup is authorized" in payload["authorization"], "cleanup v3 current authorization boundary missing")
    print(json.dumps({"status": "PASS", "contract_sha256": sha256_file(CONTRACT), "controller_sha256": bindings[7]["sha256"], "project_owned_candidates": 8, "dependency_relations": 19, "registered_method_surface": 50, "cleanup_eligible_now": 0, "server_models_deleted": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
