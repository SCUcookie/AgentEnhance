#!/usr/bin/env python3
"""Validate the frozen post-WMA static and causal completion boundary."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "comparisons" / "post-wma-cross-track-completion-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    contract = read_json(CONTRACT_PATH)
    if contract.get("status") != "FROZEN_BEFORE_ANY_ACCEPTED_MAIN_COMPARISON_RESULT_OUTSIDE_WMA":
        raise SystemExit("cross-track completion contract is not frozen")

    for item in contract["bound_inputs"]:
        path = ROOT / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise SystemExit(f"bound input identity mismatch: {item['path']}")

    tracks = {item["track_id"]: item for item in contract["tracks"]}
    if set(tracks) != {"memgallery-static-matched-v1", "causal-locomo-safety-v1"}:
        raise SystemExit("unexpected post-WMA track set")

    static = tracks["memgallery-static-matched-v1"]
    expected_recent = [
        "a-mem",
        "memoryos",
        "universalrag",
        "ngm",
        "augustus",
        "m2a",
        "v-mem",
    ]
    if static["recent_method_order"] != expected_recent:
        raise SystemExit("static recent-method order drift")
    expected_controls = [
        "no-memory",
        "full-memory-text",
        "full-memory-mm",
        "fifo-recent",
        "bm25",
        "naive-rag",
        "hybrid-rag",
    ]
    if static["control_order"] != expected_controls:
        raise SystemExit("static control order drift")

    register_path = ROOT / "comparisons" / "baseline-register.v3.csv"
    with register_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    registered_static_recent = [
        row["method_id"]
        for row in rows
        if row["year"] in {"2025", "2026"}
        and "memgallery-static-matched-v1" in row["common_track"]
        and row["comparison_tier"] != "PROPOSED"
        and row["method_id"] != "omnimem-agent"
    ]
    if registered_static_recent != expected_recent:
        raise SystemExit(
            f"registered static recent methods do not match contract: {registered_static_recent}"
        )
    if "omnimem-agent" not in static["identity_exclusions"]:
        raise SystemExit("deprecated OmniMem alias is not excluded")
    if static["matched_protocol"]["questions_expected"] != 1711:
        raise SystemExit("static denominator drift")
    if static["matched_protocol"]["official_values_allowed_in_local_cells"]:
        raise SystemExit("official values cannot enter static local cells")

    causal = tracks["causal-locomo-safety-v1"]
    expected_causal = [
        "cmi-no-memory",
        "cmi-full-history",
        "cmi-vector-memory",
        "cmi-summary-memory",
        "cmi-reflection-memory",
        "cmi-graph-memory",
        "cmi",
    ]
    if causal["method_order"] != expected_causal:
        raise SystemExit("causal method order drift")
    protocol = causal["matched_protocol"]
    if (protocol["examples_expected"], protocol["methods_expected"], protocol["predictions_expected_per_complete_attempt"]) != (87, 7, 609):
        raise SystemExit("causal denominator drift")
    if protocol["official_or_development_values_allowed_in_local_main_cells"]:
        raise SystemExit("development or official values cannot enter causal main cells")

    cmi_audit = read_json(ROOT / "comparisons" / "cmi-r2-full-recovery1-audit.v1.json")
    if cmi_audit["main_comparison_eligible"] or cmi_audit["evidence_role"] != "development foundation only":
        raise SystemExit("CMI development evidence boundary drift")
    if any((a["examples"], a["methods"], a["predictions"], a["failures"]) != (87, 7, 609, 0) for a in cmi_audit["attempts"]):
        raise SystemExit("CMI development denominator evidence drift")

    results_path = ROOT / "comparisons" / "reproduced-results.v2.csv"
    with results_path.open(encoding="utf-8", newline="") as handle:
        admitted = list(csv.DictReader(handle))
    if admitted:
        raise SystemExit("contract must remain frozen before admitted WMA rows")
    state = contract["current_numeric_state"]
    if any(state[key] != 0 for key in (
        "wma_admitted_rows",
        "memgallery_static_admitted_rows",
        "causal_locomo_main_admitted_rows",
        "agentenhance_public_rows",
    )):
        raise SystemExit("main numeric state at freeze must be zero")
    if state["cmi_development_rows"] != 7:
        raise SystemExit("unexpected CMI development-row disclosure")

    prohibited = "\n".join(contract["explicitly_prohibited"])
    for phrase in ("after WMA alone", "source-reported", "cleaning a model", "claiming SOTA"):
        if phrase not in prohibited:
            raise SystemExit(f"missing cross-track prohibition: {phrase}")
    if "every dependent method across WMA, Mem-Gallery and Causal-LoCoMo" not in contract["cleanup_gate"]:
        raise SystemExit("cleanup gate does not cover every comparison track")

    print(
        json.dumps(
            {
                "status": "PASS",
                "static_recent_methods": len(expected_recent),
                "static_controls": len(expected_controls),
                "causal_methods": len(expected_causal),
                "main_rows_at_freeze": 0,
                "development_rows_disclosed": state["cmi_development_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
