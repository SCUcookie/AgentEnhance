#!/usr/bin/env python3
"""Validate retained local evidence for the Wave-3 source-identity gate."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave3-source-materialization-audit.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
prefreeze = ROOT / audit["prefreeze"]
assert audit["status"] == "TERMINAL_ACCEPTED"
assert audit["prefreeze_sha256"] == sha256_file(prefreeze)
assert audit["scientific_evidence_role"].startswith("engineering source-identity")
assert set(row["method_id"] for row in audit["methods"]) == {"memoryos", "memgas"}

methods = {row["method_id"]: row for row in audit["methods"]}
memoryos = methods["memoryos"]
inventory_path = ROOT / memoryos["inventory"]
assert memoryos["inventory_sha256"] == sha256_file(inventory_path)
with inventory_path.open(newline="", encoding="utf-8") as handle:
    inventory = list(csv.DictReader(handle, delimiter="\t"))
assert len(inventory) == memoryos["tracked_file_count"] == 73
assert sum(int(row["bytes"]) for row in inventory) == memoryos["tracked_total_bytes"]
assert len({row["path"] for row in inventory}) == len(inventory)
assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in inventory)

memgas = methods["memgas"]
for key in (
    "revision",
    "git_tree",
    "source_materialization_record_sha256",
    "source_sha256s_sha256",
    "evidence_sha256s_sha256",
):
    expected_length = 40 if key in {"revision", "git_tree"} else 64
    assert re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", memgas[key]), key
assert memgas["tracked_file_count"] == 35
assert memgas["tracked_total_bytes"] == 788954
assert memgas["source_hash_inventory_verified"] is True
assert memgas["evidence_hash_inventory_verified"] is True
assert memgas["active_process_references_at_audit"] == 0

before = audit["wave1_non_interference_observation"]["before_source_execution"]
after = audit["wave1_non_interference_observation"]["after_source_execution"]
assert after["accepted_units"] >= before["accepted_units"]
assert before["rejected_units"] == after["rejected_units"] == 0
assert after["error_signals"] == 0
assert "No model acquisition or numerical run is authorized" in audit["next_allowed_gate"]

serialized = AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

print(
    json.dumps(
        {
            "status": "PASS",
            "accepted_source_methods": sorted(methods),
            "memoryos_inventory_rows": len(inventory),
            "memgas_inventory_rows": memgas["tracked_file_count"],
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
