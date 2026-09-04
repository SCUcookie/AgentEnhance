#!/usr/bin/env python3
"""Validate the accepted inert SigLIP2 gate package and negative live preflight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons/memgallery-siglip2-materialization-gate-control-package-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit = json.loads(PATH.read_text(encoding="utf-8"))
    if audit.get("status") != "TERMINAL_ACCEPTED_INERT_CONTROL_PACKAGE":
        raise SystemExit("SigLIP2 gate control package is not accepted and inert")
    for row in audit["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"SigLIP2 gate control dependency drift: {row['path']}")
    transport = audit["transport"]
    if (
        transport["method"], transport["rate_limit_kbit_per_second"],
        transport["archive_bytes"], transport["archive_sha256"],
    ) != (
        "resumable-sftp", 4096, 17920,
        "5b899a413786c8854160611d1f9f1fe8eb2c1d1ff0df4848c2d84c06e23eacac",
    ):
        raise SystemExit("SigLIP2 gate transport identity drift")
    inventory = audit["package_inventory"]
    if (
        inventory["sha256"], inventory["signed_files"], inventory["verification"]
    ) != (
        "56610bd06300f48857295848ee3e1aa2822ec1dd2e00a044a5324115100681b5",
        10, "PASS",
    ):
        raise SystemExit("SigLIP2 gate package inventory drift")
    validation = audit["remote_validation"]
    if (validation["unit_tests_passed"], validation["unit_tests_failed"], validation["prefreeze_validator"]) != (4, 0, "PASS"):
        raise SystemExit("SigLIP2 remote validation drift")
    negative = audit["negative_live_gate"]
    if (
        negative["execute_flag_present"], negative["observed_exit_code"], negative["status"],
        negative["network_requests_started"], negative["mutation_performed"],
    ) != (False, 4, "PREFLIGHT_REJECTED", 0, False):
        raise SystemExit("SigLIP2 negative gate semantics drift")
    for key in (
        "model_target_absent_before", "model_target_absent_after",
        "evidence_root_absent_before", "evidence_root_absent_after",
    ):
        if negative[key] is not True:
            raise SystemExit(f"SigLIP2 negative gate changed filesystem state: {key}")
    state = audit["current_state"]
    if not state["control_package_accepted"] or state["materialization_authorized_now"]:
        raise SystemExit("SigLIP2 audit opens materialization prematurely")
    if any(state[key] != 0 for key in (
        "siglip2_downloaded_files", "siglip2_downloaded_bytes", "network_requests_started", "numeric_rows"
    )):
        raise SystemExit("SigLIP2 control-package audit contains external work")
    if state["official_values_used"] or state["cleanup_eligible"]:
        raise SystemExit("SigLIP2 control-package audit permits official values or cleanup")
    print(json.dumps({
        "status": "PASS", "audit_sha256": sha256_file(PATH),
        "archive_sha256": transport["archive_sha256"],
        "inventory_sha256": inventory["sha256"],
        "signed_files": inventory["signed_files"],
        "remote_tests_passed": validation["unit_tests_passed"],
        "negative_gate_exit_code": negative["observed_exit_code"],
        "network_requests": negative["network_requests_started"],
        "downloaded_bytes": state["siglip2_downloaded_bytes"],
        "materialization_authorized_now": state["materialization_authorized_now"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
