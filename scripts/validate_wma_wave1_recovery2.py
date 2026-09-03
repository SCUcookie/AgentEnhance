#!/usr/bin/env python3
"""Validate the frozen Wave1 OOM diagnosis and recovery2 control identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFREEZE = ROOT / "comparisons/wma-r1-wave1-full-recovery2-prefreeze.v1.json"
CAPABILITY_RECOVERY = (
    ROOT / "comparisons/wma-r1-wave1-recovery2-capability-recovery1-prefreeze.v1.json"
)
CAPABILITY_AUDIT = (
    ROOT / "comparisons/wma-r1-wave1-recovery2-capability-recovery1-audit.v1.json"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PREFREEZE.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_RECOVERY_CAPABILITY_AND_FULL_RUN":
        raise SystemExit("Wave1 recovery2 is not pre-result frozen")
    diagnosis_path = ROOT / contract["diagnosis"]["path"]
    if sha256_file(diagnosis_path) != contract["diagnosis"]["sha256"]:
        raise SystemExit("Wave1 recovery1 OOM diagnosis digest mismatch")
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    if (
        diagnosis.get("status") != "TERMINAL_REJECTED"
        or diagnosis["parent_state"]["accepted_units"] != 71
        or diagnosis["parent_state"]["rejected_units"] != 1
        or diagnosis["parent_state"]["failed_unit_root"].split("/")[-1] != "072_css_03"
    ):
        raise SystemExit("Wave1 recovery1 failure state mismatch")
    change = contract["single_scientific_change"]
    if change != {**change, "field": "CHAT_GPU_MEMORY_UTILIZATION", "old": 0.95, "new": 0.90}:
        raise SystemExit("recovery2 scientific change mismatch")
    expected = {
        "capability_script": "5a06bd2255d37b4171ce5e6adde8cada6869571b339dd921ac19623784e59cc7",
        "full_scheduler_wrapper": "2df8a4eee3b0a3c121fea863e7f555d55ee2c50646c1cbf7d51700c6e0b1793b",
        "controller_wrapper": "4de657dd64da8d16df8164919aa7fd22a337f1c508a9b5dc02d52993d82f91ff",
    }
    for key, digest in expected.items():
        entry = contract["recovery_control"][key]
        if entry["sha256"] != digest or sha256_file(ROOT / entry["path"]) != digest:
            raise SystemExit(f"recovery2 control digest mismatch: {key}")
    if contract["full_recovery"]["parent_numeric_evidence_reused"] is not False:
        raise SystemExit("parent partial evidence must not be reused")
    if contract["full_recovery"]["fresh_full_runs"] != 12:
        raise SystemExit("full recovery cardinality mismatch")
    capability_recovery = json.loads(CAPABILITY_RECOVERY.read_text(encoding="utf-8"))
    if capability_recovery.get("status") != "FROZEN_BEFORE_CAPABILITY_RECOVERY":
        raise SystemExit("capability path recovery is not frozen")
    path_audit = ROOT / capability_recovery["diagnosis"]["path"]
    if sha256_file(path_audit) != capability_recovery["diagnosis"]["sha256"]:
        raise SystemExit("capability path audit digest mismatch")
    path_payload = json.loads(path_audit.read_text(encoding="utf-8"))
    if (
        path_payload.get("status") != "TERMINAL_REJECTED_BEFORE_NUMERIC_EXECUTION"
        or path_payload["observed_state"]["numeric_results_admitted"] is not False
        or path_payload["observed_state"]["services_stopped"] is not True
        or capability_recovery["single_change"]["scientific_change"] is not False
        or capability_recovery["capability_script"]["sha256"]
        != expected["capability_script"]
    ):
        raise SystemExit("capability path recovery state mismatch")
    capability_audit = json.loads(CAPABILITY_AUDIT.read_text(encoding="utf-8"))
    if (
        capability_audit.get("status") != "TERMINAL_ACCEPTED"
        or capability_audit.get("main_comparison_eligible") is not False
        or capability_audit.get("numeric_results_admitted") is not False
        or capability_audit["frozen_input"]["sample_id"] != "css_03"
        or capability_audit["frozen_input"]["sessions"] != 6
        or capability_audit["frozen_input"]["qa"] != 52
        or capability_audit["frozen_input"]["chat_gpu_memory_utilization"] != 0.90
        or capability_audit["observed"]["cuda_oom_count"] != 0
        or capability_audit["observed"]["http_500_count"] != 0
        or capability_audit["observed"]["services_stopped"] is not True
        or capability_audit["independent_verification"]["root_inventory_verified"] is not True
        or capability_audit["independent_verification"]["unit_inventory_verified"] is not True
    ):
        raise SystemExit("capability acceptance audit mismatch")
    print(
        json.dumps(
            {
                "status": "PASS",
                "parent_accepted_diagnostic_units": 71,
                "parent_rejected_units": 1,
                "capability_sample": "072_css_03",
                "gpu_memory_utilization": 0.90,
                "fresh_full_runs": 12,
                "parent_numeric_evidence_reused": False,
                "capability_path_recovery_numeric_rows": 0,
                "capability_status": "TERMINAL_ACCEPTED",
                "numeric_rows_added": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
