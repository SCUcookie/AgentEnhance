#!/usr/bin/env python3
"""Validate the pre-complete-seed Wave1 recovery2 result admission contract."""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from frozen_source_successor import render_successor  # noqa: E402


CONTRACT = ROOT / "comparisons/wma-r1-wave1-recovery2-result-admission-prefreeze.v1.json"
EXPECTED_IDS = {"wma-mmfu-single", "wma-simplemem", "wma-m2a", "wma-vilomem"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(entry: dict[str, object]) -> Path:
    path = ROOT / str(entry["path"])
    if not path.is_file() or sha256_file(path) != entry["sha256"]:
        raise SystemExit(f"frozen identity mismatch: {path}")
    return path


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_COMPLETE_SEED_RESULTS":
        raise SystemExit("Wave1 result admission contract status mismatch")
    timing = contract["timing_disclosure"]
    if (
        timing["complete_seed_aggregates"] != 0
        or timing["three_seed_method_summaries"] != 0
        or timing["admitted_result_rows"] != 0
        or timing["scores_inspected_to_define_identity"] is not False
    ):
        raise SystemExit("identity timing disclosure is not pre-complete-seed and result-free")
    for entry in contract["parents"].values():
        resolve(entry)

    wrapper = importlib.import_module("promote_wma_local_results_v3")
    parent = resolve(contract["implementation"]["parent_promoter"])
    successor = resolve(contract["implementation"]["successor_promoter"])
    if successor != Path(wrapper.__file__).resolve():
        raise SystemExit("successor promoter path mismatch")
    source = render_successor(
        parent,
        wrapper.PARENT_SHA256,
        wrapper.REPLACEMENTS,
        wrapper.RENDERED_SHA256,
    )
    compile(source, "<promote_wma_local_results_v3>", "exec")
    if hashlib.sha256(source.encode()).hexdigest() != contract["implementation"][
        "successor_promoter"
    ]["rendered_sha256"]:
        raise SystemExit("rendered successor promoter mismatch")

    identities = contract["identities"]
    if set(identities) != EXPECTED_IDS:
        raise SystemExit("Wave1 identity implementation set mismatch")
    shared = contract["shared_identity"]
    expected_run_ids = {
        method: f"wma-r1-three-seed-{method.removeprefix('wma-')}-recovery2-20260904-v1"
        for method in EXPECTED_IDS
    }
    for implementation_id, entry in identities.items():
        identity = json.loads(resolve(entry).read_text(encoding="utf-8"))
        if identity.get("status") != "FROZEN_BEFORE_COMPLETE_SEED_RESULTS":
            raise SystemExit(f"identity status mismatch: {implementation_id}")
        if identity.get("implementation_id") != implementation_id:
            raise SystemExit(f"identity implementation mismatch: {implementation_id}")
        if identity.get("run_id") != expected_run_ids[implementation_id]:
            raise SystemExit(f"identity run mismatch: {implementation_id}")
        for field, expected in shared.items():
            if identity.get(field) != expected:
                raise SystemExit(f"shared identity mismatch: {implementation_id}:{field}")
        if identity.get("retriever_id") != entry["retriever_id"]:
            raise SystemExit(f"retriever identity mismatch: {implementation_id}")
        if not str(identity.get("adapter_code_identity", "")).strip():
            raise SystemExit(f"blank adapter identity: {implementation_id}")

    template = ROOT / "comparisons/reproduced-results.v2.csv"
    with template.open(encoding="utf-8", newline="") as handle:
        if list(csv.DictReader(handle)):
            raise SystemExit("canonical successor template already contains admitted rows")
    if contract["output"]["expected_rows_after_all_four_methods_are_accepted"] != 4 * 3 * 55:
        raise SystemExit("expected Wave1 admission row cardinality mismatch")
    print(
        json.dumps(
            {
                "status": "PASS",
                "identities": len(identities),
                "complete_seed_results_at_freeze": 0,
                "admitted_rows_at_freeze": 0,
                "future_rows_after_acceptance": 660,
                "numeric_gate_changes": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
