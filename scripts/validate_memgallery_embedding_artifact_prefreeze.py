#!/usr/bin/env python3
"""Validate the synthetic-only Mem-Gallery embedding artifact contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-embedding-artifact-prefreeze.v1.json"
IMPLEMENTATION = ROOT / "scripts" / "memgallery_embedding_artifact.py"


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
        payload.get("status") == "FROZEN_SYNTHETIC_ONLY_AWAITING_REAL_DATA_MODEL_AND_SERVICE_GATES",
        "embedding-artifact status drift",
    )
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 5, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")

    spec = importlib.util.spec_from_file_location("memgallery_embedding_artifact", IMPLEMENTATION)
    require(spec is not None and spec.loader is not None, "cannot load artifact implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registered = payload.get("registered_surface", {})
    require(registered.get("methods") == ["naive-rag", "hybrid-rag"], "method order drift")
    require(registered.get("seeds") == [0, 1, 2], "seed surface drift")
    require(registered.get("future_method_seed_artifacts") == 6, "artifact denominator drift")
    require(registered.get("questions_per_method_seed") == 1711, "question denominator drift")
    require(tuple(registered.get("roles", [])) == module.ROLES == ("document", "query"), "role surface drift")

    contract_profiles = payload.get("method_profiles", {})
    require(set(contract_profiles) == set(module.PROFILE_IDENTITIES), "profile method surface drift")
    for method_id, implementation in module.PROFILE_IDENTITIES.items():
        require(contract_profiles[method_id] == implementation, f"profile identity drift: {method_id}")

    writer = payload.get("writer_contract", {})
    require(writer.get("overwrite") is False, "overwrite boundary drift")
    require(writer.get("resume") is False, "resume boundary drift")
    require(writer.get("same_root_retry") is False, "retry boundary drift")
    reload_contract = payload.get("reload_contract", {})
    require(reload_contract.get("failed_or_partial_load") is False, "partial-load boundary drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 8, "synthetic test count drift")
    for field in (
        "real_dataset_texts_read",
        "real_vectors_observed",
        "real_endpoint_calls",
        "real_artifact_roots_created",
        "predictions_observed",
        "scores_observed",
    ):
        require(validation.get(field) == 0, f"synthetic-only boundary drift: {field}")
    require("authorizes no real dataset read" in payload.get("authorization", ""), "authorization boundary missing")

    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "implementation_sha256": sha256_file(IMPLEMENTATION),
                "method_seed_artifacts": registered["future_method_seed_artifacts"],
                "questions_per_artifact": registered["questions_per_method_seed"],
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
