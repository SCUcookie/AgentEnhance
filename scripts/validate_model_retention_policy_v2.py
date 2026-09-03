#!/usr/bin/env python3
"""Validate the fail-closed model-retention policy before it can govern cleanup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "comparisons" / "model-retention-policy.v2.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

assert policy["schema_version"] == "agentenhance.model_retention_policy.v2"
assert policy["status"] == "FROZEN_BEFORE_ANY_MODEL_CLEANUP"
assert policy["supersedes_for_cleanup_decisions"].endswith("model-retention-policy.v1.json")
assert len(policy["retained_reproduction_bundle"]) >= 8
assert len(policy["eligible_weight_roots"]) == 2
assert all("AgentEnhance/cache/models/" in path for path in policy["eligible_weight_roots"])
assert any("Qwen3-VL-8B-Instruct@" in item for item in policy["protected_assets"])
assert any("Qwen3-VL-Embedding-2B@" in item for item in policy["protected_assets"])

preconditions = "\n".join(policy["cleanup_preconditions_all_required"])
for required in (
    "TERMINAL_ACCEPTED",
    "archive SHA-256",
    "immutable revision",
    "not a symlink",
    "open file descriptor",
    "DRY_RUN_ELIGIBLE",
):
    assert required in preconditions, required

phases = policy["two_phase_cleanup"]
assert set(phases) == {"phase_1", "phase_1_gate", "phase_2", "postcondition"}
assert "Atomically rename" in phases["phase_1"]
assert "explicit resolved quarantine path" in phases["phase_2"]
assert "both original and quarantine paths are absent" in phases["postcondition"]

record = "\n".join(policy["cleanup_record_required"])
for required in (
    "policy SHA-256",
    "immutable revision",
    "archive SHA-256",
    "device, inode, file count, byte count",
    "post-delete retained-evidence",
):
    assert required in record, required

fail_closed = "\n".join(policy["fail_closed_rules"])
for required in ("never authorizes cleanup", "no-longer-accessible", "active process reference"):
    assert required in fail_closed, required

print(
    json.dumps(
        {
            "status": "PASS",
            "policy": str(POLICY_PATH.relative_to(ROOT)),
            "policy_sha256": sha256_file(POLICY_PATH),
            "retained_bundle_items": len(policy["retained_reproduction_bundle"]),
            "cleanup_preconditions": len(policy["cleanup_preconditions_all_required"]),
            "cleanup_record_fields": len(policy["cleanup_record_required"]),
            "mutation_performed": False,
        },
        sort_keys=True,
    )
)
