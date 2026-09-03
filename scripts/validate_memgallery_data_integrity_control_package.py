#!/usr/bin/env python3
"""Validate the accepted but inert Mem-Gallery integrity control package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-data-integrity-control-package-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_INERT":
        raise SystemExit("integrity control package is not accepted and inert")
    stage = audit["bound_stage"]
    if sha256_file(ROOT / stage["path"]) != stage["sha256"]:
        raise SystemExit("bound integrity stage drift")
    if stage["implementation_commit"] != "dbddbb9":
        raise SystemExit("unexpected integrity implementation commit")

    archive = audit["archive"]
    if (
        archive["bytes"],
        archive["sha256"],
        archive["fresh_before_extraction"],
    ) != (
        186829,
        "fcdb9c37e2f9b022aa2c5ad6389071888a7b9e4606342f68e4dab7b8deed818f",
        True,
    ):
        raise SystemExit("integrity archive identity drift")
    if "4096 Kbit/s" not in archive["transport"] or "resumable" not in archive["transport"]:
        raise SystemExit("integrity archive transport drift")

    inventory = audit["package_inventory"]
    if (
        inventory["sha256"],
        inventory["signed_regular_files"],
        inventory["regular_files_including_inventory"],
        inventory["regular_file_bytes_including_inventory"],
        inventory["symlinks"],
        inventory["python_bytecode_files"],
    ) != (
        "9cab2960eecda00b00a5d63fe71f2eb81605b95ab453b4b11cf8e1e517ccd0f3",
        7,
        8,
        622640,
        0,
        0,
    ):
        raise SystemExit("integrity package inventory drift")
    for key in ("all_signed_files_verified_locally", "all_signed_files_verified_remotely", "inventory_excludes_itself"):
        if not inventory[key]:
            raise SystemExit(f"integrity package verification missing: {key}")

    remote = audit["remote_validation"]
    if remote["integrity_contract_validator"] != "PASS":
        raise SystemExit("remote integrity contract validation failed")
    if (remote["synthetic_tests_passed"], remote["synthetic_tests_failed"]) != (4, 0):
        raise SystemExit("remote integrity synthetic tests drift")
    if remote["environment_mutated"]:
        raise SystemExit("remote shared environment was mutated")
    for key in ("network_requests", "dataset_files_read", "dataset_files_written", "gpu_processes_started", "numeric_result_rows_added"):
        if remote[key] != 0:
            raise SystemExit(f"remote validation was not inert: {key}")

    negative = audit["negative_materialization_gate_test"]
    if negative["status"] != "ACCEPTED_FAIL_CLOSED" or negative["observed_exit_code"] != 1:
        raise SystemExit("materialization negative gate did not fail closed")
    if negative["required_marker_present"]:
        raise SystemExit("negative test unexpectedly had the required marker")
    for key in (
        "dataset_target_present_before",
        "dataset_target_present_after",
        "integrity_evidence_present_before",
        "integrity_evidence_present_after",
    ):
        if negative[key]:
            raise SystemExit(f"negative integrity gate created a forbidden path: {key}")
    if negative["network_requests_started"] != 0 or negative["numeric_result_rows_added"] != 0:
        raise SystemExit("negative integrity gate was not inert")

    runtime = audit["runtime_observation_after_acceptance"]
    if runtime["wave1_controller"] != "RUNNING" or runtime["rejected_units"] != 0:
        raise SystemExit("unexpected Wave1 state in integrity package audit")
    if runtime["dataset_target_present"] or runtime["dataset_downloaded_bytes"] != 0 or runtime["integrity_evidence_present"]:
        raise SystemExit("integrity package acceptance prematurely created data or evidence")
    mutation = audit["mutation_summary"]
    for key in (
        "dataset_files_downloaded",
        "dataset_files_modified",
        "model_files_downloaded",
        "gpu_processes_started",
        "numeric_result_rows_added",
        "files_deleted",
    ):
        if mutation[key] != 0:
            raise SystemExit(f"integrity package performed prohibited mutation: {key}")
    for phrase in ("TERMINAL_ACCEPTED", "no rejection marker", "No static method"):
        if phrase not in audit["execution_authorization"]:
            raise SystemExit(f"missing integrity execution boundary: {phrase}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "archive_sha256": archive["sha256"],
                "inventory_sha256": inventory["sha256"],
                "remote_tests_passed": remote["synthetic_tests_passed"],
                "negative_gate_exit_code": negative["observed_exit_code"],
                "dataset_downloaded_bytes": runtime["dataset_downloaded_bytes"],
                "numeric_rows_added": runtime["numeric_result_rows_added"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
