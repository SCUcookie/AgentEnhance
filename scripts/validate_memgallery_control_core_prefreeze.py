#!/usr/bin/env python3
"""Validate the frozen Mem-Gallery control-core implementation contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "comparisons" / "memgallery-control-core-prefreeze.v1.json"
EXPECTED_CONTROLS = [
    "no-memory",
    "full-memory-text",
    "full-memory-mm",
    "fifo-recent",
    "bm25",
    "naive-rag",
    "hybrid-rag",
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
        == "FROZEN_IMPLEMENTATION_ONLY_AWAITING_DATA_MODELS_AND_NUMERICAL_AUTHORIZATION",
        "control-core status drift",
    )
    require(payload.get("registered_controls") == EXPECTED_CONTROLS, "control surface drift")
    bindings = payload.get("bound_inputs", [])
    require(len(bindings) == 4, "bound-input count drift")
    for binding in bindings:
        path = ROOT / binding["path"]
        require(path.is_file(), f"missing bound input: {path}")
        require(sha256_file(path) == binding["sha256"], f"bound-input hash drift: {path}")
    retrieval = payload.get("retrieval_contract", {})
    require(set(retrieval) == set(EXPECTED_CONTROLS), "retrieval contract is incomplete")
    budget = payload.get("evidence_budget_contract", {})
    require(budget.get("formula") == "N_text + 256*N_images <= 4096", "budget formula drift")
    require(budget.get("full_memory_mm_image_cap") == 20, "image cap drift")
    validation = payload.get("validation", {})
    require(validation.get("synthetic_tests_passed") == 9, "test count drift")
    for field in ("real_dataset_rows_read", "network_requests", "gpu_processes", "predictions_observed", "scores_observed"):
        require(validation.get(field) == 0, f"implementation-only boundary drift: {field}")
    require("No real Mem-Gallery" in payload.get("authorization", ""), "authorization boundary missing")
    print(
        json.dumps(
            {
                "status": "PASS",
                "contract_sha256": sha256_file(CONTRACT),
                "controls": len(EXPECTED_CONTROLS),
                "synthetic_tests": validation["synthetic_tests_passed"],
                "scores_observed": validation["scores_observed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
