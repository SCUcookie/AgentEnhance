#!/usr/bin/env python3
"""Validate frozen Wave-3 environment and lifecycle-design contracts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "comparisons" / "wma-r1-wave3-environment-materialization-prefreeze.v2.json"
LIFECYCLE_PATH = ROOT / "comparisons" / "wma-r1-wave3-lifecycle-design-prefreeze.v2.json"
CONTROL_AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave3-control-package-audit.v2.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_requirements(path: Path) -> list[str]:
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        row = raw.strip()
        if not row or row.startswith("#"):
            continue
        assert "==" in row and not any(op in row for op in (">=", "<=", "~=", "!="))
        rows.append(row)
    return rows


environment = load(ENV_PATH)
lifecycle = load(LIFECYCLE_PATH)
control_audit = load(CONTROL_AUDIT_PATH)

assert environment["status"] == "FROZEN_BEFORE_ENVIRONMENT_MATERIALIZATION"
assert environment["supersedes"]["execution_authorized"] is False
assert environment["supersedes"]["sha256"] == sha256_file(
    ROOT / environment["supersedes"]["path"]
)
assert "no lifecycle, numerical" in environment["scientific_evidence_role"]
for gate in environment["prior_gates"]:
    assert gate["sha256"] == sha256_file(ROOT / gate["path"])
assert environment["materializer"]["sha256"] == sha256_file(
    ROOT / environment["materializer"]["path"]
)
assert environment["python"]["executable"] == "${AGENT_ENHANCE_PYTHON39}"
assert environment["python"]["required_major_minor"] == "3.9"
assert environment["resolution_policy"]["network_retry_count"] == 0
assert environment["resolution_policy"]["offline_install"] is True
assert environment["execution_contract"]["retry_count"] == 0
assert environment["execution_contract"]["gpu_count"] == 0

methods = {row["method_id"]: row for row in environment["methods"]}
assert set(methods) == {"memoryos", "memgas"}
for row in methods.values():
    requirements = ROOT / row["requirements"]
    assert row["requirements_sha256"] == sha256_file(requirements)
    assert len(exact_requirements(requirements)) >= 20
    for key in ("environment_root", "wheelhouse_root", "evidence_root"):
        assert row[key].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/")
assert "faiss-cpu==1.8.0.post1" in exact_requirements(
    ROOT / methods["memoryos"]["requirements"]
)
assert "torch==2.3.1+cpu" in exact_requirements(
    ROOT / methods["memoryos"]["requirements"]
)
assert "sentence-transformers==2.2.2" in exact_requirements(
    ROOT / methods["memgas"]["requirements"]
)
assert "torchvision==0.18.1+cpu" in exact_requirements(
    ROOT / methods["memgas"]["requirements"]
)
assert "nltk==3.9.1" in exact_requirements(ROOT / methods["memgas"]["requirements"])
assert any("vllm==0.5.3.post1" in row for row in methods["memgas"]["omitted_official_extras"])

assert lifecycle["status"] == "FROZEN_DESIGN_NOT_AUTHORIZED_FOR_EXECUTION"
assert lifecycle["supersedes"]["execution_authorized"] is False
assert lifecycle["supersedes"]["sha256"] == sha256_file(
    ROOT / lifecycle["supersedes"]["path"]
)
assert "no benchmark, superiority, or SOTA" in lifecycle["scientific_evidence_role"]
for gate in lifecycle["prior_gates"]:
    assert gate["sha256"] == sha256_file(ROOT / gate["path"])
implementation = lifecycle["frozen_implementation"]
for path_key, hash_key in (
    ("checker", "checker_sha256"),
    ("remote_wrapper", "remote_wrapper_sha256"),
    ("sitecustomize", "sitecustomize_sha256"),
    ("memoryos_adapter", "memoryos_adapter_sha256"),
    ("memgas_adapter", "memgas_adapter_sha256"),
):
    assert implementation[hash_key] == sha256_file(ROOT / implementation[path_key])
assert lifecycle["fixed_inputs"]["total_pairs"] == 12
assert lifecycle["fixed_inputs"]["total_turns"] == 24
assert re.fullmatch(r"[0-9a-f]{64}", lifecycle["fixed_inputs"]["image_sha256"])
assert lifecycle["execution_contract"]["unit_rerun_count"] == 0
assert lifecycle["execution_contract"]["parallel_runs"] == 1
assert "not executable yet" in lifecycle["authorization_gate"]

for path in (ENV_PATH, LIFECYCLE_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

assert control_audit["status"] == "TERMINAL_ACCEPTED_FOR_PREREQUISITE_EXECUTION_ONLY"
assert control_audit["supersedes"]["execution_authorized"] is False
assert control_audit["supersedes"]["sha256"] == sha256_file(
    ROOT / control_audit["supersedes"]["path"]
)
assert control_audit["archive"]["sftp_rate_limit_kbit_per_second"] == 4096
assert control_audit["file_count"] == len(control_audit["file_inventory"]) == 16
assert len({row["path"] for row in control_audit["file_inventory"]}) == 16
assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in control_audit["file_inventory"])
assert control_audit["independent_checks"]["memgas_torchvision_pin_present"] == "torchvision==0.18.1+cpu"
assert control_audit["independent_checks"]["memgas_nltk_pin_present"] == "nltk==3.9.1"
assert control_audit["independent_checks"]["wave3_environment_or_lifecycle_processes_at_audit"] == 0
serialized = CONTROL_AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

print(
    json.dumps(
        {
            "status": "PASS",
            "environment_methods": sorted(methods),
            "lifecycle_pairs": lifecycle["fixed_inputs"]["total_pairs"],
            "control_package_files": control_audit["file_count"],
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
