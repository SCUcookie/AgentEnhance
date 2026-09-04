#!/usr/bin/env python3
"""Validate the result-free shared Qwen service lifecycle prefreeze."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONTRACT = ROOT / "comparisons" / "memgallery-shared-qwen-services-prefreeze.v1.json"
IMPLEMENTATION = SCRIPTS / "manage_memgallery_shared_qwen_services.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    require(
        payload.get("status") == "FROZEN_IMPLEMENTATION_ONLY_AWAITING_WAVE1_RELEASE",
        "shared-service status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 7, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("manage_memgallery_shared_qwen_services", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load shared-service implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    require(list(module.ROLE_ORDER) == ["chat", "embedding"], "launch role order drift")
    require(list(module.STOP_ORDER) == ["embedding", "chat"], "stop role order drift")
    require(list(module.REQUIRED_GPU_INDICES) == [1, 3, 4], "required GPU surface drift")
    require(module.MAX_PREFLIGHT_GPU_USED_MIB == 100, "GPU headroom gate drift")
    require(module.READINESS_ATTEMPTS == 180, "readiness poll drift")
    require(module.READINESS_INTERVAL_SECONDS == 5, "readiness interval drift")
    require(module.STOP_TIMEOUT_SECONDS == 120, "stop timeout drift")

    protected = payload.get("protected_models", {})
    for role in module.ROLE_ORDER:
        contract_model = protected.get(role, {})
        implementation_model = module.MODEL_SPECS[role]
        expected_pairs = {
            "repository": "model_id",
            "revision": "revision",
            "path": "path",
            "placement_manifest_sha256": "manifest_sha256",
            "model_inventory_sha256": "inventory_sha256",
            "model_files": "files",
            "model_bytes": "bytes",
        }
        for contract_field, implementation_field in expected_pairs.items():
            require(
                contract_model.get(contract_field) == implementation_model[implementation_field],
                f"{role} model identity drift: {contract_field}",
            )
        require(contract_model.get("cleanup_eligible") is False, f"{role} cleanup boundary drift")
        require(contract_model.get("symlinks") == 0, f"{role} symlink boundary drift")
        require(
            contract_model.get("directory_files_including_two_manifests")
            == contract_model.get("model_files") + 2,
            f"{role} directory denominator drift",
        )

    gate = payload.get("release_and_fresh_root_gate", {})
    require(gate.get("required_release_status") == "TERMINAL_ACCEPTED", "release status drift")
    require(gate.get("accepted_units") == 1800, "release unit denominator drift")
    require(gate.get("accepted_qa") == 94872, "release QA denominator drift")
    require(gate.get("blocked_processes") == 0, "release process boundary drift")
    require(gate.get("blocked_ports") == [], "release port boundary drift")
    require(gate.get("blocked_tmux_sessions") == [], "release tmux boundary drift")
    require(gate.get("root_collision_checked_before_model_rehash") is True, "root preflight order drift")
    for field in ("overwrite", "resume", "same_root_retry"):
        require(gate.get(field) is False, f"fresh-root boundary drift: {field}")

    profiles = payload.get("service_profiles", {})
    for role in module.ROLE_ORDER:
        profile = profiles.get(role, {})
        implementation = module.SERVICE_SPECS[role]
        require(profile.get("served_model") == implementation["served_model"], f"{role} served-model drift")
        require(profile.get("endpoint") == implementation["endpoint"], f"{role} endpoint drift")
        require(profile.get("models_endpoint") == implementation["models_endpoint"], f"{role} models endpoint drift")
        require(profile.get("physical_gpu_indices") == list(implementation["gpu_indices"]), f"{role} GPU drift")
        require(profile.get("dtype") == "bfloat16", f"{role} dtype drift")
    require(profiles["chat"].get("tensor_parallel_size") == 2, "chat tensor-parallel drift")
    require(profiles["chat"].get("limit_mm_per_prompt") == {"image": 21, "video": 0}, "chat image cap drift")
    require(profiles["embedding"].get("dimensions") == 1024, "embedding dimension drift")
    require(profiles["embedding"].get("normalize") is True, "embedding normalization drift")
    require(profiles["embedding"].get("runner") == "pooling", "embedding runner drift")

    readiness = payload.get("readiness", {})
    require(readiness.get("launch_order") == list(module.ROLE_ORDER), "readiness launch order drift")
    require(readiness.get("maximum_polls_per_service") == module.READINESS_ATTEMPTS, "poll ceiling drift")
    require(readiness.get("smoke_attempts_per_service") == 1, "smoke attempt drift")
    require(readiness.get("automatic_retries") == 0, "automatic retry drift")
    require(readiness.get("ready_status") == "READY_FOR_MEMGALLERY", "ready status drift")

    ownership = payload.get("ownership_and_stop", {})
    require(ownership.get("stop_order") == list(module.STOP_ORDER), "stop order drift")
    require(ownership.get("sigterm_timeout_seconds") == module.STOP_TIMEOUT_SECONDS, "stop timeout drift")
    require(ownership.get("other_users_processes_may_be_signaled") is False, "process ownership drift")
    require(ownership.get("terminal_status") == "TERMINAL_ACCEPTED_STOPPED", "stop status drift")
    evidence = payload.get("evidence_protocol", {})
    require(evidence.get("accepted_stop_inventory_members") == 12, "accepted inventory drift")
    require(len(evidence.get("accepted_stop_files", [])) == 12, "accepted file surface drift")
    require(evidence.get("same_root_retry") is False, "same-root retry drift")

    source = IMPLEMENTATION.read_text(encoding="utf-8")
    start_services_position = source.index("def start_services(")
    require(
        source.index("    _validate_output_root(output_root", start_services_position)
        < source.index('validate_model_snapshot("chat"', start_services_position),
        "root collision is not checked before model rehash",
    )
    require(source.index("services = validate_ready_receipt(root, ready)") < source.index("for role in STOP_ORDER:", source.index("def stop_services")), "ready receipt is not validated before stop loop")

    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 11, "synthetic test count drift")
    for field in (
        "real_model_files_rehashed_by_this_freeze",
        "real_gpu_processes_started",
        "real_endpoint_requests",
        "benchmark_examples_read",
        "predictions_observed",
        "scores_observed",
        "numeric_result_rows_added",
    ):
        require(validation.get(field) == 0, f"result-free boundary drift: {field}")
    require(validation.get("official_values_used") is False, "official-value boundary drift")
    require("authorizes no current model rehash" in payload.get("authorization", ""), "authorization boundary missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "protected_models": len(module.MODEL_SPECS),
                "protected_model_bytes": sum(item["bytes"] for item in module.MODEL_SPECS.values()),
                "service_roles": list(module.ROLE_ORDER),
                "synthetic_tests": validation["synthetic_tests_passed"],
                "real_gpu_processes_started": validation["real_gpu_processes_started"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
