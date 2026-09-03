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
EXECUTION_SOURCE_PREFREEZE = ROOT / "comparisons" / "wma-r1-wave5-structmem-execution-source-prefreeze.v1.json"
EXECUTION_SOURCE_AUDIT = ROOT / "comparisons" / "wma-r1-wave5-structmem-execution-source-audit.v1.json"
MODEL_METADATA_PREFREEZE = ROOT / "comparisons" / "wma-r1-wave5-structmem-llmlingua-metadata-prefreeze.v1.json"
MODEL_METADATA_AUDIT = ROOT / "comparisons" / "wma-r1-wave5-structmem-llmlingua-metadata-audit.v1.json"
MODEL_MANIFEST = ROOT / "comparisons" / "wma-r1-wave5-structmem-model-prefetch-manifest.v1.json"
MODEL_MATERIALIZATION_PREFREEZE = ROOT / "comparisons" / "wma-r1-wave5-structmem-model-materialization-prefreeze.v1.json"
DEPENDENCY_LOCK_PREFREEZE = ROOT / "comparisons" / "wma-r1-wave5-structmem-dependency-lock-prefreeze.v1.json"


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
execution_prefreeze = json.loads(EXECUTION_SOURCE_PREFREEZE.read_text(encoding="utf-8"))
assert execution_prefreeze["status"] == "FROZEN_BEFORE_EXTERNAL_EXECUTION_SOURCE_COPY"
assert execution_prefreeze["prior_gate"]["sha256"] == sha256_file(ROOT / execution_prefreeze["prior_gate"]["path"])
assert execution_prefreeze["materializer"]["sha256"] == sha256_file(ROOT / execution_prefreeze["materializer"]["path"])
assert execution_prefreeze["unit_test"]["sha256"] == sha256_file(ROOT / execution_prefreeze["unit_test"]["path"])
copy_scope = execution_prefreeze["copy_scope"]
assert copy_scope["expected_file_count"] == 66
assert copy_scope["expected_total_bytes"] == 344766
assert copy_scope["root_license_retained"] is True
assert len(copy_scope["runtime_directories"]) == 8
assert execution_prefreeze["execution_contract"]["gpu_count"] == 0
assert execution_prefreeze["execution_contract"]["retry_count"] == 0
serialized = EXECUTION_SOURCE_PREFREEZE.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
execution_audit = json.loads(EXECUTION_SOURCE_AUDIT.read_text(encoding="utf-8"))
assert execution_audit["status"] == "TERMINAL_ACCEPTED"
assert execution_audit["prefreeze"]["sha256"] == sha256_file(ROOT / execution_audit["prefreeze"]["path"])
copy = execution_audit["execution_copy"]
checks = execution_audit["independent_checks"]
assert copy["file_count"] == checks["record_file_count"] == checks["observed_file_count"] == 66
assert copy["total_bytes"] == checks["record_total_bytes"] == checks["observed_total_bytes"] == 344766
assert checks["record_paths_sizes_hashes_equal_observed_copy"] is True
assert checks["terminal_accepted_present"] is True
assert checks["terminal_rejected_absent"] is True
assert checks["evidence_inventory_verified"] is True
assert checks["symlink_count"] == checks["bytecode_file_count"] == 0
assert checks["em2mem_path_count"] == checks["fluxmem_path_count"] == 0
assert checks["search_locomo_present"] is False
assert checks["active_destination_process_references"] == 0
preservation = execution_audit["preservation"]
assert preservation["transport"] == "resumable-sftp-4096-kbit"
assert preservation["local_hashes_equal_remote_hashes"] is True
wave1 = execution_audit["wave1_non_interference_observation"]
assert wave1["after_audit_accepted_units"] >= wave1["before_copy_accepted_units"]
assert wave1["before_copy_rejected_units"] == wave1["after_audit_rejected_units"] == 0
assert execution_audit["numeric_result_rows_added"] == 0
serialized = EXECUTION_SOURCE_AUDIT.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
model_prefreeze = json.loads(MODEL_METADATA_PREFREEZE.read_text(encoding="utf-8"))
assert model_prefreeze["status"] == "FROZEN_BEFORE_MODEL_METADATA_CLONE"
assert model_prefreeze["prior_gate"]["sha256"] == sha256_file(ROOT / model_prefreeze["prior_gate"]["path"])
model_impl = model_prefreeze["implementation"]
assert model_impl["script_sha256"] == sha256_file(ROOT / model_impl["script"])
assert model_impl["unit_test_sha256"] == sha256_file(ROOT / model_impl["unit_test"])
assert model_impl["tests"] == 3
model_contract = model_prefreeze["execution_contract"]
assert model_contract["network_retries"] == 0
assert model_contract["gpu_count"] == 0
assert model_contract["model_payload_byte_ceiling"] == 0
assert "GIT_LFS_SKIP_SMUDGE=1" in model_contract["git_mode"]
serialized = MODEL_METADATA_PREFREEZE.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
model_audit = json.loads(MODEL_METADATA_AUDIT.read_text(encoding="utf-8"))
assert model_audit["status"] == "TERMINAL_ACCEPTED"
assert model_audit["prefreeze"]["sha256"] == sha256_file(ROOT / model_audit["prefreeze"]["path"])
metadata = model_audit["metadata"]
assert metadata["tree_file_count"] == 8
assert metadata["lfs_pointer_count"] == 1
assert metadata["worktree_payload_file_count"] == 0
assert metadata["model_payload_materialized"] is False
assert metadata["model_safetensors"]["payload_bytes"] == 709388104
assert metadata["model_safetensors"]["payload_sha256"] == "22b9ecde52fec5c97e8c54a293be768727df95a81c6c8dccb03f262a50c58324"
manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
assert manifest["status"] == "FROZEN_BEFORE_DOWNLOAD"
assert len(manifest["models"]) == 1
frozen_model = manifest["models"][0]
assert frozen_model["revision"] == metadata["revision"]
assert frozen_model["expected_file_count"] == len(frozen_model["expected_files"]) == 7
assert sum(row["bytes"] for row in frozen_model["expected_files"]) == frozen_model["expected_total_bytes"] == 713308492
assert frozen_model["expected_files"][2]["sha256"] == metadata["model_safetensors"]["payload_sha256"]
assert manifest["download_policy"]["network_retries"] == 0
assert "Wave1 controller is terminal" in manifest["download_policy"]["scheduler_gate"]
for path in (MODEL_METADATA_AUDIT, MODEL_MANIFEST):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized
model_materialization = json.loads(MODEL_MATERIALIZATION_PREFREEZE.read_text(encoding="utf-8"))
assert model_materialization["status"] == "FROZEN_AWAITING_WAVE1_RESOURCE_GATE"
for gate in model_materialization["prior_gates"]:
    assert gate["sha256"] == sha256_file(ROOT / gate["path"])
