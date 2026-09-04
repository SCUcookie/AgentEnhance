#!/usr/bin/env python3
"""Validate the accepted but inert Mem-Gallery reconciliation control package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-run-reconciliation-control-package-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_INERT":
        raise SystemExit("Mem-Gallery reconciliation control package is not accepted and inert")
    stage = audit["bound_stage"]
    if sha256_file(ROOT / stage["path"]) != stage["sha256"] or stage["implementation_commit"] != "3ccc3b6":
        raise SystemExit("reconciliation control package bound-stage drift")
    archive = audit["archive"]
    if (archive["bytes"], archive["sha256"], archive["fresh_before_extraction"]) != (
        13717,
        "71a499c3254d7609272e6152bbbbab0b04fe9a27c26f2058bd5208d2343ad0d2",
        True,
    ):
        raise SystemExit("reconciliation control archive identity drift")
    if "4096 Kbit/s" not in archive["transport"] or "resumable" not in archive["transport"]:
        raise SystemExit("reconciliation control transport drift")
    inventory = audit["package_inventory"]
    if (
        inventory["sha256"],
        inventory["signed_regular_files"],
        inventory["regular_files_including_inventory"],
        inventory["regular_file_bytes_including_inventory"],
        inventory["symlinks"],
        inventory["python_bytecode_files"],
    ) != (
        "0492f671521c54b6089c04d8760366bc48495c4f63bc61e592770f9101fe9d18",
        6,
        7,
        46918,
        0,
        0,
    ):
        raise SystemExit("reconciliation control inventory drift")
    for key in ("all_signed_files_verified_locally", "all_signed_files_verified_remotely", "inventory_excludes_itself"):
        if not inventory[key]:
            raise SystemExit(f"reconciliation package verification missing: {key}")
    remote = audit["remote_validation"]
    if remote["environment_mutated"] or remote["contract_validator"] != "PASS":
        raise SystemExit("reconciliation remote validation drift")
    if (remote["tests_passed"], remote["tests_failed"]) != (5, 0):
        raise SystemExit("reconciliation remote tests drift")
    for key in ("network_requests", "gpu_processes_started", "numeric_result_rows_added"):
        if remote[key] != 0:
            raise SystemExit(f"reconciliation validation was not inert: {key}")
    negative = audit["negative_data_integrity_gate"]
    if negative["status"] != "ACCEPTED_FAIL_CLOSED" or negative["observed_exit_code"] != 1:
        raise SystemExit("reconciliation missing-data gate did not fail closed")
    if negative["output_root_present_before"] or negative["output_root_present_after"]:
        raise SystemExit("reconciliation negative gate created an output root")
    surface = audit["registered_future_surface"]
    if surface != {
        "methods": 14,
        "seeds": 3,
        "method_seed_runs": 42,
        "questions_per_run": 1711,
        "prediction_rows_if_complete": 71862,
        "current_reconciled_runs": 0,
        "current_prediction_rows": 0,
        "official_values_used": False,
    }:
        raise SystemExit("reconciliation future surface drift")
    mutation = audit["mutation_summary"]
    for key, value in mutation.items():
        if key != "control_package_uploaded_and_extracted" and value != 0:
            raise SystemExit(f"reconciliation package performed prohibited mutation: {key}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "archive_sha256": archive["sha256"],
                "inventory_sha256": inventory["sha256"],
                "tests_passed": remote["tests_passed"],
                "method_seed_runs": surface["method_seed_runs"],
                "current_prediction_rows": surface["current_prediction_rows"],
                "negative_gate_exit_code": negative["observed_exit_code"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
