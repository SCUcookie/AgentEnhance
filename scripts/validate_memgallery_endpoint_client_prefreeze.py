#!/usr/bin/env python3
"""Validate the result-free Mem-Gallery local endpoint client contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-endpoint-client-prefreeze.v1.json"
IMPLEMENTATION = ROOT / "scripts" / "memgallery_endpoint_client.py"


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
        payload.get("status") == "FROZEN_MOCK_ONLY_AWAITING_DATA_MODEL_AND_LIFECYCLE_GATES",
        "endpoint-client status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 4, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    spec = importlib.util.spec_from_file_location("memgallery_endpoint_client", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load endpoint implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transport = payload.get("transport_contract", {})
    require(transport.get("attempts_per_question") == 1, "attempt count drift")
    require(transport.get("automatic_retries") == 0, "retry policy drift")
    require(transport.get("maximum_response_bytes") == module.MAX_RESPONSE_BYTES == 16777216, "response ceiling drift")
    require(set(module.MIME_BY_SUFFIX.values()) == set(payload["image_contract"]["supported_mime_types"]), "MIME surface drift")
    validation = payload.get("validation", {})
    require(validation.get("mock_tests_passed") == 8, "mock test count drift")
    for field in (
        "real_dataset_files_read",
        "real_image_bytes_read",
        "real_endpoint_calls",
        "network_requests",
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
                "mock_tests": validation["mock_tests_passed"],
                "attempts_per_question": transport["attempts_per_question"],
                "automatic_retries": transport["automatic_retries"],
                "real_endpoint_calls": validation["real_endpoint_calls"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
