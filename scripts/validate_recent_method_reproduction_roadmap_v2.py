#!/usr/bin/env python3
"""Validate the alias-resolved recent-method reproduction roadmap."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / "comparisons" / "recent-method-reproduction-roadmap.v1.json"
V2_PATH = ROOT / "comparisons" / "recent-method-reproduction-roadmap.v2.json"
IDENTITY_PATH = ROOT / "comparisons" / "omnimem-method-identity-audit.v1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


v1 = load(V1_PATH)
v2 = load(V2_PATH)
identity = load(IDENTITY_PATH)

assert v2["status"] == "FROZEN_BEFORE_ANY_ACCEPTED_WMA_MAIN_RESULT"
assert v2["superseded_roadmap_sha256"] == sha256_file(V1_PATH)
assert v2["identity_audit"]["sha256"] == sha256_file(IDENTITY_PATH)
assert v2["validator"]["sha256"] == sha256_file(ROOT / v2["validator"]["path"])
assert identity["status"] == "TERMINAL_ACCEPTED_IDENTITY_ALIAS"

canonical = identity["identity_decision"]["canonical_local_method_id"]
alias = identity["identity_decision"]["deprecated_alias"]
assert canonical == v2["identity_audit"]["canonical_method_id"]
assert alias == v2["identity_audit"]["deprecated_alias"]
assert identity["identity_decision"]["independent_method_count"] == 1
assert identity["identity_decision"]["separate_numerical_run_for_deprecated_alias"] is False

v1_methods = [method for group in v1["groups"] for method in group["methods"]]
assert len(v1_methods) == v1["coverage"]["recent_public_methods"]
assert v1_methods.count(canonical) == 1
assert v1_methods.count(alias) == 1

adjustments = {row["group_id"]: row for row in v2["effective_group_adjustments"]}
assert adjustments["wave2_registered_wma"]["methods"].count(canonical) == 1
assert alias not in adjustments["wave2_registered_wma"]["methods"]
assert alias not in adjustments["wave3_official_repo_adapter"]["methods"]
assert set(adjustments["wave3_official_repo_adapter"]["methods"]) == {"memoryos", "memgas"}

resolved = {canonical if method == alias else method for method in v1_methods}
coverage = v2["effective_coverage"]
assert coverage["registered_recent_rows"] == len(v1_methods)
assert coverage["resolved_unique_method_entities"] == len(resolved) == 26
assert coverage["deprecated_alias_rows"] == 1
assert coverage["wma_track_unique_candidates"] == v1["coverage"]["wma_track_candidates"] - 1

remote = v2["source_discovery_snapshot"]["read_only_git_ls_remote"]
assert remote["https://github.com/aiming-lab/OmniMem.git"] == "REPOSITORY_NOT_FOUND"
assert all(
    len(value) == 40 and all(char in "0123456789abcdef" for char in value)
    for key, value in remote.items()
    if key != "https://github.com/aiming-lab/OmniMem.git"
)

assert "Official paper values" in v2["numeric_policy"]
assert any("second method" in item for item in v2["prohibited_actions"])

print(
    json.dumps(
        {
            "status": "PASS",
            "registered_recent_rows": len(v1_methods),
            "resolved_unique_method_entities": len(resolved),
            "deprecated_alias": alias,
            "canonical_method_id": canonical,
            "numeric_rows_added": 0,
        },
        sort_keys=True,
    )
)
