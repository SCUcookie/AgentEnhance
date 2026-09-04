#!/usr/bin/env python3
"""Validate the result-free NaiveRAG real probe capture prefreeze."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CONTRACT = ROOT / "comparisons" / "memgallery-naiverag-encoder-probe-capture-prefreeze.v1.json"
IMPLEMENTATION = SCRIPTS / "capture_memgallery_naiverag_encoder_probes.py"


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
        == "FROZEN_IMPLEMENTATION_ONLY_AWAITING_WAVE1_RELEASE_AND_MODEL_MATERIALIZATION",
        "probe-capture status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 6, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("capture_memgallery_naiverag_encoder_probes", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load probe capture implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    preflight = payload.get("model_preflight", {})
    require(preflight.get("repository") == module.parity.MODEL_REPOSITORY, "model repository drift")
    require(preflight.get("revision") == module.parity.MODEL_REVISION, "model revision drift")
    require(preflight.get("expected_files") == module.EXPECTED_MODEL_FILES == 24, "model file denominator drift")
    require(preflight.get("expected_bytes") == module.EXPECTED_MODEL_BYTES, "model byte denominator drift")
    require(preflight.get("config_sha256") == module.parity.MODEL_CONFIG_SHA256, "model config drift")
    require(preflight.get("pooling_config_sha256") == module.parity.POOLING_CONFIG_SHA256, "pooling config drift")

    direct = payload.get("direct_capture", {})
    require(direct.get("backend") == module.BACKENDS[0], "direct backend drift")
    require(direct.get("batch_size") == 1, "direct batch drift")
    require(direct.get("model_dtype") == "torch.float32 required", "direct model dtype drift")
    require(direct.get("output_dtype") == "torch.float32 required", "direct output dtype drift")
    require(direct.get("normalization_during_capture") is False, "direct normalization drift")
    require(direct.get("automatic_retries") == 0, "direct retry drift")
    require(direct.get("network_requests") == 0, "direct network drift")

    endpoint = payload.get("endpoint_capture", {})
    require(endpoint.get("backend") == module.BACKENDS[1], "endpoint backend drift")
    require(endpoint.get("endpoint") == module.ENDPOINT, "endpoint drift")
    require(endpoint.get("batch_size") == module.parity.ENDPOINT_BATCH_SIZE == 12, "endpoint batch drift")
    require(endpoint.get("requests") == 1, "endpoint request count drift")
    require(endpoint.get("automatic_retries") == 0, "endpoint retry drift")
    require(endpoint.get("required_service_ready", {}).get("dtype") == "float32", "endpoint dtype drift")
    require(endpoint.get("failure_call_record_retained") is True, "endpoint failure evidence drift")

    evidence = payload.get("probe_evidence", {})
    require(evidence.get("probe_set_sha256") == module.parity.PROBE_SET_SHA256, "probe-set hash drift")
    require(evidence.get("probes") == len(module.parity.PROBES) == 12, "probe denominator drift")
    require(evidence.get("dimensions_per_vector") == module.parity.DIMENSIONS == 1536, "vector dimension drift")
    require(evidence.get("direct_output_is_valid_input_to_parity_auditor") is True, "direct handoff drift")
    require(evidence.get("endpoint_output_is_valid_input_to_parity_auditor") is True, "endpoint handoff drift")

    fresh = payload.get("fresh_root_protocol", {})
    require(fresh.get("overwrite") is False, "overwrite boundary drift")
    require(fresh.get("resume") is False, "resume boundary drift")
    require(fresh.get("same_root_retry") is False, "same-root retry boundary drift")
    require(fresh.get("partial_failure_retained") is True, "failure retention drift")

    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 10, "synthetic test count drift")
    for field in (
        "real_model_files_read",
        "real_model_loads",
        "gpu_processes_started",
        "real_endpoint_calls",
        "real_vectors_observed",
        "dataset_examples_read",
        "predictions_observed",
        "scores_observed",
        "numeric_result_rows_added",
    ):
        require(validation.get(field) == 0, f"result-free boundary drift: {field}")
    require(validation.get("official_values_used") is False, "official-values boundary drift")
    require("authorizes no model acquisition" in payload.get("authorization", ""), "authorization boundary missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "model_files_future_revalidated": module.EXPECTED_MODEL_FILES,
                "model_bytes_future_revalidated": module.EXPECTED_MODEL_BYTES,
                "probes": len(module.parity.PROBES),
                "synthetic_tests": validation["synthetic_tests_passed"],
                "real_vectors_observed": validation["real_vectors_observed"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
