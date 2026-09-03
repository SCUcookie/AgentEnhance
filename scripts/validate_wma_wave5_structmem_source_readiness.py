#!/usr/bin/env python3
"""Validate the frozen StructMem source materialization gate."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFREEZE = ROOT / "comparisons" / "wma-r1-wave5-structmem-source-materialization-prefreeze.v1.json"


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
print(json.dumps({"status": "PASS", "method_id": source["method_id"], "revision": source["revision"], "numeric_rows_added": 0}, sort_keys=True))
