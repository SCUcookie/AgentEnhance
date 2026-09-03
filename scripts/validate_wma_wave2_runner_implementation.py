#!/usr/bin/env python3
"""Validate the inert, fail-closed Wave-2 lifecycle and numerical runner package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons/wma-r1-wave2-runner-implementation-prefreeze.v1.json"
DEFECT_AUDIT = ROOT / "comparisons/wma-r1-wave2-lifecycle-preexecution-defect-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runtime_guard():
    path = ROOT / "scripts/wma_wave2_runtime_guard.py"
    spec = importlib.util.spec_from_file_location("wma_wave2_runtime_guard_validation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load runtime guard")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_IMPLEMENTATION_NO_EXECUTION_AUTHORIZATION":
        raise SystemExit("Wave-2 runner implementation contract is not inert-frozen")
    fixed = contract["fixed_inputs"]
    if fixed["seeds"] != [0, 1, 2] or (
        fixed["samples_per_seed"], fixed["sessions_per_seed"], fixed["qa_per_seed"]
    ) != (150, 2761, 7906):
        raise SystemExit("Wave-2 frozen denominator mismatch")
    if fixed["retrieval_top_k"] != 10 or fixed["answer_temperature"] != 0:
        raise SystemExit("Wave-2 matched protocol mismatch")

    guard = load_runtime_guard()
    methods = contract["methods"]
    if len(methods) != 8 or {row["baseline"] for row in methods} != set(guard.PROFILES):
        raise SystemExit("Wave-2 method set mismatch")
    for row in methods:
        profile = guard.profile_for(row["baseline"])
        expected = (
            profile["slug"],
            profile["service_profile"],
            profile["primary_embedding_model"],
            profile["primary_embedding_dim"],
        )
        observed = (
            row["slug"],
            row["service_profile"],
            row["embedding_model"],
            row["embedding_dimension"],
        )
        if observed != expected:
            raise SystemExit(f"runtime profile mismatch: {row['baseline']}")

    implementation = contract["implementation"]
    for label, record in implementation.items():
        path = ROOT / record["path"]
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise SystemExit(f"implementation digest mismatch: {label}")
    if implementation["unit_test"]["tests"] != 6:
        raise SystemExit("unexpected Wave-2 runtime test count")

    shell_paths = [
        ROOT / implementation[key]["path"]
        for key in (
            "start_services",
            "stop_services",
            "lifecycle_wrapper",
            "unit_runner",
            "full_method_scheduler",
        )
    ]
    subprocess.run(["bash", "-n", *map(str, shell_paths)], check=True)
    scheduler = (ROOT / implementation["full_method_scheduler"]["path"]).read_text(
        encoding="utf-8"
    )
    for required in (
        "LIFECYCLE_ROOT",
        "NUMERICAL_AUTHORIZATION",
        "FROZEN_BEFORE_EXECUTION",
        "accepted == 150",
        "rejected == 0",
        "infrastructure_failure == 0",
    ):
        if required not in scheduler:
            raise SystemExit(f"full scheduler missing fail-closed gate: {required}")
    unit = (ROOT / implementation["unit_runner"]["path"]).read_text(encoding="utf-8")
    for required in (
        "QWEN_VL_EMBED_REMOTE_IMAGES=1",
        "AGENTENHANCE_MIRIX_ENDPOINT_GUARD_ACTIVE",
        "HTTP/[0-9.]+\" [45][0-9][0-9]",
        "ATTACHMENT_COUNT_EXPECTED",
        "TMPDIR=",
    ):
        if required not in unit:
            raise SystemExit(f"unit runner missing guard: {required}")
    start = (ROOT / implementation["start_services"]["path"]).read_text(encoding="utf-8")
    gme_hash = implementation["gme_server_launcher"]["sha256"]
    if gme_hash not in start or "MODEL_SHA256SUMS" not in start:
        raise SystemExit("service launcher does not bind model or GME launcher identity")

    defect = json.loads(DEFECT_AUDIT.read_text(encoding="utf-8"))
    if defect.get("status") != "ACCEPTED_PREEXECUTION_DEFECT_AUDIT":
        raise SystemExit("missing accepted pre-execution defect audit")
    old = defect["audited_frozen_route"]
    if old["execution_performed"] or old["disposition"] != "SUPERSEDED_BEFORE_EXECUTION":
        raise SystemExit("invalid supersession evidence")
    for key in ("contract", "wrapper"):
        path = ROOT / old[key]
        if sha256_file(path) != old[f"{key}_sha256"]:
            raise SystemExit(f"superseded {key} identity mismatch")

    breadth = contract["result_breadth"]
    if breadth["method_seed_numeric_fields"] != 55 or breadth["frozen_slice_count"] != 53:
        raise SystemExit("result breadth contract mismatch")
    if contract["transition_rule"]["current"] != "Implementation may be packaged and validated without GPU use.":
        raise SystemExit("implementation contract unexpectedly authorizes execution")
    print(
        "validated Wave-2 runner: 8 methods, 5 service profiles, 55 fields/method, "
        "53 slices, no lifecycle or numerical authorization"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
