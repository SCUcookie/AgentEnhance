#!/usr/bin/env python3
"""Validate the result-free Mem-Gallery dense embedding client contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-embedding-client-prefreeze.v1.json"
IMPLEMENTATION = ROOT / "scripts" / "memgallery_embedding_client.py"


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
        payload.get("status") == "FROZEN_MOCK_ONLY_AWAITING_MODEL_SERVICE_AND_LIFECYCLE_GATES",
        "embedding-client status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 4, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    spec = importlib.util.spec_from_file_location("memgallery_embedding_client", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load embedding implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    expected_profiles = {
        "naive-rag": {
            "profile": "gme1536",
            "model": "gme-Qwen2-VL-2B-Instruct",
            "dimensions": 1536,
        },
        "hybrid-rag": {
            "profile": "qwen1024",
            "model": "Qwen3-VL-Embedding-2B",
            "dimensions": 1024,
        },
    }
    require(module.METHOD_PROFILES == expected_profiles, "implementation method-profile drift")
    for method_id, expected in expected_profiles.items():
        registered = payload["method_profiles"][method_id]
        for field in ("profile", "model", "dimensions"):
            require(registered[field] == expected[field], f"contract profile drift: {method_id}.{field}")

    transport = payload.get("transport_contract", {})
    require(transport.get("maximum_batch_items") == module.MAX_BATCH_ITEMS == 64, "batch ceiling drift")
    require(transport.get("maximum_request_bytes") == module.MAX_REQUEST_BYTES == 8388608, "request ceiling drift")
    require(
        transport.get("maximum_response_bytes") == module.MAX_RESPONSE_BYTES == 33554432,
        "response ceiling drift",
    )
    require(transport.get("attempts_per_batch") == 1, "attempt-count drift")
    require(transport.get("automatic_retries") == 0, "retry-policy drift")

    accounting = payload.get("call_record_contract", {})
    require(accounting.get("raw_text_retained") is False, "raw-text retention drift")
    require(accounting.get("raw_vectors_in_call_record") is False, "raw-vector accounting drift")
    validation = payload.get("validation", {})
    require(validation.get("mock_tests_passed") == 11, "mock-test count drift")
    for field in (
        "real_dataset_texts_read",
        "real_endpoint_calls",
        "network_requests",
        "vectors_observed",
        "predictions_observed",
        "scores_observed",
    ):
        require(validation.get(field) == 0, f"mock-only boundary drift: {field}")
    require("authorizes no real dataset read" in payload.get("authorization", ""), "authorization boundary missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "profiles": expected_profiles,
                "maximum_batch_items": module.MAX_BATCH_ITEMS,
                "mock_tests": validation["mock_tests_passed"],
                "real_endpoint_calls": validation["real_endpoint_calls"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
