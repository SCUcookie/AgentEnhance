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
MODEL_MANIFEST_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-model-prefetch-manifest.v1.json"
MODEL_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-model-materialization-prefreeze.v1.json"
EXECUTION_SOURCE_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-execution-source-prefreeze.v1.json"
EXECUTION_SOURCE_AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-execution-source-audit.v1.json"
UV_TOOL_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-prefreeze.v1.json"
UV_TOOL_FAILURE_AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-failure-audit.v1.json"
UV_TOOL_RECOVERY_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-recovery1-prefreeze.v1.json"
UV_TOOL_TRANSFER_FAILURE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-recovery1-transfer-failure-audit.v1.json"
UV_TOOL_RECOVERY_PREFREEZE_V2_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-recovery1-prefreeze.v2.json"
UV_TOOL_RECOVERY1_FAILURE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-recovery1-failure-audit.v1.json"
UV_TOOL_RECOVERY2_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-recovery2-prefreeze.v1.json"
UV_TOOL_RECOVERY2_AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-uv-tool-recovery2-audit.v1.json"
LOCK_EXPORT_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-lock-export-prefreeze.v1.json"
LOCK_EXPORT_FAILURE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-lock-export-failure-audit.v1.json"
LOCK_EXPORT_RECOVERY_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-lock-export-recovery1-prefreeze.v1.json"
LOCK_EXPORT_RECOVERY_AUDIT_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-lock-export-recovery1-audit.v1.json"
SOURCE_AWARE_EXPORT_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-source-aware-export-prefreeze.v1.json"
SOURCE_AWARE_EXPORT_FAILURE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-source-aware-export-failure-audit.v1.json"
REGISTRY_ROUTING_PREFREEZE_PATH = ROOT / "comparisons" / "wma-r1-wave4-hindsight-registry-routing-prefreeze.v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


