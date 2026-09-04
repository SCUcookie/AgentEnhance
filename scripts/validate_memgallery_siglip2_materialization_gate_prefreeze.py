#!/usr/bin/env python3
"""Validate the frozen fail-closed SigLIP2 materialization gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "comparisons/memgallery-siglip2-materialization-gate-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = json.loads(PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_IMPLEMENTATION_AWAITING_WAVE1_AND_DATA_INTEGRITY":
        raise SystemExit("SigLIP2 gate is not frozen before resource release")
    for row in contract["bound_inputs"]:
        if sha256_file(ROOT / row["path"]) != row["sha256"]:
            raise SystemExit(f"SigLIP2 gate dependency drift: {row['path']}")
    checks = contract["preflight_checks_in_order"]
    if len(checks) != 9:
        raise SystemExit("SigLIP2 preflight check cardinality drift")
    for phrase in ("Wave-1", "ports 18113", "four payload hashes", "1711 questions", "ownership ledger v2", "target and evidence root are absent"):
        if not any(phrase in row for row in checks):
            raise SystemExit(f"SigLIP2 preflight check missing: {phrase}")
    execution = contract["execution"]
    argv = execution["argv"]
    if argv[-1] != "--execute" or "scripts/gate_memgallery_siglip2_materialization.py" not in argv:
        raise SystemExit("SigLIP2 execution bypasses the frozen gate")
    if execution["network_retry_count"] != 0 or execution["parallel_downloads"] != 1 or execution["gpu_count"] != 0:
        raise SystemExit("SigLIP2 execution resource contract drift")
    tests = contract["test_evidence"]
    if tests != {
        "tests_passed": 4,
        "covered_invariants": [
            "active WMA process rejection",
            "listening model-service port rejection",
            "missing data-integrity acceptance rejection",
            "complete released-state preflight acceptance without a network request",
        ],
        "network_requests": 0,
        "downloaded_bytes": 0,
    }:
        raise SystemExit("SigLIP2 gate test evidence drift")
    state = contract["current_state"]
    if any(state[key] for key in (
        "wave1_terminal_accepted", "data_integrity_terminal_accepted", "preflight_accepted", "mutation_performed"
    )):
        raise SystemExit("SigLIP2 gate contains premature acceptance or mutation")
    if any(state[key] != 0 for key in ("network_requests_started", "downloaded_bytes", "numeric_rows")):
        raise SystemExit("SigLIP2 gate contains premature external work")
    if "not yet authorized" not in contract["authorization"]:
        raise SystemExit("SigLIP2 external authorization boundary missing")
    print(json.dumps({
        "status": "PASS", "contract_sha256": sha256_file(PATH),
        "preflight_checks": len(checks), "tests_passed": tests["tests_passed"],
        "network_requests": state["network_requests_started"],
        "downloaded_bytes": state["downloaded_bytes"],
        "mutation_performed": state["mutation_performed"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
