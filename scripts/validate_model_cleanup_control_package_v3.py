#!/usr/bin/env python3
"""Validate the accepted inert model-cleanup v3 control package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "comparisons" / "model-cleanup-controller-control-package-audit.v3.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    require(payload.get("status") == "TERMINAL_ACCEPTED_INERT", "cleanup v3 package is not accepted inert")
    stage = payload["bound_stage"]
    require(sha256_file(ROOT / stage["path"]) == stage["sha256"], "cleanup v3 package prefreeze drift")
    require((stage["prefreeze_commit"], stage["controller_commit"]) == ("882d58d", "9a760cf"), "cleanup v3 commit identity drift")
    archive = payload["archive"]
    require((archive["bytes"], archive["sha256"]) == (28239, "ca768a0147639187f3de257aa7dcfa35d9dba653ffe75fe143719e538f40bfb7"), "cleanup v3 archive identity drift")
    require("4096 Kbit/s" in archive["transport"] and archive["fresh_before_extraction"] and archive["remote_sha256_verified"], "cleanup v3 archive transport drift")
    inventory = payload["package_inventory"]
    require((inventory["sha256"], inventory["signed_regular_files"], inventory["regular_files_including_inventory"], inventory["regular_file_bytes_including_inventory"], inventory["symlinks"], inventory["python_bytecode_files"]) == ("264370203c6e5e9b93d183984429c018dfab0d085c406f36d15ebabc67c98b39", 13, 14, 116548, 0, 0), "cleanup v3 package inventory drift")
    for field in ("all_signed_files_verified_locally", "all_signed_files_verified_remotely", "inventory_excludes_itself"):
        require(inventory[field] is True, f"cleanup v3 package verification missing: {field}")
    remote = payload["remote_validation"]
    require(remote["controller_validator"] == "PASS" and remote["environment_mutated"] is False, "cleanup v3 remote validator drift")
    require((remote["effective_project_owned_candidates"], remote["effective_dependency_relations"], remote["registered_method_surface"], remote["tests_passed"], remote["tests_failed"]) == (8, 19, 50, 6, 0), "cleanup v3 remote test surface drift")
    require(remote["test_model_scope"] == "TemporaryDirectory roots below /tmp only" and remote["temporary_fixture_weight_files_deleted"] == 1, "cleanup v3 fixture boundary drift")
    for field in ("real_model_file_content_reads", "network_requests", "gpu_processes_started"):
        require(remote[field] == 0, f"cleanup v3 remote inert boundary drift: {field}")
    require(remote["real_model_top_level_metadata_before_after_equal"] is True, "real model metadata changed")
    negative = payload["negative_gate"]
    require(negative["status"] == "ACCEPTED_FAIL_CLOSED" and negative["observed_exit_code"] == 1 and negative["observed_error_type"] == "FileNotFoundError", "cleanup v3 negative gate drift")
    for field in ("model_target_resolved", "process_scan_started", "cleanup_output_created"):
        require(negative[field] is False, f"cleanup v3 negative gate crossed boundary: {field}")
    require(negative["record_parent_absent_before"] and negative["record_parent_absent_after"], "cleanup v3 negative root mutation")
    current = payload["current_state"]
    require((current["tracks_required"], current["registered_method_surface"], current["cleanup_eligible_models"], current["real_models_quarantined"], current["real_models_deleted"]) == (3, 50, 0, 0, 0), "cleanup v3 current state drift")
    mutation = payload["mutation_summary"]
    for field in ("real_model_files_read", "real_model_files_quarantined", "real_model_files_deleted", "dataset_files_modified", "result_files_modified", "numeric_result_rows_added", "eligibility_records_created"):
        require(mutation[field] == 0, f"cleanup v3 prohibited mutation recorded: {field}")
    require(payload["effective_future_entry"]["current_real_execution_authorized"] is False, "cleanup v3 real execution prematurely authorized")
    print(json.dumps({"status": "PASS", "archive_sha256": archive["sha256"], "inventory_sha256": inventory["sha256"], "remote_tests_passed": remote["tests_passed"], "dependency_relations": remote["effective_dependency_relations"], "cleanup_eligible_now": current["cleanup_eligible_models"], "real_models_deleted": current["real_models_deleted"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
