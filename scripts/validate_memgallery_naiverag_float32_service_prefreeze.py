#!/usr/bin/env python3
"""Validate the result-free NaiveRAG float32 service prefreeze."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONTRACT = ROOT / "comparisons" / "memgallery-naiverag-float32-service-prefreeze.v1.json"
IMPLEMENTATION = SCRIPTS / "manage_memgallery_naiverag_float32_service.py"


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
        payload.get("status")
        == "FROZEN_IMPLEMENTATION_ONLY_AWAITING_WAVE1_RELEASE_AND_GME_MATERIALIZATION",
        "float32-service status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 6, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("manage_memgallery_naiverag_float32_service", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load service implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    gate = payload.get("start_gate", {})
    release = gate.get("wave1_release_receipt", {})
    require(release.get("accepted_units") == 1800, "Wave1 unit denominator drift")
    require(release.get("accepted_qa") == 94872, "Wave1 QA denominator drift")
    require(release.get("blocked_processes") == 0, "Wave1 process boundary drift")
    require(release.get("blocked_ports") == [], "Wave1 port boundary drift")
    require(release.get("blocked_tmux_sessions") == [], "Wave1 tmux boundary drift")
    require(gate.get("allowed_physical_gpu_indices") == list(module.ALLOWED_GPU_INDICES), "GPU allocation drift")
    require(gate.get("selected_gpu_max_used_mib") == module.MAX_PREFLIGHT_GPU_USED_MIB, "GPU memory gate drift")
    require(gate.get("port") == module.PORT, "port gate drift")
    require(gate.get("launcher_sha256") == module.LAUNCHER_SHA256, "launcher identity drift")

    launch = payload.get("launch_profile", {})
    require(launch.get("bind_host") == "127.0.0.1", "bind-host drift")
    require(launch.get("endpoint") == module.ENDPOINT, "embedding endpoint drift")
    require(launch.get("models_endpoint") == module.MODELS_ENDPOINT, "models endpoint drift")
    require(launch.get("served_model") == module.SERVED_MODEL, "served-model drift")
    require(launch.get("dtype") == "float32", "dtype drift")
    require(launch.get("runner") == "pooling" and launch.get("convert") == "embed", "pooling mode drift")
    require(launch.get("tensor_parallel_size") == 1, "tensor-parallel drift")
    require(launch.get("shell") is False, "shell boundary drift")
    require(launch.get("isolated_process_group") is True, "process-group boundary drift")

    readiness = payload.get("readiness", {})
    require(readiness.get("maximum_polls") == module.READINESS_ATTEMPTS, "readiness poll drift")
    require(
        readiness.get("seconds_between_polls") == module.READINESS_INTERVAL_SECONDS,
        "readiness interval drift",
    )
    require(readiness.get("automatic_retries") == 0, "readiness retry drift")
    require(
        readiness.get("ready_receipt_schema")
        == "agentenhance.memgallery_naiverag_float32_service_ready.v1",
        "ready schema drift",
    )

    ownership = payload.get("ownership_and_stop", {})
    require(ownership.get("sigterm_timeout_seconds") == module.STOP_TIMEOUT_SECONDS, "stop timeout drift")
    require(ownership.get("other_users_processes_may_be_signaled") is False, "process ownership boundary drift")
    require(ownership.get("terminal_status") == "TERMINAL_ACCEPTED_STOPPED", "stop status drift")
    evidence = payload.get("evidence_protocol", {})
    require(evidence.get("overwrite") is False, "overwrite boundary drift")
    require(evidence.get("resume") is False, "resume boundary drift")
    require(evidence.get("same_root_retry") is False, "same-root retry boundary drift")

    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 10, "synthetic test count drift")
    for field in (
        "real_release_receipts_consumed",
        "real_model_files_read",
        "real_model_loads",
        "real_gpu_processes_started",
        "real_endpoint_requests",
        "real_vectors_observed",
        "predictions_observed",
        "scores_observed",
        "numeric_result_rows_added",
    ):
        require(validation.get(field) == 0, f"result-free boundary drift: {field}")
    require(validation.get("official_values_used") is False, "official-value boundary drift")
    require("authorizes no service start" in payload.get("authorization", ""), "authorization boundary missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "endpoint": module.ENDPOINT,
                "dtype": launch["dtype"],
                "allowed_gpus": list(module.ALLOWED_GPU_INDICES),
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
