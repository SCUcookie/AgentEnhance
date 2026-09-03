#!/usr/bin/env python3
"""Validate the recovery2-aware post-Wave1 execution sequence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQUENCE = ROOT / "comparisons/wma-postwave1-release-sequence-prefreeze.v2.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    payload = json.loads(SEQUENCE.read_text(encoding="utf-8"))
    if payload.get("status") != "FROZEN_WHILE_WAVE1_RECOVERY2_RUNNING":
        raise SystemExit("post-Wave1 v2 sequence status mismatch")
    parent = ROOT / payload["supersedes"]["path"]
    if sha256_file(parent) != payload["supersedes"]["sha256"]:
        raise SystemExit("post-Wave1 parent sequence identity mismatch")
    phases = payload["phases"]
    if [row["order"] for row in phases] != [1, 2, 3, 4, 5]:
        raise SystemExit("post-Wave1 phase order mismatch")
    if phases[0]["id"] != "close_retain_and_admit_wave1_recovery2":
        raise SystemExit("phase 1 is not recovery2-aware")
    stage_paths: list[str] = []
    methods: list[str] = []
    for phase in phases:
        for stage in phase["stages"]:
            path = ROOT / stage["path"]
            if not path.is_file() or sha256_file(path) != stage["sha256"]:
                raise SystemExit(f"frozen stage identity mismatch: {path}")
            stage_paths.append(stage["path"])
        methods.extend(phase.get("method_order", []))
    if len(stage_paths) != len(set(stage_paths)) or len(stage_paths) != 17:
        raise SystemExit("post-Wave1 v2 stage cardinality mismatch")
    if len(methods) != len(set(methods)) or len(methods) != 12:
        raise SystemExit("post-Wave1 method cardinality mismatch")
    phase1 = "\n".join(stage_paths[:6])
    required_phase1 = (
        "recovery2-closure",
        "failure-history",
        "recovery2-result-admission",
    )
    if not all(value in phase1 for value in required_phase1):
        raise SystemExit("post-Wave1 phase 1 omits a recovery2 evidence stage")
    forbidden_phase1 = (
        "wave1-postprocess-prefreeze",
        "wave1-archive-prefreeze",
        "table-projection-prefreeze.v2",
    )
    if any(value in phase1 for value in forbidden_phase1):
        raise SystemExit("post-Wave1 phase 1 still targets recovery1 contracts")
    exclusion = payload["resource_exclusion"]
    if (
        exclusion["heavy_network_or_disk_stages"] != 1
        or exclusion["active_model_service_stacks"] != 1
        or exclusion["active_numerical_methods"] != 1
        or exclusion["archive_during_model_download_or_numerical_run"] is not False
    ):
        raise SystemExit("post-Wave1 resource exclusion mismatch")
    numeric = payload["numeric_admission"]
    if (
        numeric["minimum_seeds"] != [0, 1, 2]
        or numeric["samples_per_seed"] != 150
        or numeric["questions_per_seed"] != 7906
        or numeric["failed_units_allowed"] != 0
        or numeric["official_values_allowed_in_local_cells"] is not False
        or numeric["promoter"] != "scripts/promote_wma_local_results_v3.py"
    ):
        raise SystemExit("post-Wave1 numeric admission mismatch")
    serialized = SEQUENCE.read_text(encoding="utf-8")
    if "/data1/" in serialized or "/data2/" in serialized:
        raise SystemExit("post-Wave1 sequence embeds a host-specific absolute path")
    print(
        json.dumps(
            {
                "status": "PASS",
                "phases": len(phases),
                "bound_stages": len(stage_paths),
                "phase1_recovery2_stages": len(phases[0]["stages"]),
                "post_wave1_methods": len(methods),
                "numeric_rows_at_freeze": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
