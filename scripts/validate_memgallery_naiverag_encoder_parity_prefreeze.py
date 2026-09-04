#!/usr/bin/env python3
"""Validate the synthetic-only Mem-Gallery NaiveRAG encoder parity gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-naiverag-encoder-parity-prefreeze.v1.json"
IMPLEMENTATION = ROOT / "scripts" / "audit_memgallery_naiverag_encoder_parity.py"


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
        payload.get("status") == "FROZEN_SYNTHETIC_ONLY_AWAITING_WAVE1_MODEL_AND_SERVICE_RELEASE",
        "encoder-parity status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 5, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    spec = importlib.util.spec_from_file_location("audit_memgallery_naiverag_encoder_parity", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load parity implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    official = payload.get("official_implementation_identity", {})
    require(official.get("revision") == module.SOURCE_REVISION, "source revision drift")
    require(official.get("encoder_sha256") == module.ENCODER_SOURCE_SHA256, "encoder hash drift")
    require(
        official.get("function_config_sha256") == module.FUNCTION_CONFIG_SHA256,
        "function-config hash drift",
    )
    model = payload.get("model_identity", {})
    require(model.get("repository") == module.MODEL_REPOSITORY, "model repository drift")
    require(model.get("revision") == module.MODEL_REVISION, "model revision drift")
    require(model.get("model_config_sha256") == module.MODEL_CONFIG_SHA256, "model config drift")
    require(model.get("pooling_config_sha256") == module.POOLING_CONFIG_SHA256, "pooling config drift")
    require(model.get("dimensions") == module.DIMENSIONS == 1536, "dimension drift")

    surface = payload.get("probe_surface", {})
    require(surface.get("probe_set_sha256") == module.PROBE_SET_SHA256, "probe-set hash drift")
    require(surface.get("probe_count") == len(module.PROBES) == 12, "probe denominator drift")
    require(surface.get("document_probes") == 8, "document probe denominator drift")
    require(surface.get("query_probes") == 4, "query probe denominator drift")

    execution = payload.get("matched_execution", {})
    require(execution.get("direct_batch_size") == 1, "direct batch drift")
    require(execution.get("endpoint_batch_size") == module.ENDPOINT_BATCH_SIZE == 12, "endpoint batch drift")
    require(execution.get("retry_count") == 0, "retry boundary drift")
    rule = payload.get("acceptance_rule", {})
    require(rule.get("minimum_same_probe_cosine") == module.MIN_SELF_COSINE, "cosine threshold drift")
    require(
        rule.get("maximum_normalized_component_delta") == module.MAX_NORMALIZED_COMPONENT_DELTA,
        "component threshold drift",
    )
    require(
        rule.get("maximum_query_document_cosine_score_delta") == module.MAX_RETRIEVAL_SCORE_DELTA,
        "retrieval-score threshold drift",
    )
    require(rule.get("complete_eight_document_ranking_exact_for_all_four_queries") is True, "ranking gate drift")
    require(rule.get("post_observation_threshold_changes_allowed") is False, "threshold mutation boundary drift")

    branches = payload.get("terminal_branches", {})
    require(set(branches) >= {"ENDPOINT_EQUIVALENT", "DIRECT_ENCODER_REQUIRED"}, "terminal branch drift")
    artifact = payload.get("artifact_contract", {})
    require(artifact.get("overwrite") is False, "overwrite boundary drift")
    require(artifact.get("resume") is False, "resume boundary drift")
    require(artifact.get("same_root_retry") is False, "same-root retry boundary drift")
    require(artifact.get("malformed_input_creates_output_root") is False, "malformed-input boundary drift")

    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 8, "synthetic test count drift")
    for field in (
        "real_model_loads",
        "real_endpoint_calls",
        "real_vectors_observed",
        "predictions_observed",
        "scores_observed",
        "numeric_result_rows_added",
    ):
        require(validation.get(field) == 0, f"synthetic-only boundary drift: {field}")
    require(validation.get("official_values_used") is False, "official-value boundary drift")
    require("authorizes no real model load" in payload.get("authorization", ""), "authorization boundary missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "probe_set_sha256": module.PROBE_SET_SHA256,
                "probe_count": len(module.PROBES),
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
