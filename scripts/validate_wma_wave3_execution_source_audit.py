#!/usr/bin/env python3
"""Validate local retained evidence for Wave-3 execution-source acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave3-execution-source-audit.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
assert audit["status"] == "TERMINAL_ACCEPTED"
assert audit["scientific_evidence_role"].startswith("engineering execution-source")
assert audit["prefreeze"]["sha256"] == sha256_file(ROOT / audit["prefreeze"]["path"])
assert audit["control_package"]["sftp_rate_limit_kbit_per_second"] == 4096
assert audit["control_package"]["internal_adapter_and_materializer_hashes_verified"] is True

methods = {row["method_id"]: row for row in audit["methods"]}
assert set(methods) == {"memoryos", "memgas"}
assert methods["memoryos"]["file_count"] == 11
assert methods["memoryos"]["total_bytes"] == 105356
assert methods["memgas"]["file_count"] == 27
assert methods["memgas"]["total_bytes"] == 762748
assert methods["memgas"]["tracked_bytecode_files_in_official_source"] == 8
for row in methods.values():
    assert row["status"] == "TERMINAL_ACCEPTED_EXECUTION_SOURCE"
    assert row["source_clean_after_copy"] is True
    assert row["bytecode_file_count"] == 0
    assert row["untracked_file_count_copied"] == 0
    assert row["active_process_references_at_audit"] == 0
    assert re.fullmatch(r"[0-9a-f]{40}", row["source_revision"])
    assert re.fullmatch(r"[0-9a-f]{64}", row["record_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", row["evidence_inventory_sha256"])

for row in audit["adapter_overlay_identity"]:
    assert row["sha256"] == sha256_file(ROOT / row["path"])

assert audit["audit_tooling_incident"]["mutation_performed"] is False
before = audit["wave1_non_interference_observation"]["before_copy"]
after = audit["wave1_non_interference_observation"]["after_independent_audit"]
assert after["accepted_units"] >= before["accepted_units"]
assert before["rejected_units"] == after["rejected_units"] == 0
assert after["fatal_signals"] == 0
assert after["json_truncation_repair_events"] == 2

serialized = AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
assert "Model download and lifecycle execution remain gated" in audit["next_allowed_gate"]

print(
    json.dumps(
        {
            "status": "PASS",
            "accepted_execution_sources": sorted(methods),
            "copied_source_files": sum(row["file_count"] for row in methods.values()),
            "bytecode_files_copied": 0,
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
