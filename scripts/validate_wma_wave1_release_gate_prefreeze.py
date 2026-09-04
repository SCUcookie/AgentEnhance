#!/usr/bin/env python3
"""Validate the frozen read-only WMA Wave1 recovery2 release gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "comparisons/wma-r1-wave1-release-gate-prefreeze.v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("wma_wave1_release_gate", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load release gate implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_READ_ONLY_AWAITING_CONTROLLER_TERMINAL":
        raise SystemExit("release gate status drift")
    for parent in contract["bound_inputs"]:
        if sha256(ROOT / parent["path"]) != parent["sha256"]:
            raise SystemExit(f"release gate parent drift: {parent['path']}")
    implementation = contract["implementation"]
    implementation_path = ROOT / implementation["path"]
    if sha256(implementation_path) != implementation["sha256"]:
        raise SystemExit("release gate implementation drift")
    test = contract["synthetic_test"]
    test_path = ROOT / test["path"]
    if sha256(test_path) != test["sha256"]:
        raise SystemExit("release gate synthetic test drift")
    test_source = test_path.read_text(encoding="utf-8")
    if not (test_source.count("    def test_") == test["tests"] == 5):
        raise SystemExit("release gate synthetic test count drift")

    gate = load_module(implementation_path)
    fixed = contract["fixed_surface"]
    if (
        list(gate.METHODS) != fixed["methods"]
        or list(gate.SEEDS) != fixed["seeds"]
        or not (len(gate.expected_progress()) == fixed["method_seed_runs"] == 12)
        or not (gate.EXPECTED_UNITS == fixed["units_per_run"] == 150)
        or not (len(gate.expected_progress()) * gate.EXPECTED_UNITS == fixed["accepted_units_total"] == 1800)
        or not (gate.EXPECTED_SESSIONS == fixed["sessions_per_run"] == 2761)
        or not (len(gate.expected_progress()) * gate.EXPECTED_SESSIONS == fixed["accepted_sessions_total"] == 33132)
        or not (gate.EXPECTED_QA == fixed["qa_per_run"] == 7906)
        or not (len(gate.expected_progress()) * gate.EXPECTED_QA == fixed["accepted_qa_total"] == 94872)
        or gate.UNIT_INVENTORY_SHA256 != fixed["unit_inventory_sha256"]
        or gate.WMA_SOURCE_COMMIT != fixed["wma_source_commit"]
        or gate.DATASET_MANIFEST_SHA256 != fixed["dataset_manifest_sha256"]
        or gate.RECOVERY_FULL_SCHEDULER_SHA256 != fixed["recovery_full_scheduler_sha256"]
        or gate.MIN_DATA1_FREE_BYTES != contract["required_checks"]["storage"]["data1_minimum_free_bytes"]
        or gate.ARCHIVE_RESERVE_BYTES != 10737418240
    ):
        raise SystemExit("release gate fixed surface drift")
    expected_controller = str(Path(fixed["controller_root"]).name)
    if gate.CONTROLLER_NAME != expected_controller:
        raise SystemExit("release gate controller identity drift")
    if sorted(gate.BLOCKED_PORTS) != contract["required_checks"]["quiescence"]["blocked_ports_checked"]:
        raise SystemExit("release gate port surface drift")

    data1_root = Path("/data1/2026/ldh/AgentEnhance")
    data2_root = Path("/data2/2026/ldh/AgentEnhance")
    future = [
        data1_root / "runs/wma-r1-wave1-three-seed-summaries-recovery2-20260904-v1",
        data1_root / "runs/wma-r1-wave1-table-projection-recovery2-20260904-v3",
        data1_root / "runs/wma-r1-wave1-local-result-admission-recovery2-20260904-v1",
        data2_root / "archives/wma-r1-wave1-recovery2-20260904-v1",
        data2_root / "archives/wma-r1-wave1-table-projection-recovery2-20260904-v3",
        data2_root / "archives/wma-r1-wave1-failure-history-20260904-v1",
    ]
    if [str(path) for path in future] != contract["required_checks"]["future_roots"]["must_all_be_absent"]:
        raise SystemExit("release gate future-root surface drift")

    source = implementation_path.read_text(encoding="utf-8")
    forbidden_mutations = (".write_text(", ".write_bytes(", ".mkdir(", ".unlink(", "shutil.rmtree(", "os.remove(")
    if any(token in source for token in forbidden_mutations):
        raise SystemExit("release gate implementation contains a filesystem mutation")
    if "--skip-unit-hashes" in source or "verify_unit_hashes" in source:
        raise SystemExit("release gate permits accepted execution without unit hashes")
    report = contract["report_contract"]
    if (
        report["accepted_status"] != "TERMINAL_ACCEPTED"
        or not report["accepted_only_after_every_check"]
        or not report["unit_hashes_mandatory"]
        or report["scores_observed"] != 0
        or report["official_values_used"]
        or report["mutation_performed"]
    ):
        raise SystemExit("release gate report or claim boundary drift")
    current = contract["current_observation"]
    if current["controller_state"] != "RUNNING" or current["execution_authorized_now"] or current["audit_run_now"]:
        raise SystemExit("release gate current-state disclosure drift")

    print(json.dumps({
        "status": "PASS",
        "method_seed_runs": fixed["method_seed_runs"],
        "accepted_units_required": fixed["accepted_units_total"],
        "accepted_sessions_required": fixed["accepted_sessions_total"],
        "accepted_qa_required": fixed["accepted_qa_total"],
        "future_roots_required_absent": len(future),
        "synthetic_tests": test["tests"],
        "scores_observed": 0,
        "mutation_performed": False,
        "contract_sha256": sha256(CONTRACT_PATH),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
