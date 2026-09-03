#!/usr/bin/env python3
"""Validate the accepted, still-inert Mem-Gallery data control package audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "comparisons" / "memgallery-data-materialization-control-package-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_AFTER_VALIDATION_RECOVERY1":
        raise SystemExit("data control package is not accepted after recovery validation")
    stage = audit["bound_stage"]
    if sha256_file(ROOT / stage["path"]) != stage["sha256"]:
        raise SystemExit("bound data materialization stage drift")
    if stage["implementation_commit"] != "5a55b08":
        raise SystemExit("unexpected implementation commit")

    archive = audit["archive"]
    if archive["bytes"] != 190178 or len(archive["sha256"]) != 64:
        raise SystemExit("control archive identity drift")
    if "4096 Kbit/s" not in archive["transport"] or not archive["fresh_before_extraction"]:
        raise SystemExit("control archive transport or freshness drift")
    inventory = audit["package_inventory"]
    if (
        inventory["signed_regular_files"],
        inventory["regular_files_including_inventory"],
        inventory["symlinks"],
        inventory["python_bytecode_files"],
    ) != (11, 12, 0, 0):
        raise SystemExit("control package cardinality drift")
    if not inventory["all_signed_files_verified"] or not inventory["inventory_excludes_itself"]:
        raise SystemExit("control package inventory is not independently verifiable")

    attempts = audit["validation_attempts"]
    if len(attempts) != 2 or attempts[0]["status"] != "REJECTED_TEST_INVOCATION":
        raise SystemExit("initial validation failure is missing")
    if attempts[0]["dataset_download_started"] or attempts[0]["package_files_changed"]:
        raise SystemExit("initial validation failure was not inert")
    accepted = attempts[1]
    if accepted["status"] != "ACCEPTED_VALIDATION_RECOVERY1":
        raise SystemExit("recovery validation is not accepted")
    if (accepted["materializer_tests_passed"], accepted["tree_manifest_tests_passed"], accepted["tests_failed"]) != (5, 3, 0):
        raise SystemExit("control package test result drift")
    if accepted["prefetch_manifest_validator"] != "PASS" or accepted["materialization_prefreeze_validator"] != "PASS":
        raise SystemExit("control package validator result drift")

    dataset = audit["accepted_dataset_identity"]
    if (
        dataset["revision"],
        dataset["manifest_sha256"],
        dataset["files"],
        dataset["bytes"],
        dataset["dialog_files"],
        dataset["image_files"],
    ) != (
        "af912daba984e896e253016b7c7e334ef92c2a6f",
        "58ebfee481bca010910705271ae992ee42b425d267cd2354a0d9982d35f5d045",
        1515,
        545845389,
        20,
        1490,
    ):
        raise SystemExit("accepted dataset identity drift")
    runtime = audit["runtime_observation_after_acceptance"]
    if runtime["dataset_target_present"] or runtime["dataset_downloaded_bytes"] != 0:
        raise SystemExit("control package validation unexpectedly downloaded data")
    if runtime["numeric_result_rows_added"] != 0:
        raise SystemExit("control package validation added numeric rows")
    mutation = audit["mutation_summary"]
    if any(mutation[key] != 0 for key in (
        "dataset_files_downloaded",
        "model_files_downloaded",
        "gpu_processes_started",
        "numeric_result_rows_added",
        "files_deleted",
    )):
        raise SystemExit("control package validation performed a prohibited mutation")
    for phrase in ("TERMINAL_ACCEPTED", "rejection marker", "tmux", "six frozen project ports"):
        if phrase not in audit["execution_authorization"]:
            raise SystemExit(f"missing execution gate: {phrase}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "archive_sha256": archive["sha256"],
                "inventory_sha256": inventory["sha256"],
                "signed_files": inventory["signed_regular_files"],
                "tests_passed": accepted["materializer_tests_passed"] + accepted["tree_manifest_tests_passed"],
                "dataset_downloaded_bytes": runtime["dataset_downloaded_bytes"],
                "numeric_rows_added": runtime["numeric_result_rows_added"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