payload = json.loads(PREFREEZE_PATH.read_text(encoding="utf-8"))
audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
feasibility = json.loads(FEASIBILITY_PATH.read_text(encoding="utf-8"))
model_manifest = json.loads(MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
model_prefreeze = json.loads(MODEL_PREFREEZE_PATH.read_text(encoding="utf-8"))
execution_source_prefreeze = json.loads(
    EXECUTION_SOURCE_PREFREEZE_PATH.read_text(encoding="utf-8")
)
execution_source_audit = json.loads(
    EXECUTION_SOURCE_AUDIT_PATH.read_text(encoding="utf-8")
)
uv_tool_prefreeze = json.loads(UV_TOOL_PREFREEZE_PATH.read_text(encoding="utf-8"))
uv_tool_failure_audit = json.loads(
    UV_TOOL_FAILURE_AUDIT_PATH.read_text(encoding="utf-8")
)
uv_tool_recovery_prefreeze = json.loads(
    UV_TOOL_RECOVERY_PREFREEZE_PATH.read_text(encoding="utf-8")
)
uv_tool_transfer_failure = json.loads(
    UV_TOOL_TRANSFER_FAILURE_PATH.read_text(encoding="utf-8")
)
uv_tool_recovery_prefreeze_v2 = json.loads(
    UV_TOOL_RECOVERY_PREFREEZE_V2_PATH.read_text(encoding="utf-8")
)
uv_tool_recovery1_failure = json.loads(
    UV_TOOL_RECOVERY1_FAILURE_PATH.read_text(encoding="utf-8")
)
uv_tool_recovery2_prefreeze = json.loads(
    UV_TOOL_RECOVERY2_PREFREEZE_PATH.read_text(encoding="utf-8")
)
uv_tool_recovery2_audit = json.loads(
    UV_TOOL_RECOVERY2_AUDIT_PATH.read_text(encoding="utf-8")
)
lock_export_prefreeze = json.loads(
    LOCK_EXPORT_PREFREEZE_PATH.read_text(encoding="utf-8")
)
lock_export_failure = json.loads(LOCK_EXPORT_FAILURE_PATH.read_text(encoding="utf-8"))
lock_export_recovery_prefreeze = json.loads(
    LOCK_EXPORT_RECOVERY_PREFREEZE_PATH.read_text(encoding="utf-8")
)
lock_export_recovery_audit = json.loads(
    LOCK_EXPORT_RECOVERY_AUDIT_PATH.read_text(encoding="utf-8")
)
source_aware_export_prefreeze = json.loads(
    SOURCE_AWARE_EXPORT_PREFREEZE_PATH.read_text(encoding="utf-8")
)
source_aware_export_failure = json.loads(
    SOURCE_AWARE_EXPORT_FAILURE_PATH.read_text(encoding="utf-8")
)
registry_routing_prefreeze = json.loads(
    REGISTRY_ROUTING_PREFREEZE_PATH.read_text(encoding="utf-8")
)
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

assert model_manifest["status"] == "FROZEN_BEFORE_DOWNLOAD"
models = {row["component"]: row for row in model_manifest["models"]}
assert set(models) == {"embedding", "reranker"}
assert models["embedding"]["repository"] == "BAAI/bge-small-en-v1.5"
assert models["embedding"]["revision"] == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
assert models["embedding"]["expected_file_count"] == 11
assert models["embedding"]["expected_total_bytes"] == 134505940
assert models["reranker"]["configured_upstream_alias"].endswith("MiniLM-L-6-v2")
assert models["reranker"]["repository"] == "cross-encoder/ms-marco-MiniLM-L6-v2"
assert models["reranker"]["revision"] == "233902d25c440f23af6f7d6e94d2946bac0bee0a"
assert models["reranker"]["expected_file_count"] == 7
assert models["reranker"]["expected_total_bytes"] == 91819431
for model in models.values():
    assert len(model["allow_patterns"]) == model["expected_file_count"]
    assert len(model["expected_files"]) == model["expected_file_count"]
    assert len({row["path"] for row in model["expected_files"]}) == model["expected_file_count"]
    assert sum(row["bytes"] for row in model["expected_files"]) == model["expected_total_bytes"]
    assert model["expected_local_path"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/")
assert model_manifest["download_policy"]["parallel_downloads"] == 1
assert model_manifest["download_policy"]["network_retries"] == 0
assert model_manifest["download_policy"]["transport"].endswith("4096 Kbit/s.")

assert model_prefreeze["status"] == "FROZEN_BEFORE_DOWNLOAD"
assert model_prefreeze["adapter_feasibility_audit"]["sha256"] == sha256_file(
    ROOT / model_prefreeze["adapter_feasibility_audit"]["path"]
)
assert model_prefreeze["source_manifest"] == str(MODEL_MANIFEST_PATH.relative_to(ROOT))
assert model_prefreeze["source_manifest_sha256"] == sha256_file(MODEL_MANIFEST_PATH)
assert model_prefreeze["downloader_sha256"] == sha256_file(ROOT / model_prefreeze["downloader"])
assert [row["component"] for row in model_prefreeze["execution_order"]] == [
    "embedding",
    "reranker",
]
for row in model_prefreeze["execution_order"]:
    model = models[row["component"]]
    assert row["repository"] == model["repository"]
    assert row["revision"] == model["revision"]
    assert row["target"] == model["expected_local_path"]
    assert row["evidence_root"].startswith("${AGENT_ENHANCE_REMOTE_ROOT}/runs/")
assert model_prefreeze["execution_contract"]["gpu_count"] == 0
assert model_prefreeze["execution_contract"]["retry_count"] == 0
for path in (MODEL_MANIFEST_PATH, MODEL_PREFREEZE_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

assert (
    execution_source_prefreeze["status"]
    == "FROZEN_BEFORE_EXTERNAL_EXECUTION_SOURCE_COPY"
)
assert execution_source_prefreeze["prior_gate"]["sha256"] == sha256_file(
    ROOT / execution_source_prefreeze["prior_gate"]["path"]
)
assert execution_source_prefreeze["materializer"]["sha256"] == sha256_file(
    ROOT / execution_source_prefreeze["materializer"]["path"]
)
assert execution_source_prefreeze["source"]["revision"] == audit["source"]["revision"]
assert execution_source_prefreeze["copy_scope"]["expected_file_count"] == 563
assert execution_source_prefreeze["copy_scope"]["expected_total_bytes"] == 9417481
assert len(execution_source_prefreeze["copy_scope"]["runtime_directories"]) == 5
assert execution_source_prefreeze["execution_contract"]["gpu_count"] == 0
assert execution_source_prefreeze["execution_contract"]["retry_count"] == 0
serialized = EXECUTION_SOURCE_PREFREEZE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert execution_source_audit["status"] == "TERMINAL_ACCEPTED"
assert execution_source_audit["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / execution_source_audit["prefreeze_gate"]["path"]
)
copy = execution_source_audit["execution_copy"]
checks = execution_source_audit["independent_checks"]
assert copy["file_count"] == checks["record_file_count"] == checks["observed_file_count"] == 563
assert copy["total_bytes"] == checks["record_total_bytes"] == checks["observed_total_bytes"] == 9417481
assert checks["terminal_accepted_present"] is True
assert checks["terminal_rejected_absent"] is True
assert checks["evidence_inventory_verified"] is True
assert checks["record_paths_sizes_hashes_equal_observed_copy"] is True
assert checks["symlink_count"] == checks["bytecode_file_count"] == 0
assert checks["active_destination_process_references"] == 0
wave1 = execution_source_audit["wave1_non_interference_observation"]
assert wave1["after_audit_accepted_units"] >= wave1["before_copy_accepted_units"]
assert wave1["before_copy_rejected_units"] == wave1["after_audit_rejected_units"] == 0
serialized = EXECUTION_SOURCE_AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert uv_tool_prefreeze["status"] == "FROZEN_BEFORE_TOOL_DOWNLOAD"
assert uv_tool_prefreeze["prior_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_prefreeze["prior_gate"]["path"]
)
assert uv_tool_prefreeze["materializer"]["sha256"] == sha256_file(
    ROOT / uv_tool_prefreeze["materializer"]["path"]
)
release = uv_tool_prefreeze["official_release"]
assert release["version"] == "0.12.9"
assert release["target_triple"] == "x86_64-unknown-linux-gnu"
assert release["archive_bytes"] == 19423276
assert release["archive_sha256"] == "ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460"
assert uv_tool_prefreeze["execution_contract"]["network_retries"] == 0
assert uv_tool_prefreeze["execution_contract"]["gpu_count"] == 0
assert uv_tool_prefreeze["execution_contract"]["download_rate_ceiling"] == "512 KiB/s"
serialized = UV_TOOL_PREFREEZE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert uv_tool_failure_audit["status"] == "TERMINAL_REJECTED"
assert uv_tool_failure_audit["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_failure_audit["prefreeze_gate"]["path"]
)
diagnosis = uv_tool_failure_audit["diagnosis"]
assert diagnosis["curl_exit_code"] == 52
assert diagnosis["transferred_bytes"] == 0
assert diagnosis["partial_archive_retained"] is False
assert diagnosis["partial_target_retained"] is False
assert uv_tool_failure_audit["rejected_evidence"]["terminal_rejected_present"] is True
assert uv_tool_failure_audit["rejected_evidence"]["terminal_accepted_absent"] is True

assert uv_tool_recovery_prefreeze["status"] == "FROZEN_BEFORE_RECOVERY_TRANSFER"
assert uv_tool_recovery_prefreeze["failure_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_recovery_prefreeze["failure_gate"]["path"]
)
for row in uv_tool_recovery_prefreeze["materializers"]:
    assert row["sha256"] == sha256_file(ROOT / row["path"])
assert uv_tool_recovery_prefreeze["release_identity"]["archive_sha256"] == release["archive_sha256"]
assert uv_tool_recovery_prefreeze["release_identity"]["archive_bytes"] == release["archive_bytes"]
transfer = uv_tool_recovery_prefreeze["transfer_contract"]
assert transfer["sftp_rate_limit_kbit_per_second"] == 4096
assert transfer["maximum_sftp_connections"] == 3
assert transfer["parallel_transfers"] == 1
assert uv_tool_recovery_prefreeze["execution_contract"]["retry_count_after_verified_transfer"] == 0
assert uv_tool_recovery_prefreeze["execution_contract"]["gpu_count"] == 0
for path in (UV_TOOL_FAILURE_AUDIT_PATH, UV_TOOL_RECOVERY_PREFREEZE_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

assert (
    uv_tool_transfer_failure["status"]
    == "TERMINAL_REJECTED_PREFLIGHT_COMMAND_SEMANTICS"
)
assert uv_tool_transfer_failure["superseded_prefreeze"]["sha256"] == sha256_file(
    ROOT / uv_tool_transfer_failure["superseded_prefreeze"]["path"]
)
attempt = uv_tool_transfer_failure["attempt"]
assert attempt["connection_index"] == 1
assert attempt["transferred_bytes"] == 0
assert all(
    attempt[key] is True
    for key in (
        "remote_archive_absent",
        "remote_checksum_absent",
        "remote_control_package_absent",
        "tool_target_absent",
        "evidence_root_absent",
    )
)

assert uv_tool_recovery_prefreeze_v2["status"] == "FROZEN_BEFORE_RECOVERY_TRANSFER"
assert uv_tool_recovery_prefreeze_v2["supersedes"]["sha256"] == sha256_file(
    ROOT / uv_tool_recovery_prefreeze_v2["supersedes"]["path"]
)
assert uv_tool_recovery_prefreeze_v2["transfer_failure_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_recovery_prefreeze_v2["transfer_failure_gate"]["path"]
)
for row in uv_tool_recovery_prefreeze_v2["materializers"]:
    assert row["sha256"] == sha256_file(ROOT / row["path"])
transfer_v2 = uv_tool_recovery_prefreeze_v2["transfer_contract"]
assert transfer_v2["initial_mode_when_remote_absent"] == "put"
assert transfer_v2["resume_mode_when_remote_partial"] == "put -a"
assert transfer_v2["sftp_rate_limit_kbit_per_second"] == 4096
assert transfer_v2["connections_consumed_by_v1_preflight"] == 1
assert transfer_v2["connections_remaining"] == 2
assert uv_tool_recovery_prefreeze_v2["execution_contract"]["gpu_count"] == 0
for path in (UV_TOOL_TRANSFER_FAILURE_PATH, UV_TOOL_RECOVERY_PREFREEZE_V2_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

assert uv_tool_recovery1_failure["status"] == "TERMINAL_REJECTED"
assert uv_tool_recovery1_failure["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_recovery1_failure["prefreeze_gate"]["path"]
)
recovery1_diagnosis = uv_tool_recovery1_failure["diagnosis"]
assert recovery1_diagnosis["archive_and_sidecar_identity_accepted"] is True
assert recovery1_diagnosis["safe_archive_members_accepted"] is True
assert recovery1_diagnosis["observed_output"] == "uv 0.12.9 (x86_64-unknown-linux-gnu)"
assert uv_tool_recovery1_failure["retained_partial_target"]["cleanup_authorized"] is False

assert uv_tool_recovery2_prefreeze["status"] == "FROZEN_BEFORE_LOCAL_REEXTRACTION"
assert uv_tool_recovery2_prefreeze["failure_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_recovery2_prefreeze["failure_gate"]["path"]
)
for row in uv_tool_recovery2_prefreeze["materializers"]:
    assert row["sha256"] == sha256_file(ROOT / row["path"])
assert uv_tool_recovery2_prefreeze["release_identity"]["expected_version_output"] == recovery1_diagnosis["observed_output"]
assert uv_tool_recovery2_prefreeze["execution_contract"]["network_connections"] == 0
assert uv_tool_recovery2_prefreeze["execution_contract"]["retry_count"] == 0
assert uv_tool_recovery2_prefreeze["execution_contract"]["gpu_count"] == 0
for path in (UV_TOOL_RECOVERY1_FAILURE_PATH, UV_TOOL_RECOVERY2_PREFREEZE_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

assert uv_tool_recovery2_audit["status"] == "TERMINAL_ACCEPTED"
assert uv_tool_recovery2_audit["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / uv_tool_recovery2_audit["prefreeze_gate"]["path"]
)
accepted_tool = uv_tool_recovery2_audit["accepted_tool"]
assert accepted_tool["version_output"] == uv_tool_recovery2_prefreeze["release_identity"]["expected_version_output"]
assert [row["path"] for row in accepted_tool["files"]] == ["uv", "uvx"]
assert accepted_tool["symlink_count"] == 0
assert accepted_tool["active_process_references_after_audit"] == 0
accepted_evidence = uv_tool_recovery2_audit["accepted_evidence"]
assert accepted_evidence["terminal_accepted_present"] is True
assert accepted_evidence["terminal_rejected_absent"] is True
assert accepted_evidence["evidence_inventory_verified"] is True
assert len(uv_tool_recovery2_audit["preserved_rejected_history"]) == 3
serialized = UV_TOOL_RECOVERY2_AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert lock_export_prefreeze["status"] == "FROZEN_BEFORE_OFFLINE_EXPORT"
assert lock_export_prefreeze["prior_gate"]["sha256"] == sha256_file(
    ROOT / lock_export_prefreeze["prior_gate"]["path"]
)
assert lock_export_prefreeze["source_identity"]["revision"] == audit["source"]["revision"]
assert lock_export_prefreeze["source_identity"]["uv_lock_bytes"] == 1037159
assert lock_export_prefreeze["source_identity"]["uv_lock_sha256"] == "ce0966c58ac9018c77b8aa1d7d93fe9f405deb6c0fadb54e52608fe10a992063"
assert lock_export_prefreeze["tool_identity"]["sha256"] == accepted_tool["files"][0]["sha256"]
assert lock_export_prefreeze["exporter"]["sha256"] == sha256_file(
    ROOT / lock_export_prefreeze["exporter"]["path"]
)
export_contract = lock_export_prefreeze["execution_contract"]
assert export_contract["independent_export_passes"] == 2
assert export_contract["network_connections"] == 0
assert export_contract["dependency_installations"] == 0
assert export_contract["retry_count"] == 0
assert export_contract["gpu_count"] == 0
assert "--frozen" in export_contract["uv_export_flags"]
assert "--offline" in export_contract["uv_export_flags"]
assert "--no-emit-workspace" in export_contract["uv_export_flags"]
serialized = LOCK_EXPORT_PREFREEZE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert lock_export_failure["status"] == "TERMINAL_REJECTED"
assert lock_export_failure["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / lock_export_failure["prefreeze_gate"]["path"]
)
export_diagnosis = lock_export_failure["diagnosis"]
assert export_diagnosis["differing_lines"] == [2]
assert export_diagnosis["normalized_bodies_byte_identical"] is True
assert export_diagnosis["normalized_body_bytes"] == 256006
assert export_diagnosis["normalized_body_sha256_a"] == export_diagnosis["normalized_body_sha256_b"]
assert export_diagnosis["requirement_head_count"] == 208
assert export_diagnosis["network_connections"] == 0
assert export_diagnosis["dependency_installations"] == 0

assert lock_export_recovery_prefreeze["status"] == "FROZEN_BEFORE_OFFLINE_EXPORT"
assert lock_export_recovery_prefreeze["failure_gate"]["sha256"] == sha256_file(
    ROOT / lock_export_recovery_prefreeze["failure_gate"]["path"]
)
for row in lock_export_recovery_prefreeze["exporters"]:
    assert row["sha256"] == sha256_file(ROOT / row["path"])
normalization = lock_export_recovery_prefreeze["normalization_contract"]
assert normalization["removed_line_count"] == 2
assert normalization["whitespace_or_requirement_normalization"] is False
assert normalization["expected_body_bytes"] == export_diagnosis["normalized_body_bytes"]
assert normalization["expected_body_sha256"] == export_diagnosis["normalized_body_sha256_a"]
assert normalization["expected_requirement_head_count"] == export_diagnosis["requirement_head_count"]
recovery_export = lock_export_recovery_prefreeze["execution_contract"]
assert recovery_export["independent_export_passes"] == 2
assert recovery_export["network_connections"] == 0
assert recovery_export["dependency_installations"] == 0
assert recovery_export["retry_count"] == 0
assert recovery_export["gpu_count"] == 0
for path in (LOCK_EXPORT_FAILURE_PATH, LOCK_EXPORT_RECOVERY_PREFREEZE_PATH):
    serialized = path.read_text(encoding="utf-8")
    assert "/data1/" not in serialized and "/data2/" not in serialized

assert lock_export_recovery_audit["status"] == "TERMINAL_ACCEPTED"
assert lock_export_recovery_audit["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / lock_export_recovery_audit["prefreeze_gate"]["path"]
)
audit_execution = lock_export_recovery_audit["execution"]
assert audit_execution["network_enabled"] is False
assert audit_execution["dependency_install_performed"] is False
assert audit_execution["gpu_count"] == 0
assert audit_execution["active_process_references_after_exit"] == 0
audit_export = lock_export_recovery_audit["canonical_export"]
assert audit_export["bytes"] == normalization["expected_body_bytes"]
assert audit_export["sha256"] == normalization["expected_body_sha256"]
assert audit_export["requirement_head_count"] == normalization["expected_requirement_head_count"]
assert audit_export["normalized_bodies_byte_identical"] is True
assert lock_export_recovery_audit["evidence"]["inventory_entries_verified"] == 8
assert lock_export_recovery_audit["evidence"]["traceback_exception_panic_nonfinite_matches"] == 0
serialized = LOCK_EXPORT_RECOVERY_AUDIT_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert source_aware_export_prefreeze["status"] == "FROZEN_BEFORE_OFFLINE_EXPORT"
assert source_aware_export_prefreeze["prior_gate"]["sha256"] == sha256_file(
    ROOT / source_aware_export_prefreeze["prior_gate"]["path"]
)
source_identities = source_aware_export_prefreeze["frozen_identities"]
assert source_identities["exporter_sha256"] == sha256_file(ROOT / source_identities["exporter"])
assert source_identities["body_reference_bytes"] == audit_export["bytes"]
assert source_identities["body_reference_sha256"] == audit_export["sha256"]
assert source_identities["requirement_head_count"] == audit_export["requirement_head_count"]
source_contract = source_aware_export_prefreeze["source_contract"]
assert set(source_contract["required_public_urls"]) == {
    "https://pypi.org/simple",
    "https://download.pytorch.org/whl/cpu",
}
assert source_contract["https_only"] is True
assert source_contract["credentials_forbidden"] is True
source_execution = source_aware_export_prefreeze["execution_contract"]
assert source_execution["independent_export_passes"] == 2
assert source_execution["network_connections"] == 0
assert source_execution["dependency_installations"] == 0
assert source_execution["retry_count"] == 0
serialized = SOURCE_AWARE_EXPORT_PREFREEZE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert source_aware_export_failure["status"] == "TERMINAL_REJECTED"
assert source_aware_export_failure["prefreeze_gate"]["sha256"] == sha256_file(
    ROOT / source_aware_export_failure["prefreeze_gate"]["path"]
)
source_diagnosis = source_aware_export_failure["diagnosis"]
assert source_diagnosis["observed_source_directives"] == [
    "--index-url https://pypi.org/simple"
]
assert source_diagnosis["required_but_absent_source"] == (
    "https://download.pytorch.org/whl/cpu"
)
assert source_diagnosis["dependency_body_suffix_bytes"] == audit_export["bytes"]
assert source_diagnosis["dependency_body_suffix_sha256"] == audit_export["sha256"]
assert source_diagnosis["dependency_body_preserved"] is True
assert source_diagnosis["network_connections"] == 0
assert source_diagnosis["dependency_installations"] == 0
serialized = SOURCE_AWARE_EXPORT_FAILURE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized

assert registry_routing_prefreeze["status"] == "FROZEN_BEFORE_OFFLINE_SPLIT"
assert registry_routing_prefreeze["failure_gate"]["sha256"] == sha256_file(
    ROOT / registry_routing_prefreeze["failure_gate"]["path"]
)
routing_identities = registry_routing_prefreeze["frozen_identities"]
assert routing_identities["splitter_sha256"] == sha256_file(
    ROOT / routing_identities["splitter"]
)
assert routing_identities["body_reference_bytes"] == audit_export["bytes"]
assert routing_identities["body_reference_sha256"] == audit_export["sha256"]
routing_contract = registry_routing_prefreeze["routing_contract"]
assert routing_contract["total_requirement_blocks"] == 208
assert {row["id"]: row["expected_blocks"] for row in routing_contract["routes"]} == {
    "pypi": 206,
    "pytorch-cpu": 2,
}
assert routing_contract["byte_exact_reconstruction_required"] is True
routing_execution = registry_routing_prefreeze["execution_contract"]
assert routing_execution["independent_split_passes"] == 2
assert routing_execution["network_connections"] == 0
assert routing_execution["dependency_installations"] == 0
assert routing_execution["retry_count"] == 0
serialized = REGISTRY_ROUTING_PREFREEZE_PATH.read_text(encoding="utf-8")
assert "/data1/" not in serialized and "/data2/" not in serialized
print(
    json.dumps(
        {
            "status": "PASS",
            "tierb_candidates": len(candidates),
            "source_materialization_eligible": ["hindsight"],
            "accepted_hindsight_source_files": source["tracked_file_count"],
            "hindsight_adapter_design_eligible": True,
            "frozen_hindsight_models": sorted(row["repository"] for row in models.values()),
            "frozen_hindsight_model_bytes": sum(row["expected_total_bytes"] for row in models.values()),
            "hindsight_execution_source_files": execution_source_prefreeze["copy_scope"]["expected_file_count"],
            "accepted_hindsight_execution_source_files": copy["file_count"],
            "frozen_uv_tool_version": release["version"],
            "uv_tool_recovery_transport": "resumable-sftp-4096-kbit",
            "accepted_uv_tool": accepted_tool["version_output"],
            "numeric_result_rows_added": 0,
        },
        sort_keys=True,
    )
)
