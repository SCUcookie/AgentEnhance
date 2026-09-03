#!/usr/bin/env python3
"""Validate the frozen StructMem source materialization gate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFREEZE = ROOT / "comparisons" / "wma-r1-wave5-structmem-source-materialization-prefreeze.v1.json"
AUDIT = ROOT / "comparisons" / "wma-r1-wave5-structmem-source-materialization-audit.v1.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


payload = json.loads(PREFREEZE.read_text(encoding="utf-8"))
assert payload["status"] == "FROZEN_BEFORE_EXTERNAL_SOURCE_MATERIALIZATION"
assert "no import, dependency, lifecycle, benchmark, numerical" in payload["scientific_evidence_role"]
prior = payload["prior_gate"]
assert prior["sha256"] == sha256_file(ROOT / prior["path"])
source = payload["source"]
assert source["method_id"] == "structmem"
assert source["repository"] == "https://github.com/zjunlp/LightMem.git"
assert re.fullmatch(r"[0-9a-f]{40}", source["revision"])
assert source["target"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/third_party/")
assert source["evidence_root"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/runs/")
assert source["materializer_sha256"] == sha256_file(ROOT / source["materializer"])
contract = payload["execution_contract"]
assert contract["gpu_count"] == 0
assert contract["retry_count"] == 0
assert contract["fresh_roots_required"] is True
assert contract["source_worktree_byte_ceiling"] == 512 * 1024 * 1024
assert any("MIT LICENSE" in item for item in payload["admission_rule"])
assert any("ACL 2026 LightMem" in item for item in payload["prohibited_actions"])
serialized = PREFREEZE.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
audit = json.loads(AUDIT.read_text(encoding="utf-8"))
assert audit["status"] == "TERMINAL_ACCEPTED"
assert audit["prefreeze"]["sha256"] == sha256_file(ROOT / audit["prefreeze"]["path"])
accepted = audit["source"]
assert accepted["revision"] == source["revision"]
assert accepted["git_tree"] == "da4212efaa196112988b89c2afd9813db27f1784"
assert accepted["tracked_file_count"] == 609
assert accepted["tracked_total_bytes"] == 18846018
assert accepted["license"] == "MIT"
assert accepted["worktree_clean"] is True
assert accepted["submodule_count"] == 0
assert accepted["symlink_count"] == 0
assert accepted["git_lfs_pointer_count"] == 0
assert accepted["prohibited_weight_file_count"] == 0
assert accepted["active_process_references_at_audit"] == 0
evidence = audit["accepted_evidence"]
assert evidence["terminal_accepted_present"] is True
assert evidence["terminal_rejected_absent"] is True
assert evidence["evidence_inventory_verified"] is True
preservation = audit["preservation"]
assert preservation["transport"] == "resumable-sftp-4096-kbit"
assert preservation["local_hashes_equal_remote_hashes"] is True
assert preservation["source_archive"]["bytes"] == 9334060
assert preservation["evidence_archive"]["bytes"] == 60444
assert audit["numeric_result_rows_added"] == 0
serialized = AUDIT.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
print(json.dumps({"status": "PASS", "method_id": source["method_id"], "revision": source["revision"], "tracked_files": accepted["tracked_file_count"], "numeric_rows_added": 0}, sort_keys=True))
