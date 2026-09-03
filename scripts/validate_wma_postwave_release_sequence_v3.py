#!/usr/bin/env python3
"""Validate the recovery2-aware sequence with guarded Wave2 replacement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons/wma-postwave1-release-sequence-prefreeze.v3.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    if payload.get("status") != "FROZEN_WHILE_WAVE1_RECOVERY2_RUNNING":
        raise SystemExit("v3 sequence is not frozen")
    prior = payload["supersedes"]
    if sha256_file(ROOT / prior["path"]) != prior["sha256"]:
        raise SystemExit("v2 sequence identity mismatch")
    if payload["inherited_without_change"]["effective_phase_orders"] != [1, 3, 4, 5]:
        raise SystemExit("unexpected inherited phases")

    phase = payload["replacement_phase"]
    if phase.get("order") != 2 or len(phase.get("method_order", [])) != 8:
        raise SystemExit("invalid guarded Wave2 replacement")
    if len(set(phase["method_order"])) != 8:
        raise SystemExit("duplicate Wave2 method")
    for record in phase["inputs"]:
        if sha256_file(ROOT / record["path"]) != record["sha256"]:
            raise SystemExit(f"v3 bound input mismatch: {record['path']}")
    runner = json.loads(
        (ROOT / "comparisons/wma-r1-wave2-runner-implementation-prefreeze.v1.json").read_text(
            encoding="utf-8"
        )
    )
    if runner.get("status") != "FROZEN_IMPLEMENTATION_NO_EXECUTION_AUTHORIZATION":
        raise SystemExit("runner implementation must remain inert")
    audit = json.loads(
        (ROOT / "comparisons/wma-r1-wave2-runner-control-package-recovery1-audit.v1.json").read_text(
            encoding="utf-8"
        )
    )
    if audit.get("status") != "TERMINAL_ACCEPTED":
        raise SystemExit("runner recovery package is not accepted")
    if phase["accepted_control_inventory_sha256"] != audit["recovery"]["inventory_sha256"]:
        raise SystemExit("accepted runner inventory mismatch")
    protocol = phase["matched_protocol"]
    if (
        protocol["seeds"],
        protocol["samples_per_seed"],
        protocol["questions_per_seed"],
        protocol["failed_units_allowed"],
        protocol["method_seed_numeric_fields"],
        protocol["frozen_slices"],
    ) != ([0, 1, 2], 150, 7906, 0, 55, 53):
        raise SystemExit("guarded Wave2 matched protocol drift")
    if protocol["official_values_allowed_in_local_cells"]:
        raise SystemExit("official values cannot enter local cells")
    prohibited = "\n".join(payload["explicitly_prohibited"])
    for required in (
        "remote_wma_wave2_adapter_lifecycle.sh",
        "rejected non-recovery control extraction root",
        "numerical authorization",
        "claiming SOTA",
    ):
        if required not in prohibited:
            raise SystemExit(f"missing v3 prohibition: {required}")
    observation = payload["current_observation"]
    if observation["wave2_numeric_rows"] != 0 or observation["agentenhance_numeric_rows"] != 0:
        raise SystemExit("v3 was influenced by numerical outcomes")
    print(
        json.dumps(
            {
                "status": "PASS",
                "effective_phases": 5,
                "guarded_wave2_methods": 8,
                "numeric_rows_at_freeze": 0,
                "runner_control_inventory": phase["accepted_control_inventory_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