model_materializer = model_materialization["implementation"]
assert model_materializer["downloader_sha256"] == sha256_file(ROOT / model_materializer["downloader"])
assert model_materializer["unit_test_sha256"] == sha256_file(ROOT / model_materializer["unit_test"])
assert model_materializer["unit_tests"] == 4
assert "exact per-file SHA-256" in model_materializer["difference_from_v1"]
assert model_materialization["model"]["expected_file_count"] == frozen_model["expected_file_count"]
assert model_materialization["model"]["expected_total_bytes"] == frozen_model["expected_total_bytes"]
assert model_materialization["execution_contract"]["network_retry_count"] == 0
assert model_materialization["execution_contract"]["logical_requests_per_file"] == 1
serialized = MODEL_MATERIALIZATION_PREFREEZE.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
dependency_lock = json.loads(DEPENDENCY_LOCK_PREFREEZE.read_text(encoding="utf-8"))
assert dependency_lock["status"] == "FROZEN_AWAITING_WAVE1_RESOURCE_GATE"
for gate in dependency_lock["prior_gates"]:
    assert gate["sha256"] == sha256_file(ROOT / gate["path"])
workspace = dependency_lock["frozen_workspace"]
assert workspace["sha256"] == sha256_file(ROOT / workspace["path"])
assert workspace["bytes"] == (ROOT / workspace["path"]).stat().st_size == 1616
assert workspace["direct_dependency_count"] == 58
lock_impl = dependency_lock["implementation"]
assert lock_impl["materializer_sha256"] == sha256_file(ROOT / lock_impl["materializer"])
assert lock_impl["unit_test_sha256"] == sha256_file(ROOT / lock_impl["unit_test"])
assert lock_impl["unit_tests"] == 3
assert dependency_lock["execution_contract"]["network_retry_count"] == 0
assert dependency_lock["execution_contract"]["dependency_installations"] == 0
assert dependency_lock["outputs"]["independent_lock_passes"] == 2
serialized = DEPENDENCY_LOCK_PREFREEZE.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
print(json.dumps({"status": "PASS", "method_id": source["method_id"], "revision": source["revision"], "tracked_files": accepted["tracked_file_count"], "adapter_design_eligible": True, "feasibility_revision": 2, "mock_boundary_tests": implementation["mock_boundary_tests"], "execution_source_files": checks["observed_file_count"], "model_metadata_ready": True, "model_files": frozen_model["expected_file_count"], "model_bytes": frozen_model["expected_total_bytes"], "model_materialization_gate": model_materialization["status"], "model_materializer_tests": model_materializer["unit_tests"], "dependency_lock_gate": dependency_lock["status"], "direct_dependencies": workspace["direct_dependency_count"], "lock_materializer_tests": lock_impl["unit_tests"], "numeric_rows_added": 0}, sort_keys=True))
