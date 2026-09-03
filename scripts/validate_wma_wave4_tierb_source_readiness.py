#!/usr/bin/env python3
"""Validate the Wave-4 Tier-B source-identity and acquisition prefreeze."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-tierb-source-readiness-prefreeze.v1.json"
AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-source-audit.v1.json"
FEASIBILITY_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-adapter-feasibility-audit.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


payload = json.loads(PREFREEZE_PATH.read_text(encoding="utf-8"))
audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
feasibility = json.loads(FEASIBILITY_PATH.read_text(encoding="utf-8"))
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

assert audit["status"] == "TERMINAL_ACCEPTED"
assert audit["prefreeze"]["sha256"] == sha256_file(ROOT / audit["prefreeze"]["path"])
assert audit["control_package"]["sftp_rate_limit_kbit_per_second"] == 4096
source = audit["source"]
assert source["revision"] == candidates["hindsight"]["observed_head"]
assert source["tracked_file_count"] == 4323
assert source["tracked_total_bytes"] == 222626687
assert source["license"] == "MIT"
assert source["worktree_clean"] is True
assert source["submodule_count"] == 0
assert source["git_lfs_pointer_count"] == 0
assert source["prohibited_weight_file_count"] == 0
assert source["active_process_references_at_audit"] == 0
assert source["all_source_hashes_verified_independently"] is True
before = audit["wave1_non_interference_observation"]["before_source_stage"]
after = audit["wave1_non_interference_observation"]["after_source_audit"]
assert after["accepted_units"] >= before["accepted_units"]
assert before["rejected_units"] == after["rejected_units"] == 0
serialized = AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert feasibility["status"] == "TERMINAL_ACCEPTED_FOR_ADAPTER_DESIGN"
assert feasibility["source_gate"]["sha256"] == sha256_file(
    ROOT / feasibility["source_gate"]["path"]
)
assert feasibility["source_identity"]["requires_python"] == ">=3.11"
assert feasibility["source_identity"]["version"] == "0.9.2"
assert len(feasibility["audited_files"]) == 10
assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in feasibility["audited_files"])
defaults = feasibility["official_defaults"]
assert defaults["embedding_model"] == "BAAI/bge-small-en-v1.5"
assert defaults["reranker_model"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
assert defaults["text_search"] is True
assert defaults["temporal_retrieval"] is True
assert defaults["graph_retrieval"] is True
assert defaults["reranking"] is True
assert feasibility["proposed_wma_mapping"]["final_answer"].startswith("Never call reflect")
assert "caption-mediated" in feasibility["fairness_and_claim_boundaries"]["multimodality"]
serialized = FEASIBILITY_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
print(
    json.dumps(
        {
            "status": "PASS",
            "tierb_candidates": len(candidates),
            "source_materialization_eligible": ["hindsight"],
            "accepted_hindsight_source_files": source["tracked_file_count"],
            "hindsight_adapter_design_eligible": True,
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
