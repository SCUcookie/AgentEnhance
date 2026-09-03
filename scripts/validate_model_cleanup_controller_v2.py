#!/usr/bin/env python3
"""Validate the cross-track successor model-cleanup controller."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons" / "model-cleanup-controller-prefreeze.v2.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(entry: dict) -> None:
    if sha256_file(ROOT / entry["path"]) != entry["sha256"]:
        raise SystemExit(f"v2 cleanup dependency drift: {entry['path']}")


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_ANY_PROJECT_OWNED_MODEL_CLEANUP":
        raise SystemExit("v2 cleanup controller is not frozen")
    verify(contract["supersedes"])
    verify(contract["unchanged_inner_controller"])
    gate = contract["cross_track_gate"]
    for key in ("implementation", "tests", "global_contract", "wma_table_spec"):
        verify(gate[key])
    if gate["tests"]["passed"] != 3:
        raise SystemExit("v2 cleanup test count drift")
    if gate["required_record"] != "/data1/2026/ldh/AgentEnhance/runs/baseline-cross-track-completion-20260904-v1/cross-track-completion.json":
        raise SystemExit("global completion record path drift")

    surfaces = {row["track_id"]: row for row in contract["complete_surfaces"]}
    if set(surfaces) != {
        "wma-lifecycle-matched-v1",
        "memgallery-static-matched-v1",
        "causal-locomo-safety-v1",
    }:
        raise SystemExit("v2 cleanup track surface drift")
    if surfaces["wma-lifecycle-matched-v1"]["registered_public_or_control_methods"] != 29:
        raise SystemExit("WMA cleanup surface count drift")
    if surfaces["memgallery-static-matched-v1"]["registered_methods"] != 14:
        raise SystemExit("Mem-Gallery cleanup surface count drift")
    if surfaces["causal-locomo-safety-v1"]["registered_methods"] != 7:
        raise SystemExit("Causal-LoCoMo cleanup surface count drift")

    fields = "\n".join(contract["global_record_required_fields"])
    for phrase in ("all three tracks", "terminal-accepted", "all denominators", "official_values_used false"):
        if phrase not in fields:
            raise SystemExit(f"v2 cleanup global record is underspecified: {phrase}")
    current = contract["current_state"]
    if any(current[key] for key in ("wma_complete", "memgallery_complete", "causal_locomo_complete", "global_completion_record_present")):
        raise SystemExit("v2 cleanup freeze falsely records completion")
    if current["project_owned_models_cleanup_eligible"] != 0 or current["mutation_performed"]:
        raise SystemExit("v2 cleanup freeze authorizes a current mutation")
    for phrase in ("Only scripts/model_cleanup_controller_v2.py", "direct invocation is prohibited", "authorizes no present"):
        if phrase not in contract["authorization"]:
            raise SystemExit(f"v1 fallback was not closed: {phrase}")

    source = (ROOT / gate["implementation"]["path"]).read_text(encoding="utf-8")
    for phrase in (
        "GLOBAL_COMPLETION_RECORD",
        "EXPECTED_METHODS",
        "official_values_used",
        "all_denominators_reconciled",
        "validate_track_archive",
        "base.preflight",
        "base.quarantine",
        "base.delete_quarantine",
    ):
        if phrase not in source:
            raise SystemExit(f"v2 cleanup implementation omits guard: {phrase}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "controller_sha256": gate["implementation"]["sha256"],
                "tracks": len(surfaces),
                "registered_method_surface": 29 + 14 + 7,
                "cleanup_eligible_now": current["project_owned_models_cleanup_eligible"],
                "mutation_performed": current["mutation_performed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
