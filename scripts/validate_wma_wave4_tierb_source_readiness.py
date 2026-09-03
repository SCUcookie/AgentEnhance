#!/usr/bin/env python3
"""Validate the Wave-4 Tier-B source-identity and acquisition prefreeze."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-tierb-source-readiness-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


payload = json.loads(PREFREEZE_PATH.read_text(encoding="utf-8"))
assert payload["status"] == "FROZEN_BEFORE_HINDSIGHT_SOURCE_MATERIALIZATION"
assert "no adapter, lifecycle, numerical" in payload["scientific_evidence_role"]
candidates = {row["method_id"]: row for row in payload["candidates"]}
assert set(candidates) == {
    "hindsight",
    "memory-r1",
    "apex-mem",
    "lightmem-acl-2026",
}
assert candidates["hindsight"]["source_status"] == "ELIGIBLE_FOR_FROZEN_SOURCE_MATERIALIZATION"
assert re.fullmatch(r"[0-9a-f]{40}", candidates["hindsight"]["observed_head"])
assert candidates["memory-r1"]["source_status"] == "NOT_EXECUTABLE_CODE_COMING_SOON"
assert candidates["apex-mem"]["official_repository"] is None
assert candidates["lightmem-acl-2026"]["official_repository"] is None
assert "differ" in candidates["lightmem-acl-2026"]["rejected_name_collision"]["reason"]

stage = payload["hindsight_source_materialization"]
assert stage["materializer_sha256"] == sha256_file(ROOT / stage["materializer"])
assert stage["revision"] == candidates["hindsight"]["observed_head"]
assert stage["target"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/third_party/")
assert stage["evidence_root"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/runs/")
assert stage["execution"]["gpu_count"] == 0
assert stage["execution"]["dependency_installation"] is False
assert stage["execution"]["model_download"] is False
assert stage["execution"]["llm_calls"] == 0
assert stage["execution"]["retry_count"] == 0

serialized = PREFREEZE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
print(
    json.dumps(
        {
            "status": "PASS",
            "tierb_candidates": len(candidates),
            "source_materialization_eligible": ["hindsight"],
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
