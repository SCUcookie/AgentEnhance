#!/usr/bin/env python3
"""Validate the accepted and inert cross-track cleanup control package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "model-cleanup-controller-control-package-audit.v2.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_INERT":
        raise SystemExit("cleanup v2 package is not accepted and inert")
    stage = audit["bound_stage"]
    if sha256_file(ROOT / stage["path"]) != stage["sha256"] or stage["implementation_commit"] != "5d88565":
        raise SystemExit("cleanup v2 package bound-stage drift")
    archive = audit["archive"]
    if (archive["bytes"], archive["sha256"]) != (
        15531,
        "4197e3fd60bf45916e2549cb9126dce9bd1fd455656d65d9a7184b0037d80567",
    ):
        raise SystemExit("cleanup v2 archive identity drift")
    if "4096 Kbit/s" not in archive["transport"] or not archive["fresh_before_extraction"]:
        raise SystemExit("cleanup v2 archive transport drift")
    inventory = audit["package_inventory"]
    if (
        inventory["sha256"],
        inventory["signed_regular_files"],
        inventory["regular_files_including_inventory"],
        inventory["regular_file_bytes_including_inventory"],
        inventory["symlinks"],
        inventory["python_bytecode_files"],
    ) != (
        "469f547f8e78502310f0f18d048a405f891c0954c2d6e39fd7a59a748cc455f5",
        8,
        9,
        56881,
        0,
        0,
    ):
        raise SystemExit("cleanup v2 package inventory drift")
    for key in ("all_signed_files_verified_locally", "all_signed_files_verified_remotely", "inventory_excludes_itself"):
        if not inventory[key]:
            raise SystemExit(f"cleanup v2 package verification missing: {key}")
    remote = audit["remote_validation"]
    if remote["environment_mutated"] or remote["controller_validator"] != "PASS":
        raise SystemExit("cleanup v2 remote validation drift")
    if (remote["tests_passed"], remote["tests_failed"]) != (3, 0):
        raise SystemExit("cleanup v2 remote test result drift")
    negative = remote["negative_global_gate"]
    if negative["status"] != "ACCEPTED_FAIL_CLOSED" or negative["observed_exit_code"] != 1:
        raise SystemExit("cleanup v2 negative global gate did not fail closed")
    if negative["inner_v1_controller_reached"] or negative["model_mutation_performed"]:
        raise SystemExit("cleanup v2 negative gate reached a mutation path")
    entry = audit["effective_execution_entry"]
    if entry["script"] != "scripts/model_cleanup_controller_v2.py" or not entry["direct_v1_invocation_prohibited"]:
        raise SystemExit("cleanup v2 package did not close the v1 fallback")
    current = audit["current_state"]
    if current != {
        "registered_method_surface": 50,
        "tracks_required": 3,
        "global_completion_present": False,
        "cleanup_eligible_models": 0,
        "models_quarantined": 0,
        "models_deleted": 0,
    }:
        raise SystemExit("cleanup v2 current state drift")
    mutation = audit["mutation_summary"]
    for key, value in mutation.items():
        if key != "control_package_uploaded_and_extracted" and value != 0:
            raise SystemExit(f"cleanup v2 package performed a prohibited mutation: {key}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "archive_sha256": archive["sha256"],
                "inventory_sha256": inventory["sha256"],
                "tracks_required": current["tracks_required"],
                "registered_method_surface": current["registered_method_surface"],
                "cleanup_eligible_now": current["cleanup_eligible_models"],
                "models_deleted": current["models_deleted"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
