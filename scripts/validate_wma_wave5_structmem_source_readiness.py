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
FEASIBILITY = ROOT / "comparisons" / "wma-r1-wave5-structmem-adapter-feasibility-audit.v1.json"
FEASIBILITY_V2 = ROOT / "comparisons" / "wma-r1-wave5-structmem-adapter-feasibility-audit.v2.json"
ADAPTER_DESIGN = ROOT / "comparisons" / "wma-r1-wave5-structmem-adapter-design-prefreeze.v1.json"


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
feasibility = json.loads(FEASIBILITY.read_text(encoding="utf-8"))
assert feasibility["status"] == "TERMINAL_ACCEPTED_FOR_ADAPTER_DESIGN"
assert feasibility["source_gate"]["sha256"] == sha256_file(ROOT / feasibility["source_gate"]["path"])
assert feasibility["source_identity"]["revision"] == source["revision"]
assert feasibility["source_identity"]["requires_python"] == ">=3.10,<3.12"
assert feasibility["source_identity"]["root_license"] == "MIT"
assert feasibility["source_identity"]["package_metadata_license"] == "Apache-2.0"
assert len(feasibility["audited_files"]) == 11
assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in feasibility["audited_files"])
settings = feasibility["method_mechanism"]["official_locomo_settings_to_preserve"]
assert settings["extraction_mode"] == "event"
assert settings["summary_time_window_seconds"] == 3600
assert settings["summary_top_k_seeds"] == 15
assert "GLOBAL_TOPIC_IDX" in feasibility["wma_mapping"]["reset"]
assert "process_all=True" in feasibility["wma_mapping"]["end_session"]
assert "top_k total" in feasibility["wma_mapping"]["retrieve"]
assert feasibility["required_additional_model"]["status"] == "IDENTITY_VERIFIED_FILE_MANIFEST_PENDING"
assert feasibility["required_additional_model"]["observed_revision"] == "5f0c82792b7ea14c6484e015b6a072009496b7f2"
assert feasibility["numeric_result_rows_added"] == 0
serialized = FEASIBILITY.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
feasibility_v2 = json.loads(FEASIBILITY_V2.read_text(encoding="utf-8"))
assert feasibility_v2["status"] == "TERMINAL_ACCEPTED_FOR_ADAPTER_DESIGN"
assert feasibility_v2["superseded_sha256"] == sha256_file(ROOT / feasibility_v2["supersedes"])
corrected = feasibility_v2["corrected_wma_mapping"]
assert "every buffered source utterance" in corrected["end_session"]
assert "empty assistant placeholder" in corrected["end_session"]
assert "strictly increasing" in corrected["timestamp_guard"]
assert len(feasibility_v2["adapter_test_obligations"]) == 8
assert feasibility_v2["numeric_result_rows_added"] == 0
serialized = FEASIBILITY_V2.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
adapter_design = json.loads(ADAPTER_DESIGN.read_text(encoding="utf-8"))
assert adapter_design["status"] == "FROZEN_DESIGN_AWAITING_DEPENDENCY_MODEL_GATES"
for gate in adapter_design["prior_gates"]:
    assert gate["sha256"] == sha256_file(ROOT / gate["path"])
implementation = adapter_design["frozen_implementation"]
for key in ("adapter", "sitecustomize", "unit_test"):
    assert implementation[f"{key}_sha256"] == sha256_file(ROOT / implementation[key])
assert implementation["mock_boundary_tests"] == 5
defaults = adapter_design["frozen_defaults"]
assert defaults["extraction_mode"] == "event"
assert defaults["summary_process_all_after_each_session"] is True
assert defaults["summary_candidate_limit"] == 5
assert defaults["embedding_dimension"] == 384
assert "assistant utterances" in adapter_design["static_acceptance"][0]
assert adapter_design["model_and_backbone_contract"]["native_multimodal"] is False
serialized = ADAPTER_DESIGN.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
print(json.dumps({"status": "PASS", "method_id": source["method_id"], "revision": source["revision"], "tracked_files": accepted["tracked_file_count"], "adapter_design_eligible": True, "feasibility_revision": 2, "mock_boundary_tests": implementation["mock_boundary_tests"], "numeric_rows_added": 0}, sort_keys=True))
