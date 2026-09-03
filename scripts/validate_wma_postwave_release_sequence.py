#!/usr/bin/env python3
"""Validate the frozen post-Wave1 evidence-first execution sequence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEQUENCE = ROOT / "comparisons/wma-postwave1-release-sequence-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    payload = json.loads(SEQUENCE.read_text(encoding="utf-8"))
    assert payload["status"] == "FROZEN_WHILE_WAVE1_RUNNING"
    phases = payload["phases"]
    assert [row["order"] for row in phases] == [1, 2, 3, 4, 5]
    assert phases[0]["id"] == "close_and_retain_wave1"
    stage_paths = []
    methods = []
    for phase in phases:
        for stage in phase["stages"]:
            path = ROOT / stage["path"]
            assert path.is_file()
            assert stage["sha256"] == sha256_file(path)
            stage_paths.append(stage["path"])
        methods.extend(phase.get("method_order", []))
    assert len(stage_paths) == len(set(stage_paths)) == 15
    assert len(methods) == len(set(methods)) == 12
    exclusion = payload["resource_exclusion"]
    assert exclusion["heavy_network_or_disk_stages"] == 1
    assert exclusion["active_model_service_stacks"] == 1
    assert exclusion["active_numerical_methods"] == 1
    assert exclusion["archive_during_model_download_or_numerical_run"] is False
    numeric = payload["numeric_admission"]
    assert numeric["minimum_seeds"] == [0, 1, 2]
    assert numeric["samples_per_seed"] == 150
    assert numeric["questions_per_seed"] == 7906
    assert numeric["failed_units_allowed"] == 0
    assert numeric["official_values_allowed_in_local_cells"] is False
    serialized = SEQUENCE.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized
    print(
        json.dumps(
            {
                "status": "PASS",
                "phases": len(phases),
                "bound_stages": len(stage_paths),
                "post_wave1_methods": len(methods),
                "numeric_rows_added": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
