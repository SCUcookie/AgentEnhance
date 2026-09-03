#!/usr/bin/env python3
"""Validate the ACL-2026 source-discovery roadmap revision."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V2_PATH = ROOT / "comparisons" / "recent-method-reproduction-roadmap.v2.json"
V3_PATH = ROOT / "comparisons" / "recent-method-reproduction-roadmap.v3.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


v3 = load(V3_PATH)
audit_path = ROOT / v3["source_discovery_audit"]["path"]
registry_path = ROOT / v3["registry"]["path"]
audit = load(audit_path)

assert v3["status"] == "FROZEN_BEFORE_ANY_ACCEPTED_WMA_MAIN_RESULT"
assert v3["superseded_roadmap_sha256"] == sha256_file(V2_PATH)
assert v3["source_discovery_audit"]["sha256"] == sha256_file(audit_path)
assert v3["registry"]["sha256"] == sha256_file(registry_path)
assert v3["registry"]["superseded_sha256"] == sha256_file(ROOT / v3["registry"]["supersedes"])
assert v3["validator"]["sha256"] == sha256_file(ROOT / v3["validator"]["path"])

coverage = v3["effective_coverage"]
assert coverage == {
    "registered_recent_rows": 29,
    "resolved_unique_method_entities": 28,
    "deprecated_alias_rows": 1,
    "wma_track_unique_candidates": 16,
    "note": "Counts distinguish bibliographic registry rows from independently executable method entities. HeLa-Mem remains registered but execution-blocked until licensed.",
}
with registry_path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))
recent = [row for row in rows if row["year"] in {"2025", "2026"} and row["comparison_tier"] != "PROPOSED"]
assert len(recent) == coverage["registered_recent_rows"]
assert audit["selection_firewall"]["local_result_state_at_freeze"].endswith("contains zero rows")

states = {row["method_id"]: row["execution_state"] for row in audit["methods"]}
assert states["structmem"] == "ELIGIBLE_FOR_SOURCE_MATERIALIZATION"
assert states["hela-mem"] == "OFFICIAL_CODE_LICENSE_MISSING_EXECUTION_BLOCKED"
assert states["memory-r1"] == "OFFICIAL_REPOSITORY_CODE_COMING_SOON"
assert states["apex-mem"] == "NO_OFFICIAL_CODE_VERIFIED"
assert states["lightmem-acl-2026"] == "NO_OFFICIAL_CODE_VERIFIED_NAME_COLLISION_REJECTED"

wave5 = next(row for row in v3["effective_group_adjustments"] if row["group_id"] == "wave5_newly_verified_acl2026")
assert wave5["methods"] == ["structmem", "hela-mem"]
assert "zjunlp/LightMem" in v3["prohibited_actions"][0]

print(
    json.dumps(
        {
            "status": "PASS",
            "registered_recent_rows": len(recent),
            "resolved_unique_method_entities": coverage["resolved_unique_method_entities"],
            "newly_registered": wave5["methods"],
            "numeric_rows_added": 0,
        },
        sort_keys=True,
    )
)
