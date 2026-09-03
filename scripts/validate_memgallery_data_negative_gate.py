#!/usr/bin/env python3
"""Validate the inert Wave1 prerequisite negative-control observation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "memgallery-data-materialization-negative-gate-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_NEGATIVE_CONTROL":
        raise SystemExit("negative gate audit is not accepted")
    for item in audit["bound_inputs"]:
        if sha256_file(ROOT / item["path"]) != item["sha256"]:
            raise SystemExit(f"negative gate bound input mismatch: {item['path']}")

    execution = audit["execution"]
    if execution["observed_exit_code"] == 0 or execution["expected_exit"] != "nonzero before any path creation":
        raise SystemExit("materializer did not fail closed")
    if "prerequisite marker gate failed" not in execution["observed_stderr"]:
        raise SystemExit("negative gate failure reason drift")
    if not execution["python_bytecode_writes_disabled"]:
        raise SystemExit("negative gate could write bytecode")

    pre = audit["precondition_observation"]
    if pre["required_wave1_acceptance_marker_present"]:
        raise SystemExit("negative control was not run before Wave1 acceptance")
    if pre["forbidden_wave1_rejection_marker_present"]:
        raise SystemExit("negative control observed a rejected Wave1")
    if pre["wave1_controller"] != "RUNNING" or pre["wave1_rejected_units"] != 0:
        raise SystemExit("unexpected Wave1 state during negative control")

    post = audit["postcondition"]
    for key in ("target_present", "stage_root_present", "evidence_root_present"):
        if post[key]:
            raise SystemExit(f"negative gate created a forbidden path: {key}")
    for key in (
        "dataset_files_downloaded",
        "dataset_bytes_downloaded",
        "network_requests_started",
        "numeric_result_rows_added",
        "files_deleted",
    ):
        if post[key] != 0:
            raise SystemExit(f"negative gate performed a mutation: {key}")
    if "does not authorize" not in audit["interpretation"]:
        raise SystemExit("negative gate audit improperly authorizes execution")

    print(
        json.dumps(
            {
                "status": "PASS",
                "observed_exit_code": execution["observed_exit_code"],
                "forbidden_paths_created": 0,
                "network_requests_started": post["network_requests_started"],
                "dataset_bytes_downloaded": post["dataset_bytes_downloaded"],
                "numeric_rows_added": post["numeric_result_rows_added"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
