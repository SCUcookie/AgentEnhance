#!/usr/bin/env python3
"""Validate the result-free NaiveRAG parity lifecycle prefreeze."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONTRACT = ROOT / "comparisons" / "memgallery-naiverag-parity-lifecycle-prefreeze.v1.json"
IMPLEMENTATION = SCRIPTS / "run_memgallery_naiverag_parity_lifecycle.py"
EXPECTED_STAGE_ORDER = [
    "direct_capture",
    "service_start",
    "endpoint_capture",
    "service_stop",
    "parity_audit",
]


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
        "parity-lifecycle status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 6, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "run_memgallery_naiverag_parity_lifecycle", IMPLEMENTATION
    )
    require(spec is not None and spec.loader is not None, "cannot load lifecycle implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    roots = payload.get("fresh_roots", {})
    require(roots.get("controller") == module.CONTROLLER_NAME, "controller root drift")
    require(roots.get("direct") == module.DIRECT_NAME, "direct root drift")
    require(roots.get("service") == module.SERVICE_NAME, "service root drift")
    require(roots.get("endpoint") == module.ENDPOINT_NAME, "endpoint root drift")
    require(roots.get("audit") == module.AUDIT_NAME, "audit root drift")
    for field in ("overwrite", "resume", "same_root_retry"):
        require(roots.get(field) is False, f"fresh-root boundary drift: {field}")

    gate = payload.get("start_gate", {})
    require(gate.get("wave1_release_status") == "TERMINAL_ACCEPTED", "Wave1 status drift")
    require(gate.get("wave1_method_seed_runs") == 12, "Wave1 run denominator drift")
    require(gate.get("wave1_accepted_units") == 1800, "Wave1 unit denominator drift")
    require(gate.get("wave1_accepted_qa") == 94872, "Wave1 QA denominator drift")
    require(gate.get("blocked_processes") == 0, "Wave1 process boundary drift")
    require(gate.get("blocked_ports") == [], "Wave1 port boundary drift")
    require(gate.get("blocked_tmux_sessions") == [], "Wave1 tmux boundary drift")
    require(
        gate.get("allowed_physical_gpu_indices") == list(module.service.ALLOWED_GPU_INDICES),
        "GPU allocation drift",
    )
    require(
        gate.get("selected_gpu_max_used_mib") == module.service.MAX_PREFLIGHT_GPU_USED_MIB,
        "GPU memory gate drift",
    )

    execution = payload.get("execution", {})
    require(execution.get("ordered_stages") == EXPECTED_STAGE_ORDER, "stage order drift")
    require(execution.get("attempts_per_stage") == 1, "stage attempt drift")
    require(execution.get("automatic_retries") == 0, "automatic retry drift")
    require(execution.get("endpoint") == module.service.ENDPOINT, "endpoint drift")
    require(execution.get("audit_after_stop") is True, "audit ordering boundary drift")
    require(
        execution.get("service_must_be_terminal_accepted_stopped_before_audit") is True,
        "service-stop boundary drift",
    )
    source = IMPLEMENTATION.read_text(encoding="utf-8")
    stage_positions = [source.index(f'"{stage}"') for stage in EXPECTED_STAGE_ORDER]
    require(stage_positions == sorted(stage_positions), "implementation stage order drift")
    require('"failure_cleanup_service_stop"' in source, "failure cleanup stage missing")

    child = payload.get("child_evidence", {})
    require(child.get("direct_capture_inventory_members") == 3, "direct inventory drift")
    require(child.get("endpoint_capture_inventory_members") == 3, "endpoint inventory drift")
    require(child.get("stopped_service_inventory_members") == 7, "service inventory drift")
    require(child.get("parity_audit_inventory_members") == 1, "audit inventory drift")

    decision = payload.get("decision_rule", {})
    require(
        decision.get("accepted_decisions")
        == ["ENDPOINT_EQUIVALENT", "DIRECT_ENCODER_REQUIRED"],
        "accepted decision set drift",
    )
    require(decision.get("selection_is_diagnostic_only") is True, "diagnostic boundary drift")
    require(decision.get("claim_eligible") is False, "claim boundary drift")

    failure = payload.get("failure_semantics", {})
    require(failure.get("controller_status") == "TERMINAL_REJECTED", "failure status drift")
    require(failure.get("regular_stage_retry") is False, "failure retry drift")
    require(failure.get("other_users_processes_may_be_signaled") is False, "ownership boundary drift")
    require(failure.get("same_root_retry_allowed") is False, "same-root retry drift")

    controller = payload.get("controller_evidence", {})
    require(controller.get("successful_inventory_members") == 13, "controller inventory drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 7, "synthetic test count drift")
    for field in (
        "real_release_receipts_consumed",
        "real_model_files_read",
        "real_model_loads",
        "real_gpu_processes_started",
        "real_endpoint_requests",
        "real_vectors_observed",
        "benchmark_examples_read",
        "predictions_observed",
        "scores_observed",
        "numeric_result_rows_added",
    ):
        require(validation.get(field) == 0, f"result-free boundary drift: {field}")
    require(validation.get("official_values_used") is False, "official-value boundary drift")
    require("authorizes no current service start" in payload.get("authorization", ""), "authorization missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "stage_order": EXPECTED_STAGE_ORDER,
                "accepted_decisions": decision["accepted_decisions"],
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
